"""本机能否跑 eNSP 的 AR 路由器？——取决于**嵌套虚拟化**。

背景（详见 data/lab_reports/issues.md 的 P23）：
- eNSP 的 AR 系列（AR1220/AR2220）不是进程模拟，而是来宾里的一台
  **VirtualBox 虚拟机**（AR_Base 克隆），Guest OS type 是 Linux，必须靠
  VT-x / AMD-V 才能跑起来；交换机是 eNSP 内部进程模拟，不依赖嵌套虚拟化。
- 这台宿主机本身开了 **VBS / Hyper-V**（`systeminfo` 显示
  「基于虚拟化的安全性: 状态： 正在运行」「已检测到虚拟机监控程序」）。
  VMware Workstation 在这个模式下走 Windows Hypervisor Platform，
  **不再支持把虚拟化指令透传给来宾**：给 VMX 加 `vhv.enable = "TRUE"` 后
  `vmrun start` 直接报「操作已被用户取消」，VM 起不来（去掉立刻恢复正常）。
- 来宾里的证据也对得上：`eNSP\\vboxserver\\AR_Base\\Logs\\VBox.log` 写着
  `HM: HMR3Init: Falling back to raw-mode: AMD-V is not available`，
  AR 虚拟机起来 7 秒就 TERMINATED → PoweredOff；
  `eNSP\\tools\\eNSP_VBoxManage.log` 跟着报
  `Machine 'AR_Clone_xxx' is not currently running`。
  所以 eNSP 一开放 Telnet 端口（它以为设备起来了），背后根本没有 VRP，
  登录回显恒为 `'##\\x00'` —— 这就是 P22 的真根因。

结论：只要 nested 虚拟化不可用，含 AR 的实验**路由器必然 0 分**，
为此多等 120s 静置、60s 登录超时 × 6 次重试纯属白烧。

用法：
    python tools/nested_virt.py            # 打印结论（带缓存）
    python tools/nested_virt.py --force    # 忽略缓存重新探测

其它模块：
    from tools.nested_virt import router_can_boot
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
CACHE = BASE_DIR / "data" / "lab_reports" / ".nested_virt"
CACHE_TTL = 12 * 3600  # 12 小时内不重复跑 systeminfo（它本身要十几秒）

# systeminfo 里说明「本机跑在虚拟机监控程序上 / VBS 已开」的行
_BLOCKERS = [
    r"基于虚拟化的安全性.*状态[:：]\s*正在运行",
    r"Virtualization[- ]Based Security.*Running",
    r"已检测到虚拟机监控程序",
    r"A hypervisor has been detected",
]

_V: bool | None = None


def _host_has_hypervisor() -> bool | None:
    """宿主机是否在跑 hypervisor（VBS/Hyper-V）。探测失败返回 None。"""
    try:
        p = subprocess.run(["systeminfo"], capture_output=True, timeout=180)
    except (OSError, subprocess.TimeoutExpired):
        return None
    txt = p.stdout.decode("gbk", "replace")
    if not txt.strip():
        txt = p.stdout.decode("utf-8", "replace")
    for pat in _BLOCKERS:
        if re.search(pat, txt, re.I):
            return True
    return False if txt.strip() else None


def router_can_boot(force: bool = False) -> bool:
    """eNSP 的 AR 路由器在本机有没有可能起来（结果带缓存）。

    返回 True 表示「没发现阻碍」，不代表一定成功；False 表示已确认不可能。
    探测不到真相时保守返回 True——宁可多等，也不要把本该成功的实验跳过。
    """
    global _V
    if _V is not None and not force:
        return _V

    if not force and CACHE.exists():
        try:
            head = CACHE.read_text(encoding="utf-8").strip().splitlines()
            val, ts = head[0].strip(), float(head[1])
            if val in ("0", "1") and time.time() - ts < CACHE_TTL:
                _V = (val == "1")
                return _V
        except Exception:  # noqa: BLE001
            pass

    hv = _host_has_hypervisor()
    if os.environ.get("NETWORKCLAW_NESTED_VIRT") in ("0", "1"):
        val = os.environ["NETWORKCLAW_NESTED_VIRT"] == "1"
    elif hv is None:
        val = True  # 没探出来就按“可以”处理（保守：不减少等待）
    else:
        val = not hv

    _V = val
    try:
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        CACHE.write_text(f"{int(val)}\n{time.time()}\n", encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass
    return val


def main() -> int:
    force = "--force" in sys.argv
    ok = router_can_boot(force=force)
    print(f"嵌套虚拟化可用 = {ok}")
    if not ok:
        print("→ eNSP 的 AR 系列在本机不可能起来（详见 issues.md P23）。")
        print("  含路由器的实验只能拿到交换机那部分的分，不必为 AR 白白等待。")
    else:
        print("→ 未发现阻碍，AR 有可能起来（仍以实际登录探测结果为准）。")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
