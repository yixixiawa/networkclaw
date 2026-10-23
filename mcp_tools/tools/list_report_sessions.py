"""MCP 工具 list_report_sessions：列出可导出报告的会话。

作用点：**发现**。回答「都有哪些对话跑过实验」；拿到会话标识后可传给
export_workflow_report(session=...) 导出那个对话的报告。
"""
from __future__ import annotations

from mcp_tools.tools import _bootstrap  # noqa: F401  (sys.path 兜底)


def list_report_sessions() -> str:
    """列出可导出报告的会话（当前对话 + 其他对话，只读总览）。

    用于回答「都有哪些对话跑过实验」；拿到会话标识后可传给
    export_workflow_report(session=...) 导出那个对话的报告。
    """
    from core import session_skills

    rows = session_skills.list_sessions()
    if not rows:
        return "还没有任何会话产生过设备技能/运行日志。"

    out = [f"共 {len(rows)} 个会话（目录 session/）："]
    for s in rows:
        mark = " ← 当前对话" if s["current"] else ""
        out.append(f"  [{s['sid']}] 更新于 {s['updated']}，{s['files']} 个文件{mark}")
    out.append("导出某个会话：export_workflow_report(session=\"<会话标识>\")")
    return "\n".join(out)
