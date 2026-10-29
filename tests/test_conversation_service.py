from types import SimpleNamespace

import pytest

from core import conversation_service as cs


class FakeHub:
    def __init__(self, tools=True):
        self.tools = [{"name": "fake"}] if tools else []


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
async def test_agent_without_tools_falls_back_to_rag(monkeypatch):
    calls = {}

    def fake_rag(*args):
        calls["args"] = args
        return "rag answer"

    monkeypatch.setattr(cs, "get_provider", lambda name=None: provider(name or "local"))
    monkeypatch.setattr(cs, "rag_ask", fake_rag)
    logs = []
    result = await cs.ConversationService(FakeHub(tools=False)).run(
        "question", provider="local", on_log=logs.append, stream=False)

    assert result.answer == "rag answer"
    assert result.meta["kind"] == "rag"
    assert calls["args"][2] is False
    assert logs


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
