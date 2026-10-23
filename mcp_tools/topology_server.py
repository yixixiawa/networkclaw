"""拓扑泛洪发现 MCP 服务端：让模型自己"探"出设备之间的连接与上下级关系。

本文件只做**注册中心**：建 FastMCP 实例，把 mcp_tools/tools/ 下单工具模块
装配进来。工具实现不在这里——一个工具一个文件（见 mcp_tools/tools/__init__.py）。

设计意图：
    手工维护的 `data/device_inventory.json#topology_notes` 会过期，而且写错了
    没人发现。设备自己"知道"邻居是谁（LLDP 邻居表 / MAC 地址表 / ARP 表），
    让模型在需要时主动泛洪这几张表，就能把「谁连着谁、谁是上级」从人工记录
    变成**实测事实**，还能顺带出图。

工具列表（实现文件 → 工具名）：
    tools/discover_topology.py        discover_topology(workers, timeout, roots, save, devices)
        逐个连接设备并泛洪只读命令，解析邻居关系、推导层级，返回报告 + Mermaid 图
    tools/load_discovered_topology.py load_discovered_topology()
        不重新泛洪，直接读上次落盘的结果（省时间）
    tools/topology_summary.py         topology_summary()
        只回紧凑摘要（适合直接塞进上下文）
    tools/topology_mermaid.py         topology_mermaid(direction)
        只要 Mermaid 图源码，便于贴进文档

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

mcp = FastMCP("Network-Topology-Flood")

# ---------------------------------------------------------------- 工具装配
# 一个工具一个文件：从 mcp_tools/tools/<工具名>.py 导入同名函数后注册。
from mcp_tools.tools.discover_topology import discover_topology  # noqa: E402
from mcp_tools.tools.load_discovered_topology import (  # noqa: E402
    load_discovered_topology,
)
from mcp_tools.tools.topology_mermaid import topology_mermaid  # noqa: E402
from mcp_tools.tools.topology_summary import topology_summary  # noqa: E402

mcp.tool(discover_topology)
mcp.tool(load_discovered_topology)
mcp.tool(topology_summary)
mcp.tool(topology_mermaid)


if __name__ == "__main__":
    mcp.run(transport="stdio")
