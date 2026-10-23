"""MCP 工具 search_knowledge：通用知识库检索。

作用点：**向量库检索**。返回片段带知识分级前缀（现行规则/历史记录/实例数据）。

关键设计：必须区分「没查到」与「检索挂了」两种失败——
    降级（向量库或 Embedding 服务不可用）时明确说"不可用"，否则模型会把
    "检索失败" 当成 "知识库里没有"，进而凭空编造配置命令。这是踩过的真坑。

归属服务端：Network-Knowledge（mcp_tools/template_server.py）
"""
from __future__ import annotations

from mcp_tools.tools import _bootstrap  # noqa: F401  (sys.path 兜底)


def search_knowledge(query: str, top: int = 3) -> str:
    """通用知识库检索：华为设备产品线介绍、基础配置命令说明等。

    返回内容会带**知识分级**前缀：现行规则 / 历史记录 / 实例数据。
    检索降级（向量库或 Embedding 服务不可用）时会显式返回"不可用"，
    此时不要声称"知识库中没有相关内容"——那是故障，不是结论。

    Args:
        query: 检索问题，例如"S5700 适用什么场景"
        top: 返回片段数，默认 3
    """
    from core.rag import build_index as build_knowledge_index
    from core.rag import retrieve_ex

    try:
        if not query.strip():
            return "query 不能为空"
        build_knowledge_index()  # 幂等：索引与知识文档指纹一致时自动跳过
        res = retrieve_ex(query.strip(), n_results=max(1, top))
        if not res.ok:
            if res.degraded:
                # 关键：让模型能区分"没查到"与"检索挂了"
                return (f"⚠ 知识库检索不可用（{res.status}）：{res.reason}\n"
                        f"这不是「知识库中没有相关内容」，而是检索链路故障。"
                        f"请明确告知用户检索失败，不要凭记忆编造命令或结论。"
                        f"（修复：启动 Ollama 并执行 ollama pull nomic-embed-text）")
            return f"知识库中没有找到与「{query}」相关的内容（{res.reason}）"

        lines = [f"问题「{query}」检索到 {len(res.chunks)} 个知识片段："]
        for i, doc in enumerate(res.chunks, 1):
            lines.append(f"[{i}] {doc}")
        return "\n\n".join(lines)
    except Exception as e:  # noqa: BLE001  工具不抛异常
        return f"知识库检索失败：{type(e).__name__}: {e}"
