"""MCP 客户端层：以 stdio 方式拉起本地 MCP 服务端，并统一调用其工具。

职责：
- 管理多个 MCP 服务端的生命周期（进入 / 退出时自动建立与关闭连接）
- 聚合所有服务端的工具清单（记录工具名 → 服务端的路由关系）
- 提供统一的工具调用入口，并把 MCP 返回值转成纯文本
- 生成 OpenAI 风格工具定义，供 core.agent 交给本地模型做工具调用

约定：
- 所有服务端都用**当前解释器**（.venv 里的 python）拉起，避免装到别的环境；
  打包成 exe 后没有解释器，改为让 exe 用 `--serve-mcp <标识>` 复用自身拉起服务端
  （派发逻辑在项目根的 launcher.py，标识 → 模块的映射在 mcp_tools/__init__.py）
- 工具内部不抛异常，失败统一转成可读文本，Agent 循环不会因工具报错中断

运行自检：
    python -m mcp_tools.client        # 列出工具并实际调用一次
"""
import asyncio
import contextlib
import json
import os
import sys
from contextlib import AsyncExitStack
from pathlib import Path

from fastmcp import Client
from fastmcp.client.transports import StdioTransport

from core.paths import BASE_DIR, SERVE_FLAG, is_frozen
from mcp_tools import module_for

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PYTHON = sys.executable

# 单个服务端的连接超时（导入 fastmcp/chromadb 较慢，给足裕量）
SERVER_TIMEOUT = 60.0

# 默认接入的服务端：知识检索 / 设备串口 / 设备 Telnet / 图像识别（均纯本地）
# 值为服务端脚本路径（开发模式用得到；打包后按服务端标识复用 exe 自身）
DEFAULT_SERVERS: dict[str, str] = {
    "knowledge": str(PROJECT_ROOT / "mcp_tools" / "template_server.py"),
    "device-serial": str(PROJECT_ROOT / "mcp_tools" / "device_server.py"),
    "device-telnet": str(PROJECT_ROOT / "mcp_tools" / "telnet_server.py"),
    "vision": str(PROJECT_ROOT / "mcp_tools" / "vision_server.py"),
}
# 可选服务端：联网搜索（依赖 npx + open-websearch，按需接入）
SEARCH_SERVER: dict[str, str] = {
    "search": str(PROJECT_ROOT / "mcp_tools" / "internet.py"),
}


def _transport_spec(name: str, script: str) -> tuple[str, list[str], str]:
    """计算拉起某个服务端所需的 (可执行文件, 参数, 工作目录)。

    开发模式：python mcp_tools/xxx.py
    打包模式：NetworkClaw.exe --serve-mcp xxx     （复用自身，避免依赖外部解释器）
    """
    if is_frozen():
        return sys.executable, [SERVE_FLAG, module_for(name) or name], str(BASE_DIR)
    return PYTHON, [script], str(PROJECT_ROOT)


