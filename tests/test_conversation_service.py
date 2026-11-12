from types import SimpleNamespace

import pytest

from core import conversation_service as cs


class FakeHub:
    def __init__(self, tools=True):
        self.tools = [{"name": "fake"}] if tools else []

    def openai_tools(self):
        return ([{"type": "function",
                  "function": {"name": t["name"], "description": t["name"],
                               "parameters": {}}} for t in self.tools])


def provider(name="local", supports_tools=True):
    return SimpleNamespace(name=name, model="model", supports_tools=supports_tools)


@pytest.mark.anyio
async def test_agent_route_passes_session_and_callbacks(monkeypatch):
    calls = {}

    async def fake_agent(*args, **kwargs):
        calls.update(kwargs)
        return "agent answer"

    monkeypatch.setattr(cs, "get_provider", lambda name=None: provider(name or "local"))
    monkeypatch.setattr(cs, "run_agent", fake_agent)
    service = cs.ConversationService(FakeHub())

    result = await service.run("question", provider="local", session="sid-1")

    assert result.answer == "agent answer"
    assert result.meta["kind"] == "agent"
    assert calls["session"] == "sid-1"


@pytest.mark.anyio
async def test_unified_entry_without_tools_still_routes_agent(monkeypatch):
    """统一对话入口：无 MCP 工具时不再回退独立 RAG，仍走 agent 通路
    （agent 内部只挂内置 search_knowledge，或退化为纯对话）。"""
    calls = {}

    async def fake_agent(query, hub, **kwargs):
        calls["hub"] = hub
        calls.update(kwargs)
        return "agent answer"

    monkeypatch.setattr(cs, "get_provider", lambda name=None: provider(name or "local"))
    monkeypatch.setattr(cs, "run_agent", fake_agent)
    logs = []
    result = await cs.ConversationService(FakeHub(tools=False)).run(
        "question", provider="local", on_log=logs.append, stream=False)

    assert result.answer == "agent answer"
    assert result.meta["kind"] == "agent"
    assert calls["hub"] is not None
    assert logs


@pytest.mark.anyio
async def test_legacy_rag_mode_is_alias_of_agent(monkeypatch):
    """旧调用方传 mode="rag" 时按统一入口（agent）处理，不报错。"""
    kinds = {}

    async def fake_agent(query, hub, **kwargs):
        return "agent answer"

    monkeypatch.setattr(cs, "get_provider", lambda name=None: provider(name or "local"))
    monkeypatch.setattr(cs, "run_agent", fake_agent)
    result = await cs.ConversationService(FakeHub()).run(
        "question", mode="rag", provider="local")
    kinds["kind"] = result.meta["kind"]
    assert kinds["kind"] == "agent"


@pytest.mark.anyio
async def test_plan_mode_uses_plan_system_prompt(monkeypatch):
    """PLAN 模式：走 agent 通路并注入 PLAN 专用系统提示词。"""
    calls = {}

    async def fake_agent(query, hub, **kwargs):
        calls.update(kwargs)
        return "plan answer"

    monkeypatch.setattr(cs, "get_provider", lambda name=None: provider(name or "local"))
    monkeypatch.setattr(cs, "run_agent", fake_agent)
    logs = []
    result = await cs.ConversationService(FakeHub()).run(
        "question", mode="plan", provider="local", on_log=logs.append)

    assert result.answer == "plan answer"
    assert result.meta["kind"] == "plan"
    assert calls["system_prompt"] == cs.PLAN_SYSTEM_PROMPT
    assert any("plan" in ln.lower() for ln in logs)


@pytest.mark.anyio
async def test_parallel_route_returns_report_metadata(monkeypatch):
    report = SimpleNamespace(
        synthesis="combined", synth_label="local", elapsed=1.2,
        outcomes=[], render=lambda: "parallel report",
    )
    monkeypatch.setattr(cs, "run_multimodal_parallel", lambda *args: report)
    monkeypatch.setattr(cs, "get_provider", lambda name=None: provider(name or "local"))
    logs = []

    result = await cs.ConversationService(FakeHub()).run(
        "question", parallel=True, on_log=logs.append)

    assert result.answer == "combined"
    assert result.meta["kind"] == "parallel"
    assert result.meta["elapsed"] == 1.2
    assert logs == ["parallel report"]
