"""MCP 工具 export_workflow_report：导出整轮工作流报告。

作用点：**产出报告文件**。模型的「跑完了」不止是说完一句话，还要留下可复盘、
可当语料的产物。默认只导当前对话——与「一个对话一套技能」的隔离语义一致。
"""
from __future__ import annotations

from mcp_tools.tools import _bootstrap  # noqa: F401  (sys.path 兜底)


def export_workflow_report(session: str = "", format: str = "md",
                           days: int = 3) -> str:
    """导出当前对话（或指定会话）的完整工作流报告。

    跑完实验/配置后调用它，把「这次做了什么」汇总成一份自包含报告：
    设备技能、逐条命令历史、逐步的工具调用与设备回显、验收结论。
    默认只导出当前对话，不影响也不包含其他对话的内容。

    Args:
        session: 会话标识；留空表示当前对话（推荐留空）。
            仅在用户明确要求复盘另一个对话时才传具体标识。
        format: 输出格式，md（默认，人可读）/ json（结构化）/ both（两者都出）
        days: 回溯运行日志的天数，默认 3（跨越午夜的实验也能取全）
    """
    from core import data_report, session_skills

    fmt = (format or "md").strip().lower()
    if fmt not in ("md", "json", "both"):
        return f"format 只能是 md / json / both，收到的是「{format}」"
    try:
        res = data_report.export(session, days=days, fmt=fmt)
    except session_skills.SessionError as e:
        return f"导出失败：{e}"
    except OSError as e:
        return f"导出失败（文件错误）：{e}"
    return data_report.summary_text(res)
