"""会话持久化：把桌面端的会话记录存成 JSON，并支持导出 Markdown。

存储位置：`<工作目录>/data/sessions.json`（打包后即 exe 同目录的 data/）。
选 JSON 而不是数据库的原因：会话量级很小（个人使用），出问题时用户能直接打开看、
甚至手工修；也不需要引入额外依赖。

记录结构（单条）：
    {"mode": "agent", "question": "...", "answer": "...",
     "provider": "local", "elapsed": 3.2, "time": "2026-09-21 15:04:05"}
"""
from __future__ import annotations

import datetime
import json
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from core.paths import BASE_DIR
from core.session_export import build_document, export_markdown, render_markdown

STORE_FILE = BASE_DIR / "data" / "sessions.json"
MAX_SESSIONS = 200


def _now() -> str:
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


@dataclass
class Session:
    """一次会话（左侧历史列表里的一项）"""

    sid: str
    title: str = "新会话"
    created: str = field(default_factory=_now)
    updated: str = field(default_factory=_now)
    records: list[dict] = field(default_factory=list)
    pinned: bool = False  # 顶置：始终排在列表最前

    # -------------------------------------------------- 展示
    @property
    def preview(self) -> str:
        """列表里的副标题：显示最后一条提问（截断）"""
        for rec in reversed(self.records):
            q = (rec.get("question") or "").strip().replace("\n", " ")
            if q:
                return q if len(q) <= 40 else q[:40] + "…"
        return "（空会话）"

    def add_record(self, mode: str, question: str, answer: str,
                   provider: str = "", elapsed: float = 0.0) -> dict:
        rec = {"mode": mode, "question": question, "answer": answer,
               "provider": provider, "elapsed": elapsed, "time": _now()}
        self.records.append(rec)
        self.updated = rec["time"]
        if self.title == "新会话" and question.strip():
            q = question.strip().replace("\n", " ")
            self.title = q if len(q) <= 24 else q[:24] + "…"
        return rec

    def to_markdown(self) -> str:
        document = build_document(
            self.records, sid=self.sid, title=self.title,
            created=self.created, updated=self.updated)
        return render_markdown(document)

    def export_markdown(self, path: str | Path) -> Path:
        document = build_document(
            self.records, sid=self.sid, title=self.title,
            created=self.created, updated=self.updated)
        return export_markdown(document, path)

    def to_dict(self) -> dict:
        return {"sid": self.sid, "title": self.title, "created": self.created,
                "updated": self.updated, "records": self.records,
                "pinned": self.pinned}

    @classmethod
    def from_dict(cls, data: dict) -> "Session":
        return cls(
            sid=data.get("sid") or uuid.uuid4().hex[:12],
            title=data.get("title") or "新会话",
            created=data.get("created") or _now(),
            updated=data.get("updated") or _now(),
            records=list(data.get("records") or []),
            pinned=bool(data.get("pinned")),
        )


class SessionStore:
    """会话集合的读写（整体读写，量小且简单可控）"""

    def __init__(self, path: Path | None = None):
        self.path = Path(path) if path else STORE_FILE
        self.sessions: list[Session] = []

    # -------------------------------------------------- 读写
    def load(self) -> list[Session]:
        if not self.path.is_file():
            self.sessions = []
            return self.sessions
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            self.sessions = []
            return self.sessions
        items = data.get("sessions") if isinstance(data, dict) else data
        self.sessions = [Session.from_dict(d) for d in (items or []) if isinstance(d, dict)]
        # 只保留有对话历史的会话：空会话没有复盘价值，却会随启动/新建不断堆积，
        # 用户要求「空 session 一律删除」。当前会话在界面层另行兜底（见 main_window）。
        self.sessions = [s for s in self.sessions if s.records]
        return self.sessions

    def save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            payload = {"version": 1, "saved_at": _now(),
                       "sessions": [s.to_dict() for s in self.sessions[:MAX_SESSIONS]]}
            self.path.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                                 encoding="utf-8")
        except OSError:
            pass  # 存档失败不应影响正在进行的对话

    # -------------------------------------------------- 增删改查
    def _pinned_count(self) -> int:
        """顶置会话数量（都排在列表最前）"""
        return sum(1 for s in self.sessions if s.pinned)

    def create(self, title: str = "新会话") -> Session:
        s = Session(sid=uuid.uuid4().hex[:12], title=title)
        # 插在顶置块之后、普通会话之前（顶置始终压在最前）
        self.sessions.insert(self._pinned_count(), s)
        self.save()
        return s

    def get(self, sid: str) -> Session | None:
        return next((s for s in self.sessions if s.sid == sid), None)

    def delete(self, sid: str) -> None:
        self.sessions = [s for s in self.sessions if s.sid != sid]
        self.save()

    def rename(self, sid: str, title: str) -> None:
        s = self.get(sid)
        if s is not None and title.strip():
            s.title = title.strip()
            s.updated = _now()
            self.save()

    def set_pinned(self, sid: str, pinned: bool) -> None:
        """顶置 / 取消顶置，并保持「顶置块在前」的顺序"""
        s = self.get(sid)
        if s is None or s.pinned == pinned:
            return
        s.pinned = pinned
        self.sessions.remove(s)
        if pinned:
            self.sessions.insert(0, s)
        else:
            self.sessions.insert(self._pinned_count(), s)
        self.save()

    def touch(self, sid: str) -> None:
        """把某个会话移到最前（最近使用优先；顶置会话移到顶置块最前）"""
        s = self.get(sid)
        if s is None:
            return
        self.sessions.remove(s)
        self.sessions.insert(self._pinned_count() if not s.pinned else 0, s)
        self.save()

    def prune_empty(self, keep: str | None = None) -> int:
        """删除没有对话历史的空会话（keep 指定的 sid 保留，例如正在使用的当前会话）。

        注意：这里只清 GUI 清单（sessions.json）。会话在磁盘上的技能目录
        （session/<sid>/skill/）可能含有 MCP 写入的设备手册/命令历史，
        不在这里删，避免误伤运行期产物；目录清理走独立的维护入口。
        返回删除的数量。
        """
        before = len(self.sessions)
        self.sessions = [s for s in self.sessions if s.records or s.sid == keep]
        removed = before - len(self.sessions)
        if removed:
            self.save()
        return removed
