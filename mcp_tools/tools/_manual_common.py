"""单工具模块的手册类公共支撑：会话位置说明 + 正文截断。

manual_server 的 6 个工具都要回答一个问题：「你读/写的到底是哪个会话？」
说得含糊，模型就会把别处对话的结论当成本对话的经验。所以统一走 `where()`。
"""
from __future__ import annotations

MAX_MANUAL_CHARS = 12000     # 回给模型的正文上限，避免挤爆上下文


def where(session: str = "") -> str:
    """给人看的「位置」说明：显式跨会话时写清楚，避免模型误以为是当前会话的。"""
    from core import session_skills

    return f"会话 {session}（非当前会话）" if session else f"当前会话 {session_skills.current()}"


def truncate_manual(text: str, limit: int = MAX_MANUAL_CHARS) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n...（手册共 {len(text)} 字，已截断）"