def _child_env() -> dict[str, str]:
    """子进程环境变量。

    fastmcp 的 StdioTransport 一旦显式传 env 就会**整体替换**掉默认环境，
    之前只传了 PYTHONPATH/PYTHONIOENCODING，Windows 上会缺 SystemRoot、PATH 等，
    容易在加载 DLL / 调用外部命令时才暴露问题。这里以系统默认环境为底，再叠加本项目需要的项。
    """
    env: dict[str, str] = {}
    try:
        from mcp.client.stdio import get_default_environment

        env.update(get_default_environment())
    except Exception:
        env.update(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    if not is_frozen():
        env["PYTHONPATH"] = str(PROJECT_ROOT)
    # 密钥要能传到 MCP 服务端（联网搜索等场景可能需要）
    for key in ("DEEPSEEK_API_KEY", "NETWORKCLAW_MMPROJ", "NETWORKCLAW_PROVIDER"):
        if os.environ.get(key):
            env[key] = os.environ[key]
    return env



def _result_to_text(result) -> str:
    """把 MCP 的 CallToolResult 转成纯文本（兼容不同返回形态）"""
    if result is None:
        return ""
    if isinstance(result, str):
        return result

    content = getattr(result, "content", None)
    if content:
        parts = []
        for block in content:
            text = getattr(block, "text", None)
            if text is not None:
                parts.append(text)
            else:
                data = getattr(block, "data", None)
                parts.append(str(data) if data is not None else str(block))
        text = "\n".join(parts)
        if getattr(result, "is_error", False):
            text = f"[工具返回错误] {text}"
        return text

    structured = getattr(result, "structured_content", None)
    if structured is not None:
        return json.dumps(structured, ensure_ascii=False)
    return str(result)


class McpHub:
    """多个 MCP 服务端的统一入口（异步上下文管理器）。

    用法：
        async with McpHub() as hub:
            tools = await hub.list_tools()          # 聚合后的工具清单
            print(await hub.call_tool("search_knowledge", {"query": "S5700"}))
    """

    def __init__(self, servers: dict[str, str] | None = None):
        self.servers = dict(servers) if servers is not None else dict(DEFAULT_SERVERS)
        self._stack: AsyncExitStack | None = None
        self._clients: dict[str, Client] = {}
        self._tools: list[dict] = []
        self._tool_server: dict[str, str] = {}
        self.failed_servers: list[str] = []

    # ------------------------------------------------------------ 生命周期
    async def __aenter__(self) -> "McpHub":
        self._stack = AsyncExitStack()
        env = _child_env()
        for server, script in self.servers.items():
            command, args, cwd = _transport_spec(server, script)
            transport = StdioTransport(
                command=command,
                args=args,
                cwd=cwd,
                env=env,
            )
            try:
                client = await self._stack.enter_async_context(Client(transport))
            except Exception as e:
                self.failed_servers.append(server)
                print(f"[MCP] 服务端 {server} 连接失败：{type(e).__name__}: {e}")
                continue
            self._clients[server] = client
        self._tools = await self._load_tools()
        return self

    async def __aexit__(self, exc_type, exc, tb):
        if self._stack is not None:
            await self._stack.aclose()
            self._stack = None
        self._clients.clear()
        return False

    # ------------------------------------------------------------ 工具清单
    async def _load_tools(self) -> list[dict]:
        tools: list[dict] = []
        for server, client in self._clients.items():
            try:
                listed = await client.list_tools()
            except Exception as e:
                self.failed_servers.append(server)
                print(f"[MCP] 服务端 {server} 工具列表获取失败：{type(e).__name__}: {e}")
                continue
            for t in listed:
                schema = (
                    getattr(t, "input_schema", None)
                    or getattr(t, "inputSchema", None)
                    or {"type": "object", "properties": {}}
                )
                # 工具重名会让路由指向错误的服务端，必须显式提示（后注册者覆盖前者）
                owner = self._tool_server.get(t.name)
                if owner is not None and owner != server:
                    print(f"[MCP] 警告：工具名冲突 {t.name}（{owner} 与 {server}），"
                          f"调用将路由到 {server}")
                    tools = [x for x in tools if x["name"] != t.name]
                tools.append({
                    "server": server,
                    "name": t.name,
                    "description": (t.description or "").strip(),
                    "input_schema": schema,
                })
                self._tool_server[t.name] = server
        return tools

    async def list_tools(self) -> list[dict]:
        """聚合工具清单（首次调用时加载，之后走缓存）"""
        if not self._tools:
            self._tools = await self._load_tools()
        return self._tools

    async def refresh_tools(self) -> list[dict]:
        self._tools = await self._load_tools()
        return self._tools

    @property
    def tools(self) -> list[dict]:
        return self._tools

    @property
    def connected_servers(self) -> list[str]:
        """已成功连接的服务端名列表"""
        return list(self._clients)

    def openai_tools(self) -> list[dict]:
        """转成 OpenAI 风格的工具定义，交给本地模型做 function calling"""
        return [{
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t["description"] or t["name"],
                "parameters": t["input_schema"],
            },
        } for t in self._tools]

    def describe_tools(self) -> str:
        """给命令行 /tools 用的可读清单"""
        if not self._tools:
            lines = ["（没有可用的 MCP 工具）"]
            if self.failed_servers:
                lines.append(f"连接失败的服务端：{', '.join(self.failed_servers)}")
            return "\n".join(lines)
        lines = [f"共 {len(self._tools)} 个 MCP 工具（服务端：{', '.join(self._clients)}）："]
        for t in self._tools:
            props = ", ".join((t["input_schema"].get("properties") or {}).keys())
            first_line = t["description"].splitlines()[0] if t["description"] else ""
            lines.append(f"  - {t['name']}（{t['server']}）参数：{props or '无'}")
            if first_line:
                lines.append(f"      {first_line}")
        return "\n".join(lines)

    # ------------------------------------------------------------ 工具调用
    async def call_tool(self, name: str, arguments: dict | None = None) -> str:
        """按工具名路由到对应服务端调用；任何失败都返回可读文本而非抛异常"""
        server = self._tool_server.get(name)
        if server is None:
            available = ", ".join(self._tool_server) or "无"
            return f"未知工具：{name}（可用工具：{available}）"
        client = self._clients.get(server)
        if client is None:
            return f"服务端 {server} 未连接，无法调用 {name}"
        try:
            result = await client.call_tool(name, arguments or {}, raise_on_error=False)
        except Exception as e:
            return f"调用工具 {name} 失败：{type(e).__name__}: {e}"
        return _result_to_text(result)


async def _self_check():
    async with McpHub() as hub:
        print(hub.describe_tools())
        print("\n--- 调用 query_command_template ---")
        print(await hub.call_tool("query_command_template", {
            "intent": "配置OSPF宣告网段", "vendor": "Huawei", "device_type": "router",
        }))
        print("\n--- 调用 search_knowledge ---")
        print(await hub.call_tool("search_knowledge", {"query": "S5700 适用什么场景"}))


if __name__ == "__main__":
    asyncio.run(_self_check())
