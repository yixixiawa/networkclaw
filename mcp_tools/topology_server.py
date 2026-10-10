"""拓扑泛洪发现 MCP 服务端：让模型自己"探"出设备之间的连接与上下级关系。

设计意图：
    手工维护的 `data/device_inventory.json#topology_notes` 会过期，而且写错了
    没人发现。设备自己"知道"邻居是谁（LLDP 邻居表 / MAC 地址表 / ARP 表），
    让模型在需要时主动泛洪这几张表，就能把「谁连着谁、谁是上级」从人工记录
    变成**实测事实**，还能顺带出图。

工具列表：
1. discover_topology(workers, timeout, roots, save)
   - 逐个连接设备并泛洪只读命令（display lldp neighbor / mac-address / arp），
     解析邻居关系、推导层级与上下级，返回文字报告 + Mermaid 图。
     耗时较长（每台设备一次完整登录），必要时使用。
2. load_discovered_topology()
   - 不重新泛洪，直接读上次落盘的结果（省时间）。
3. topology_summary()
   - 只回紧凑摘要（适合直接塞进上下文）；若从未发现过会提示先跑 discover。
4. topology_mermaid()
   - 只要 Mermaid 图源码，便于贴进文档或让用户直接渲染。

安全性：
    本服务端只下发 `display` / `show` 开头的**只读**命令，全部命中
    command_guard 的 `allow` 级；不会修改任何设备配置。
"""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from fastmcp import FastMCP  # noqa: E402

from core import topology_flood  # noqa: E402
from core import device_registry  # noqa: E402

mcp = FastMCP("Network-Topology-Flood")

MAX_REPORT_CHARS = 8000


def _truncate(text: str, limit: int = MAX_REPORT_CHARS) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n...（报告共 {len(text)} 字，已截断）"


def _devices_for_flood() -> list[dict]:
    """取可泛洪的设备（当前只支持 Telnet 通道；串口需要用户给 COM 口，见下）。"""
    return [d for d in device_registry.list_devices() if d.get("transport") == "telnet"]


@mcp.tool
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
    except Exception as e:
        return f"拓扑泛洪失败：{type(e).__name__}: {e}"

    report = topology_flood.render_text(topo)
    tail = ""
    if save:
        tail = (f"\n\n（已落盘到 data/topology_discovered.json，"
                f"下次可直接用 load_discovered_topology 复用）")
    return _truncate(report) + tail


@mcp.tool
def load_discovered_topology() -> str:
    """读取上次泛洪发现的拓扑结果（不重新连设备，秒回）。

    若从未发现过或快照已过期，会提示改用 discover_topology 重新探测。
    """
    topo = topology_flood.load_snapshot()
    if topo is None:
        return ("还没有拓扑发现结果。请先调用 discover_topology 做一次泛洪探测"
                "（会对每台设备下发 display lldp neighbor 等只读命令）。")
    age = topology_flood.snapshot_age_min()
    head = f"（结果为 {topo.generated} 生成"
    if age is not None:
        head += f"，约 {age} 分钟前"
    head += "；如需最新状态请重新 discover_topology）\n\n"
    return head + _truncate(topology_flood.render_text(topo))


@mcp.tool
def topology_summary() -> str:
    """返回拓扑的紧凑摘要（设备层级 + 链路 + 上下级），适合直接放进上下文。

    比 load_discovered_topology 短得多；用于回答「现在拓扑是什么样」这类问题。
    """
    topo = topology_flood.load_snapshot()
    if topo is None:
        return ("还没有拓扑发现结果。先调用 discover_topology 探测一次，"
                "之后就可以用本工具快速读取摘要。")
    age = topology_flood.snapshot_age_min()
    body = topology_flood.context_for_model(topo)
    if age is not None:
        body += f"\n（快照约 {age} 分钟前生成）"
    return body


@mcp.tool
def topology_mermaid(direction: str = "TD") -> str:
    """只返回 Mermaid 拓扑图源码（可贴进 Markdown / 腾讯文档直接渲染成图）。

    Args:
        direction: 布局方向，TD（上下，默认）/ LR（左右）/ BT / RL
    """
    topo = topology_flood.load_snapshot()
    if topo is None:
        return ("还没有拓扑发现结果。先调用 discover_topology 探测一次。")
    d = direction if direction in ("TD", "LR", "BT", "RL") else "TD"
    return f"```mermaid\n{topology_flood.render_mermaid(topo, direction=d)}\n```"


if __name__ == "__main__":
    mcp.run(transport="stdio")
