"""命令模板语义检索（阶段二）。

职责：
- 读取 knowledge/command_templates.csv（手工维护的命令模板表，唯一数据源）
- 用 nomic-embed-text 将「设备类型 + 功能分类 + 用户意图」向量化，存入 Chroma 的
  command_templates 集合
- 检索时先做语义匹配（用户自然语言意图），再按厂商 / 设备类型元数据过滤

集合隔离：与知识库共用 data/Rag_data 这一个 Chroma 库，但用不同的集合
（TEMPLATE_COLLECTION vs KNOWLEDGE_COLLECTION），集合名与索引指纹都在
core/ollama_interface.py 注册，重建本集合不会影响知识库集合。

运行方式：
    python -m core.template_search "我想远程登录设备" --vendor Huawei
    python -m core.template_search --rebuild          # CSV 更新后重建索引
"""
import argparse
import csv
from pathlib import Path

from core.ollama_interface import (
    BASE_DIR,
    TEMPLATE_COLLECTION,
    check_embedder,
    compute_fingerprint,
    get_collection,
    index_is_fresh,
    reset_collection,
    save_index_state,
)

TEMPLATE_CSV = BASE_DIR / "knowledge" / "command_templates.csv"
COLLECTION_NAME = TEMPLATE_COLLECTION  # 兼容旧引用


def load_rows() -> list[dict]:
    """读取命令模板 CSV（utf-8-sig，兼容 Excel 直接编辑保存）"""
    with open(TEMPLATE_CSV, "r", encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    return [r for r in rows if (r.get("vendor") or "").strip()]


def _documents(rows: list[dict]) -> list[str]:
    """向量化文本：设备类型 + 分类 + 意图（决定语义匹配效果）"""
    return [f"{r['device_type']}，{r['category']}：{r['intent']}" for r in rows]


def build_index(force: bool = False) -> int:
    """将 CSV 全量写入命令模板集合，返回条数。

    以「CSV 内容指纹 + 条数」判断是否需要重建（比只比条数更可靠：
    改命令、改说明但条数不变时同样能识别出来）；force=True 强制重建。
    只重建 TEMPLATE_COLLECTION，不影响知识库集合。
    """
    rows = load_rows()
    documents = _documents(rows)
    fingerprint = compute_fingerprint(documents)

    if not force and index_is_fresh(COLLECTION_NAME, fingerprint, len(rows)):
        print(f"命令模板索引已是最新（{len(rows)} 条），跳过重建（--rebuild 可强制重建）")
        return len(rows)

    check_embedder()  # 先预检：重建是「先删后建」，Embedding 不可用时不能动旧索引
    coll = reset_collection(COLLECTION_NAME)
    coll.add(
        documents=documents,
        ids=[f"tmpl_{i:04d}" for i in range(len(rows))],
        metadatas=[{
            "vendor": r["vendor"].strip(),
            "device_type": (r.get("device_type") or "both").strip(),
            "category": r["category"].strip(),
            "intent": r["intent"].strip(),
            "command": r["command"].strip(),
            "mode": r["mode"].strip(),
            "note": (r.get("note") or "").strip(),
        } for r in rows],
    )
    save_index_state(
        COLLECTION_NAME, fingerprint, len(rows),
        source=str(TEMPLATE_CSV.relative_to(BASE_DIR)),
    )
    print(f"命令模板索引已重建：{len(rows)} 条写入集合 {COLLECTION_NAME}")
    return len(rows)


def search(intent: str, vendor: str | None = None, device_type: str | None = None,
           n: int = 5) -> list[dict]:
    """按用户意图语义检索命令模板；vendor / device_type 指定时做元数据过滤。

    返回：[{"vendor", "device_type", "category", "intent", "command", "mode", "note", "distance"}, ...]
    集合为空或过滤后无命中时返回空列表（不发起查询、不报错）。
    """
    if not (intent or "").strip():
        return []

    coll = get_collection(COLLECTION_NAME)
    total = coll.count()
    if total == 0:
        return []

    conds = []
    if vendor:
        conds.append({"vendor": vendor})
    if device_type:
        conds.append({"device_type": device_type})
    where = None
    if len(conds) == 1:
        where = conds[0]
    elif len(conds) > 1:
        where = {"$and": conds}

    # n 的收敛：有过滤条件时按「过滤后命中数」收敛，否则按集合总数收敛。
    # 注意不能用 max(count, 1) 兜底——集合为空时那样会拿 n=1 去查空集合。
    if where:
        matched = len(coll.get(where=where, include=[])["ids"])
        if matched == 0:
            return []
        n = min(n, matched)
    else:
        n = min(n, total)
    n = max(1, n)

    results = coll.query(
        query_texts=[intent],
        n_results=n,
        where=where,
    )

    items = []
    metadatas = results["metadatas"][0]
    distances = results["distances"][0]
    for meta, dist in zip(metadatas, distances):
        items.append({**meta, "distance": round(dist, 4)})
    return items


def _main():
    parser = argparse.ArgumentParser(description="命令模板语义检索")
    parser.add_argument("intent", nargs="*", help="用户意图，例如：远程登录设备")
    parser.add_argument("--vendor", default=None, help="按厂商过滤：Huawei / H3C / Cisco")
    parser.add_argument("--device-type", default=None, dest="device_type",
                        help="按设备类型过滤：switch / router / both")
    parser.add_argument("--top", type=int, default=5, help="返回条数，默认 5")
    parser.add_argument("--rebuild", action="store_true", help="强制重建向量索引")
    args = parser.parse_args()

    if args.rebuild:
        build_index(force=True)
        return

    if not args.intent:
        parser.error("请提供要检索的意图描述，或使用 --rebuild")
    query = " ".join(args.intent)

    build_index()  # 幂等：与 CSV 一致时跳过
    items = search(query, vendor=args.vendor, device_type=args.device_type, n=args.top)

    print(f"\n意图：{query}"
          + (f"（厂商过滤：{args.vendor}）" if args.vendor else "")
          + (f"（设备过滤：{args.device_type}）" if args.device_type else ""))
    if not items:
        print("没有匹配到命令模板")
        return
    for i, it in enumerate(items, 1):
        print(f"\n[{i}] {it['vendor']} ｜ {it.get('device_type', '')} ｜ {it['category']} ｜ 相似度距离 {it['distance']}")
        print(f"    意图：{it['intent']}")
        print(f"    命令：{it['command']}")
        print(f"    模式：{it['mode']}")
        if it["note"]:
            print(f"    说明：{it['note']}")


if __name__ == "__main__":
    _main()
