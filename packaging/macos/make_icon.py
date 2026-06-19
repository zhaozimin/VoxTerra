#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
[INPUT]: 读 voicelog/assets/icon.png(白色透明 logo)
[OUTPUT]: 生成 packaging/macos/VoiceLog_iconmaster.png(1024 方形 App 图标:深色 squircle + 白 logo)
[POS]: macOS 打包资源生成器;仅打包期运行,非运行依赖。配 sips/iconutil 产出 .icns。
[PROTOCOL]: 变更时更新此头部，然后检查 CLAUDE.md

设计:照搬原 logo 品牌——近黑炭灰背景 + 居中白色话筒/无限符号。macOS 圆角方(squircle)。
为消除锯齿,全程在 2x 超采样画布上绘制,最后一次性降采样。
"""
from pathlib import Path
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "voicelog" / "assets" / "icon.png"
OUT = Path(__file__).resolve().parent / "VoiceLog_iconmaster.png"

S = 1024          # 目标边长
SS = 2            # 超采样倍率
N = S * SS
MARGIN = 98 * SS  # Apple 图标栅格:形状四周留白
RADIUS = 186 * SS # 圆角半径(≈ 0.225 * 形状边长)
TOP = (0x28, 0x28, 0x2d)     # 顶部炭灰
BOT = (0x15, 0x15, 0x17)     # 底部近黑
LOGO_W_RATIO = 0.64          # 白 logo 占形状宽度的比例


def vertical_gradient(w: int, h: int, top, bot) -> Image.Image:
    """竖直渐变填充,模拟原 logo 背景的微妙明暗。"""
    grad = Image.new("RGB", (1, h))
    for y in range(h):
        t = y / max(1, h - 1)
        grad.putpixel((0, y), tuple(round(top[i] + (bot[i] - top[i]) * t) for i in range(3)))
    return grad.resize((w, h))


def main() -> None:
    box = N - 2 * MARGIN

    # 1) squircle 蒙版(超采样下圆角抗锯齿自然)
    mask = Image.new("L", (N, N), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        [MARGIN, MARGIN, N - MARGIN, N - MARGIN], radius=RADIUS, fill=255)

    # 2) 渐变底 + 蒙版裁成圆角方
    canvas = Image.new("RGBA", (N, N), (0, 0, 0, 0))
    grad = vertical_gradient(N, N, TOP, BOT).convert("RGBA")
    canvas.paste(grad, (0, 0), mask)

    # 3) 白色 logo 居中(按宽缩放,保持原始宽高比)
    logo = Image.open(SRC).convert("RGBA")
    lw = int(box * LOGO_W_RATIO)
    lh = round(lw * logo.height / logo.width)
    logo = logo.resize((lw, lh), Image.LANCZOS)
    canvas.alpha_composite(logo, ((N - lw) // 2, (N - lh) // 2))

    # 4) 降采样到目标尺寸,落盘
    canvas.resize((S, S), Image.LANCZOS).save(OUT)
    print("wrote", OUT)


if __name__ == "__main__":
    main()
