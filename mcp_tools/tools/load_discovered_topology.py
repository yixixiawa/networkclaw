"""MCP 工具 load_discovered_topology：读取上次泛洪发现的拓扑结果。

作用点：**复用**。不重新连设备、秒回；已有结果时优先用它而不是重新 discover。
"""
from __future__ import annotations

from mcp_tools.tools import _bootstrap  # noqa: F401  (sys.path 兜底)

MAX_REPORT_CHARS = 8000


def load_discovered_topology() -> str:
    """读取上次泛洪发现的拓扑结果（不重新连设备，秒回）。

    若从未发现过或快照已过期，会提示改用 discover_topology 重新探测。
    """
    from core import topology_flood

    topo = topology_flood.load_snapshot()
    if topo is None:
        return ("还没有拓扑发现结果。请先调用 discover_topology 做一次泛洪探测"
                "（会对每台设备下发 display lldp neighbor 等只读命令）。")

    age = topology_flood.snapshot_age_min()
    head = f"（结果为 {topo.generated} 生成"
    if age is not None:
        head += f"，约 {age} 分钟前"
    head += "；如需最新状态请重新 discover_topology）\n\n"

    body = topology_flood.render_text(topo)
    if len(body) > MAX_REPORT_CHARS:
        body = body[:MAX_REPORT_CHARS] + f"\n...（报告共 {len(body)} 字，已截断）"
    return head + body
