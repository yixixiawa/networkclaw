"""一条命令把一个实验从零拉到「设备可 Telnet 配置」状态。

流程（全自动，不需要人在 VM 桌面上点任何东西）：
    1. 关干扰窗口 + （可选）杀掉旧 eNSP
    2. 以管理员身份拉起 eNSP 并打开 <实验>.topo       ← 必须提权，路由器要驱动 VirtualBox
    3. 点画布 → Ctrl+A 全选 → 点工具栏绿色 ▶「开启设备」
    4. 等 Telnet 2000+ 端口开放
    5. Telnet 逐台探测，打印设备 ↔ 端口映射

用法：
    python tools/lab_up.py 01
    python tools/lab_up.py 01 --fresh          # 先杀掉旧 eNSP
    python tools/lab_up.py 01 --no-wait 120    # 缩短等待
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from tools.ensp_open_lab import (  # noqa: E402
    best_topo, close_nuisance, guest_path, kill_ensp, launch, resolve,
)
from tools.ensp_start_devices import (  # noqa: E402
    PORTS_LO, ports, select_all, status_png, wait_ports_expect,
)
from tools.ensp_ui import click_icon  # noqa: E402
from tools.lab_probe_devices import is_router, load_devices, probe_all  # noqa: E402
from tools.nested_virt import router_can_boot  # noqa: E402

HOST = "192.168.10.130"
# eNSP 在路由器**开始启动**时就开放了 Telnet 端口，但 AR2220 的 VRP 还要加载好几分钟。
# 端口一到齐就去登录，只会拿到 '##\x00'（2026-10-01 实验 03 实测 AR1/AR2/AR3 全挂）。
ROUTER_SETTLE = 120


def up(num: str, fresh: bool = False, wait: int = 300) -> None:
    def say(m: str) -> None:
        print(m, flush=True)

    name, d = resolve(num)
    topo = best_topo(d)
    if topo is None:
        raise SystemExit(f"实验「{name}」没有 .topo")
    say(f"### 实验 {num}：{name}")

    if fresh:
        say("[0] 关闭旧 eNSP: " + kill_ensp().strip())
    say("[1] 关干扰窗口: " + close_nuisance().strip()[:120])
    say("[2] 启动 eNSP: " + launch(guest_path(topo)).strip())
    time.sleep(6)

    devs = load_devices(num)
    expected = len(devs)
    # eNSP 启动后几秒内可能才弹「eNSP 帮助（检查虚拟网卡设置）」，正好盖住
    # 画布与工具栏——Ctrl+A 全选落空、绿色 ▶ 也搜不到（2026-10-01 实测）。
    # 所以拉起之后**再清一次**干扰窗口，然后才碰画布。
    say("[2b] 启动后再清一次干扰窗口: " + close_nuisance().strip()[:120])
    time.sleep(1)

    say(f"[3] 全选: " + select_all().strip())
    say("[4] 状态栏 -> " + status_png("sel"))
    res = click_icon("green").strip()
    if "未找到" in res:
        # 弹窗可能比 6 秒更晚出现，或第一次没关掉：清一次 → 重新全选 → 再点
        say("[5] 点绿色开启设备: " + res)
        say("[5a] 绿色图标没找到，清理弹窗后重试")
        say("     关干扰窗口: " + close_nuisance().strip()[:120])
        time.sleep(1)
        say("     再全选: " + select_all().strip())
        res = click_icon("green").strip()
        say("[5b] 重试点绿色开启设备: " + res)
    else:
        say("[5] 点绿色开启设备: " + res)

    say(f"[6] 等待 {expected} 个 Telnet 端口（{PORTS_LO}+）…")
    say(wait_ports_expect(expected, wait=wait))
    # routers == [] 表示纯交换机，不必静置
    routers = [m for _, _, m in devs if is_router(m)]
    if routers and router_can_boot():
        say(f"[6b] 拓扑含 {len(routers)} 台路由器，端口开放 ≠ VRP 就绪，"
            f"额外等 {ROUTER_SETTLE}s …")
        for left in range(ROUTER_SETTLE, 0, -30):
            say(f"     还需 {left}s")
            time.sleep(30)
    elif routers:
        # 嵌套虚拟化不可用时 AR 是 VirtualBox 虚拟机、根本起不来（issues P23），
        # 静置只是白等：每个含路由器的实验省 2 分钟。
        say(f"[6b] 含 {len(routers)} 台路由器，但本机不支持嵌套虚拟化（P23：AR 起不来），"
            f"跳过 {ROUTER_SETTLE}s 静置")
    say("[7] 设备探测：")
    probe_all(num, host=HOST)


def main(argv: list[str]) -> int:
    num = argv[1] if len(argv) > 1 else "01"
    wait = 300
    if "--no-wait" in argv:
        wait = int(argv[argv.index("--no-wait") + 1])
    up(num, fresh="--fresh" in argv, wait=wait)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
