"""core/template_search.py 单元测试：语义检索的过滤、收敛与空集合行为。

不依赖 Ollama：用假的 collection 替身验证 search() 的三条关键规则——
① 空意图直接返回空（不发起查询）；
② 集合为空时返回空（不拿 n=1 去查空集合）；
③ 有过滤条件时按「过滤后命中数」收敛 n，而不是按集合总数。
"""
import pytest

from core import template_search as ts


class FakeColl:
    """记录 query 调用参数的假集合。"""

    def __init__(self, rows=None, total=None):
        self.rows = rows if rows is not None else []
        self.total = total if total is not None else len(self.rows)
        self.queries = []

    def count(self):
        return self.total

    def get(self, where=None, include=None):
        if where is None:
            return {"ids": [str(i) for i in range(self.total)]}
        return {"ids": [str(i) for i in range(len(self.rows))]}

    def query(self, query_texts=None, n_results=5, where=None):
        self.queries.append({"texts": query_texts, "n": n_results, "where": where})
        metas = [dict(m) for m in self.rows[:n_results]]
        return {
            "metadatas": [metas],
            "distances": [[round(0.1 * (i + 1), 4) for i in range(len(metas))]],
        }


def _rows(n, vendor="Huawei"):
    return [{"vendor": vendor, "device_type": "switch", "category": "vlan",
             "intent": f"意图{i}", "command": f"cmd {i}", "mode": "system-view",
             "note": ""} for i in range(n)]


def test_empty_intent_returns_empty(monkeypatch):
    coll = FakeColl(_rows(3))
    monkeypatch.setattr(ts, "get_collection", lambda *a, **k: coll)
    assert ts.search("   ") == []
    assert coll.queries == [], "空意图不应发起查询"


def test_empty_collection_returns_empty(monkeypatch):
    """集合为空时必须直接返回，且不能用 n=1 去查空集合。"""
    coll = FakeColl(rows=[], total=0)
    monkeypatch.setattr(ts, "get_collection", lambda *a, **k: coll)
    assert ts.search("远程登录设备") == []
    assert coll.queries == []


def test_search_without_filter_converges_to_total(monkeypatch):
    """无过滤时 n 收敛到集合总数。"""
    coll = FakeColl(_rows(3), total=3)
    monkeypatch.setattr(ts, "get_collection", lambda *a, **k: coll)
    out = ts.search("任意意图", n=10)
    assert coll.queries[0]["n"] == 3
    assert len(out) == 3


def test_search_with_filter_converges_to_matched(monkeypatch):
    """有过滤条件时按过滤后命中数收敛，而不是集合总数。"""
    coll = FakeColl(_rows(2), total=100)     # 集合有 100 条，过滤后只剩 2 条
    monkeypatch.setattr(ts, "get_collection", lambda *a, **k: coll)
    out = ts.search("任意意图", vendor="Huawei", n=10)
    assert coll.queries[0]["n"] == 2
    assert coll.queries[0]["where"] == {"vendor": "Huawei"}
    assert len(out) == 2


def test_search_filter_no_match_short_circuits(monkeypatch):
    """过滤后无命中时直接返回，不发起查询。"""
    coll = FakeColl(rows=[], total=50)
    monkeypatch.setattr(ts, "get_collection", lambda *a, **k: coll)
    assert ts.search("任意意图", vendor="Cisco") == []
    assert coll.queries == []


def test_search_multi_filter_uses_and(monkeypatch):
    """厂商 + 设备类型两个条件应组合成 $and。"""
    coll = FakeColl(_rows(1), total=10)
    monkeypatch.setattr(ts, "get_collection", lambda *a, **k: coll)
    ts.search("任意意图", vendor="Huawei", device_type="router")
    where = coll.queries[0]["where"]
    assert "$and" in where
    assert {"vendor": "Huawei"} in where["$and"]
    assert {"device_type": "router"} in where["$and"]


def test_search_result_carries_distance(monkeypatch):
    coll = FakeColl(_rows(2), total=2)
    monkeypatch.setattr(ts, "get_collection", lambda *a, **k: coll)
    out = ts.search("任意意图")
    assert all("distance" in item for item in out)
    assert out[0]["command"] == "cmd 0"


def test_documents_and_rows_shape():
    """数据源 CSV 的行规整：device_type 只允许三类，非法值应归为 both 或原样保留可检测。"""
    rows = ts.load_rows()
    assert isinstance(rows, list)
    for r in rows[:20]:
        assert "command" in r
        if r.get("device_type"):
            assert r["device_type"] in {"switch", "router", "both"}, r
