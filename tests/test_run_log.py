"""core/run_log.py 单元测试：会话写入 / 读取 / 开关 / 文件名安全化。

run_log 的落盘根目录默认是项目 data/run_logs——测试里改用 tmp_path，
避免污染真实运行日志。
"""
import json
import os

import pytest

from core import run_log as rl


@pytest.fixture()
def isolated_log(tmp_path, monkeypatch):
    """把日志根指向临时目录，并把模块级会话状态复位。"""
    monkeypatch.setattr(rl, "LOG_ROOT", tmp_path / "run_logs")
    monkeypatch.setattr(rl, "_dir", None)
    monkeypatch.setattr(rl, "_session", "default")
    monkeypatch.setattr(rl, "_seq", {"n": 0})
    return tmp_path / "run_logs"


def test_safe_name_strips_path_chars():
    """实验名常带中文与顿号，还可能有斜杠——必须转成安全文件名。"""
    assert "/" not in rl._safe("01-ACL/IP-PREFIX")
    assert rl._safe("") == "default"
    assert len(rl._safe("x" * 200)) <= 80


def test_event_written_and_read_back(isolated_log):
    rl.set_session("测试会话")
    rl.event("device_probe", name="LSW1", port=2000, ok=True)
    rl.event("verify", name="LSW1", pct=100.0)
    rows = []
    for line in rl.events_path().read_text(encoding="utf-8").splitlines():
        rows.append(json.loads(line))
    assert [r["kind"] for r in rows] == ["device_probe", "verify"]
    # 每条都自动盖了时间戳、序号与会话名
    assert rows[0]["name"] == "LSW1"
    assert "ts" in rows[0] and rows[0]["seq"] == 1 and rows[1]["seq"] == 2
    assert rows[0]["session"] == "测试会话"


def test_log_step_truncates_long_output(isolated_log):
    """设备回显可能上千行，落盘要截断，避免日志文件失控。"""
    rl.set_session("t")
    row = rl.log_step(round_no=1, name="exec_telnet_command",
                      args={"command": "display current-configuration"},
                      output="x" * 9000)
    assert len(row["output"]) == 4000
    assert row["output_len"] == 9000          # 原始长度仍保留，便于判断是否被截断


def test_read_session_roundtrip(isolated_log):
    rl.set_session("s1")
    rl.log_step(round_no=1, name="toolA", args={}, output="o1")
    rl.log_step(round_no=2, name="toolB", args={}, output="o2")
    import datetime
    today = datetime.date.today().isoformat()
    rows = rl.read_session(today, "s1")
    assert [r["tool"] for r in rows] == ["toolA", "toolB"]


def test_read_session_missing_returns_empty(isolated_log):
    import datetime
    rows = rl.read_session(datetime.date.today().isoformat(), "不存在的会话")
    assert rows == []


def test_list_sessions_excludes_events(isolated_log):
    """会话列表来自 <会话>.jsonl，`.events.jsonl` 是附属文件不算独立会话。

    labA 只有 events（没用过 log_step）时不会出现在列表里——这是刻意的：
    列表语义是「会话名」，不是「文件存在」。
    """
    rl.set_session("labA")
    rl.event("x", a=1)
    rl.set_session("labB")
    rl.log_step(round_no=1, name="t", args={}, output="o")
    import datetime
    names = rl.list_sessions(datetime.date.today().isoformat())
    assert "labB" in names
    assert not any(n.endswith(".events") for n in names), "事件的 .events 后缀不应作为会话名出现"
    assert "labA" not in names, "只有 events 的会话不进列表"


def test_disabled_switch_writes_nothing(isolated_log, monkeypatch):
    """NETWORKCLAW_RUNLOG=0 时不再落盘（但函数仍返回记录，便于调用方复用）。"""
    monkeypatch.setenv("NETWORKCLAW_RUNLOG", "0")
    rl.set_session("off")
    row = rl.event("device_probe", name="LSW1")
    assert row["kind"] == "device_probe"          # 返回值照给
    assert not rl.events_path().exists(), "关闭后不应创建文件"


def test_enabled_default_true(isolated_log, monkeypatch):
    monkeypatch.delenv("NETWORKCLAW_RUNLOG", raising=False)
    assert rl.enabled() is True
    monkeypatch.setenv("NETWORKCLAW_RUNLOG", "false")
    assert rl.enabled() is False


def test_log_call_captures_summary_not_full_prompt(isolated_log):
    """提示词只存摘要（角色 + 长度 + 头部），否则 4K token 的系统提示会撑爆日志。"""

    class R:
        provider, model = "local", "Qwen3.5-9B"
        content = "答案"
        tool_calls: list = []
        think_chunks = answer_chunks = 0
        usage = {"total_tokens": 10}

    rl.set_session("c")
    row = rl.log_call(messages=[{"role": "system", "content": "S" * 5000}],
                      result=R(), elapsed=1.234)
    assert row["kind"] == "llm_call"
    assert row["messages"][0]["len"] == 5000
    assert len(row["messages"][0]["head"]) == 400    # 只留头部
    assert row["elapsed_s"] == 1.23
