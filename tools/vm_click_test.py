"""点击链路对照测试：起记事本 → 关它 → 看是否弹出「保存」确认框。

用 UIA 拿到记事本关闭按钮的真实矩形，再用真实鼠标点击它中心。
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from tools.vm_guest import capture_screen, guest_run  # noqa: E402
from tools.vm_uia import click_action  # noqa: E402
from tools.vm_win import send_keys  # noqa: E402

if __name__ == "__main__":
    log = []
    log.append(guest_run(
        "Get-Process notepad -ErrorAction SilentlyContinue | Stop-Process -Force; "
        "Start-Process notepad; Start-Sleep -Seconds 4; "
        "'notepad pid=' + (Get-Process notepad).Id", timeout=180, interactive=True))
    log.append("--- 找关闭按钮 ---")
    log.append(click_action("关闭", 1, "click"))
    time.sleep(2)
    capture_screen(str(BASE_DIR / "logs" / "click_test.png"))
    log.append("截图 -> logs/click_test.png")
    # 若弹出保存框，用 Alt+N 关掉
    log.append("Alt+N: " + send_keys("%n"))
    time.sleep(1)
    capture_screen(str(BASE_DIR / "logs" / "click_test2.png"))
    out = "\n".join(log)
    (BASE_DIR / "logs" / "click_test.txt").write_text(out, encoding="utf-8")
    print(out)
