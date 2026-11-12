"""会话恢复：把 GUI 记录还原成模型上下文（避免切换会话后「失忆」）。

背景（实测）：`_switch_session` 原来只发 `reset_history`，界面把气泡重绘出来了，
但 worker 的 `_history` 是空的——切回旧会话继续追问，模型完全不记得前文
（刚配过什么、查过哪台设备）。这里锁住「记录 → [{role,content}]」的转换契约。
"""
from __future__ import annotations

from core.conversation_service import HISTORY_WINDOW, history_from_records


def _rec(q: str, a: str) -> dict:
    return {"mode": "agent", "question": q, "answer": a,
            "provider": "deepseek-flash", "elapsed": 1.0}


def test_empty_records_restore_nothing():
    assert history_from_records([]) == []
    assert history_from_records(None) == []


def test_question_answer_become_user_assistant_pair():
    msgs = history_from_records([_rec("display version", "VRP V5")])
    assert msgs == [{"role": "user", "content": "display version"},
                    {"role": "assistant", "content": "VRP V5"}]


def test_order_preserved_across_multiple_rounds():
    msgs = history_from_records([_rec("第一问", "第一答"), _rec("第二问", "第二答")])
    assert [m["content"] for m in msgs] == ["第一问", "第一答", "第二问", "第二答"]
    assert [m["role"] for m in msgs] == ["user", "assistant", "user", "assistant"]


def test_window_keeps_latest_messages_only():
    records = [_rec(f"q{i}", f"a{i}") for i in range(10)]
    msgs = history_from_records(records)
    assert len(msgs) == HISTORY_WINDOW
    # 保留的是最近几条（和运行期 del self._history[:-8] 的窗口一致）
    assert msgs[-1]["content"] == "a9"


def test_failed_round_without_answer_keeps_user_message():
    msgs = history_from_records([{"question": "ping 8.8.8.8", "answer": ""}])
    assert msgs == [{"role": "user", "content": "ping 8.8.8.8"}]


def test_blank_and_non_dict_entries_are_skipped():
    msgs = history_from_records([{"question": "  ", "answer": "  "}, "junk", None,
                                 _rec("真问题", "真回答")])
    assert msgs == [{"role": "user", "content": "真问题"},
                    {"role": "assistant", "content": "真回答"}]


def test_limit_zero_keeps_everything():
    records = [_rec(f"q{i}", f"a{i}") for i in range(6)]
    assert len(history_from_records(records, limit=0)) == 12
