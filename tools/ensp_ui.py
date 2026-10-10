"""eNSP 界面自动化基座：动态定位窗口 → 找图标 → 真实点击。

关键教训（都踩过）：
- eNSP 窗口位置会变（被拖动/重开），**绝不能缓存屏幕绝对坐标**；
- eNSP 的工具栏是自绘的，UIA 看不到按钮，只能靠截图找彩色图标；
- 来宾鼠标现在可控（VMX 里关了 vmmouse 指针集成），可以用 mouse_event 真点击。

用法（也可 import）：
    python tools/ensp_ui.py rect                 打印 eNSP 窗口矩形
    python tools/ensp_ui.py icons                在工具栏区域找彩色图标
    python tools/ensp_ui.py click green          点击最大的绿色图标（启动设备）
    python tools/ensp_ui.py click red            点击最大的红色图标（停止设备）
    python tools/ensp_ui.py shot [路径]          截图
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from tools.vm_guest import capture_screen, guest_run  # noqa: E402
from tools.vm_img import color  # noqa: E402
from tools.vm_win import click  # noqa: E402

SHOT = BASE_DIR / "logs" / "ensp_now.png"

_UIA_RECT = r"""
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
$AE = [System.Windows.Automation.AutomationElement]
$kids = $AE::RootElement.FindAll([System.Windows.Automation.TreeScope]::Children,
        [System.Windows.Automation.Condition]::TrueCondition)
foreach ($k in $kids) {
  $c = $k.Current
  if ($c.Name -eq 'eNSP_Client') {
    $r = $c.BoundingRectangle
    "$([int]$r.X) $([int]$r.Y) $([int]$r.Width) $([int]$r.Height)"
  }
}
"""


def window_rect() -> tuple[int, int, int, int] | None:
    out = guest_run(_UIA_RECT, timeout=240, interactive=True)
    for line in out.splitlines():
        parts = line.strip().split()
        if len(parts) == 4 and all(p.lstrip("-").isdigit() for p in parts):
            x, y, w, h = (int(p) for p in parts)
            return x, y, w, h
    return None


def shot(path: str | Path | None = None) -> Path:
    p = Path(path) if path else SHOT
    capture_screen(str(p))
    return p


def toolbar_box(rect: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
    """工具栏在窗口内的相对位置（实测：窗口顶 +36px 起，高约 48px）。

    必须跳过两侧：
    - 左侧**设备面板**也有绿色图标（设备图标连通块比工具栏 ▶ 还大）；
    - 右侧是**窗口按钮区**（红色 X 比其他红色块都大，会误当成"停止设备"）。
    """
    x, y, w, h = rect
    left = x + int(w * 0.30)
    right = x + w - 150
    return left, y + 36, right - left, 48


def _parse_clusters(text: str) -> list[tuple[int, int, int]]:
    """从 color() 输出里解析 (n, cx, cy)，按 n 降序。"""
    out = []
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("n="):
            continue
        try:
            n = int(line.split("n=")[1].split()[0])
            cx = int(line.split("center=(")[1].split(",")[0])
            cy = int(line.split("center=(")[1].split(")")[0].split(",")[1])
            out.append((n, cx, cy))
        except (IndexError, ValueError):
            continue
    out.sort(key=lambda t: -t[0])
    return out


def find_icons(colour: str = "green", img: Path | None = None,
               min_px: int = 20) -> list[tuple[int, int, int]]:
    rect = window_rect()
    if rect is None:
        raise SystemExit("eNSP 窗口未找到")
    img = img or shot()
    bx, by, bw, bh = toolbar_box(rect)
    return _parse_clusters(color(str(img), bx, by, bw, bh, colour, min_px))


def click_icon(colour: str = "green", nth: int = 1, settle: float = 2.0) -> str:
    """实时截图 → 定位图标 → 点击。窗口位置在调用之间可能变，所以必须一体化。"""
    icons = find_icons(colour)
    if len(icons) < nth:
        return f"未找到 {colour} 图标（找到 {len(icons)} 个）"
    n, cx, cy = icons[nth - 1]
    msg = click(cx, cy)
    time.sleep(settle)
    return f"{colour} 图标 n={n} @({cx},{cy}) -> {msg}"


def main(argv: list[str]) -> int:
    op = argv[1] if len(argv) > 1 else "rect"
    if op == "rect":
        print(window_rect())
    elif op == "shot":
        print(shot(argv[2] if len(argv) > 2 else None))
    elif op == "icons":
        print("green:", find_icons("green"))
        print("red:", find_icons("red"))
    elif op == "click":
        print(click_icon(argv[2] if len(argv) > 2 else "green",
                         int(argv[3]) if len(argv) > 3 else 1))
    else:
        print(__doc__)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
