"""MCP 工具 topology_summary：拓扑的紧凑摘要。

作用点：**省 context**。只给层级 + 链路 + 上下级，比完整报告短得多；
回答「现在拓扑是什么样」这类问题时用这个，不要用 load_discovered_topology。
"""
from __future__ import annotations

from mcp_tools.tools import _bootstrap  # noqa: F401  (sys.path 兜底)


def topology_summary() -> str:
    """返回拓扑的紧凑摘要（设备层级 + 链路 + 上下级），适合直接放进上下文。

    比 load_discovered_topology 短得多；用于回答「现在拓扑是什么样」这类问题。
    """
    from core import topology_flood

    topo = topology_flood.load_snapshot()
    if topo is None:
        return ("还没有拓扑发现结果。先调用 discover_topology 探测一次，"
                "之后就可以用本工具快速读取摘要。")

    body = topology_flood.context_for_model(topo)
    age = topology_flood.snapshot_age_min()
    if age is not None:
        body += f"\n（快照约 {age} 分钟前生成）"
    return body
