"""MCP 工具 list_device_manuals：当前会话的设备建档情况。

作用点：**决策入口**。首次处理某台设备前先调它，决定是「读已有手册」
还是「先建档」。只列当前对话的技能——其他对话的记忆刻意不搬过来。
"""
from __future__ import annotations

from mcp_tools.tools import _bootstrap  # noqa: F401  (sys.path 兜底)


def list_device_manuals() -> str:
    """列出设备建档情况：当前会话里哪些设备已有手册、哪些还没建（含手册更新时间）。

    首次处理某台设备前先调它，决定是「读已有手册」还是「先建档」。
    注意：只看**当前对话**的技能；其他对话的设备记忆相互隔离，不在这里出现。
    """
    from core import device_manual, device_registry, session_skills
    from mcp_tools.tools._manual_common import where

    try:
        known = device_registry.list_devices()
        has = {m["name"]: m for m in device_manual.list_manuals()}
    except Exception as e:  # noqa: BLE001  工具不抛异常
        return f"读取设备清单失败：{type(e).__name__}: {e}"

    lines: list[str] = []
    missing: list[str] = []
    for d in known:
        name = d.get("name") or d.get("key", "")
        m = has.get(name)
        if m:
            lines.append(f"  [{name}] 已有手册（{m['bytes']} 字节，更新于 {m['updated']}，"
                         f"历史 {m['history_lines']} 条）")
        else:
            missing.append(name)

    extra = [m for n, m in has.items() if n not in {d.get('name') for d in known}]
    out = [f"设备共 {len(known)} 台，本会话已建档 {len(has)} 台"
           f"（{where()}，目录 session/{session_skills.current()}/skill/）："]
    out += lines or ["  （暂无手册）"]
    if missing:
        out.append(f"尚未建档（首次操作前建议先 create_device_manual）：{', '.join(missing)}")
    if extra:
        out.append("手册存在但不在当前清单里的设备："
                   + ", ".join(f"{m['name']}（{m['updated']}）" for m in extra))
    # 让模型知道「还有别的对话」，但不把别处的内容搬过来
    others = [s for s in session_skills.list_sessions() if not s["current"]]
    if others:
        out.append(f"另有 {len(others)} 个对话拥有自己的设备技能（相互隔离，不在此列出）；"
                   f"用户问起时用 list_session_skills 查看分布。")
    return "\n".join(out)
