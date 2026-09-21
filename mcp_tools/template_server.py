"""知识服务 MCP 服务端：把两类检索能力封装为独立 MCP 工具。

工具列表：
1. query_command_template(vendor, device_type, intent, top)
   - 按厂商、设备类型、意图检索命令模板（Chroma 语义匹配 + 元数据过滤）
2. search_knowledge(query, top)
   - 通用知识库检索：华为设备介绍、配置说明等（huawei_devices 集合）

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

from core.rag import build_index as build_knowledge_index, retrieve  # noqa: E402
from core.template_search import (  # noqa: E402
    build_index as build_template_index,
    search as search_templates,
)

mcp = FastMCP("Network-Knowledge")

VENDOR_MAP = {"huawei": "Huawei", "h3c": "H3C", "cisco": "Cisco"}
DEVICE_TYPES = {"switch", "router", "both"}


@mcp.tool
def query_command_template(intent: str, vendor: str = "", device_type: str = "", top: int = 5) -> str:
    """按厂商、设备类型、意图检索网络设备命令模板。

    Args:
        intent: 用户意图的自然语言描述，例如“配置OSPF宣告网段”
        vendor: 厂商过滤：Huawei / H3C / Cisco，留空表示不过滤
        device_type: 设备类型过滤：switch / router / both，留空表示不过滤
        top: 返回条数，默认 5
    """
    try:
        vendor_norm = None
        if vendor.strip():
            vendor_norm = VENDOR_MAP.get(vendor.strip().lower(), vendor.strip())
        device_norm = None
        if device_type.strip():
            device_norm = device_type.strip().lower()
            if device_norm not in DEVICE_TYPES:
                return f"device_type 仅支持 {' / '.join(sorted(DEVICE_TYPES))}，收到：{device_type}"
        if not intent.strip():
            return "intent 不能为空"

        build_template_index()  # 幂等：与 CSV 一致时跳过
        items = search_templates(intent.strip(), vendor=vendor_norm, device_type=device_norm, n=max(1, top))
        if not items:
            return f"未匹配到命令模板：{intent}"

        lines = [f"意图「{intent}」的命令模板（{len(items)} 条）："]
        for i, it in enumerate(items, 1):
            lines.append(
                f"[{i}] {it['vendor']} | {it['device_type']} | {it['category']} | 相似度距离 {it['distance']}\n"
                f"    命令：{it['command']}\n"
                f"    模式：{it['mode']}"
                + (f"\n    说明：{it['note']}" if it["note"] else "")
            )
        return "\n".join(lines)
    except Exception as e:  # MCP 工具不抛异常，统一返回错误说明
        return f"命令模板检索失败：{type(e).__name__}: {e}"


@mcp.tool
def search_knowledge(query: str, top: int = 3) -> str:
    """通用知识库检索：华为设备产品线介绍、基础配置命令说明等。

    Args:
        query: 检索问题，例如“S5700 适用什么场景”
        top: 返回片段数，默认 3
    """
    try:
        if not query.strip():
            return "query 不能为空"
        build_knowledge_index()  # 幂等：索引与知识文档指纹一致时自动跳过
        docs = retrieve(query.strip(), n_results=max(1, top))
        if not docs:
            return f"知识库中没有找到与「{query}」相关的内容"
        lines = [f"问题「{query}」检索到 {len(docs)} 个知识片段："]
        for i, doc in enumerate(docs, 1):
            lines.append(f"[{i}] {doc}")
        return "\n\n".join(lines)
    except Exception as e:
        return f"知识库检索失败：{type(e).__name__}: {e}"


if __name__ == "__main__":
    mcp.run(transport="stdio")
