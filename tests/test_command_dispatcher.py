from types import SimpleNamespace

import pytest

from gui.command_dispatcher import CommandDispatcher


class FakeHub:
    tools = [{"name": "demo", "server": "test", "input_schema": {
        "properties": {"value": {}}
    }}]

    def __init__(self):
        self.calls = []

    def describe_tools(self):
        return "tools"

    async def call_tool(self, name, args):
        self.calls.append((name, args))
        return "tool result"


class FakeServices:
    async def vision_report(self):
        return "vision"

    async def provider_probe_report(self):
        return "probe"

    async def services_snapshot(self):
        return {"llama": True}


@pytest.mark.anyio
async def test_dispatch_routes_mcp_commands():
    hub = FakeHub()
    dispatcher = CommandDispatcher(hub, FakeServices())

    result = await dispatcher.dispatch("call", tool="demo", args={"value": 1})

    assert result.text == "tool result"
    assert hub.calls == [("demo", {"value": 1})]


@pytest.mark.anyio
async def test_dispatch_handles_reset_and_unconnected_hub():
    dispatcher = CommandDispatcher(None, FakeServices())

    reset = await dispatcher.dispatch("reset_history")
    tools = await dispatcher.dispatch("tools")

    assert reset.reset_history is True
    assert tools.text == "（MCP 未连接）"


@pytest.mark.anyio
async def test_dispatch_rebuild_returns_refresh_marker(monkeypatch):
    import gui.command_dispatcher as module

    monkeypatch.setattr(module, "build_knowledge_index", lambda force: 3)
    monkeypatch.setattr(module, "build_template_index", lambda force: 2)
    result = await CommandDispatcher(FakeHub(), FakeServices()).dispatch("rebuild")

    assert "知识库 3 个文本块" in result.text
    assert "命令模板 2 条" in result.text
    assert result.refresh_services is True
