"""MCP 工具 topology_mermaid：只返回 Mermaid 拓扑图源码。

作用点：**出图**。贴进 Markdown / 腾讯文档即可渲染，不需要额外工具。
"""
from __future__ import annotations

from mcp_tools.tools import _bootstrap  # noqa: F401  (sys.path 兜底)


def topology_mermaid(direction: str = "TD") -> str:
    """只返回 Mermaid 拓扑图源码（可贴进 Markdown / 腾讯文档直接渲染成图）。

    Args:
        direction: 布局方向，TD（上下，默认）/ LR（左右）/ BT / RL
    """
    from core import topology_flood

    topo = topology_flood.load_snapshot()
    if topo is None:
        return "还没有拓扑发现结果。先调用 discover_topology 探测一次。"
    d = direction if direction in ("TD", "LR", "BT", "RL") else "TD"
    return f"```mermaid\n{topology_flood.render_mermaid(topo, direction=d)}\n```"
