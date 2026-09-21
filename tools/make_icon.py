"""生成 NetworkClaw 应用图标（assets/networkclaw.png 与 .ico）。

为什么用脚本生成而不是塞一张二进制图片进仓库：
    图标要跟着主题色/品牌微调，脚本化之后改几个常量就能重出全套尺寸，
    也避免把「来路不明的图片」提交进版本库。

用法：
    python tools/make_icon.py            # 重新生成 assets/ 下的两个文件

设计：深色圆角底 + 青色「爪」弧线 + 网络拓扑节点，呼应「Network + Claw」。
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

# 输出位置：项目根/assets/
OUT_DIR = Path(__file__).resolve().parent.parent / "assets"
SUPERSAMPLE = 4  # 先画 4 倍再缩小，得到平滑边缘
BASE = 256

BG_TOP = (11, 18, 32)
BG_BOTTOM = (22, 36, 60)
EDGE = (40, 60, 92)
ACCENT = (56, 189, 248)       # sky-400
ACCENT_DIM = (14, 116, 144)
NODE = (226, 240, 253)
CENTER = (125, 211, 252)


def _rounded_mask(size: int, radius: int) -> Image.Image:
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, size - 1, size - 1), radius=radius, fill=255)
    return mask


def _gradient(size: int) -> Image.Image:
    """竖直渐变底色（逐行插值，使用 numpy 提速）"""
    import numpy as np

    top = np.array(BG_TOP, dtype=np.float32)
    bottom = np.array(BG_BOTTOM, dtype=np.float32)
    t = np.linspace(0.0, 1.0, size, dtype=np.float32)[:, None]
    column = top[None, :] * (1 - t) + bottom[None, :] * t          # (size, 3)
    rows = np.repeat(column[:, None, :], size, axis=1)             # (size, size, 3)
    arr = np.clip(rows, 0, 255).astype(np.uint8)
    return Image.fromarray(arr, "RGB")


def _draw_icon(size: int) -> Image.Image:
    """在给定尺寸上绘制图标（内部按超采样尺寸绘制）"""
    s = size
    img = _gradient(s).convert("RGBA")

    # 与底色同色系的描边，缩小后形成一圈细腻的高光轮廓
    ImageDraw.Draw(img).rounded_rectangle(
        (2, 2, s - 3, s - 3), radius=int(s * 0.22), outline=EDGE + (255,), width=max(2, s // 128)
    )

    draw = ImageDraw.Draw(img, "RGBA")

    cx, cy = s * 0.5, s * 0.62

    # --- 三根「爪」弧线：由中心下方扇出，末端汇聚到三个节点
    tips = [(s * 0.20, s * 0.30), (s * 0.50, s * 0.20), (s * 0.80, s * 0.30)]
    for tx, ty in tips:
        # 二次贝塞尔近似：控制点偏向中心外侧，形成外扩的爪痕
        mx, my = (cx + tx) / 2 + (s * 0.06 if tx < cx else (-s * 0.06 if tx > cx else 0)), (cy + ty) / 2
        steps = 96
        pts = []
        for i in range(steps + 1):
            t = i / steps
            x = (1 - t) ** 2 * cx + 2 * (1 - t) * t * mx + t ** 2 * tx
            y = (1 - t) ** 2 * cy + 2 * (1 - t) * t * my + t ** 2 * ty
            pts.append((x, y))
        # 由粗到细画三段，模拟收尖的笔触
        for width, shade in ((0.055, ACCENT_DIM), (0.034, ACCENT), (0.016, NODE)):
            seg = pts[: int(len(pts) * 0.86)]
            draw.line(seg, fill=shade + (255,), width=max(2, int(s * width)), joint="curve")

    # --- 拓扑连线：把三个末梢连成一个三角，体现「网络」
    for i in range(3):
        x1, y1 = tips[i]
        x2, y2 = tips[(i + 1) % 3]
        draw.line([(x1, y1), (x2, y2)], fill=CENTER + (170,), width=max(2, int(s * 0.012)))

    # --- 节点：末梢小节点 + 中心大节点
    r_tip = s * 0.055
    for tx, ty in tips:
        draw.ellipse((tx - r_tip, ty - r_tip, tx + r_tip, ty + r_tip), fill=NODE + (255,))
    r_core = s * 0.085
    draw.ellipse((cx - r_core, cy - r_core, cx + r_core, cy + r_core), fill=CENTER + (255,))
    r_ring = s * 0.125
    draw.ellipse((cx - r_ring, cy - r_ring, cx + r_ring, cy + r_ring), outline=ACCENT + (200,),
                 width=max(2, int(s * 0.016)))

    # 圆角裁切
    out = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    out.paste(img, (0, 0), _rounded_mask(s, int(s * 0.22)))
    return out


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    big = _draw_icon(BASE * SUPERSAMPLE).resize((BASE, BASE), Image.LANCZOS)

    png_path = OUT_DIR / "networkclaw.png"
    big.save(png_path, "PNG")
    print(f"[图标] 已写出 {png_path}")

    ico_path = OUT_DIR / "networkclaw.ico"
    sizes = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
    big.save(ico_path, "ICO", sizes=sizes)
    print(f"[图标] 已写出 {ico_path}（{', '.join(f'{w}x{h}' for w, h in sizes)}）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
