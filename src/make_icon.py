#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""程序化生成 App 图标（放大镜 + 扫描条），纯标准库绘制，无版权素材。
   输出 src/icon.icns。仅在打包机（macOS）上运行，依赖 sips / iconutil。"""
import os, math, struct, zlib, subprocess, tempfile, shutil

N = 1024


def smooth(edge0, edge1, x):
    t = max(0.0, min(1.0, (x - edge0) / (edge1 - edge0)))
    return t * t * (3 - 2 * t)


def mix(a, b, t):
    return tuple(a[i] + (b[i] - a[i]) * t for i in range(3))


def sd_seg(px, py, ax, ay, bx, by):
    apx, apy = px - ax, py - ay
    abx, aby = bx - ax, by - ay
    h = max(0.0, min(1.0, (apx * abx + apy * aby) / (abx * abx + aby * aby)))
    dx, dy = apx - abx * h, apy - aby * h
    return math.hypot(dx, dy)


def render():
    cx, cy, R, ring = 430.0, 415.0, 205.0, 44.0        # 镜片
    hx0, hy0 = cx + R * 0.707, cy + R * 0.707            # 手柄起点（镜片边缘）
    hx1, hy1 = 735.0, 720.0                              # 手柄终点
    handle_w = 58.0
    inner = R - ring - 8                                 # 镜片内可绘制半径
    bars = [(-58, 150), (0, 190), (58, 120)]            # 扫描条 (dy, 半宽)
    bar_h = 24.0
    top_col, bot_col = (0x7C, 0x5C, 0xFF), (0xC1, 0x3C, 0xE8)
    white = (255, 255, 255)
    aa = 1.6

    px = bytearray(N * N * 4)
    corner = 224.0  # 圆角
    for y in range(N):
        for x in range(N):
            fx, fy = x + 0.5, y + 0.5
            # 圆角矩形遮罩
            qx = abs(fx - N / 2) - (N / 2 - corner)
            qy = abs(fy - N / 2) - (N / 2 - corner)
            d_rect = math.hypot(max(qx, 0), max(qy, 0)) + min(max(qx, qy), 0) - corner
            mask = smooth(1.0, -1.0, d_rect)
            if mask <= 0:
                continue
            # 背景渐变（左上→右下）
            t = (fx + fy) / (2 * N)
            col = mix(top_col, bot_col, t)

            # 白色前景：镜环 + 手柄 + 扫描条
            d_ring = abs(math.hypot(fx - cx, fy - cy) - R) - ring / 2
            a = smooth(aa, -aa, d_ring)
            d_handle = sd_seg(fx, fy, hx0, hy0, hx1, hy1) - handle_w / 2
            a = max(a, smooth(aa, -aa, d_handle))
            if math.hypot(fx - cx, fy - cy) < inner:
                for dy, hw in bars:
                    bx0, bx1 = cx - hw, cx + hw
                    by = cy + dy
                    d_bar = sd_seg(fx, fy, bx0, by, bx1, by) - bar_h / 2
                    a = max(a, smooth(aa, -aa, d_bar))
            if a > 0:
                col = mix(col, white, a)

            o = (y * N + x) * 4
            px[o] = int(col[0] + 0.5)
            px[o + 1] = int(col[1] + 0.5)
            px[o + 2] = int(col[2] + 0.5)
            px[o + 3] = int(mask * 255 + 0.5)
    return bytes(px)


def write_png(path, rgba):
    def chunk(tag, data):
        return (struct.pack(">I", len(data)) + tag + data +
                struct.pack(">I", zlib.crc32(tag + data) & 0xffffffff))
    raw = bytearray()
    for y in range(N):
        raw.append(0)
        raw += rgba[y * N * 4:(y + 1) * N * 4]
    ihdr = struct.pack(">IIBBBBB", N, N, 8, 6, 0, 0, 0)
    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n")
        f.write(chunk(b"IHDR", ihdr))
        f.write(chunk(b"IDAT", zlib.compress(bytes(raw), 9)))
        f.write(chunk(b"IEND", b""))


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    print("绘制图标 …")
    png = os.path.join(here, "icon-1024.png")
    write_png(png, render())
    if not shutil.which("sips") or not shutil.which("iconutil"):
        print("已生成 PNG，但缺少 sips/iconutil，无法生成 .icns"); return
    ico = os.path.join(tempfile.mkdtemp(), "icon.iconset")
    os.makedirs(ico, exist_ok=True)
    for size in (16, 32, 64, 128, 256, 512, 1024):
        subprocess.run(["sips", "-z", str(size), str(size), png,
                        "--out", os.path.join(ico, f"icon_{size}x{size}.png")],
                       check=True, capture_output=True)
        if size <= 512:
            subprocess.run(["sips", "-z", str(size * 2), str(size * 2), png,
                            "--out", os.path.join(ico, f"icon_{size}x{size}@2x.png")],
                           check=True, capture_output=True)
    subprocess.run(["iconutil", "-c", "icns", ico,
                    "-o", os.path.join(here, "icon.icns")], check=True)
    os.remove(png)
    print("✅ 生成 icon.icns")


if __name__ == "__main__":
    main()
