"""截图辅助：裁剪放大 / 叠加绝对坐标网格（用于人工读点或用例比对）。

用法：
    python tools/vm_img.py grid <src> <x> <y> <w> <h> <out> [step] [zoom]
    python tools/vm_img.py crop <src> <x> <y> <w> <h> <out> [zoom]
    python tools/vm_img.py size <src>
"""
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw

BASE_DIR = Path(__file__).resolve().parent.parent


def _abs(p: str) -> str:
    path = Path(p)
    return str(path if path.is_absolute() else BASE_DIR / path)


def grid(src: str, x: int, y: int, w: int, h: int, out: str,
         step: int = 50, zoom: int = 3) -> str:
    img = Image.open(_abs(src)).convert("RGB")
    box = (x, y, min(x + w, img.width), min(y + h, img.height))
    crop = img.crop(box)
    crop = crop.resize((crop.width * zoom, crop.height * zoom), Image.NEAREST)
    d = ImageDraw.Draw(crop)
    for ax in range(box[0] - box[0] % step + step, box[2], step):
        cx = (ax - box[0]) * zoom
        d.line([(cx, 0), (cx, crop.height)], fill=(255, 0, 255), width=1)
        d.text((cx + 3, 3), str(ax), fill=(255, 0, 255))
    for ay in range(box[1] - box[1] % step + step, box[3], step):
        cy = (ay - box[1]) * zoom
        d.line([(0, cy), (crop.width, cy)], fill=(0, 200, 255), width=1)
        d.text((3, cy + 2), str(ay), fill=(0, 200, 255))
    crop.save(_abs(out))
    return f"grid -> {out} box={box} step={step} zoom={zoom}"


def crop(src: str, x: int, y: int, w: int, h: int, out: str, zoom: int = 2) -> str:
    img = Image.open(_abs(src)).convert("RGB")
    box = (x, y, min(x + w, img.width), min(y + h, img.height))
    c = img.crop(box).resize(((box[2] - box[0]) * zoom, (box[3] - box[1]) * zoom),
                             Image.NEAREST)
    c.save(_abs(out))
    return f"crop -> {out} box={box} zoom={zoom}"


def size(src: str) -> str:
    img = Image.open(_abs(src))
    return f"{src}: {img.width}x{img.height}"


def find(src: str, x: int, y: int, w: int, h: int, min_px: int = 30,
         dark: int = 205, sat_min: int = 45) -> str:
    """在区域内找「非背景色」像素连通块，输出绝对坐标。

    比对着渲染缩略图估算坐标可靠得多：渲染会缩放，读数会偏。
    """
    img = Image.open(_abs(src)).convert("RGB")
    box = (x, y, min(x + w, img.width), min(y + h, img.height))
    crop = img.crop(box)
    px = crop.load()
    W, H = crop.size
    mask = [[False] * W for _ in range(H)]
    for j in range(H):
        for i in range(W):
            r, g, b = px[i, j]
            lum = (r * 299 + g * 587 + b * 114) // 1000
            sat = max(r, g, b) - min(r, g, b)
            mask[j][i] = lum < dark or (sat_min > 0 and sat > sat_min)
    seen = [[False] * W for _ in range(H)]
    out = []
    for j0 in range(H):
        for i0 in range(W):
            if not mask[j0][i0] or seen[j0][i0]:
                continue
            stack = [(i0, j0)]
            seen[j0][i0] = True
            xs, ys, n = [], [], 0
            while stack:
                i, j = stack.pop()
                xs.append(i); ys.append(j); n += 1
                for di, dj in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    ni, nj = i + di, j + dj
                    if 0 <= ni < W and 0 <= nj < H and mask[nj][ni] and not seen[nj][ni]:
                        seen[nj][ni] = True
                        stack.append((ni, nj))
            if n >= min_px:
                out.append((n, box[0] + min(xs), box[1] + min(ys),
                            box[0] + max(xs), box[1] + max(ys)))
    out.sort(key=lambda t: (t[1], t[2]))
    lines = [f"共 {len(out)} 个连通块（区域 {box}）"]
    for n, x0, y0, x1, y1 in out:
        cx, cy = (x0 + x1) // 2, (y0 + y1) // 2
        lines.append(f"  n={n:6d} bbox=({x0},{y0})-({x1},{y1}) center=({cx},{cy}) "
                     f"size={x1 - x0 + 1}x{y1 - y0 + 1}")
    return "\n".join(lines)


