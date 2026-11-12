"""会话存储（gui.store）的顶置 / 删除 / 顺序约定。

只测纯逻辑层，不导入 PyQt6。这里的三个约定都来自真实 bug：

1. 删除当前会话后必须还能选到「下一个」会话——原来 _delete_session 会
   立刻新建，顶端看起来永远「删不掉」（修复在 main_window，存储层负责
   保证删除后剩余顺序正确）。
2. 顶置会话必须始终排在非顶置之前，create / touch 都不能把普通会话
   插到顶置块前面。
3. pinned 状态要随 save/load 往返持久化。
"""
from __future__ import annotations

import json

import pytest

from gui.store import Session, SessionStore


@pytest.fixture
def store(tmp_path):
    return SessionStore(path=tmp_path / "sessions.json")


# ---------------------------------------------------------------- 顶置顺序

def test_set_pinned_moves_session_to_front(store):
    a = store.create("A")
    b = store.create("B")
    c = store.create("C")
    # create 是 newest-first：[C, B, A]
    assert [s.sid for s in store.sessions] == [c.sid, b.sid, a.sid]
    store.set_pinned(a.sid, True)
    # 顶置的在第一位，其余保持相对顺序
    assert [s.sid for s in store.sessions] == [a.sid, c.sid, b.sid]
    assert store.sessions[0].pinned is True
    assert all(not s.pinned for s in store.sessions[1:])


def test_pinned_block_stays_above_new_and_touched(store):
    a = store.create("A")
    store.set_pinned(a.sid, True)
    b = store.create("B")   # 新会话应插在顶置块之后
    assert store.sessions[0].sid == a.sid
    assert store.sessions[1].sid == b.sid
    # touch 普通/顶置会话都不应越过顶置块
    store.touch(b.sid)
    assert store.sessions[0].sid == a.sid
    store.touch(a.sid)
    assert store.sessions[0].sid == a.sid


def test_unpin_returns_to_unpinned_block(store):
    a = store.create("A")
    b = store.create("B")
    c = store.create("C")          # 列表：[C, B, A]
    store.set_pinned(c.sid, True)  # [C, B, A]（本就在最前）
    store.set_pinned(c.sid, False)
    # 取消顶置后回到普通块头部（无其他顶置时即列表最前），不破坏 a/b 相对顺序
    assert [s.sid for s in store.sessions] == [c.sid, b.sid, a.sid]
    assert all(not s.pinned for s in store.sessions)


def test_pin_order_preserved_among_multiple_pinned(store):
    a = store.create("A")
    b = store.create("B")
    store.set_pinned(a.sid, True)
    store.set_pinned(b.sid, True)
    # 后顶置的排最前（与 touch 语义一致）
    assert [s.sid for s in store.sessions] == [b.sid, a.sid]


# ---------------------------------------------------------------- 删除

def test_delete_topmost_then_next_is_selectable(store):
    first = store.create("top")     # 先创建 → 排在后面
    second = store.create("second") # 后创建 → newest-first 排最前
    assert store.sessions[0].sid == second.sid
    store.delete(second.sid)        # 删除最顶端
    assert store.get(second.sid) is None
    # 删除顶端后，剩余的第一个就是应选中的「下一个」会话
    assert store.sessions[0].sid == first.sid


def test_delete_pinned_session(store):
    a = store.create("A")
    b = store.create("B")           # 列表：[B, A]
    store.set_pinned(a.sid, True)   # [A, B]
    store.delete(a.sid)
    assert [s.sid for s in store.sessions] == [b.sid]


# ---------------------------------------------------------------- 持久化

def test_pinned_round_trips_through_disk(store):
    a = store.create("A")
    a.add_record("agent", "看下拓扑", "好的")
    store.set_pinned(a.sid, True)
    store.save()
    store2 = SessionStore(path=store.path)
    store2.load()
    assert store2.get(a.sid) is not None
    assert store2.get(a.sid).pinned is True


def test_legacy_file_without_pinned_field_loads(store, tmp_path):
    old = {"version": 1, "sessions": [
        {"sid": "x1", "title": "旧会话", "created": "t", "updated": "t",
         "records": [{"question": "q", "answer": "a"}]}]}
    store.path.write_text(json.dumps(old, ensure_ascii=False), encoding="utf-8")
    store.load()
    s = store.get("x1")
    assert s is not None and s.pinned is False


# ---------------------------------------------------------------- 空会话清理

def test_load_drops_empty_sessions(store):
    """用户约定：只保留有对话历史的 session，空 session 一律不载入。

    背景：原来每次启动都无条件新建空会话，空会话在列表里越积越多。
    """
    a = store.create("有内容")
    a.add_record("agent", "display version", "VRP V5")
    store.create("空会话")            # create 会 save
    store.save()
    store2 = SessionStore(path=store.path)
    loaded = store2.load()
    assert [s.sid for s in loaded] == [a.sid]


def test_load_all_empty_leaves_nothing(store, tmp_path):
    old = {"version": 1, "sessions": [
        {"sid": "e1", "title": "空1", "records": []},
        {"sid": "e2", "title": "空2", "records": []}]}
    store.path.write_text(json.dumps(old, ensure_ascii=False), encoding="utf-8")
    assert store.load() == []
    assert store.sessions == []


def test_prune_empty_keeps_protected_sid(store):
    keep = store.create("正在用")
    junk1 = store.create("空1")
    junk2 = store.create("空2")
    removed = store.prune_empty(keep=keep.sid)
    assert removed == 2
    assert [s.sid for s in store.sessions] == [keep.sid]
    assert store.get(junk1.sid) is None and store.get(junk2.sid) is None


def test_prune_empty_keeps_session_with_records(store):
    a = store.create("A")
    a.add_record("agent", "q", "a")
    removed = store.prune_empty()
    assert removed == 0
    assert store.get(a.sid) is not None
