"""Pure service-side operations used by the Qt worker adapter."""
from __future__ import annotations

import asyncio

from core.llama_start import find_mmproj, is_server_running, mmproj_hint
from core.ollama_interface import check_embedder
from core.providers import configured_providers, list_providers, probe
from core.vision import vision_status


class ServiceCoordinator:
    """Coordinate local/runtime probes without owning Qt signals or a thread."""

    def __init__(self, local, hub=None):
        self.local = local
        self.hub = hub

    async def services_snapshot(self) -> dict:
        def collect() -> dict:
            snapshot = {
                "llama": bool(is_server_running()),
                "llama_owned": self.local.owned,
            }
            mmproj = find_mmproj()
            snapshot["mmproj"] = str(mmproj) if mmproj else ""
            try:
                check_embedder()
                snapshot["ollama"] = True
                snapshot["ollama_detail"] = "nomic-embed-text 可用"
            except Exception as exc:
                snapshot["ollama"] = False
                snapshot["ollama_detail"] = str(exc).splitlines()[0][:80]
            state = vision_status()
            snapshot["vision"] = state["available"]
            snapshot["vision_detail"] = state["detail"]
            return snapshot

        snapshot = await asyncio.to_thread(collect)
        snapshot["mcp_servers"] = list(self.hub.connected_servers) if self.hub else []
        snapshot["mcp_tools"] = len(self.hub.tools) if self.hub else 0
        return snapshot

    async def ensure_vision(self) -> None:
        if self.local.running and vision_status()["available"] is True:
            return
        await asyncio.to_thread(self.local.ensure, True)

    async def start_local(self, with_vision: bool) -> tuple[bool, bool]:
        started = await asyncio.to_thread(self.local.ensure, with_vision)
        return started, bool(self.local.running)

    async def stop_local(self) -> None:
        await asyncio.to_thread(self.local.stop)

    async def device_probe(self, session: str = "") -> list[dict]:
        """探测设备在线状态（只读 TCP/串口枚举，不下发命令）。

        会话隔离：session 非空时只探测**本会话**出现过的设备
        （session/<sid>/skill/ 里有手册或命令历史的）；未打开会话返回空。
        """
        from core import device_registry

        if not session:
            return []
        devs = await asyncio.to_thread(device_registry.session_devices, session)
        if not devs:
            return []
        return await asyncio.to_thread(device_registry.probe_all, devs)

    async def vision_report(self) -> str:
        def collect() -> str:
            status = vision_status()
            found = find_mmproj()
            lines = [
                f"视觉能力：{'可用' if status['available'] else ('待确认' if status['available'] is None else '不可用')}",
                f"判据：{status['detail']}",
                f"mmproj：{found if found else '未找到'}",
            ]
            for provider in list_providers():
                lines.append(
                    f"  {provider.name}："
                    f"{'支持图片' if provider.supports_vision else '不支持图片（走多模态桥接）'}"
                )
            if not found:
                lines.append(mmproj_hint())
            return "\n".join(lines)

        return await asyncio.to_thread(collect)

    async def provider_probe_report(self) -> str:
        def collect() -> str:
            lines = ["提供方可用性探测："]
            for provider in configured_providers():
                result = probe(provider)
                flag = "可用" if result["ok"] else "不可用"
                extra = f"（{result['latency']}s）" if result.get("latency") else ""
                lines.append(
                    f"[{flag}] {provider.name:<18} {provider.model:<20} "
                    f"{extra} {result['detail']}"
                )
            return "\n".join(lines)

        return await asyncio.to_thread(collect)
