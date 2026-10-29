"""Shared ordinary conversation export model and renderers."""
from __future__ import annotations

import datetime
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class SessionRecord:
    mode: str = "?"
    question: str = ""
    answer: str = ""
    provider: str = ""
    elapsed: float = 0.0
    time: str = ""


@dataclass
class SessionDocument:
    sid: str = ""
    title: str = "NetworkClaw 会话记录"
    created: str = ""
    updated: str = ""
    records: list[SessionRecord] = field(default_factory=list)


def _now() -> str:
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def normalize_record(record) -> SessionRecord:
    if isinstance(record, dict):
        return SessionRecord(
            mode=str(record.get("mode", "?")),
            question=str(record.get("question", "")),
            answer=str(record.get("answer", "")),
            provider=str(record.get("provider", "")),
            elapsed=float(record.get("elapsed", 0.0) or 0.0),
            time=str(record.get("time", "")),
        )
    values = list(record or ())
    return SessionRecord(
        mode=str(values[0]) if len(values) > 0 else "?",
        question=str(values[1]) if len(values) > 1 else "",
        answer=str(values[2]) if len(values) > 2 else "",
    )


def build_document(records, *, sid: str = "", title: str = "NetworkClaw 会话记录",
                   created: str = "", updated: str = "") -> SessionDocument:
    normalized = [normalize_record(record) for record in (records or [])]
    return SessionDocument(
        sid=sid,
        title=title or "NetworkClaw 会话记录",
        created=created or _now(),
        updated=updated or (normalized[-1].time if normalized and normalized[-1].time else _now()),
        records=normalized,
    )


def render_markdown(document: SessionDocument) -> str:
    lines = [f"# {document.title}", "", f"- 会话标识：{document.sid or '未指定'}",
             f"- 创建时间：{document.created}", f"- 最后更新：{document.updated}",
             f"- 轮次：{len(document.records)}", ""]
    for index, record in enumerate(document.records, 1):
        head = f"## {index}. [{record.mode}]"
        if record.provider:
            head += f" {record.provider}"
        if record.elapsed:
            head += f"（{record.elapsed}s）"
        lines += [head, "", f"**提问：** {record.question}", "",
                  record.answer or "（无回答）", ""]
    return "\n".join(lines)


def render_json(document: SessionDocument) -> str:
    payload = asdict(document)
    payload["records"] = [asdict(record) for record in document.records]
    return json.dumps(payload, ensure_ascii=False, indent=2)


def export_markdown(document: SessionDocument, path: str | Path) -> Path:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render_markdown(document), encoding="utf-8")
    return output
