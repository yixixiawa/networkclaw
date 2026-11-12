"""输入框粘贴图片：以「文件名」形式贴上、悬停预览、删标记同步附件。

覆盖三件事（对应本轮需求）：
1. 剪贴板有图 → 粘贴后输入框里出现 `🖼 <文件名>`，而不是内联一张图；
2. 鼠标指向这段文件名 → 浮层预览（移开/滚轮/失焦即消失）；
3. 文件名删掉 ≈ 取消该附件；附件栏点 ✕ 也会把文件名一起删掉。

CI 不装 PyQt6：importorskip 让这些用例在 CI 上跳过而不是挂掉。
"""
from __future__ import annotations

import json
import os

import pytest

pytest.importorskip("PyQt6.QtWidgets")

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path

from PyQt6.QtCore import QEvent, QMimeData, QPoint, QPointF, Qt
from PyQt6.QtGui import QColor, QImage, QMouseEvent


# ---------------------------------------------------------------- 夹具

#: QApplication 必须由 Python 侧持有一个引用，否则包装对象被回收 → C++ 的 app 跟着销毁，
#: 之后的第一个 QWidget 直接 qFatal（"Must construct a QApplication before a QWidget"），
#: 进程以 0xC0000409 静默退出，pytest 连 traceback 都留不下来。
_APP = None


@pytest.fixture(scope="session")
def app():
    global _APP
    from PyQt6.QtWidgets import QApplication

    _APP = QApplication.instance() or QApplication([])
    return _APP


@pytest.fixture()
def paste_dir(tmp_path, monkeypatch):
    """粘贴落盘改到 tmp，别往真实 data/pasted_images 里写测试垃圾"""
    import core.paste_store as ps
    d = tmp_path / "pasted"
    monkeypatch.setattr(ps, "paste_dir", lambda: d)
    return d


@pytest.fixture()
def edit(app, paste_dir):
    import gui.main_window as mw
    from gui.theme import get_palette

    w = mw.InputEdit(get_palette("dark"))
    w.resize(420, 120)
    w.show()
    yield w
    w.close()


@pytest.fixture()
def window(app, tmp_path, monkeypatch, paste_dir):
    """真 MainWindow + 假 worker（只拦 submit/start，不起线程）"""
    import gui.store as gs
    import gui.main_window as mw
    import gui.worker as gw

    monkeypatch.setattr(gs, "STORE_FILE", tmp_path / "sessions.json")
    gs.STORE_FILE.write_text(json.dumps({"version": 1, "sessions": []}), encoding="utf-8")

    class _FakeWorker(gw.AgentWorker):
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            self.jobs = []

        def submit(self, kind, **p):
            self.jobs.append((kind, p))

        def start(self):
            pass

    monkeypatch.setattr(mw, "AgentWorker", _FakeWorker)

    w = mw.MainWindow({})
    yield w
    w.close()


# ---------------------------------------------------------------- 工具

def image_mime(w: int = 90, h: int = 60, color: str = "#3366ff") -> QMimeData:
    img = QImage(w, h, QImage.Format.Format_RGB32)
    img.fill(QColor(color))
    mime = QMimeData()
    mime.setImageData(img)
    return mime


def marker_point(edit, path: str) -> QPoint:
    """标记文本中间的控件内坐标"""
    from gui.widgets import image_marker_text

    cur = edit.document().find(image_marker_text(path))
    assert not cur.isNull(), "文本里没有该图片的文件名标记"
    cur.setPosition(cur.selectionStart() + 2)
    rect = edit.cursorRect(cur)
    return QPoint(rect.center().x(), rect.center().y())


def move_mouse(edit, pos: QPoint):
    global_pos = edit.viewport().mapToGlobal(pos)
    edit.mouseMoveEvent(QMouseEvent(
        QEvent.Type.MouseMove, QPointF(pos), QPointF(global_pos),
        Qt.MouseButton.NoButton, Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier))


# ---------------------------------------------------------------- 粘贴

def test_paste_image_inserts_filename_marker(edit):
    from gui.widgets import image_marker_text

    pasted: list[list[str]] = []
    edit.images_pasted.connect(pasted.append)

    edit.insertFromMimeData(image_mime())

    assert len(pasted) == 1
    path = pasted[0][0]
    assert Path(path).is_file()
    # 输入框里是文件名文本，不是内联图像
    assert edit.toPlainText().strip() == image_marker_text(path)
    assert Path(path).name in edit.toPlainText()
    assert edit.document().isEmpty() is False


def test_paste_same_image_twice_reuses_file(edit, paste_dir):
    pasted: list[list[str]] = []
    edit.images_pasted.connect(pasted.append)

    edit.insertFromMimeData(image_mime())
    edit.insertFromMimeData(image_mime())

    assert pasted[0] == pasted[1]
    assert len(list(Path(paste_dir).iterdir())) == 1


