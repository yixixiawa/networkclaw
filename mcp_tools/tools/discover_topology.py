"""MCP 工具 discover_topology：泛洪探测设备，发现链路与上下级关系。

作用点：**实测拓扑**。手工维护的 topology_notes 会过期，而设备自己"知道"
邻居是谁（LLDP 邻居表 / MAC 地址表 / ARP 表）。逐台读出来就能把「谁连着谁、
谁是上级」从人工记录变成事实，还能顺带出图。

只读保证：只下发 display/show 开头的命令，全部命中 command_guard 的 allow 级。

归属服务端：Network-Topology-Flood（mcp_tools/topology_server.py）
"""
from __future__ import annotations

from mcp_tools.tools import _bootstrap  # noqa: F401  (sys.path 兜底)

MAX_REPORT_CHARS = 8000


def _devices_for_flood() -> list[dict]:
    """取可泛洪的设备（当前只支持 Telnet 通道；串口需要用户给 COM 口）。"""
    from core import device_registry

    return [d for d in device_registry.list_devices() if d.get("transport") == "telnet"]


def discover_topology(workers: int = 4, timeout: float = 25.0,
                      roots: str = "", save: bool = True,
                      devices: str = "") -> str:
    """泛洪探测各设备，自动发现链路与上下级关系，并生成拓扑图。

    **做什么**：对每台设备建立独立连接，依次下发只读命令
    `display lldp neighbor brief`（思科为 `show cdp neighbors detail`）、
    `display mac-address`、`display arp`、`display ip interface brief`，
    解析邻居表与地址表，推导出「谁连谁、谁是上级」，并输出 Mermaid 拓扑图。

    **前提**：设备需已开启 LLDP（华为 `lldp enable`）且对端设置了 sysname；
    未开 LLDP 的设备会被标注为「未读到邻居」，不会导致整体失败。

    **耗时**：每台设备一次完整 Telnet 登录 + 若干条命令，4 台约 20~60 秒。
    只在需要拓扑信息时调用；已有结果时优先用 load_discovered_topology 复用。

    Args:
        workers: 并发探测的设备数，默认 4（eNSP 上建议不超过 4，避免抢端口）
        timeout: 单条命令超时秒数，默认 25
        roots: 指定根/核心设备（逗号分隔，如 "R1"）。留空则按「没有上行邻居」自动判定
        save: 是否把结果落盘到 data/topology_discovered.json（默认 True，便于复用）
        devices: 只探测指定设备（逗号分隔，如 "SW1,SW2"）。留空探测清单里全部 Telnet 设备
    """
    from core import topology_flood

    devs = _devices_for_flood()
    if not devs:
        return ("没有可泛洪的设备：data/device_inventory.json 里没有 Telnet 设备。"
                "（串口设备需要先由用户提供 COM 口信息）")
    if devices.strip():
        want = {topology_flood.clean_name(x) for x in devices.split(",") if x.strip()}
        devs = [d for d in devs if topology_flood.clean_name(d.get("name", "")) in want]
        if not devs:
            return f"指定的设备 {devices} 不在清单里。"

    root_list = [x.strip() for x in roots.split(",") if x.strip()] or None
    try:
        topo = topology_flood.discover(
            devs, roots=root_list,
            workers=max(1, int(workers)), timeout=float(timeout), save=bool(save))
    except Exception as e:  # noqa: BLE001  工具不抛异常
        return f"拓扑泛洪失败：{type(e).__name__}: {e}"

    report = topology_flood.render_text(topo)
    if len(report) > MAX_REPORT_CHARS:
        report = report[:MAX_REPORT_CHARS] + f"\n...（报告共 {len(report)} 字，已截断）"
    tail = ""
    if save:
        tail = ("\n\n（已落盘到 data/topology_discovered.json，"
                "下次可直接用 load_discovered_topology 复用）")
        # 会话副本：GUI 的拓扑页签按会话隔离，只读 session/<sid>/ 下的这一份。
        # MCP 子进程每次工具调用前都会读会话指针，这里能拿到当前 sid。
        try:
            from core.session_skills import current, session_dir

            sid = current()
            if sid:
                topology_flood.save_snapshot(
                    topo, path=session_dir(sid) / "topology_discovered.json")
                tail += f"\n（本会话快照：session/{sid}/topology_discovered.json）"
        except Exception:  # noqa: BLE001  会话副本失败不影响全局快照与报告
            pass
    return report + tail
