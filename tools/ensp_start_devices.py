"""启动 / 停止 eNSP 拓扑里的全部设备，并等待 Telnet 管理端口开放。

为什么必须 Ctrl+A：工具栏的绿色 ▶「启动设备」只对**选中的设备**生效，
不选中时点它不会有任何反应（这是之前反复"点了没反应"的真正原因之一）。
另一半原因是 UIPI：eNSP 以管理员(High IL)运行时，我们注入的键鼠被静默丢弃；
eNSP 以管理员身份运行（High IL），注入进程同为 High IL 才送达；
降权反而会让路由器（要驱动 VirtualBox）初始化失败。

用法：
    python tools/ensp_start_devices.py start [等待秒数]
    python tools/ensp_start_devices.py stop
    python tools/ensp_start_devices.py ports
    python tools/ensp_start_devices.py select        # 只做全选并打印状态栏
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from tools.ensp_ui import click_icon, shot, window_rect  # noqa: E402
from tools.vm_guest import capture_screen, guest_run  # noqa: E402
from tools.vm_hotkey import hotkey  # noqa: E402
from tools.vm_img import crop  # noqa: E402
from tools.vm_win import click  # noqa: E402

PORTS_LO, PORTS_HI = 2000, 2015


def _ports_ps() -> str:
    return (
        "Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue | "
        f"Where-Object {{ $_.LocalPort -ge {PORTS_LO} -and $_.LocalPort -le {PORTS_HI} }} | "
        "Sort-Object LocalPort | Select-Object LocalPort,OwningProcess | "
        "Format-Table -AutoSize | Out-String -Width 80"
    )


def ports() -> str:
    return guest_run(_ports_ps(), timeout=180)


def status_png(tag: str) -> str:
    """裁状态栏（含「总数/选中」）出来，便于人工核对。窗口不在时返回提示。"""
    rect = window_rect()
    if rect is None:
        return "<窗口未找到，跳过状态栏截图>"
    img = shot(BASE_DIR / "logs" / f"ensp_{tag}.png")
    x, y, w, h = rect
    out = BASE_DIR / "logs" / f"ensp_{tag}_status.png"
    crop(str(img), x + 4, y + h - 30, 340, 26, str(out), zoom=5)
    return str(out)


def select_all() -> str:
    """点画布空白取焦点 -> Ctrl+A 全选。"""
    rect = window_rect()
    if rect is None:
        return "eNSP 窗口未找到"
    x, y, w, h = rect
    cx, cy = x + int(w * 0.85), y + int(h * 0.55)
    click(cx, cy)
    time.sleep(0.8)
    msg = hotkey(["ctrl", "a"])
    time.sleep(1.2)
    return f"canvas=({cx},{cy}) {msg}"


def port_count() -> int:
    """当前已开放的 Telnet 端口数量。"""
    out = ports()
    n = 0
    for line in out.splitlines():
        parts = line.split()
        if parts and parts[0].isdigit() and PORTS_LO <= int(parts[0]) <= PORTS_HI:
            n += 1
    return n


def wait_ports_expect(expected: int, wait: int = 600, settle: int = 2) -> str:
    """等端口数达到 expected 并保持稳定。

    设备是**逐个**启动的，只看到第一个端口就返回会误判「已就绪」
    （实测：先出 2000，2001 还没起来就去登录会失败）。

    默认等待从 300s 提到 **600s**：AR2220 路由器比交换机慢得多，
    实测一个 4 台路由器 + 1 台交换机的拓扑，300s 只起来 1 台（交换机），
    4 台路由器全部超时 → 模型连不上，整个实验直接 0 分，看起来像模型不行，
    其实是没等够。

    另外加了「停止增长」判定：端口数长时间不再增加就提前放弃，
    别把已经坏掉的启动干等到超时。
    """
    # 等待期必须有心跳：这一段最长 900 秒，期间一条日志都不出，
    # 进程万一被回收（P20）或真的在克隆 AR_Base 磁盘，从日志上完全无法区分。
    def beat(msg: str) -> None:
        print(msg, flush=True)

    t0 = time.time()
    deadline = t0 + wait
    last = -1
    stall_since = time.time()
    while time.time() < deadline:
        n = port_count()
        beat(f"    端口 {n}/{expected}（已等 {int(time.time() - t0)}s）")
        if n >= expected and n == last:
            return ports()
        if n > last:
            last = n
            stall_since = time.time()  # 还在长，重置停滞计时
        elif time.time() - stall_since > 420 and n > 0:
            # 7 分钟没有任何新端口才放弃。
            # 阈值必须够大：eNSP 启动一台 AR2220 要先**克隆 AR_Base 磁盘**再拉起
            # VirtualBox 虚拟机，实测远超 4 分钟；判太激进会把正在克隆的路由器判死，
            # 表现为"只有交换机起来、路由器全都没起来"，很容易误判成设备坏了。
            return (f"停止增长：期望 {expected} 个端口，实际 {n} 个（420s 无新增）\n"
                    + ports())
        time.sleep(settle if n >= expected else 5)
    return f"超时：期望 {expected} 个端口，实际 {port_count()} 个\n" + ports()


def start_all(wait: int = 150) -> None:
    """边跑边打印（避免中途异常把已完成步骤的日志全丢掉）。"""
    def say(msg: str) -> None:
        print(msg, flush=True)

    say("[1] 全选: " + select_all())
    say("[2] 状态栏 -> " + status_png("sel"))

    say("[3] 点绿色启动: " + click_icon("green"))
    time.sleep(3)
    capture_screen(str(BASE_DIR / "logs" / "ensp_start_clicked.png"))
    say("    截图 -> logs/ensp_start_clicked.png")

    say(f"[4] 等待 Telnet {PORTS_LO}-{PORTS_HI} 端口 …")
    deadline = time.time() + wait
    hit = False
    while time.time() < deadline:
        p = ports()
        if str(PORTS_LO) in p:
            hit = True
            break
        time.sleep(5)
    say("端口已开放" if hit else "超时未见端口")
    say(ports())
    capture_screen(str(BASE_DIR / "logs" / "ensp_started.png"))
    say("状态栏 -> " + status_png("started"))


def stop_all() -> str:
    return (select_all() + "\n" + click_icon("red") + "\n" + ports())


def main(argv: list[str]) -> int:
    op = argv[1] if len(argv) > 1 else "ports"
    if op == "start":
        start_all(int(argv[2]) if len(argv) > 2 else 150)
    elif op == "stop":
        print(stop_all())
    elif op == "select":
        print(select_all())
        print(status_png("sel"))
    else:
        print(ports())
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
