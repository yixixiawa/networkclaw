"""验证「点画布 → Ctrl+A 全选」链路，并裁剪状态栏读「选中: N」。

用法: python tools/ensp_ctrla.py [keys...]    默认 ctrl a
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from tools.ensp_ui import shot, window_rect  # noqa: E402
from tools.vm_hotkey import hotkey  # noqa: E402
from tools.vm_img import crop  # noqa: E402
from tools.vm_win import click  # noqa: E402


def read_status(img: Path, rect) -> Path:
    x, y, w, h = rect
    out = BASE_DIR / "logs" / "status.png"
    crop(str(img), x + 4, y + h - 30, 340, 26, str(out), zoom=5)
    return out


def main(argv: list[str]) -> int:
    keys = argv[1:] or ["ctrl", "a"]
    rect = window_rect()
    print("rect =", rect)
    if rect is None:
        return 1
    x, y, w, h = rect

    # 画布空白点：窗口右侧中部的拓扑空白区
    cx, cy = x + int(w * 0.85), y + int(h * 0.55)
    print("click canvas", (cx, cy), "->", click(cx, cy))
    time.sleep(1.0)

    print("hotkey", keys, "->", hotkey(keys))
    time.sleep(1.5)

    img = shot(BASE_DIR / "logs" / "ctrla.png")
    print("shot ->", img)
    print("status ->", read_status(img, rect))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
