"""MCP 工具 get_topology_snapshot：读最近一次拓扑巡检的快照。

作用点：**免推理**。回答涉及当前拓扑的问题前先看有没有现成结论，有就直接用；
结论过期或用户说拓扑变了时改用 capture_topology。
"""
from __future__ import annotations

from mcp_tools.tools import _bootstrap  # noqa: F401  (sys.path 兜底)


def get_topology_snapshot() -> str:
    """读取最近一次自动拓扑巡检的结论快照（不重新截图、不推理，瞬时返回）。

    什么时候用：回答涉及当前拓扑的问题前，先看这里有没有现成结论；
    结论过期或用户说拓扑变了时改用 capture_topology。
    """
    from core import auto_topology

    snap = auto_topology.load_snapshot()
    if not snap or not (snap.get("description") or "").strip():
        return ("（尚无拓扑快照。可调用 capture_topology 实时查看，"
                "或请用户手动截图后用 analyze_topology_image 识读）")

    age = auto_topology.snapshot_age_h(snap)
    head = f"快照时间：{snap.get('time', '未知')}"
    if age is not None:
        stale = "，已过期，建议用 capture_topology 重新查看" if age > auto_topology.SNAPSHOT_MAX_AGE_H else ""
        head += f"（{age:.1f} 小时前{stale}）"
    return f"{head}\n来源窗口：{snap.get('window', '')}\n\n{snap['description']}"