_COLORS = {
    "green": lambda r, g, b: g > 110 and g - r > 45 and g - b > 30,
    "red": lambda r, g, b: r > 130 and r - g > 60 and r - b > 60,
    "blue": lambda r, g, b: b > 130 and b - r > 45 and b - g > 25,
    "yellow": lambda r, g, b: r > 190 and g > 170 and b < 130 and abs(r - g) < 70,
}


def color(src: str, x: int, y: int, w: int, h: int, name: str,
          min_px: int = 25) -> str:
    """找指定颜色像素的连通块（用于定位工具栏彩色图标，如绿色「启动」）。"""
    pred = _COLORS[name]
    img = Image.open(_abs(src)).convert("RGB")
    box = (x, y, min(x + w, img.width), min(y + h, img.height))
    crop = img.crop(box)
    px = crop.load()
    W, H = crop.size
    mask = [[False] * W for _ in range(H)]
    for j in range(H):
        for i in range(W):
            mask[j][i] = pred(*px[i, j])
    seen = [[False] * W for _ in range(H)]
    out = []
    for j0 in range(H):
        for i0 in range(W):
            if not mask[j0][i0] or seen[j0][i0]:
                continue
            stack = [(i0, j0)]
            seen[j0][i0] = True
            xs, ys, n = [], [], 0
            while stack:
                i, j = stack.pop()
                xs.append(i); ys.append(j); n += 1
                for di, dj in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    ni, nj = i + di, j + dj
                    if 0 <= ni < W and 0 <= nj < H and mask[nj][ni] and not seen[nj][ni]:
                        seen[nj][ni] = True
                        stack.append((ni, nj))
            if n >= min_px:
                out.append((n, box[0] + min(xs), box[1] + min(ys),
                            box[0] + max(xs), box[1] + max(ys)))
    out.sort(key=lambda t: -t[0])
    lines = [f"{name} 连通块 {len(out)} 个（区域 {box}）"]
    for n, x0, y0, x1, y1 in out:
        lines.append(f"  n={n:6d} bbox=({x0},{y0})-({x1},{y1}) "
                     f"center=({(x0 + x1) // 2},{(y0 + y1) // 2}) size={x1 - x0 + 1}x{y1 - y0 + 1}")
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 1
    op = argv[1]
    a = argv[2:]
    if op == "size":
        print(size(a[0]))
    elif op == "crop":
        print(crop(a[0], int(a[1]), int(a[2]), int(a[3]), int(a[4]), a[5],
                   int(a[6]) if len(a) > 6 else 2))
    elif op == "color":
        print(color(a[0], int(a[1]), int(a[2]), int(a[3]), int(a[4]), a[5],
                    int(a[6]) if len(a) > 6 else 25))
    elif op == "find":
        print(find(a[0], int(a[1]), int(a[2]), int(a[3]), int(a[4]),
                   int(a[5]) if len(a) > 5 else 30,
                   int(a[6]) if len(a) > 6 else 205,
                   int(a[7]) if len(a) > 7 else 45))
    elif op == "grid":
        print(grid(a[0], int(a[1]), int(a[2]), int(a[3]), int(a[4]), a[5],
                   int(a[6]) if len(a) > 6 else 50,
                   int(a[7]) if len(a) > 7 else 3))
    else:
        print(f"未知操作: {op}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
