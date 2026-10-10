"""模型运行日志：把每一次 LLM 调用、每一次工具下发都落盘成 JSONL。

存在的意义：
    本地模型（Qwen3.5-9B）在真实设备上配置时，经常出现「想得很多、答得很短」
    「工具参数拼错」「命令顺序颠倒」等问题。要定位这些问题不能靠回忆，必须有
    可回溯的原始记录——每一轮的提示词、思考、回答、工具调用与设备回显都得留下。

    这些记录同时是**微调数据集的原料**：跑完一批实验后，用 tools/build_sft.py
    从里面筛出「模型做对了」的样本，导出成 SFT 的 instruction/output 对。

落盘位置：
    data/run_logs/<日期>/<会话标识>.jsonl         每次调用一行
    data/run_logs/<日期>/<会话标识>.events.jsonl  实验过程事件（设备探测、校验…）

开关：
    环境变量 NETWORKCLAW_RUNLOG = 0 时关闭（默认开启）。

用法：
    from core import run_log
    run_log.set_session("01-ACCESS配置")   # 设定当前会话（决定文件名）
    run_log.event("device_probe", name="LSW1", port=2000, ok=True)
    # core.llm_client 会自动调用 log_call()；core.agent 会自动调用 log_step()
"""
from __future__ import annotations

import datetime
import json
import os
import re
import threading
from pathlib import Path
from typing import Any

from core.paths import BASE_DIR

LOG_ROOT = BASE_DIR / "data" / "run_logs"
_LOCK = threading.Lock()

_session: str = "default"
_dir: Path | None = None
_seq = {"n": 0}


def enabled() -> bool:
    return os.environ.get("NETWORKCLAW_RUNLOG", "1") not in ("0", "false", "False", "")


def _safe(name: str) -> str:
    """把会话名做成安全文件名（实验名里常有中文与顿号）"""
    s = re.sub(r"[\\/:*?\"<>|\r\n\t]", "_", (name or "default").strip())
    return s[:80] or "default"


def set_session(tag: str) -> Path:
    """设定当前会话标识，返回日志文件路径"""
    global _session, _dir
    _session = _safe(tag)
    _seq["n"] = 0
    _dir = LOG_ROOT / datetime.date.today().isoformat()
    _dir.mkdir(parents=True, exist_ok=True)
    return _dir / f"{_session}.jsonl"


def session() -> str:
    return _session


def path() -> Path:
    if _dir is None:
        set_session(_session)
    assert _dir is not None
    return _dir / f"{_session}.jsonl"


def events_path() -> Path:
    if _dir is None:
        set_session(_session)
    assert _dir is not None
    return _dir / f"{_session}.events.jsonl"


def _write(fp: Path, row: dict) -> None:
    fp.parent.mkdir(parents=True, exist_ok=True)
    with _LOCK:
        with fp.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
            f.flush()


def _stamp(row: dict) -> dict:
    _seq["n"] += 1
    row.setdefault("ts", datetime.datetime.now().isoformat(timespec="seconds"))
    row.setdefault("seq", _seq["n"])
    row.setdefault("session", _session)
    return row


def event(kind: str, **data: Any) -> dict:
    """记录一个过程事件（设备探测、配置下发、校验结果、人工批注…）"""
    row = _stamp({"kind": kind, **data})
    if enabled():
        try:
            _write(events_path(), row)
        except Exception:
            pass
    return row


def log_call(*, messages: list[dict] | None, result: Any, elapsed: float,
             tag: str = "", note: str = "") -> dict:
    """记录一次 LLM 调用（由 core.llm_client.stream_chat 自动调用）。

    提示词只存摘要：系统提示词记长度，用户/工具消息记角色与前若干字符，
    避免日志文件被 4K token 的系统提示词撑爆。
    """
    msgs: list[dict] = []
    for m in messages or []:
        c = m.get("content")
        text = c if isinstance(c, str) else json.dumps(c, ensure_ascii=False)
        msgs.append({
            "role": m.get("role", "?"),
            "len": len(text),
            "head": text[:400],
        })
    usage = getattr(result, "usage", None) or {}
    row = _stamp({
        "kind": "llm_call",
        "tag": tag,
        "provider": getattr(result, "provider", ""),
        "model": getattr(result, "model", ""),
        "elapsed_s": round(elapsed, 2),
        "messages": msgs,
        "answer": (getattr(result, "content", "") or ""),
        "answer_len": len(getattr(result, "content", "") or ""),
        "tool_calls": getattr(result, "tool_calls", []) or [],
        "think_chunks": getattr(result, "think_chunks", 0),
        "answer_chunks": getattr(result, "answer_chunks", 0),
        "usage": usage,
        "note": note,
    })
    if enabled():
        try:
            _write(path(), row)
        except Exception:
            pass
    return row


def log_step(*, round_no: int, name: str, args: dict, output: str) -> dict:
    """记录 Agent 循环里的一次工具调用（命令下发 + 设备回显）。"""
    row = _stamp({
        "kind": "tool_step",
        "round": round_no,
        "tool": name,
        "args": args,
        "output": (output or "")[:4000],
        "output_len": len(output or ""),
    })
    if enabled():
        try:
            _write(path(), row)
        except Exception:
            pass
    return row


def read_session(day: str | None = None, tag: str = "default") -> list[dict]:
    """读取某个会话的日志行（供复盘/导出微调数据用）"""
    d = LOG_ROOT / (day or datetime.date.today().isoformat())
    fp = d / f"{_safe(tag)}.jsonl"
    if not fp.exists():
        return []
    rows = []
    for line in fp.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def list_sessions(day: str | None = None) -> list[str]:
    d = LOG_ROOT / (day or datetime.date.today().isoformat())
    if not d.exists():
        return []
    return sorted(p.name[: -len(".jsonl")] for p in d.glob("*.jsonl")
                  if not p.name.endswith(".events.jsonl"))


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "list":
        day = sys.argv[2] if len(sys.argv) > 2 else None
        for s in list_sessions(day):
            print(s)
    else:
        print(f"日志根目录：{LOG_ROOT}")
        for d in sorted(LOG_ROOT.glob("*")):
            if d.is_dir():
                print(f"  {d.name}: {len(list(d.glob('*.jsonl')))} 个会话")
