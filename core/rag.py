"""RAG 流程层：知识库切分写入 + 检索问答（流式输出）。

职责：
- 加载 knowledge/ 下的知识文档并切分写入向量库
- 提供检索（retrieve）与流式问答（ask）：实时打印模型思考过程与回答 token，
  并统计输出 token 数
- 生成走 llama-server，检索向量化走 Ollama

集合隔离：
- 本模块只操作 KNOWLEDGE_COLLECTION（知识库）这一个集合，且通过
  ollama_interface.get_collection(...) 现取句柄，不持有长生命周期集合对象；
- 命令模板检索在 core/template_search.py，操作 TEMPLATE_COLLECTION，两者
  索引指纹各自记录（data/index_state.json），互不干扰；
- 重建知识库索引不会影响命令模板集合，反之亦然。

运行方式：
    python -m core.rag              # 交互式问答
    python -m core.rag --rebuild    # 强制重建知识库索引
"""
import argparse

from langchain_text_splitters import RecursiveCharacterTextSplitter

from core.llm_client import print_stats, stream_chat
from core.ollama_interface import (
    BASE_DIR,
    KNOWLEDGE_COLLECTION,
    check_embedder,
    compute_fingerprint,
    get_collection,
    index_is_fresh,
    reset_collection,
    save_index_state,
)

KNOWLEDGE_FILE = BASE_DIR / "knowledge" / "huawei_devices_introduce.txt"


def load_chunks() -> list[str]:
    """读取知识文档并切分为文本块"""
    with open(KNOWLEDGE_FILE, "r", encoding="utf-8") as f:
        raw_text = f.read()

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=300,
        chunk_overlap=50,
        separators=["\n\n", "\n", "。", "，", " "]
    )
    return splitter.split_text(raw_text)


def build_index(force: bool = False) -> int:
    """把知识文档切分后写入知识库集合，返回文本块数量。

    以「内容指纹 + 块数」判断是否需要重建：
    - 一致 → 跳过（幂等，可在每次启动时放心调用）
    - 不一致或 force=True → 仅重建知识库集合（不触碰命令模板集合）

    注意：改完 knowledge/ 里的文档后无需手动清理，指纹变化会自动触发重建。
    """
    chunks = load_chunks()
    fingerprint = compute_fingerprint(chunks)

    if not force and index_is_fresh(KNOWLEDGE_COLLECTION, fingerprint, len(chunks)):
        print(f"知识库索引已是最新（{len(chunks)} 个文本块），跳过重建")
        return len(chunks)

    check_embedder()  # 先预检：重建是「先删后建」，Embedding 不可用时不能动旧索引
    coll = reset_collection(KNOWLEDGE_COLLECTION)
    coll.add(
        documents=chunks,
        ids=[f"hw_{i}" for i in range(len(chunks))]
    )
    save_index_state(
        KNOWLEDGE_COLLECTION, fingerprint, len(chunks),
        source=str(KNOWLEDGE_FILE.relative_to(BASE_DIR)),
    )
    print(f"知识库索引已重建：{len(chunks)} 个文本块写入集合 {KNOWLEDGE_COLLECTION}")
    return len(chunks)


def retrieve(query: str, n_results: int = 3) -> list[str]:
    """从知识库集合检索相关片段（集合为空时返回空列表，不发起查询）"""
    coll = get_collection(KNOWLEDGE_COLLECTION)
    total = coll.count()
    if total == 0:
        return []
    n_results = max(1, min(n_results, total))
    results = coll.query(query_texts=[query], n_results=n_results)
    return results["documents"][0]


def _build_prompt(query: str, context: str) -> str:
    return f"""你是一个华为网络设备专家。请严格根据以下知识片段回答问题。如果知识片段中没有相关信息，请明确说“知识库中没有找到相关信息”。

知识片段：
{context}

用户问题：{query}

回答："""


def ask(query: str, show_thinking: bool = True, stream: bool = True) -> str:
    """检索 + 流式 LLM 生成，返回最终回答文本。

    - show_thinking=True 时实时打印模型思考过程
    - stream=True 时逐 token 实时打印回答；stream=False 则只收集不打印，
      由调用方（如 main.py）统一渲染返回值，便于同时记录会话历史。
    """
    retrieved = retrieve(query)
    if retrieved:
        print(f"检索到 {len(retrieved)} 个相关片段：")
        for i, doc in enumerate(retrieved, 1):
            print(f"  [{i}] {doc[:80]}...")
    else:
        print("知识库中未检索到相关片段（索引为空或问题不匹配），将仅依赖模型自身知识回答")

    prompt = _build_prompt(query, "\n\n".join(retrieved))
    result = stream_chat(
        messages=[{"role": "user", "content": prompt}],
        show_thinking=show_thinking,
        show_answer=stream,
    )
    print_stats(result)
    return result.content


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="RAG 知识库问答")
    parser.add_argument("--rebuild", action="store_true", help="强制重建知识库索引")
    args = parser.parse_args()

    build_index(force=args.rebuild)
    while True:
        query = input("\n请输入查询内容（q 退出）：")
        if query.strip().lower() in ("q", "quit", "exit"):
            break
        ask(query)
