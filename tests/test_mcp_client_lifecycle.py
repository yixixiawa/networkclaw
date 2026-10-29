import asyncio
from types import SimpleNamespace

import pytest

from mcp_tools import client as mc


class FakeClient:
    def __init__(self, *, listed=None, list_delay=0, call_delay=0, close_delay=0):
        self.listed = listed or []
        self.list_delay = list_delay
        self.call_delay = call_delay
        self.close_delay = close_delay
        self.entered = False
        self.exited = False
        self.calls = []

    async def __aenter__(self):
        self.entered = True
        return self

    async def __aexit__(self, exc_type, exc, tb):
        if self.close_delay:
            await asyncio.sleep(self.close_delay)
        self.exited = True

    async def list_tools(self):
        if self.list_delay:
            await asyncio.sleep(self.list_delay)
        return self.listed

    async def call_tool(self, name, args, raise_on_error=False):
        self.calls.append((name, args))
        if self.call_delay:
            await asyncio.sleep(self.call_delay)
        return "ok"


def tool(name):
    return SimpleNamespace(name=name, description="test", input_schema={
        "type": "object", "properties": {}
    })


@pytest.mark.anyio
async def test_call_timeout_returns_explicit_error(monkeypatch):
    fake = FakeClient(call_delay=0.05)
    hub = mc.McpHub({})
    hub._clients["test"] = fake
    hub._tool_server["ping"] = "test"
    hub._tools = [{"name": "ping", "server": "test", "description": "",
                   "input_schema": {"type": "object", "properties": {}}}]
    monkeypatch.setattr(mc, "TOOL_CALL_TIMEOUT", 0.001)

    result = await hub.call_tool("ping")

    assert "超时" in result


@pytest.mark.anyio
async def test_list_timeout_marks_server_failed(monkeypatch):
    fake = FakeClient(listed=[tool("ping")], list_delay=0.05)
    monkeypatch.setattr(mc, "Client", lambda transport: fake)
    monkeypatch.setattr(mc, "TOOL_LIST_TIMEOUT", 0.001)
    hub = mc.McpHub({"test": "ignored.py"})

    await hub.__aenter__()

    assert "test" in hub.failed_servers
    assert hub.tools == []
    await hub.__aexit__(None, None, None)
    assert fake.exited is True


@pytest.mark.anyio
async def test_exit_clears_routes_and_tools(monkeypatch):
    fake = FakeClient(listed=[tool("ping")])
    monkeypatch.setattr(mc, "Client", lambda transport: fake)
    hub = mc.McpHub({"test": "ignored.py"})

    await hub.__aenter__()
    assert hub.tools
    await hub.__aexit__(None, None, None)

    assert fake.exited is True
    assert hub.tools == []
    assert hub.connected_servers == []
    assert hub._tool_server == {}
    assert hub.failed_servers == []


@pytest.mark.anyio
async def test_refresh_removes_old_routes(monkeypatch):
    fake = FakeClient(listed=[tool("old")])
    monkeypatch.setattr(mc, "Client", lambda transport: fake)
    hub = mc.McpHub({"test": "ignored.py"})

    await hub.__aenter__()
    fake.listed = [tool("new")]
    await hub.refresh_tools()

    assert [item["name"] for item in hub.tools] == ["new"]
    assert hub._tool_server == {"new": "test"}
    await hub.__aexit__(None, None, None)
