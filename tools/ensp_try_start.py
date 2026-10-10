"""点「启动设备」并观测结果：进程 / 端口 / 截图差异。"""
from __future__ import annotations

import sys
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from tools.ensp_ui import click_icon, find_icons, shot, window_rect  # noqa: E402
from tools.vm_guest import guest_run  # noqa: E402

PROCS = ("Get-Process eNSP_Client,eNSP_Server,eNSP_VBoxServer,VBoxSVC,vboxheadless,"
         "VirtualBoxVM -ErrorAction SilentlyContinue | "
         "Select-Object ProcessName,Id | Format-Table -AutoSize | Out-String -Width 80")
PORTS = ("Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue | "
         "Where-Object { $_.LocalPort -ge 2000 -and $_.LocalPort -le 2020 } | "
         "Sort-Object LocalPort | Select-Object LocalPort,OwningProcess | "
         "Format-Table -AutoSize | Out-String -Width 80")

if __name__ == "__main__":
    log = []
    r = window_rect()
    log.append(f"窗口矩形: {r}")
    log.append(f"绿色图标: {find_icons('green')}")
    before = shot(BASE_DIR / "logs" / "try_before.png")
    log.append(f"点击前截图: {before}")
    log.append("点击结果: " + click_icon("green"))
    time.sleep(8)
    log.append("--- 进程 ---")
    log.append(guest_run(PROCS, timeout=180))
    log.append("--- 2000-2020 端口 ---")
    log.append(guest_run(PORTS, timeout=180))
    after = shot(BASE_DIR / "logs" / "try_after.png")
    log.append(f"点击后截图: {after}")
    out = "\n".join(log)
    (BASE_DIR / "logs" / "try_start.txt").write_text(out, encoding="utf-8")
    print(out)
