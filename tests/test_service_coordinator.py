from types import SimpleNamespace

import pytest

from gui import service_coordinator as sc


class FakeLocal:
    owned = True
    running = False

    def __init__(self):
        self.calls = []

    def ensure(self, vision=False):
        self.calls.append(("ensure", vision))
        self.running = True
        return True

    def stop(self):
        self.calls.append(("stop",))
        self.running = False


class FakeHub:
    connected_servers = ["test"]
    tools = [{"name": "one"}]


@pytest.mark.anyio
async def test_services_snapshot_collects_runtime_state(monkeypatch):
    monkeypatch.setattr(sc, "is_server_running", lambda: True)
    monkeypatch.setattr(sc, "find_mmproj", lambda: None)
    monkeypatch.setattr(sc, "check_embedder", lambda: None)
    monkeypatch.setattr(sc, "vision_status", lambda: {"available": True, "detail": "ok"})

    result = await sc.ServiceCoordinator(FakeLocal(), FakeHub()).services_snapshot()

    assert result["llama"] is True
    assert result["mcp_servers"] == ["test"]
    assert result["mcp_tools"] == 1
    assert result["vision"] is True


@pytest.mark.anyio
async def test_local_lifecycle_is_delegated():
    local = FakeLocal()
    coordinator = sc.ServiceCoordinator(local)

    started, running = await coordinator.start_local(True)
    await coordinator.stop_local()

    assert started is True and running is True
    assert local.calls == [("ensure", True), ("stop",)]


@pytest.mark.anyio
async def test_provider_probe_report_is_pure(monkeypatch):
    monkeypatch.setattr(sc, "configured_providers", lambda: [
        SimpleNamespace(name="local", model="qwen")
    ])
    monkeypatch.setattr(sc, "probe", lambda provider: {
        "ok": True, "latency": 0.1, "detail": "ready"
    })

    result = await sc.ServiceCoordinator(FakeLocal()).provider_probe_report()

    assert "local" in result and "ready" in result
