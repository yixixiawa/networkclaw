"""MCP 客户端测试脚本：连接 open-websearch 服务并调用 search 工具。

运行方式：
    python -m mcp_tools.search_client
"""
import asyncio

from fastmcp import Client
from fastmcp.client.transports import StdioTransport


async def main():
    transport = StdioTransport(
        command="npx",
        args=["-y", "open-websearch@latest"],
        env={"DEFAULT_SEARCH_ENGINE": "bing"}
    )

    async with Client(transport) as client:
        # 列出可用工具
        tools = await client.list_tools()
        print("可用工具:", [t.name for t in tools])

        # 调用搜索
        result = await client.call_tool(
            "search",
            {"query": "华为交换机最新配置命令", "limit": 3}
        )
        print("搜索结果:", result)


asyncio.run(main())
