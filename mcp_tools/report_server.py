"""数据报告 MCP 服务端：让**本地模型自己**在跑完后导出整个工作流的内容。

本文件只做**注册中心**：建 FastMCP 实例，把 mcp_tools/tools/ 下单工具模块
装配进来。工具实现不在这里——一个工具一个文件（见 mcp_tools/tools/__init__.py）。

设计意图（用户要求）：
    一次对话/一个实验跑完，产生的信息散落在会话技能目录、运行日志、实验报告三处。
    模型（或用户）需要一个动作把它们汇总成一份自包含报告——本服务端提供这个出口。

    导出的报告包含：
      · 总览（设备数、手册数、命令数、模型调用数、工具调用数）
      · 每台设备的技能与执行过的命令序列
      · 工作流逐步记录（每一步的工具、目标、输入命令、设备回显）
      · 过程事件（设备探测、验收比对、实验起止）
      · 实验报告全文（若该会话对应一个 eNSP 实验）

    与「一个对话一套技能」的关系：默认只导出**当前对话**的工作流；需要复盘别的对话时
    显式传 session 参数（只读，不会污染当前会话的技能）。

工具列表（实现文件 → 工具名）：
    tools/export_workflow_report.py    export_workflow_report([session, format, days])
        导出工作流报告（Markdown / JSON / 两者），返回文件路径与统计摘要
    tools/workflow_report_overview.py  workflow_report_overview([session])
        只看统计摘要（不落盘），用于快速确认「这次跑了多少、做了什么」
    tools/list_report_sessions.py      list_report_sessions()
        列出可导出报告的会话（当前对话 + 其他对话）

运行方式（stdio，由 MCP 客户端拉起）：
    python mcp_tools/report_server.py
"""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from fastmcp import FastMCP  # noqa: E402

mcp = FastMCP("Network-Data-Report")

# ---------------------------------------------------------------- 工具装配
# 一个工具一个文件：从 mcp_tools/tools/<工具名>.py 导入同名函数后注册。
from mcp_tools.tools.export_workflow_report import export_workflow_report  # noqa: E402
from mcp_tools.tools.list_report_sessions import list_report_sessions  # noqa: E402
from mcp_tools.tools.workflow_report_overview import (  # noqa: E402
    workflow_report_overview,
)

mcp.tool(export_workflow_report)
mcp.tool(workflow_report_overview)
mcp.tool(list_report_sessions)


if __name__ == "__main__":
    mcp.run(transport="stdio")
