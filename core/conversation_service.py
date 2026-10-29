"""Shared conversation orchestration for the CLI and GUI entry points."""
from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from core.agent import run_agent
from core.parallel import run_multimodal_parallel
from core.providers import get_provider
from core.rag import ask as rag_ask


@dataclass
class ConversationResult:
    answer: str
    meta: dict = field(default_factory=dict)


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
        """Run one turn in agent, RAG, or parallel mode.

        The caller owns history mutation. This keeps CLI and GUI free to choose
        their own persistence model while sharing the execution decision.
        """
        pname = provider or get_provider().name
        selected_mode = "parallel" if parallel else mode
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
        use_agent = (selected_mode == "agent" and self.hub is not None
                     and bool(self.hub.tools) and prov.supports_tools)
        if selected_mode == "agent" and not use_agent and on_log:
            on_log("（agent 模式不可用：无 MCP 工具或该模型不支持工具调用，本次改用知识库问答）")

        if use_agent:
            if on_log:
                on_log(f"[agent] 模型 {pname} 自主调用 MCP 工具…")
            answer = await run_agent(
                text, self.hub, history=history, max_rounds=max_rounds,
                show_thinking=show_thinking, images=image_list or None,
                provider=pname, on_think=on_think, on_answer=on_answer,
                session=session, on_confirmation=on_confirmation,
            )
            return ConversationResult(answer, {
                "provider": pname,
                "model": prov.model,
                "kind": "agent",
            })

        answer = await asyncio.to_thread(
            rag_ask, text, show_thinking, stream, image_list or None, pname,
            on_think, on_answer)
        return ConversationResult(answer, {
            "provider": pname,
            "model": prov.model,
            "kind": "rag",
        })
