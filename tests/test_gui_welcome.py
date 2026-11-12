"""欢迎页：启动不打开任何会话，历史只在用户点击侧边栏时才加载。

CI 不装 PyQt6：importorskip 让这些用例在 CI 上跳过而不是挂掉
（教训见 docs/build_and_ci_fix.md：tests 直接 import gui.* 曾经炸掉构建）。
"""
from __future__ import annotations

import json

import pytest

pytest.importorskip("PyQt6.QtWidgets")

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture()
def window(tmp_path, monkeypatch):
    import gui.store as gs
    import gui.main_window as mw

    monkeypatch.setattr(gs, "STORE_FILE", tmp_path / "sessions.json")
    gs.STORE_FILE.write_text(json.dumps(
        {"version": 1, "sessions": [
            {"sid": "A", "title": "配置SW1",
             "records": [{"question": "display version", "answer": "VRP V5"}]},
            {"sid": "B", "title": "排查VLAN",
             "records": [{"question": "q2", "answer": "a2"}]}]},
        ensure_ascii=False), encoding="utf-8")

    # 子类化真 worker：保留全部信号（main_window 启动时要 connect），
    # 只拦截 submit/start —— 测试里不能真起线程
    import gui.worker as gw

    class _FakeWorker(gw.AgentWorker):
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            self.jobs = []

        def submit(self, kind, **p):
            self.jobs.append((kind, p))

        def start(self):
            pass

    monkeypatch.setattr(mw, "AgentWorker", _FakeWorker)

    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    w = mw.MainWindow({})
    yield w
    w.close()


def test_startup_lands_on_welcome_not_any_session(window):
    from gui.main_window import PAGE_WELCOME

    assert window.current_session is None                      # 不持有任何会话
    assert window.chat_stack.currentIndex() == PAGE_WELCOME    # 落在欢迎页
    assert window.session_list.count() == 2                    # 历史仍在侧边栏
    assert window.session_list.currentItem() is None           # 但不选中任何一项


def test_welcome_lists_recent_sessions(window):
    titles = [b.toolTip().split(" ｜")[0] for b in window.welcome._recent_buttons]
    assert titles == ["配置SW1", "排查VLAN"]


def test_sidebar_click_opens_history(window):
    from gui.main_window import PAGE_CHAT

    window._on_session_clicked(window.session_list.item(1))
    assert window.current_session.sid == "B"
    assert window.chat_stack.currentIndex() == PAGE_CHAT
    # 点击历史不新建：清单还是 A、B 两条
    assert [s.sid for s in window.store.sessions] == ["A", "B"]


def test_sending_from_welcome_creates_session_first(window):
    from gui.main_window import PAGE_CHAT

    window._show_welcome()
    window.input.setPlainText("display interface brief")
    window._send()
    assert window.current_session is not None                  # 自动落了一个会话
    assert window.chat_stack.currentIndex() == PAGE_CHAT
    assert any(k == "ask" for k, _ in window.worker.jobs)


def test_delete_all_sessions_returns_to_welcome(window):
    from gui.main_window import PAGE_WELCOME

    for s in list(window.store.sessions):
        window.store.delete(s.sid)
    window._show_welcome()
    assert window.current_session is None
    assert window.chat_stack.currentIndex() == PAGE_WELCOME
    assert window.store.sessions == []                         # 不凭空造空会话


# ---------------------------------------------------------------- 草稿态建会话

def test_new_session_shows_window_without_creating_session(window):
    """点「新建会话」只展示空白窗口：不落 store、不占侧边栏（发出第一句才建）。"""
    window._show_welcome()
    window._new_session()
    assert window.current_session is None               # 草稿态不持有会话
    assert window.store.sessions == [] if not window.store.sessions else True
    assert len(window.store.sessions) == 2              # store 里还是原来两条
    assert window.session_list.currentItem() is None    # 侧边栏无选中
    assert window.chat.bubble_count() == 0


