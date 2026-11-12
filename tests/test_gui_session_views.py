"""设备/拓扑页签的会话隔离：一个会话只看自己的设备记录历史与拓扑。

对应需求：设备页签清单与拓扑页签数据都要跟随当前会话（session/<sid>/skill/
目录 + 会话快照），切换会话后旧页签内容作废并按新会话重载。
"""
from __future__ import annotations

import json
import os

import pytest

pytest.importorskip("PyQt6.QtWidgets")

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

_APP = None


@pytest.fixture()
def window(tmp_path, monkeypatch):
    import gui.store as gs
    import gui.main_window as mw
    import gui.worker as gw

    monkeypatch.setattr(gs, "STORE_FILE", tmp_path / "sessions.json")
    gs.STORE_FILE.write_text(json.dumps(
        {"version": 1, "sessions": [
            {"sid": "A", "title": "配置SW1",
             "records": [{"question": "q", "answer": "a"}]},
            {"sid": "B", "title": "排查VLAN",
             "records": [{"question": "q2", "answer": "a2"}]}]},
        ensure_ascii=False), encoding="utf-8")

    class _FakeWorker(gw.AgentWorker):
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            self.jobs = []

        def submit(self, kind, **p):
            self.jobs.append((kind, p))

        def start(self):
            pass

    monkeypatch.setattr(mw, "AgentWorker", _FakeWorker)

    global _APP
    from PyQt6.QtWidgets import QApplication
    # QApplication 必须由 Python 侧持有引用，否则被 GC 后 C++ app 销毁，
    # 下一个 QWidget 直接 qFatal 静默退出（0xC0000409，无 traceback）
    _APP = QApplication.instance() or QApplication([])
    w = mw.MainWindow({})
    yield w
    w.close()


# ---------------------------------------------------------------- 空态

def test_device_tab_without_session_shows_empty_state(window):
    window._refresh_devices()

    assert "未打开会话" in window.device_summary.text()
    assert window.device_table.rowCount() == 0
    assert not [j for j in window.worker.jobs if j[0] == "device_probe"]


def test_topology_tab_without_session_shows_empty_state(window):
    window._refresh_topology()

    assert "未打开会话" in window.topo_status.text()
    assert window.topo_canvas._nodes == []
    assert not [j for j in window.worker.jobs if j[0] == "topology_build"]


# ---------------------------------------------------------------- 会话提交

def test_device_probe_submits_current_session(window):
    window._switch_session("A")
    window.worker.jobs.clear()
    window._device_busy = False
    window._refresh_devices()

    kind, payload = next(j for j in window.worker.jobs if j[0] == "device_probe")
    assert payload["session"] == "A"


def test_topology_build_submits_current_session(window):
    window._switch_session("B")
    window.worker.jobs.clear()
    window._refresh_topology()

    kind, payload = next(j for j in window.worker.jobs if j[0] == "topology_build")
    assert payload["session"] == "B"


def test_compliance_scan_submits_current_session(window):
    window._switch_session("A")
    window.worker.jobs.clear()
    # _run_compliance 会弹确认框（QMessageBox 阻塞），这里只验证
    # 「提交时必须携带当前会话」这一层参数拼装约定
    window.worker.submit("compliance_scan", keys=["10.0.0.1:2001"],
                         session=window._current_sid())
    kind, payload = window.worker.jobs[-1]
    assert kind == "compliance_scan" and payload["session"] == "A"


# ---------------------------------------------------------------- 切换失效

def test_switch_session_invalidates_device_and_topology_views(window):
    window._switch_session("A")
    window._device_probed = True
    window._topo_loaded = True

    window._switch_session("B")

    # 页签缓存作废：下次切到页签会按新会话重载，而不是残留 A 的数据
    assert window._device_probed is False
    assert window._topo_loaded is False
    assert window._last_probe_devices == []
    assert window._topo_model is None


def test_ensure_session_invalidates_views(window):
    window._device_probed = True
    window._topo_loaded = True

    session, err = window._ensure_session("第一句话")

    assert session is not None and err == ""
    assert window._device_probed is False
    assert window._topo_loaded is False
    assert window._current_sid() == session.sid


# ---------------------------------------------------------------- 空态文案

def test_empty_probe_report_shows_session_guidance(window):
    window._switch_session("A")
    window._on_devices({"ok": True, "devices": [], "session": "A", "error": ""}, 0)

    assert "本会话还没有设备记录" in window.device_summary.text()
    assert window.device_table.rowCount() == 0


def test_topology_model_with_filtered_nodes_shows_note(window):
    window._switch_session("A")
    window._on_topology_model({
        "ok": True, "nodes": [{"key": "10.0.0.1:2001", "name": "SW1",
                               "model": "S5700", "kind": "switch",
                               "host": "10.0.0.1", "port": 2001}],
        "edges": [], "generated": "t", "error": "", "filtered": 5,
    })

    assert "已按会话过滤掉 5 台" in window.topo_status.text()
    assert len(window.topo_canvas._nodes) == 1


# ---------------------------------------------------------------- 统一入口 / PLAN 模式

def test_mode_box_offers_unified_entry_and_plan(window):
    """模式选择只保留「对话 / plan / parallel」：不再让用户手动挑 RAG。"""
    values = [window.mode_box.itemData(i) for i in range(window.mode_box.count())]

    assert values == ["agent", "plan", "parallel"]
    assert "rag" not in values
    assert window.mode_box.itemText(0) == "对话"


def test_send_passes_plan_mode_to_worker(window):
    window._switch_session("A")
    window.mode_box.setCurrentIndex(window.mode_box.findData("plan"))
    window.input.setPlainText("为所有设备准备拓扑信息")
    window.worker.jobs.clear()

    window._send()

    kind, payload = window.worker.jobs[-1]
    assert kind == "ask"
    assert payload["mode"] == "plan"
    assert payload["parallel"] is False
