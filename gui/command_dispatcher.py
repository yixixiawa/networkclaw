"""Pure command dispatch for the GUI worker console."""
from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass

from core.providers import active_name, describe_table
from core.rag import build_index as build_knowledge_index
from core.template_search import build_index as build_template_index


@dataclass
class CommandResult:
    name: str
    text: str = ""
    reset_history: bool = False
    refresh_services: bool = False


class CommandDispatcher:
    """Execute worker console commands without Qt signal or thread concerns."""

    def __init__(self, hub, services):
        self.hub = hub
        self.services = services

    async def dispatch(self, name: str, *, arg: str = "", tool: str = "",
                       args: dict | None = None) -> CommandResult:
        if name == "reset_history":
            return CommandResult(name, reset_history=True)
        if name == "tools":
            return CommandResult(name, self.hub.describe_tools() if self.hub else "（MCP 未连接）")
        if name == "call":
            if self.hub is None:
                return CommandResult(name, "（MCP 未连接）")
            return CommandResult(name, await self.hub.call_tool(tool, args or {}))
        if name == "audit":
            if self.hub is None:
                return CommandResult(name, "（MCP 未连接）")
            count = int(arg) if str(arg).isdigit() else 10
            return CommandResult(name, await self.hub.call_tool("recent_audit", {"n": count}))
        if name == "vision":
            return CommandResult(name, await self.services.vision_report())
        if name == "rebuild":
            knowledge = await asyncio.to_thread(build_knowledge_index, True)
            templates = await asyncio.to_thread(build_template_index, True)
            return CommandResult(
                name,
                f"索引已重建：知识库 {knowledge} 个文本块，命令模板 {templates} 条",
                refresh_services=True,
            )
        if name == "probe":
            return CommandResult(name, await self.services.provider_probe_report())
        if name == "providers":
            return CommandResult(name, describe_table(active=active_name()))
        if name == "services":
            snapshot = await self.services.services_snapshot()
            return CommandResult(name, "\n".join(f"{key}: {value}" for key, value in snapshot.items()))
        if name == "tools_json":
            tools = self.hub.tools if self.hub else []
            text = json.dumps([
                {"name": item["name"], "server": item["server"],
                 "params": list((item["input_schema"].get("properties") or {}).keys())}
                for item in tools
            ], ensure_ascii=False, indent=2)
            return CommandResult(name, text)
        return CommandResult(name, f"未知命令：{name}")
