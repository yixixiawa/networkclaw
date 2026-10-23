"""知识服务 MCP 服务端：把两类检索能力封装为独立 MCP 工具。

本文件只做**注册中心**：建 FastMCP 实例，把 mcp_tools/tools/ 下单工具模块
装配进来。工具实现不在这里——一个工具一个文件（见 mcp_tools/tools/__init__.py）。

工具列表（实现文件 → 工具名）：
    tools/query_command_template.py  query_command_template(vendor, device_type, intent, top)
        按厂商、设备类型、意图检索命令模板（Chroma 语义匹配 + 元数据过滤）
    tools/search_knowledge.py        search_knowledge(query, top)
        通用知识库检索：华为设备介绍、配置说明等（huawei_devices 集合）

运行方式（stdio，供 MCP 客户端拉起）：
    python mcp_tools/template_server.py
    # 或项目根目录下：python -m mcp_tools.template_server
"""
import sys
from pathlib import Path

# 保证从任意工作目录被 MCP 客户端拉起时都能导入 core 包
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from fastmcp import FastMCP  # noqa: E402

mcp = FastMCP("Network-Knowledge")

# ---------------------------------------------------------------- 工具装配
# 一个工具一个文件：从 mcp_tools/tools/<工具名>.py 导入同名函数后注册。
from mcp_tools.tools.query_command_template import query_command_template  # noqa: E402
from mcp_tools.tools.search_knowledge import search_knowledge  # noqa: E402

mcp.tool(query_command_template)
mcp.tool(search_knowledge)


if __name__ == "__main__":
    mcp.run(transport="stdio")
