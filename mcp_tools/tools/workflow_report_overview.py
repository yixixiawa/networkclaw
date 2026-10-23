"""MCP 工具 workflow_report_overview：只看工作流统计摘要（不落盘）。

作用点：**先看一眼再决定要不要导出**。模型跑完后先用它确认「这次到底跑了多少、
做了什么」，避免盲目导出 48KB 的报告。
"""
from __future__ import annotations

from mcp_tools.tools import _bootstrap  # noqa: F401  (sys.path 兜底)

MAX_OVERVIEW_CHARS = 6000


def workflow_report_overview(session: str = "") -> str:
    """查看工作流统计摘要（不写文件），用于快速确认这次跑了什么。

    返回：会话标识、涉及设备、手册数量、命令条数、模型/工具调用次数、
    以及每台设备执行过的命令条数。要看逐条明细请用 export_workflow_report。

    Args:
        session: 会话标识；留空表示当前对话
    """
    from pathlib import Path

    from core import data_report, session_skills

    try:
        data = data_report.collect(session)
    except session_skills.SessionError as e:
        return f"读取失败：{e}"

    c = data["counts"]
    lines = [
        f"会话：{data['session']}"
        + ("（当前对话）" if data["is_current"] else "（指定会话）"),
        f"数据日期：{'、'.join(data['days']) or '（无运行日志）'}",
        "",
        f"设备 {data['device_count']} 台｜手册 {c['manuals']} 份｜"
        f"命令历史 {c['history_total']} 条（成功执行 {c['history_executed']}）",
        f"模型调用 {c['llm_calls']} 次｜工具调用 {c['tool_steps']} 次｜"
        f"过程事件 {c['events']} 条",
    ]
    if data["devices"]:
        lines += ["", "各设备："]
        for d in data["devices"]:
            flag = "有手册" if d["has_manual"] else "无手册"
            lines.append(f"  {d['device']}：{flag}，命令 {d['history_total']} 条"
                         f"（执行 {d['history_executed']}）")
    if data["lab_report_path"]:
        lines += ["", f"实验报告：{Path(data['lab_report_path']).name}"]
    if data["other_sessions"]:
        lines += ["", f"另有 {len(data['other_sessions'])} 个对话"
                      f"（相互隔离，用 session 参数可指定导出）"]
    return "\n".join(lines)[:MAX_OVERVIEW_CHARS]
