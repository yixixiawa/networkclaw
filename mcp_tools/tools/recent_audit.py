"""MCP 工具 recent_audit：查看最近的命令审计记录。

作用点：**审计回看**。回答「刚才那条命令到底执行了没有 / 被谁拦下的」。

归属服务端：Network-Device-Serial（mcp_tools/device_server.py）
"""
from __future__ import annotations

from mcp_tools.tools import _bootstrap  # noqa: F401  (sys.path 兜底)


def recent_audit(n: int = 10) -> str:
    """查看最近的命令执行审计记录（谁通过什么通道下发了什么命令、是否被拦截）。

    Args:
        n: 返回最近 n 条，默认 10
    """
    from core.command_guard import LEVEL_CN, audit_tail

    rows = audit_tail(max(1, n))
    if not rows:
        return "暂无审计记录"

    lines = [f"最近 {len(rows)} 条命令审计："]
    for r in rows:
        flag = "已执行" if r.get("executed") else "未执行"
        lines.append(
            f"  [{r.get('time')}] {r.get('transport')} → {r.get('target')} | "
            f"{LEVEL_CN.get(r.get('level'), r.get('level'))} | {flag} | {r.get('command')}"
        )
    return "\n".join(lines)