def test_paste_plain_text_still_works(edit):
    mime = QMimeData()
    mime.setText("display current-configuration")

    edit.insertFromMimeData(mime)

    assert edit.toPlainText() == "display current-configuration"


# ---------------------------------------------------------------- 悬停预览

def test_hover_marker_hits_and_blank_area_misses(edit):
    pasted: list[list[str]] = []
    edit.images_pasted.connect(pasted.append)
    edit.insertFromMimeData(image_mime())
    path = pasted[0][0]

    assert edit.marker_path_at(marker_point(edit, path)) == path
    assert edit.marker_path_at(QPoint(5, edit.height() - 5)) == ""


def test_mouse_move_shows_preview_and_leave_hides(edit):
    pasted: list[list[str]] = []
    edit.images_pasted.connect(pasted.append)
    edit.insertFromMimeData(image_mime())
    path = pasted[0][0]

    move_mouse(edit, marker_point(edit, path))
    assert edit._preview.isVisible()
    assert edit._hover_path == path

    edit.leaveEvent(QEvent(QEvent.Type.Leave))
    assert not edit._preview.isVisible()
    assert edit._hover_path == ""


def test_preview_caption_carries_filename_and_size(edit):
    pasted: list[list[str]] = []
    edit.images_pasted.connect(pasted.append)
    edit.insertFromMimeData(image_mime(120, 80))
    path = pasted[0][0]

    move_mouse(edit, marker_point(edit, path))

    caption = edit._preview._caption.text()
    assert Path(path).name in caption
    assert "120×80" in caption


def test_missing_file_hides_preview(edit, paste_dir):
    pasted: list[list[str]] = []
    edit.images_pasted.connect(pasted.append)
    edit.insertFromMimeData(image_mime())
    path = pasted[0][0]

    Path(path).unlink()
    edit._preview._cache.clear()

    assert edit._preview.show_for(path, QPoint(10, 10)) is False
    assert not edit._preview.isVisible()


# ---------------------------------------------------------------- 删除同步

def test_deleting_marker_text_emits_image_removed(edit):
    pasted: list[list[str]] = []
    removed: list[str] = []
    edit.images_pasted.connect(pasted.append)
    edit.image_removed.connect(removed.append)

    edit.insertFromMimeData(image_mime())
    edit.selectAll()
    edit.textCursor().removeSelectedText()

    assert removed == pasted[0]


def test_programmatic_clear_does_not_emit_removal(edit):
    removed: list[str] = []
    edit.image_removed.connect(removed.append)
    edit.insertFromMimeData(image_mime())

    edit.clear()  # 发送后清空输入框：不该被当成「用户删了这张图」

    assert removed == []
    assert edit.toPlainText() == ""


def test_remove_marker_strips_text_and_keeps_other_markers(edit):
    pasted: list[list[str]] = []
    edit.images_pasted.connect(pasted.append)
    edit.insertFromMimeData(image_mime(color="#ff0000"))
    edit.insertFromMimeData(image_mime(color="#00ff00"))
    first, second = pasted[0][0], pasted[1][0]

    edit.remove_marker(first)

    text = edit.toPlainText()
    assert Path(first).name not in text
    assert Path(second).name in text


def test_decorate_images_restores_hover_after_plaintext_restore(edit):
    """草稿还原走 setPlainText（纯文本丢字符格式），补一次标记才能继续悬停"""
    from gui.widgets import image_marker_text

    pasted: list[list[str]] = []
    edit.images_pasted.connect(pasted.append)
    edit.insertFromMimeData(image_mime())
    path = pasted[0][0]

    edit.setPlainText(image_marker_text(path))          # 纯文本：没有路径属性
    assert edit.marker_path_at(marker_point(edit, path)) == ""

    edit.decorate_images([path])                        # 补回标记格式
    assert edit.marker_path_at(marker_point(edit, path)) == path


# ---------------------------------------------------------------- 窗口集成

def test_window_shows_chip_and_submits_pasted_image(window):
    window.input.insertFromMimeData(image_mime())

    assert len(window.images) == 1
    assert window.attach_bar.isVisibleTo(window)

    window._send()

    kind, payload = window.worker.jobs[-1]
    assert kind == "ask"
    assert len(payload["images"]) == 1, "粘贴的图片要随本轮提交给模型"
    assert payload["images"][0].endswith(".png")
    assert window.input.toPlainText() == ""      # 发完清空
    assert window.images == []                   # 附件栏也清空


def test_window_bubble_reuses_pasted_filename_without_duplicate_line(window):
    window.input.insertFromMimeData(image_mime())
    name = Path(window.images[0]).name

    window._send()

    shown = window.chat._bubbles[-1]._answer
    assert name in shown          # 用户气泡里有文件名
    assert "📎" not in shown       # 但不再重复补一行附件清单


def test_window_attach_bar_remove_strips_marker(window):
    window.input.insertFromMimeData(image_mime())
    path = window.images[0]

    window._remove_image(path)

    assert window.images == []
    assert Path(path).name not in window.input.toPlainText()
