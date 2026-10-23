"""MCP 工具 query_command_template：按厂商/设备类型/意图检索命令模板。

作用点：**命令模板检索**。数据源是 knowledge/command_templates.csv（唯一真源），
经 core/template_search 语义匹配 + 元数据过滤。

归属服务端：Network-Knowledge（mcp_tools/template_server.py）
"""
from __future__ import annotations

from mcp_tools.tools import _bootstrap  # noqa: F401  (sys.path 兜底)

VENDOR_MAP = {"huawei": "Huawei", "h3c": "H3C", "cisco": "Cisco"}
DEVICE_TYPES = {"switch", "router", "both"}


def query_command_template(intent: str, vendor: str = "", device_type: str = "",
                           top: int = 5) -> str:
    """按厂商、设备类型、意图检索网络设备命令模板。

    Args:
        intent: 用户意图的自然语言描述，例如"配置OSPF宣告网段"
        vendor: 厂商过滤：Huawei / H3C / Cisco，留空表示不过滤
        device_type: 设备类型过滤：switch / router / both，留空表示不过滤
        top: 返回条数，默认 5
    """
    from core.template_search import build_index as build_template_index
    from core.template_search import search as search_templates

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
        items = search_templates(intent.strip(), vendor=vendor_norm,
                                 device_type=device_norm, n=max(1, top))
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
    except Exception as e:  # noqa: BLE001  MCP 工具不抛异常
        return f"命令模板检索失败：{type(e).__name__}: {e}"
