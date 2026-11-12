"""MCP 工具 list_device_manuals：当前会话的设备建档情况。

作用点：**决策入口**。首次处理某台设备前先调它，决定是「读已有手册」
还是「先建档」。只列当前对话的技能——其他对话的记忆刻意不搬过来。

为什么同时列地址与「仅有历史」的设备（2026-10 修）：
    手册与历史按名字落目录，但历史可能存在于**没有手册**的目录里（旧命名、
    或工具先执行后建档）。只列有 SKILL.md 的目录会让这些设备凭空消失，
    模型就以为「从没接触过」，于是重做一遍。这里统一由
    device_registry.identities() 给出可查询集合，并附上「可用的查询写法」，
    让模型下一次能用对名字查到历史。
"""
from __future__ import annotations

from mcp_tools.tools import _bootstrap  # noqa: F401  (sys.path 兜底)


def _addr(d: dict) -> str:
    if d.get("host") and d.get("port"):
        return f"{d['host']}:{d['port']}"
    return d.get("serial_port") or ""


def list_device_manuals(session: str = "") -> str:
    """列出设备建档情况：当前会话里哪些设备已有手册、哪些只有历史、哪些还没建。

    首次处理某台设备前先调它，决定是「读已有手册」还是「先建档」。
    注意：只看**当前对话**的技能；其他对话的设备记忆相互隔离，不在这里出现。
    """
    from core import device_manual, device_registry, session_skills
    from mcp_tools.tools._manual_common import where

    try:
        devices = device_registry.identities(session)
        has = {m["name"]: m for m in device_manual.list_manuals(session)}
        hist_only = set(device_manual.history_only_devices(session))
    except Exception as e:  # noqa: BLE001  工具不抛异常
        return f"读取设备清单失败：{type(e).__name__}: {e}"

    documented: list[str] = []
    only_hist: list[str] = []
    missing: list[str] = []
    for d in devices:
        name = d.get("name") or d.get("key", "")
        addr = _addr(d)
        tail = f"｜地址 {addr}" if addr else ""
        m = has.get(name)
        if m:
            documented.append(f"  [{name}] 已有手册（{m['bytes']} 字节，更新于 "
                              f"{m['updated']}，历史 {m['history_lines']} 条）{tail}")
        elif name in hist_only:
            n = len(device_manual.tail_history_merged([name], 9999, session))
            only_hist.append(f"  [{name}] 只有历史（{n} 条，无手册）{tail}")
        else:
            missing.append(f"{name}（{addr}）" if addr else name)

    out = [f"设备共 {len(devices)} 台，本会话已建档 {len(has)} 台"
           f"（{where(session)}，目录 session/{session or session_skills.current()}/skill/）："]
    out += documented or ["  （暂无手册）"]
    if only_hist:
        out += only_hist
    if missing:
        out.append(f"尚未建档（首次操作前建议先 create_device_manual）：{', '.join(missing)}")
    out.append("查询提示：设备名、别名（含 IP:端口 / 端口号）都可以用于 "
               "read_device_manual 与 recent_device_history；同名设备会被自动区分。")
    # 让模型知道「还有别的对话」，但不把别处的内容搬过来
    others = [s for s in session_skills.list_sessions() if not s["current"]]
    if others:
        out.append(f"另有 {len(others)} 个对话拥有自己的设备技能（相互隔离，不在此列出）；"
                   f"用户问起时用 list_session_skills 查看分布。")
    return "\n".join(out)
