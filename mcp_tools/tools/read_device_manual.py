"""MCP 工具 read_device_manual：读某台设备的操作手册。

作用点：**读手册**。操作设备前先读它：常用配置、注意事项。
默认当前对话；显式传 session 才跨对话只读（用户问「上次那个会话」时才用）。
"""
from __future__ import annotations

from mcp_tools.tools import _bootstrap  # noqa: F401  (sys.path 兜底)


def read_device_manual(device: str, session: str = "") -> str:
    """读取某台设备的操作手册（常用配置、注意事项）。

    Args:
        device: 设备名或地址，例如 SW1 / LSW1 / 192.168.1.10:2003 / COM3
        session: 可选，显式读取**其他对话**的手册（用户问「上次那个会话」时才用）；
            留空表示当前对话
    """
    from core import device_manual, device_registry
    from mcp_tools.tools._manual_common import resolve, truncate_manual

    r, err = resolve(device, session)
    if r is None:
        # 歧义必须拒绝（同名两台，读错就是串味）；「查无此设备」则按旧语义回答
        # 「没有手册」，并附上可查询清单——空答案对模型没有下一步动作。
        if device_registry.resolve_device(device, session).get("reason") == "ambiguous":
            return err
        miss = (f"会话「{session}」里没有设备「{device}」的手册。"
                if session else
                f"当前会话里设备「{device}」还没有手册。")
        return miss + f"\n{err}\n建议先用 create_device_manual 建档，再执行配置。"

    name = r["name"]
    try:
        text = device_manual.read_manual(name, session)
    except device_manual.ManualError as e:
        return str(e)
    if not text:
        if session:
            return (f"会话「{session}」里没有设备「{name}」的手册。"
                    f"可先用 list_session_skills 看该会话到底有哪些设备。")
        return (f"当前会话里设备「{name}」还没有手册（{r.get('host') or device}）。"
                f"建议先用 create_device_manual 建档，再执行配置；"
                f"配置验证有效后用 update_device_manual_section 沉淀。")
    head = ""
    if r.get("matched") not in ("name", "key"):
        head = f"（按「{device}」解析到设备 {name}）\n\n"
    return head + truncate_manual(text)