def test_first_send_in_draft_creates_session(window):
    """草稿态发出第一段对话：此刻才创建 session，且以首句命名。"""
    window._show_welcome()
    window._new_session()
    window.input.setPlainText("display vlan")
    window._send()
    assert window.current_session is not None
    assert window.current_session.title.startswith("display vlan")
    assert window.input.toPlainText() == ""             # 发送后清空
    assert any(k == "ask" for k, _ in window.worker.jobs)


def test_draft_input_cached_across_switch(window):
    """草稿打了字没发就切走：暂存；回草稿时还原，不丢用户输入。"""
    window._show_welcome()
    window._new_session()
    window.input.setPlainText("还没想好的问题")
    window._switch_session("A")                         # 切去旧会话
    assert window.input.toPlainText() == ""             # 输入框被暂存清空
    assert window.current_session.sid == "A"
    window._new_session()                               # 再回草稿
    assert window.input.toPlainText() == "还没想好的问题"  # 还原
    # 发送后缓存作废
    window.input.setPlainText("正式问题")
    window._send()
    window._new_session()
    assert window.input.toPlainText() == ""


def test_session_create_failure_keeps_input_and_draft(window, monkeypatch):
    """建会话失败（磁盘满等）：保持草稿态、报错、输入还原——消息不丢。"""
    window._show_welcome()
    window._new_session()
    window.input.setPlainText("珍贵的提问")

    def _boom():
        raise OSError("disk full")
    monkeypatch.setattr(window.store, "create", _boom)
    window._send()
    assert window.current_session is None               # 仍是草稿态
    assert window.input.toPlainText() == "珍贵的提问"    # 输入还原
    assert window.chat.bubble_count() == 1              # 有一条错误提示气泡
    assert not any(k == "ask" for k, _ in window.worker.jobs)


# ---------------------------------------------------------------- 草稿态建会话

def test_new_session_shows_window_without_creating_session(window):
    """点「新建会话」只展示空白窗口：不落 store、不占侧边栏（发出第一句才建）。"""
    window._show_welcome()
    window._new_session()
    assert window.current_session is None               # 草稿态不持有会话
    assert window.store.sessions == [] if not window.store.sessions else True
    assert len(window.store.sessions) == 2              # store 里还是原来两条
    assert window.session_list.currentItem() is None    # 侧边栏无选中
    assert window.chat.bubble_count() == 0


def test_first_send_in_draft_creates_session(window):
    """草稿态发出第一段对话：此刻才创建 session，且以首句命名。"""
    window._show_welcome()
    window._new_session()
    window.input.setPlainText("display vlan")
    window._send()
    assert window.current_session is not None
    assert window.current_session.title.startswith("display vlan")
    assert window.input.toPlainText() == ""             # 发送后清空
    assert any(k == "ask" for k, _ in window.worker.jobs)


def test_draft_input_cached_across_switch(window):
    """草稿打了字没发就切走：暂存；回草稿时还原，不丢用户输入。"""
    window._show_welcome()
    window._new_session()
    window.input.setPlainText("还没想好的问题")
    window._switch_session("A")                         # 切去旧会话
    assert window.input.toPlainText() == ""             # 输入框被暂存清空
    assert window.current_session.sid == "A"
    window._new_session()                               # 再回草稿
    assert window.input.toPlainText() == "还没想好的问题"  # 还原
    # 发送后缓存作废
    window.input.setPlainText("正式问题")
    window._send()
    window._new_session()
    assert window.input.toPlainText() == ""


def test_session_create_failure_keeps_input_and_draft(window, monkeypatch):
    """建会话失败（磁盘满等）：保持草稿态、报错、输入还原——消息不丢。"""
    window._show_welcome()
    window._new_session()
    window.input.setPlainText("珍贵的提问")

    def _boom():
        raise OSError("disk full")
    monkeypatch.setattr(window.store, "create", _boom)
    window._send()
    assert window.current_session is None               # 仍是草稿态
    assert window.input.toPlainText() == "珍贵的提问"    # 输入还原
    assert window.chat.bubble_count() == 1              # 有一条错误提示气泡
    assert not any(k == "ask" for k, _ in window.worker.jobs)
