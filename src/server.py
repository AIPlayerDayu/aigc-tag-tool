#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AI 元数据检测器 —— 本地服务 + 拖拽网页前端。

启动后监听 127.0.0.1:8765，提供：
  GET  /               拖拽页面
  GET  /ping           健康检查
  POST /detect         上传文件字节做检测（供浏览器内拖拽）
  POST /detect-path    直接按本地路径检测（供拖到 App 图标 / 命令行）
  POST /clean          去除 AI / AIGC 标识，生成干净副本
  GET  /download       下载干净副本

纯标准库；检测复用 detect.py；去标识用 exiftool(图片) / ffmpeg(视频)。
"""
import os, sys, json, uuid, tempfile, threading, time, subprocess, shutil, urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import detect  # noqa: E402

HOST, PORT = "127.0.0.1", 8765
HERE = os.path.dirname(os.path.abspath(__file__))
TOKENS = {}                      # token -> {path, name, uploaded, kind}
DOWNLOADS = {}                   # dtoken -> path
IDLE_LIMIT = 30 * 60            # 30 分钟无活动自动退出
_last = time.time()
_lock = threading.Lock()


def touch():
    global _last
    _last = time.time()


def idle_watch():
    while True:
        time.sleep(60)
        if time.time() - _last > IDLE_LIMIT:
            os._exit(0)


# --------------------------------------------------------------------------- #
#  去除 AI / AIGC 标识（仅移除元数据，不改动画面像素）
# --------------------------------------------------------------------------- #
FFMPEG_HELP = ("视频去标识需要 ffmpeg。Windows 请运行： winget install Gyan.FFmpeg "
               "（或 choco install ffmpeg）；macOS 请运行： brew install ffmpeg。装好后重开本工具即可。")


def clean_file(src, name, kind):
    """生成一个去除了 AI/AIGC 标识的干净副本，返回 (out_path, out_name)。"""
    stem, ext = os.path.splitext(name)
    out_name = f"{stem}_已去AI标识{ext}"
    out_dir = tempfile.mkdtemp(prefix="ai-clean-")
    out = os.path.join(out_dir, out_name)

    if kind == "video":
        ff = detect.find_ffmpeg()
        if not ff:
            raise RuntimeError(FFMPEG_HELP)
        # 直接流拷贝，去掉全部容器标签（含 AIGC），不重新编码 → 画质无损、速度快
        cmd = [ff, "-y", "-i", src, "-map_metadata", "-1", "-map", "0", "-c", "copy", out]
        r = subprocess.run(cmd, capture_output=True, timeout=600, **detect._NO_WINDOW)
        if r.returncode != 0 or not os.path.exists(out):
            raise RuntimeError("ffmpeg 处理失败：" + r.stderr.decode("utf-8", "replace")[-400:])
    else:
        # 图片：纯 Python 无损剥离，零外部依赖（Windows 也无需装任何东西）
        if not detect.strip_image_metadata(src, out):
            et = detect.find_exiftool()   # HEIC 等少见格式回退到 exiftool
            if not et:
                raise RuntimeError("该图片格式暂需 exiftool 才能去除元数据（常见 JPEG/PNG/WebP 无需）")
            subprocess.run([et, "-all=", "-o", out, src],
                           capture_output=True, timeout=120, **detect._NO_WINDOW)
            if not os.path.exists(out):
                raise RuntimeError("exiftool 处理失败")
    return out, out_name


# --------------------------------------------------------------------------- #
#  HTTP
# --------------------------------------------------------------------------- #
class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="application/json; charset=utf-8", extra=None):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    # ---- 检测结果打包 ----
    def _result_payload(self, path, name, uploaded, real_path=None):
        r = detect.analyze(path)
        r["name"] = name
        token = uuid.uuid4().hex
        with _lock:
            TOKENS[token] = {"path": real_path or path, "name": name,
                             "uploaded": uploaded, "kind": r.get("kind", "image")}
        return {
            "token": token, "name": name, "verdict": r["verdict"],
            "kind": r.get("kind", "image"),
            "canClean": r["verdict"] in ("ai", "suspect"),
            "findings": [f["label"] for f in r["findings"]],
            "cardHtml": detect.render_card(r),
        }

    def do_GET(self):
        touch()
        u = urllib.parse.urlparse(self.path)
        if u.path == "/ping":
            return self._send(200, '{"ok":true}')
        if u.path == "/" or u.path == "/index.html":
            try:
                with open(os.path.join(HERE, "index.html"), "rb") as f:
                    return self._send(200, f.read(), "text/html; charset=utf-8")
            except OSError:
                return self._send(500, '{"error":"index.html missing"}')
        if u.path == "/download":
            q = urllib.parse.parse_qs(u.query)
            dt = q.get("t", [""])[0]
            p = DOWNLOADS.get(dt)
            if not p or not os.path.exists(p):
                return self._send(404, '{"error":"not found"}')
            with open(p, "rb") as f:
                data = f.read()
            fn = urllib.parse.quote(os.path.basename(p))
            return self._send(200, data, "application/octet-stream",
                              {"Content-Disposition": f"attachment; filename*=UTF-8''{fn}"})
        return self._send(404, '{"error":"not found"}')

    def _read_body(self):
        n = int(self.headers.get("Content-Length", 0))
        return self.rfile.read(n) if n else b""

    def do_POST(self):
        touch()
        u = urllib.parse.urlparse(self.path)
        try:
            if u.path == "/detect":
                name = urllib.parse.unquote(self.headers.get("X-Filename", "file"))
                ext = os.path.splitext(name)[1]
                n = int(self.headers.get("Content-Length", 0))
                fd, tmp = tempfile.mkstemp(prefix="ai-up-", suffix=ext)
                remaining = n
                with os.fdopen(fd, "wb") as f:
                    while remaining > 0:
                        chunk = self.rfile.read(min(1 << 20, remaining))
                        if not chunk:
                            break
                        f.write(chunk)
                        remaining -= len(chunk)
                return self._send(200, json.dumps(
                    self._result_payload(tmp, name, uploaded=True)))

            if u.path == "/detect-path":
                req = json.loads(self._read_body() or b"{}")
                out = []
                for p in req.get("paths", []):
                    if os.path.isfile(p):
                        out.append(self._result_payload(p, os.path.basename(p),
                                                         uploaded=False))
                return self._send(200, json.dumps({"results": out}))

            if u.path == "/clean":
                req = json.loads(self._read_body() or b"{}")
                info = TOKENS.get(req.get("token", ""))
                if not info:
                    return self._send(404, '{"error":"token 失效，请重新拖入文件"}')
                out, out_name = clean_file(info["path"], info["name"], info["kind"])
                # 复检，证明确实干净了
                rr = detect.analyze(out)
                resp = {"outName": out_name, "verdict": rr["verdict"],
                        "cardHtml": detect.render_card(rr)}
                if info["uploaded"]:
                    dt = uuid.uuid4().hex
                    DOWNLOADS[dt] = out
                    resp["download"] = f"/download?t={dt}"
                else:
                    # 直接落盘到原文件所在目录（不可写则回退到"下载"）
                    dest_dir = os.path.dirname(info["path"])
                    dest = os.path.join(dest_dir, out_name)
                    try:
                        shutil.copyfile(out, dest)
                        resp["savedPath"] = dest
                    except OSError:
                        dt = uuid.uuid4().hex
                        DOWNLOADS[dt] = out
                        resp["download"] = f"/download?t={dt}"
                return self._send(200, json.dumps(resp))
        except Exception as e:
            return self._send(500, json.dumps({"error": str(e)}))
        return self._send(404, '{"error":"not found"}')


def main():
    try:
        srv = ThreadingHTTPServer((HOST, PORT), Handler)
    except OSError:
        # 端口被占用 —— 说明已有实例在跑，直接退出即可
        sys.exit(0)
    threading.Thread(target=idle_watch, daemon=True).start()
    srv.serve_forever()


if __name__ == "__main__":
    main()
