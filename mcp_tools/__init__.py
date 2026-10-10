"""mcp_tools 包：基于 FastMCP 的 MCP 服务端与客户端。

服务端注册表说明：
    开发（源码）模式下，客户端用解释器逐个拉起服务端脚本：
        python mcp_tools/template_server.py
    打包成单个 exe 后没有可用的解释器了，于是改为让 exe **复用自身**：
        NetworkClaw.exe --serve-mcp knowledge
    这条路径由 launcher.py 接收并派发到对应模块。因此「服务端标识 → 模块路径」
    必须是唯一的一份映射，两边都从这里取，避免改了名字只改一处。
"""
from __future__ import annotations

# 服务端标识 → Python 模块路径（与 mcp_tools/client.py 的 DEFAULT_SERVERS / SEARCH_SERVER 对应）
SERVERS: dict[str, str] = {
    "knowledge": "mcp_tools.template_server",
    "device-serial": "mcp_tools.device_server",
    "device-telnet": "mcp_tools.telnet_server",
    "device-manual": "mcp_tools.manual_server",
    "topology": "mcp_tools.topology_server",
    "vision": "mcp_tools.vision_server",
    "search": "mcp_tools.internet",
}


def module_for(name_or_path: str) -> str | None:
    """把服务端标识（或脚本路径）解析成模块路径；无法解析时返回 None。"""
    key = (name_or_path or "").strip()
    if not key:
        return None
    if key in SERVERS:
        return SERVERS[key]
    # 容错：允许直接传 mcp_tools/xxx.py 或 mcp_tools.xxx
    normalized = key.replace("\\", "/").rstrip()
    if normalized.endswith(".py"):
        normalized = normalized[: -len(".py")]
    module = normalized.replace("/", ".").strip(".")
    return module if module.startswith("mcp_tools") else None
