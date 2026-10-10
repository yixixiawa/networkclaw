"""来宾窗口/输入自动化服务（宿主端运行，一次启动多次调用）。

背景（2026-10-01 实测）
----------------------
- `vmrun runProgramInGuest`（不加 -interactive）走的是**服务会话（Session 0）**，
  看不到交互桌面上的窗口，UIA RootElement 子窗口数 = 0，也无法注入输入。
- 带 `-interactive` 时凭据必须等于当前交互登录用户（yixixiawa）。
- 所以：**所有窗口/输入自动化都必须用 -interactive（普通用户身份）**；
  只有 HKLM 写、设备禁用、杀 SYSTEM 进程这类才走 tools/vm_sys.py 的 SYSTEM 计划任务。

用法：
    python tools/vm_act.py watch            # 常驻轮询（打印前台窗口）
    python tools/vm_act.py fg <标题片段>     # 置前
    python tools/vm_act.py min <标题片段>    # 最小化
    python tools/vm_act.py restore <标题>    # 还原+置前
    python tools/vm_act.py click <x> <y> [标题]  # 指定 DPI 坐标 + 注入点击
    python tools/vm_act.py key <vk...> [标题]
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

from tools.vm_hotkey import hotkey  # noqa: E402
from tools.vm_kbd import foreground  # noqa: E402


def _c(t: str) -> str:
    return t.strip()


def act_fg(title: str) -> str:
    return foreground(title)


def act_min(title: str) -> str:
    """最小化：先置前再发 Alt+Space, N（Windows 无障碍最小化）。"""
    fg = foreground(title)
    r = hotkey(["alt", "space"], title=title)
    r2 = hotkey(["n"], title=title)
    return f"{fg}\n{r}\n{r2}"


def main(argv: list[str]) -> int:
    op = argv[1] if len(argv) > 1 else "watch"
    if op == "fg":
        print(act_fg(argv[2]))
    elif op == "min":
        print(act_min(argv[2]))
    elif op == "watch":
        n = int(argv[2]) if len(argv) > 2 else 100000
        for i in range(n):
            print(f"[{time.strftime('%H:%M:%S')}] " + foreground("eNSP_Client"))
            sys.stdout.flush()
            time.sleep(5)
    else:
        print(__doc__)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
