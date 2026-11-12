"""Shared conversation orchestration for the CLI and GUI entry points.

统一对话入口（2026-11 起）：不再由用户手动挑选 RAG / Agent 模式——
所有普通提问都走 agent 通路（模型自主决定是否检索/调工具）：
- agent.py 默认挂载内置 search_knowledge：即使 MCP 服务端不可用，知识检索仍在；
- 系统提示词固定写入「配置前必查」硬性规则（search_knowledge / SKILL.md）；
- 旧的 rag 模式（固定「先检索后生成」的单轮问答）不再是独立入口，检索能力
  由 agent 内的工具承接。provider 不支持工具调用时自动退化为纯对话。
"""
from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from core.agent import PLAN_SYSTEM_PROMPT, run_agent
from core.parallel import run_multimodal_parallel
from core.providers import get_provider


@dataclass
class ConversationResult:
    answer: str
    meta: dict = field(default_factory=dict)


#: 模型端保留的历史消息条数（user+assistant 合计），与 GUI worker 的窗口一致
HISTORY_WINDOW = 8


def history_from_records(records: list[dict] | None,
                         limit: int = HISTORY_WINDOW) -> list[dict]:
    """把会话记录还原成模型端可直接使用的 `[{role, content}]` 历史。

    为什么需要：切换会话时界面只是重绘气泡，模型端的历史列表是空的，
    继续提问就「失忆」（不记得这个会话里配过什么、查过什么）。
    这里按 question/answer 还原成 user/assistant 对，并保留最近 `limit` 条消息
    （与运行期 `del self._history[:-8]` 的窗口一致，避免恢复后比正常对话更长）。
    """
    msgs: list[dict] = []
    for rec in records or []:
        if not isinstance(rec, dict):
            continue
        q = str(rec.get("question") or "").strip()
        a = str(rec.get("answer") or "").strip()
        if q:
            msgs.append({"role": "user", "content": q})
        if a:
            msgs.append({"role": "assistant", "content": a})
    if limit and limit > 0:
        return msgs[-limit:]
    return msgs


class ConversationService:
    """Run one conversation turn without owning a UI, thread, or event loop."""

    def __init__(self, hub):
        self.hub = hub

    async def run(self, text: str, *, mode: str = "agent", provider: str = "",
                  history: list[dict] | None = None, images: list[str] | None = None,
                  parallel_providers: list[str] | None = None,
                  max_rounds: int = 4, show_thinking: bool = True,
                  session: str = "", on_think: Callable[[str], None] | None = None,
                  on_answer: Callable[[str], None] | None = None,
                  on_log: Callable[[str], None] | None = None,
                  on_confirmation: Callable[[dict], Awaitable[str | None]] | None = None,
                  parallel: bool = False, stream: bool = True) -> ConversationResult:
        """Run one turn.

        Modes:
            agent    普通对话（统一入口；模型自主检索/调工具，默认能力）
            plan     PLAN 模式：为各设备预先准备拓扑信息（只读探测 + 手册沉淀）
            parallel 多模型并行：同一问题交给多个模型并融合答案
        传入旧值 "rag" 时按 agent 处理（检索已并入 agent 的工具集）。

        The caller owns history mutation. This keeps CLI and GUI free to choose
        their own persistence model while sharing the execution decision.
        """
        pname = provider or get_provider().name
        if parallel or mode == "parallel":
            selected_mode = "parallel"
        else:
            selected_mode = "agent" if mode in ("", "rag") else mode
        image_list = [str(item) for item in (images or []) if item]

        if selected_mode == "parallel":
            report = await asyncio.to_thread(
                run_multimodal_parallel,
                text,
                image_list or None,
                parallel_providers or None,
                "parallel",
                True,
                None,
                show_thinking,
                None,
                on_think,
                on_answer,
            )
            if on_log:
                on_log(report.render())
            if report.synthesis:
                answer = report.synthesis
            else:
                answer = "\n\n".join(
                    (item.result.content if item.ok else f"[{item.label} 失败] {item.error}")
                    for item in report.outcomes
                ) or "（没有拿到任何回答）"
                if on_log:
                    on_log("（未生成融合答案，以上为各路原始回答）")
            return ConversationResult(answer, {
                "provider": report.synth_label or "parallel",
                "model": "",
                "kind": "parallel",
                "elapsed": report.elapsed,
            })

        prov = get_provider(pname)
        if on_log:
            if selected_mode == "plan":
                on_log(f"[plan] 为设备准备拓扑信息（只读探测 + 手册沉淀），模型 {pname}…")
            else:
                on_log(f"[agent] 模型 {pname}（知识检索已内置，MCP 工具按需调用）…")
        # 统一入口：hub 为 None / 工具不可用时 run_agent 会自动只挂内置
        # search_knowledge（provider 不支持工具则退化为纯对话），不再回退独立 RAG。
        system_prompt = PLAN_SYSTEM_PROMPT if selected_mode == "plan" else None
        answer = await run_agent(
            text, self.hub, history=history, max_rounds=max_rounds,
            show_thinking=show_thinking, images=image_list or None,
            provider=pname, on_think=on_think, on_answer=on_answer,
            session=session, on_confirmation=on_confirmation,
            system_prompt=system_prompt,
        )
        return ConversationResult(answer, {
            "provider": pname,
            "model": prov.model,
            "kind": selected_mode,
        })
