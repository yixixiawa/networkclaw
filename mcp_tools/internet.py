from fastmcp import FastMCP, Client
from fastmcp.client.transports import StdioTransport

mcp = FastMCP("Internet-Search")

@mcp.tool
async def search(query: str, limit: int = 5) -> str:
    """使用 open-websearch 进行网络搜索"""
    transport = StdioTransport(
        command="npx",
        args=["-y", "open-websearch@latest"],
        env={"DEFAULT_SEARCH_ENGINE": "bing"}
    )
    async with Client(transport) as client:
        result = await client.call_tool(
            "search",
            {"query": query, "limit": limit}
        )
        return str(result)

if __name__ == "__main__":
    mcp.run(transport="stdio")