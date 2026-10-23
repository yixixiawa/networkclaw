"""MCP 工具 read_device_manual：读某台设备的操作手册。

作用点：**读手册**。操作设备前先读它：常用配置、注意事项。
默认当前对话；显式传 session 才跨对话只读（用户问「上次那个会话」时才用）。
"""
from __future__ import annotations

from mcp_tools.tools import _bootstrap  # noqa: F401  (sys.path 兜底)


def read_device_manual(device: str, session: str = "") -> str:
    """读取某台设备的操作手册（常用配置、注意事项）。

    Args:
        device: 设备名，例如 SW1 / R1 / COM3
        session: 可选，显式读取**其他对话**的手册（用户问「上次那个会话」时才用）；
            留空表示当前对话
    """
    from core import device_manual
    from mcp_tools.tools._manual_common import truncate_manual

    try:
        text = device_manual.read_manual(device, session)
    except device_manual.ManualError as e:
        return str(e)
    if not text:
        if session:
            return (f"会话「{session}」里没有设备「{device}」的手册。"
                    f"可先用 list_session_skills 看该会话到底有哪些设备。")
        return (f"当前会话里设备「{device}」还没有手册。建议先用 create_device_manual 建档，"
                f"再执行配置；配置验证有效后用 update_device_manual_section 沉淀。")
    return truncate_manual(text)
