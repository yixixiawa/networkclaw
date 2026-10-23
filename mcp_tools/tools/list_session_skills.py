"""MCP 工具 list_session_skills：所有对话各自的设备技能分布（只读总览）。

作用点：**跨对话索引**。回答「上次那个会话里给 SW1 配过什么」时，先用它拿到
会话标识，再用 read_device_manual(device, session=...) 显式读那个会话的手册。

日常操作不需要调它——默认只看当前对话的技能。
"""
from __future__ import annotations

from mcp_tools.tools import _bootstrap  # noqa: F401  (sys.path 兜底)


def list_session_skills() -> str:
    """查看**所有对话**各自的设备技能分布（只读总览，不返回手册正文）。

    用于回答「上次那个会话里给 SW1 配过什么」这类跨对话问题：先从这里拿到
    会话标识，再用 read_device_manual(device, session=...) 显式读那个会话的手册。
    日常操作不需要调它——默认只看当前对话的技能。
    """
    from core import device_manual

    rows = device_manual.sessions_overview()
    if not rows:
        return ("还没有任何对话产生过设备技能。首次接触设备时用 create_device_manual "
                "建档，技能会存放在 session/<当前会话>/skill/<设备名>/ 下。")

    out = [f"共 {len(rows)} 个对话拥有设备技能（目录 session/）："]
    for s in rows:
        mark = "← 当前对话" if s["current"] else ""
        devs = "、".join(s["detail"]) or "（无设备技能）"
        out.append(f"  [{s['sid']}] 更新于 {s['updated']}，{s['files']} 个文件 {mark}")
        out.append(f"      {devs}")
    out.append("读取某个对话的手册：read_device_manual(device, session=\"<上面的会话标识>\")")
    return "\n".join(out)
