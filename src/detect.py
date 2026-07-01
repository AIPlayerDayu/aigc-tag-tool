#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AI 元数据检测器 —— 检测图片/视频文件里是否携带 "AI 生成 / AI 编辑" 的元数据痕迹。

设计目标：
  * 纯标准库即可运行（不依赖任何第三方 Python 包）。
  * 若系统里装了 exiftool（可选），会额外调用它做权威、全格式的元数据提取，
    覆盖 HEIC / 视频 / C2PA 等纯 Python 难以解析的情况。
  * 输出一份自包含的 HTML 报告并用默认浏览器打开。

判定分三档：
  🔴 ai      —— 找到明确的 "AI 生成" 标记（C2PA/IPTC 合成声明、SD/ComfyUI 参数、知名生成器署名等）
  🟠 suspect —— 找到 "内容凭证 / AI 参与编辑" 等间接痕迹，需人工判断
  🟢 clean   —— 未发现 AI 元数据（注意：元数据可被抹除或伪造，"未发现" ≠ "一定是人拍/画的"）
"""

import sys, os, json, struct, zlib, re, html, tempfile, subprocess, shutil, webbrowser, datetime

# --------------------------------------------------------------------------- #
#  已知 AI 生成 / 编辑工具的署名特征（只在"元数据文本"里匹配，避免误伤正文像素）
# --------------------------------------------------------------------------- #
# level: 'gen'  -> 视为 AI 生成
#        'edit' -> 视为 AI 参与编辑（存疑）
AI_TOOL_PATTERNS = [
    # ---- 图像生成器 ----
    (r"midjourney",                      "Midjourney",                 "gen"),
    (r"dall[\-·\.]?e|openai",       "OpenAI DALL·E",              "gen"),
    (r"stable\s*diffusion|sd-metadata",  "Stable Diffusion",           "gen"),
    (r"automatic1111|a1111",             "AUTOMATIC1111 (WebUI)",       "gen"),
    (r"comfyui",                          "ComfyUI",                    "gen"),
    (r"invokeai",                         "InvokeAI",                   "gen"),
    (r"novelai",                          "NovelAI",                    "gen"),
    (r"imagen|made with google ai|gemini","Google Imagen / Gemini",     "gen"),
    (r"ideogram",                         "Ideogram",                   "gen"),
    (r"leonardo\.?\s*ai",                "Leonardo.Ai",                "gen"),
    (r"black\s*forest\s*labs|flux\.\d|flux\s*(dev|pro|schnell)", "FLUX", "gen"),
    (r"bing\s*image\s*creator|image creator", "Bing Image Creator",     "gen"),
    (r"playground\s*ai",                  "Playground AI",              "gen"),
    (r"recraft",                          "Recraft",                    "gen"),
    (r"\bkrea\b",                         "Krea",                       "gen"),
    (r"grok|\bxai\b|aurora",             "xAI Grok / Aurora",          "gen"),
    (r"dreamstudio|dream studio",         "DreamStudio",                "gen"),
    (r"nightcafe",                        "NightCafe",                  "gen"),
    (r"copilot|designer",                 "Microsoft Copilot / Designer","gen"),
    (r"canva.*(text to image|magic media|dream)", "Canva AI",          "gen"),
    (r"seedream|seededit|jimeng|即梦|doubao|豆包", "字节 即梦 / 豆包",  "gen"),
    (r"tongyi|wanx|通义|万相",           "阿里 通义万相",              "gen"),
    (r"ernie|文心|一格",                 "百度 文心一格",              "gen"),
    (r"liblib|哩布",                     "LiblibAI",                   "gen"),
    (r"tusiart|吐司",                    "TusiArt",                    "gen"),
    # ---- 视频生成器 ----
    (r"\bsora\b",                        "OpenAI Sora",                "gen"),
    (r"runway|gen-?[23]",                "Runway",                     "gen"),
    (r"\bpika\b",                        "Pika",                       "gen"),
    (r"\bkling\b|可灵",                  "快手 可灵 (Kling)",          "gen"),
    (r"\bveo\b",                         "Google Veo",                 "gen"),
    (r"luma|dream machine",              "Luma Dream Machine",         "gen"),
    (r"hailuo|minimax|海螺",             "MiniMax 海螺",               "gen"),
    (r"vidu",                            "Vidu",                       "gen"),
    # ---- AI 编辑 / 修图（存疑，非纯生成）----
    (r"firefly",                         "Adobe Firefly",              "gen"),
    (r"generative\s*(fill|expand|remove)","Adobe 生成式填充/扩展",     "edit"),
    (r"neural\s*filter",                 "Photoshop 神经滤镜",         "edit"),
    (r"\btopaz\b|gigapixel",             "Topaz AI",                   "edit"),
    (r"luminar",                         "Luminar Neo AI",             "edit"),
    (r"\bremini\b",                      "Remini",                     "edit"),
    (r"facetune",                        "Facetune",                   "edit"),
    (r"\bmagic eraser|魔术橡皮擦",       "Magic Eraser",               "edit"),
]

# IPTC DigitalSourceType（合成媒体分类标准）——最权威的"这是 AI 生成"声明
IPTC_SYNTHETIC = {
    "trainedalgorithmicmedia":   ("纯 AI 生成 (IPTC: trainedAlgorithmicMedia)", "gen"),
    "compositewithtrainedalgorithmicmedia": ("含 AI 合成 (IPTC: composite w/ trained)", "gen"),
    "compositesynthetic":        ("合成媒体 (IPTC: compositeSynthetic)", "gen"),
    "algorithmicmedia":          ("算法生成 (IPTC: algorithmicMedia)",   "gen"),
    "algorithmicallyenhanced":   ("算法增强 (IPTC: algorithmicallyEnhanced)", "edit"),
}

# 字节级高置信标记（只有很具体、几乎不会误报的字符串才放这里）
AIGC_LABEL = "中国 AIGC 生成合成内容标识 (GB 45438-2025)"
BYTE_MARKERS = [
    (b"trainedAlgorithmicMedia",  "IPTC 合成声明: trainedAlgorithmicMedia", "gen"),
    (b"compositeSynthetic",       "IPTC 合成声明: compositeSynthetic",      "gen"),
    (b"c2pa.actions",             "C2PA 动作声明 (c2pa.actions)",           "prov"),
    (b"c2pa.created",             "C2PA: 内容由工具创建 (c2pa.created)",     "prov"),
    (b'"ContentProducer"',        AIGC_LABEL,                                "gen"),
    (b'"ProduceID"',              AIGC_LABEL,                                "gen"),
]


def decode_aigc(text):
    """把 AIGC 隐式标识 JSON 解析成人类可读的说明。"""
    try:
        d = json.loads(text)
    except Exception:
        return text[:300]
    label = str(d.get("Label", "")).strip()
    meaning = {"1": "AI 生成合成", "2": "疑似生成合成"}.get(label, f"Label={label}")
    who = d.get("ContentProducer", "") or d.get("ContentPropagator", "")
    extra = f"；服务提供者编码 {who}" if who else ""
    return f"该文件被写入 AIGC 标识：{meaning}{extra}"

MAX_SCAN = 8 * 1024 * 1024  # 大文件只扫描首尾各 8MB 找标记


# --------------------------------------------------------------------------- #
#  exiftool（可选）
# --------------------------------------------------------------------------- #
def find_exiftool():
    for c in ("/opt/homebrew/bin/exiftool", "/usr/local/bin/exiftool", "exiftool"):
        p = shutil.which(c) if "/" not in c else (c if os.path.exists(c) else None)
        if p:
            return p
    return None


def run_exiftool(path, tool):
    try:
        out = subprocess.run(
            [tool, "-j", "-G1", "-a", "-u", "-ee", "-api", "largefilesupport=1", path],
            capture_output=True, timeout=60,
        )
        data = json.loads(out.stdout.decode("utf-8", "replace"))
        return data[0] if data else {}
    except Exception:
        return None


def find_ffprobe():
    for c in ("/opt/homebrew/bin/ffprobe", "/usr/local/bin/ffprobe", "ffprobe"):
        p = shutil.which(c) if "/" not in c else (c if os.path.exists(c) else None)
        if p:
            return p
    return None


def run_ffprobe(path, probe):
    """返回视频容器 / 各流的标签 {tag: value}。"""
    try:
        out = subprocess.run(
            [probe, "-v", "error", "-show_entries",
             "format_tags:stream_tags", "-of", "json", path],
            capture_output=True, timeout=60,
        )
        data = json.loads(out.stdout.decode("utf-8", "replace"))
        tags = dict(data.get("format", {}).get("tags", {}))
        for s in data.get("streams", []):
            tags.update(s.get("tags", {}))
        return tags
    except Exception:
        return {}


# --------------------------------------------------------------------------- #
#  纯 Python 解析各文件格式，抽取"文本型"元数据
# --------------------------------------------------------------------------- #
def parse_png(data):
    """返回 PNG 里的 tEXt/iTXt/zTXt 文本块 {key: value}。"""
    out = {}
    i = 8
    n = len(data)
    while i + 8 <= n:
        try:
            length = struct.unpack(">I", data[i:i + 4])[0]
            ctype = data[i + 4:i + 8]
        except struct.error:
            break
        body = data[i + 8:i + 8 + length]
        if ctype in (b"tEXt", b"iTXt", b"zTXt"):
            try:
                if ctype == b"tEXt":
                    k, _, v = body.partition(b"\x00")
                    out[k.decode("latin1", "replace")] = v.decode("latin1", "replace")
                elif ctype == b"zTXt":
                    k, _, rest = body.partition(b"\x00")
                    v = zlib.decompress(rest[1:]).decode("latin1", "replace")
                    out[k.decode("latin1", "replace")] = v
                elif ctype == b"iTXt":
                    k, _, rest = body.partition(b"\x00")
                    comp_flag = rest[0:1]
                    rest = rest[2:]  # skip compression flag+method
                    _lang, _, rest = rest.partition(b"\x00")
                    _trans, _, txt = rest.partition(b"\x00")
                    if comp_flag == b"\x01":
                        txt = zlib.decompress(txt)
                    out[k.decode("utf-8", "replace")] = txt.decode("utf-8", "replace")
            except Exception:
                pass
        if ctype == b"IEND":
            break
        i += 12 + length
    return out


def _tiff_software(data):
    """从一段 TIFF/EXIF 数据里抠出 Software(0x0131)/Artist(0x013B)/ImageDescription(0x010E)。"""
    out = {}
    if len(data) < 8:
        return out
    endian = data[0:2]
    if endian == b"II":
        bo = "<"
    elif endian == b"MM":
        bo = ">"
    else:
        return out
    try:
        offset = struct.unpack(bo + "I", data[4:8])[0]
        count = struct.unpack(bo + "H", data[offset:offset + 2])[0]
        tags = {0x010E: "ImageDescription", 0x0131: "Software", 0x013B: "Artist", 0x9286: "UserComment"}
        for j in range(count):
            e = offset + 2 + j * 12
            tag, typ, cnt = struct.unpack(bo + "HHI", data[e:e + 8])
            if tag in tags and typ == 2:  # ASCII
                if cnt <= 4:
                    val = data[e + 8:e + 8 + cnt]
                else:
                    ptr = struct.unpack(bo + "I", data[e + 8:e + 12])[0]
                    val = data[ptr:ptr + cnt]
                out[tags[tag]] = val.rstrip(b"\x00").decode("latin1", "replace")
    except Exception:
        pass
    return out


def parse_jpeg(data):
    """扫描 JPEG 的 APP 段：EXIF(APP1) 软件字段、XMP(APP1) 包、C2PA(APP11)。"""
    out = {"exif": {}, "xmp": "", "c2pa": False}
    i = 2
    n = len(data)
    while i + 4 <= n and data[i] == 0xFF:
        marker = data[i + 1]
        if marker in (0xD8, 0xD9) or 0xD0 <= marker <= 0xD7:
            i += 2
            continue
        seg_len = struct.unpack(">H", data[i + 2:i + 4])[0]
        seg = data[i + 4:i + 2 + seg_len]
        if marker == 0xE1:  # APP1
            if seg.startswith(b"Exif\x00\x00"):
                out["exif"].update(_tiff_software(seg[6:]))
            elif b"http://ns.adobe.com/xap/1.0/" in seg[:40]:
                out["xmp"] += seg.split(b"\x00", 1)[-1].decode("utf-8", "replace")
        elif marker == 0xEB:  # APP11 —— C2PA/JUMBF 常用
            if b"JP" in seg[:8] or b"jumb" in seg[:40] or b"c2pa" in seg[:200]:
                out["c2pa"] = True
        if marker == 0xDA:  # SOS，之后是压缩图像数据
            break
        i += 2 + seg_len
    return out


def parse_webp(data):
    out = {"exif": {}, "xmp": ""}
    if data[8:12] != b"WEBP":
        return out
    i = 12
    n = len(data)
    while i + 8 <= n:
        fourcc = data[i:i + 4]
        size = struct.unpack("<I", data[i + 4:i + 8])[0]
        body = data[i + 8:i + 8 + size]
        if fourcc == b"EXIF":
            out["exif"].update(_tiff_software(body[6:] if body[:6] == b"Exif\x00\x00" else body))
        elif fourcc == b"XMP ":
            out["xmp"] += body.decode("utf-8", "replace")
        i += 8 + size + (size & 1)
    return out


def extract_xmp_fields(xmp):
    """从 XMP 文本里抽取关键字段。"""
    out = {}
    if not xmp:
        return out
    patterns = {
        "DigitalSourceType": r"(?:Iptc4xmpExt:)?DigitalSourceType[>=\"']+\s*([^<\"'\s]+)",
        "CreatorTool":       r"(?:xmp:)?CreatorTool[>=\"']+\s*([^<\"']+)",
        "Software":          r"(?:tiff:)?Software[>=\"']+\s*([^<\"']+)",
        "Credit":            r"(?:photoshop:)?Credit[>=\"']+\s*([^<\"']+)",
        "History":           r"stEvt:softwareAgent[>=\"']+\s*([^<\"']+)",
    }
    for k, pat in patterns.items():
        m = re.search(pat, xmp, re.IGNORECASE)
        if m:
            out[k] = m.group(1).strip()
    # C2PA 在 XMP 里的痕迹
    if re.search(r"c2pa|contentauth|content credentials|CAI:", xmp, re.IGNORECASE):
        out["_c2pa_xmp"] = True
    return out


# --------------------------------------------------------------------------- #
#  规则引擎
# --------------------------------------------------------------------------- #
def add(findings, seen, label, detail, level, source):
    key = (label, level)
    if key in seen:
        return
    seen.add(key)
    findings.append({"label": label, "detail": detail, "level": level, "source": source})


def match_tools(text, findings, seen, source):
    low = text.lower()
    for pat, label, level in AI_TOOL_PATTERNS:
        if re.search(pat, low):
            add(findings, seen, f"生成/编辑工具署名：{label}", text.strip()[:300], level, source)


def analyze(path):
    result = {
        "path": path, "name": os.path.basename(path),
        "verdict": "clean", "confidence": "low",
        "findings": [], "meta_text": {}, "exif_present": False,
    }
    try:
        size = os.path.getsize(path)
    except OSError as e:
        result["verdict"] = "error"
        result["error"] = str(e)
        return result
    result["size"] = size

    ext = os.path.splitext(path)[1].lower().lstrip(".")
    findings = result["findings"]
    seen = set()
    meta = result["meta_text"]

    # ---- 读文件（大文件只读首尾） ----
    try:
        with open(path, "rb") as f:
            head = f.read(min(size, MAX_SCAN))
            tail = b""
            if size > MAX_SCAN * 2:
                f.seek(-MAX_SCAN, os.SEEK_END)
                tail = f.read(MAX_SCAN)
    except OSError as e:
        result["verdict"] = "error"
        result["error"] = str(e)
        return result
    blob = head + tail
    sig = head[:16]

    # ---- 按格式做结构化解析 ----
    is_video = ext in ("mp4", "mov", "m4v", "webm", "avi", "mkv") or sig[4:8] == b"ftyp"
    result["kind"] = "video" if is_video else "image"

    if sig.startswith(b"\x89PNG"):
        chunks = parse_png(head)
        for k, v in chunks.items():
            meta[f"PNG:{k}"] = v
            lk = k.lower()
            vl = v.lower()
            if lk == "parameters" and re.search(r"steps:|sampler|cfg scale|seed:", vl):
                add(findings, seen, "Stable Diffusion / WebUI 生成参数",
                    "PNG 内嵌 'parameters' 生成参数（Steps/Sampler/Seed…）", "gen", "PNG:parameters")
            if lk in ("prompt", "workflow"):
                add(findings, seen, "ComfyUI 工作流数据",
                    f"PNG 内嵌 '{k}' JSON（ComfyUI 节点图/提示词）", "gen", f"PNG:{k}")
            if lk == "software" and "novelai" in vl:
                add(findings, seen, "NovelAI 生成", v, "gen", "PNG:Software")
            if lk in ("dream", "sd-metadata"):
                add(findings, seen, "InvokeAI 生成", v[:200], "gen", f"PNG:{k}")
            match_tools(f"{k} {v}", findings, seen, f"PNG:{k}")

    elif sig.startswith(b"\xff\xd8"):
        j = parse_jpeg(head)
        for k, v in j["exif"].items():
            meta[f"EXIF:{k}"] = v
            match_tools(v, findings, seen, f"EXIF:{k}")
        if j["exif"]:
            result["exif_present"] = True
        if j["c2pa"]:
            add(findings, seen, "C2PA 内容凭证 (Content Credentials)",
                "JPEG APP11 段包含 C2PA/JUMBF 清单", "prov", "APP11")
        xf = extract_xmp_fields(j["xmp"])
        _apply_xmp(xf, findings, seen, meta)

    elif sig[:4] == b"RIFF" and head[8:12] == b"WEBP":
        w = parse_webp(head)
        for k, v in w["exif"].items():
            meta[f"EXIF:{k}"] = v
            match_tools(v, findings, seen, f"EXIF:{k}")
        _apply_xmp(extract_xmp_fields(w["xmp"]), findings, seen, meta)

    # ---- 通用：在原始字节里找 XMP 包 + 高置信标记（覆盖视频/HEIC/未知容器） ----
    m = re.search(rb"<x:xmpmeta.*?</x:xmpmeta>", blob, re.DOTALL)
    if m:
        _apply_xmp(extract_xmp_fields(m.group(0).decode("utf-8", "replace")),
                   findings, seen, meta)
    if b"jumbf" in blob.lower() and b"c2pa" in blob.lower():
        add(findings, seen, "C2PA 内容凭证 (Content Credentials)",
            "文件内嵌 JUMBF/C2PA 清单（Adobe/OpenAI/相机厂商等的来源溯源）", "prov", "bytes")
    for marker, label, level in BYTE_MARKERS:
        if marker in blob:
            detail = marker.decode("latin1")
            if label == AIGC_LABEL:
                m2 = re.search(rb'\{[^{}]*"ProduceID"[^{}]*\}', blob)
                detail = decode_aigc(m2.group(0).decode("utf-8", "replace")) if m2 else detail
            add(findings, seen, label, detail, level, "bytes")

    # ---- exiftool（可选，权威补充） ----
    tool = find_exiftool()
    if tool:
        et = run_exiftool(path, tool)
        if et:
            result["exiftool"] = {k: (str(v)[:500]) for k, v in et.items()
                                  if k not in ("SourceFile",)}
            _apply_exiftool(et, findings, seen)

    # ---- ffprobe（可选，视频容器标签的兜底，尤其是 exiftool 缺席时） ----
    if is_video:
        probe = find_ffprobe()
        if probe:
            for k, v in run_ffprobe(path, probe).items():
                meta[f"ffprobe:{k}"] = v
                if not _apply_aigc(k, v, findings, seen, f"ffprobe:{k}"):
                    match_tools(f"{k} {v}", findings, seen, f"ffprobe:{k}")

    # ---- 汇总判定 ----
    levels = {f["level"] for f in findings}
    if "gen" in levels:
        result["verdict"] = "ai"
        result["confidence"] = "high"
    elif "edit" in levels or "prov" in levels:
        result["verdict"] = "suspect"
        result["confidence"] = "medium"
    else:
        result["verdict"] = "clean"
    return result


def _apply_xmp(xf, findings, seen, meta):
    for k, v in xf.items():
        if k == "_c2pa_xmp" and v:
            add(findings, seen, "C2PA 内容凭证 (Content Credentials)",
                "XMP 中包含 C2PA / Content Credentials 声明", "prov", "XMP")
            continue
        if k == "DigitalSourceType":
            meta["XMP:DigitalSourceType"] = v
            leaf = v.rstrip("/").split("/")[-1].lower()
            if leaf in IPTC_SYNTHETIC:
                label, level = IPTC_SYNTHETIC[leaf]
                add(findings, seen, f"IPTC 合成媒体声明：{label}", v, level, "XMP:DigitalSourceType")
            continue
        meta[f"XMP:{k}"] = v
        match_tools(v, findings, seen, f"XMP:{k}")


def _apply_aigc(key, value, findings, seen, source):
    """识别中国 AIGC 隐式标识（GB 45438-2025）。返回是否命中。"""
    vs = str(value)
    if key.lower().endswith("aigc") or ('"ProduceID"' in vs and '"ContentProducer"' in vs) \
            or ('"Label"' in vs and '"ContentProducer"' in vs):
        add(findings, seen, AIGC_LABEL, decode_aigc(vs), "gen", source)
        return True
    return False


def _apply_exiftool(et, findings, seen):
    # 汇总所有值成一段文本，做工具署名匹配（只匹配元数据，不碰像素）
    joined = []
    for k, v in et.items():
        ks = k.lower()
        vs = str(v)
        vl = vs.lower()
        if _apply_aigc(k, v, findings, seen, f"exiftool:{k}"):
            continue
        # C2PA / JUMBF 组
        if "c2pa" in ks or "jumbf" in ks:
            add(findings, seen, "C2PA 内容凭证 (Content Credentials)",
                f"{k} = {vs[:200]}", "prov", "exiftool")
        # IPTC DigitalSourceType
        if "digitalsourcetype" in ks:
            leaf = vl.rstrip("/").split("/")[-1]
            if leaf in IPTC_SYNTHETIC:
                label, level = IPTC_SYNTHETIC[leaf]
                add(findings, seen, f"IPTC 合成媒体声明：{label}", vs, level, f"exiftool:{k}")
        # 明确的 AI 动作 / 关键字段
        if ks.endswith("action") and vl in ("c2pa.created", "created"):
            add(findings, seen, "C2PA: 内容由工具创建", vs, "prov", f"exiftool:{k}")
        if any(t in ks for t in ("software", "creatortool", "make", "model",
                                 "credit", "description", "comment", "usercomment",
                                 "claimgenerator", "artist", "toolname", "history",
                                 "softwareagent", "parameters", "prompt")):
            joined.append(vs)
    if joined:
        match_tools("  ".join(joined), findings, seen, "exiftool")


# --------------------------------------------------------------------------- #
#  HTML 报告
# --------------------------------------------------------------------------- #
VERDICT_META = {
    "ai":      ("🔴", "检测到 AI 生成元数据", "#e5484d", "该文件携带明确的 AI 生成标记。"),
    "suspect": ("🟠", "疑似 AI 参与 / 含内容凭证", "#f5a623",
                "发现内容凭证或 AI 编辑痕迹，建议结合下方证据人工判断。"),
    "clean":   ("🟢", "未发现 AI 元数据", "#30a46c",
                "未找到 AI 相关元数据。注意：元数据可被抹除或伪造，"
                "此结论不能证明内容一定由人类创作。"),
    "error":   ("⚠️", "无法读取", "#8b949e", ""),
}


def esc(s):
    return html.escape(str(s))


def render_card(r):
    icon, title, color, note = VERDICT_META.get(r["verdict"], VERDICT_META["error"])
    parts = [f'<div class="card" style="--vc:{color}">']
    parts.append(f'<div class="head"><span class="badge">{icon} {esc(title)}</span>'
                 f'<span class="fname">{esc(r["name"])}</span></div>')
    if r["verdict"] == "error":
        parts.append(f'<p class="note">{esc(r.get("error",""))}</p></div>')
        return "".join(parts)

    kind = "视频" if r.get("kind") == "video" else "图片"
    try:
        sz = f'{r["size"]/1024/1024:.2f} MB' if r["size"] >= 1024*1024 else f'{r["size"]/1024:.1f} KB'
    except Exception:
        sz = ""
    parts.append(f'<div class="sub">{kind} · {sz} · 置信度 {esc(r.get("confidence","-"))}</div>')
    parts.append(f'<p class="note">{esc(note)}</p>')

    if r["findings"]:
        parts.append('<div class="findings"><div class="ft">证据</div>')
        for f in r["findings"]:
            lv = {"gen": "gen", "edit": "edit", "prov": "prov"}.get(f["level"], "info")
            parts.append(
                f'<div class="finding {lv}"><div class="fl">{esc(f["label"])}</div>'
                f'<div class="fd"><code>{esc(f["detail"])}</code></div>'
                f'<div class="fs">{esc(f["source"])}</div></div>')
        parts.append('</div>')

    # 元数据明细（可折叠）
    meta = r.get("meta_text", {})
    exif = r.get("exiftool", {})
    if meta or exif:
        parts.append('<details class="meta"><summary>查看元数据明细</summary>')
        if meta:
            parts.append('<div class="mt">关键字段（内置解析）</div><table>')
            for k, v in meta.items():
                parts.append(f'<tr><td>{esc(k)}</td><td>{esc(str(v)[:600])}</td></tr>')
            parts.append('</table>')
        if exif:
            parts.append('<div class="mt">exiftool 全量输出</div><table>')
            for k, v in sorted(exif.items()):
                parts.append(f'<tr><td>{esc(k)}</td><td>{esc(v)}</td></tr>')
            parts.append('</table>')
        parts.append('</details>')
    parts.append('</div>')
    return "".join(parts)


PAGE = """<!DOCTYPE html><html lang="zh-CN"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>AI 元数据检测报告</title><style>
:root{--bg:#f6f7f9;--fg:#1f2328;--muted:#656d76;--border:#e3e6ea;--card:#fff;--code:#f2f4f7}
@media (prefers-color-scheme:dark){:root{--bg:#0d1117;--fg:#e6edf3;--muted:#8b949e;--border:#2a3038;--card:#161b22;--code:#0d1117}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);
 font-family:-apple-system,BlinkMacSystemFont,"PingFang SC","Segoe UI",sans-serif}
.wrap{max-width:900px;margin:0 auto;padding:28px 20px 60px}
h1{font-size:20px;margin:0 0 2px}
.top{color:var(--muted);font-size:13px;margin-bottom:22px}
.card{background:var(--card);border:1px solid var(--border);border-left:5px solid var(--vc);
 border-radius:12px;padding:16px 18px;margin:0 0 16px;box-shadow:0 1px 2px rgba(0,0,0,.04)}
.head{display:flex;align-items:center;gap:10px;flex-wrap:wrap}
.badge{font-weight:700;font-size:15px;color:var(--vc)}
.fname{color:var(--muted);font-size:13px;word-break:break-all}
.sub{font-size:12px;color:var(--muted);margin:6px 0 2px}
.note{font-size:13px;color:var(--muted);margin:8px 0 4px;line-height:1.6}
.findings{margin-top:12px}
.ft{font-size:12px;font-weight:600;color:var(--muted);margin-bottom:6px}
.finding{border:1px solid var(--border);border-radius:9px;padding:9px 11px;margin-bottom:8px;background:var(--bg)}
.finding.gen{border-color:#e5484d55}.finding.edit{border-color:#f5a62355}.finding.prov{border-color:#4493f855}
.fl{font-weight:600;font-size:13.5px}
.fd{margin:4px 0}.fd code{font-size:12px;background:var(--code);padding:2px 6px;border-radius:5px;
 word-break:break-all;white-space:pre-wrap;display:inline-block;max-width:100%}
.fs{font-size:11px;color:var(--muted)}
details.meta{margin-top:12px}
summary{cursor:pointer;font-size:13px;color:var(--muted);user-select:none}
.mt{font-size:12px;font-weight:600;margin:12px 0 6px;color:var(--muted)}
table{width:100%;border-collapse:collapse;font-size:12px;table-layout:fixed}
td{border:1px solid var(--border);padding:5px 8px;vertical-align:top;word-break:break-all}
td:first-child{width:34%;color:var(--muted);font-weight:600}
footer{color:var(--muted);font-size:11.5px;margin-top:26px;line-height:1.7;text-align:center}
</style></head><body><div class="wrap">
<h1>🔎 AI 元数据检测报告</h1>
<div class="top">__TOP__</div>
__CARDS__
<footer>本工具通过读取文件的 C2PA 内容凭证、IPTC/XMP/EXIF 元数据与已知生成器署名来判断。<br>
元数据可被编辑、压缩或社交平台抹除，也可被伪造 —— 结果仅供参考，不能作为唯一证据。<br>
全过程在本机离线完成，不上传任何文件。<br><br>
⚠️ 免责声明：本工具仅供技术研究、学习与合法的元数据检测测试之用，请勿用于任何违法违规用途；
使用者应仅对自己拥有合法权利的文件进行操作并遵守所在地法律，一切后果由使用者自行承担，与作者无关。</footer>
</div></body></html>"""


def build_report(results):
    n = len(results)
    ai = sum(1 for r in results if r["verdict"] == "ai")
    sus = sum(1 for r in results if r["verdict"] == "suspect")
    ok = sum(1 for r in results if r["verdict"] == "clean")
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    top = f'共 {n} 个文件 · 🔴 AI {ai} · 🟠 疑似 {sus} · 🟢 未发现 {ok} · {ts}'
    cards = "\n".join(render_card(r) for r in results)
    exiftool_note = "" if find_exiftool() else \
        '<div class="top" style="color:#f5a623">提示：未检测到 exiftool，视频 / HEIC 等格式解析能力有限；' \
        '可 <code>brew install exiftool</code> 后重试以获得完整结果。</div>'
    return PAGE.replace("__TOP__", esc(top) + exiftool_note).replace("__CARDS__", cards)


def main(argv):
    files = [a for a in argv if os.path.isfile(a)]
    if not files:
        print("用法: detect.py <文件1> [文件2 ...]")
        return 1
    results = [analyze(p) for p in files]
    html_out = build_report(results)
    fd, path = tempfile.mkstemp(prefix="ai-meta-", suffix=".html")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(html_out)
    webbrowser.open("file://" + path)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
