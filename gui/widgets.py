"""界面基础控件：消息气泡、对话区、会话列表、附件栏、状态点等。

设计要点：
- 流式输出时分两段渲染：**输出中**用 PlainText 直接 setText（快，且不会把
  模型输出里的 `<xxx>` 当成 HTML 吞掉）；**输出结束**再切成 RichText 做一次
  轻量 Markdown 渲染（代码块、标题、列表、粗体、行内代码）。这样既有打字机效果，
  又不会每来一个 token 就重排一次富文本。
- 所有控件都不直接碰业务逻辑，只通过信号对外通报，方便 main_window 统一编排。
"""
from __future__ import annotations

import html
import re

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont, QGuiApplication, QTextCursor
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from gui.theme import Palette


# ---------------------------------------------------------------- 小工具

def status_dot(state: bool | None, palette: Palette) -> str:
    """状态点：True 绿 / False 红 / None 灰黄（未知）"""
    if state is True:
        return f'<span style="color:{palette.ok}">●</span>'
    if state is False:
        return f'<span style="color:{palette.err}">●</span>'
    return f'<span style="color:{palette.warn}">●</span>'


_FENCE_RE = re.compile(r"^```([\w+#.-]*)\s*$")
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
_LIST_RE = re.compile(r"^\s*([-*+]|\d+[.)])\s+(.*)$")


def mini_markdown(text: str, palette: Palette) -> str:
    """把模型输出渲染成 QLabel 能吃下的 HTML（够用即可，不求完整 Markdown）。

    支持：代码围栏、标题、无序/有序列表、粗体、行内代码、分隔线。
    其余内容转义后原样输出，避免 `<S5700>` 这类内容被当成标签。
    """
    code_css = (f"background:{palette.code_bg};color:{palette.text};"
                f"border:1px solid {palette.border};border-radius:6px;"
                "padding:8px 10px;white-space:pre-wrap;"
                "font-family:Consolas,'Cascadia Mono',monospace;font-size:12px;")
    inline_css = (f"background:{palette.code_bg};color:{palette.accent};"
                  "font-family:Consolas,'Cascadia Mono',monospace;font-size:12px;"
                  "padding:1px 4px;border-radius:4px;")

    out: list[str] = []
    lines = (text or "").splitlines()
    in_code = False
    code_buf: list[str] = []
    list_open: str | None = None

    def close_list():
        nonlocal list_open
        if list_open:
            out.append(f"</{list_open}>")
            list_open = None

    for raw in lines:
        fence = _FENCE_RE.match(raw.strip())
        if fence:
            if in_code:
                out.append(f'<pre style="{code_css}">{html.escape(chr(10).join(code_buf))}</pre>')
                code_buf.clear()
                in_code = False
            else:
                close_list()
                in_code = True
            continue
        if in_code:
            code_buf.append(raw)
            continue

        line = raw.rstrip()
        if not line:
            close_list()
            out.append("<div style='height:6px'></div>")
            continue
        if line.strip() in ("---", "***", "___"):
            close_list()
            out.append(f'<div style="border-top:1px solid {palette.border};margin:6px 0"></div>')
            continue

        heading = _HEADING_RE.match(line)
        if heading:
            close_list()
            level = len(heading.group(1))
            size = max(13, 18 - level)
            out.append(f'<div style="font-size:{size}px;font-weight:700;margin:6px 0 2px 0">'
                       f"{_inline(heading.group(2), inline_css, palette)}</div>")
            continue

        bullet = _LIST_RE.match(line)
        if bullet:
            want = "ul" if not bullet.group(1)[0].isdigit() else "ol"
            if list_open != want:
                close_list()
                out.append(f'<{want} style="margin:2px 0 2px 18px">')
                list_open = want
            out.append(f"<li>{_inline(bullet.group(2), inline_css, palette)}</li>")
            continue

        close_list()
        out.append(f"<div>{_inline(line, inline_css, palette)}</div>")

    if in_code and code_buf:
        out.append(f'<pre style="{code_css}">{html.escape(chr(10).join(code_buf))}</pre>')
    close_list()
    return "".join(out) or "<div>(空)</div>"


def _inline(text: str, inline_css: str, palette: Palette) -> str:
    """行内格式：行内代码、粗体（先转义再替换，避免注入）"""
    escaped = html.escape(text)
    escaped = re.sub(r"`([^`]+)`", lambda m: f'<code style="{inline_css}">{m.group(1)}</code>', escaped)
    escaped = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", escaped)
    escaped = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"<i>\1</i>", escaped)
    return escaped


# ---------------------------------------------------------------- 消息气泡

ROLE_META = {
    "user": ("你", "BubbleUser"),
    "assistant": ("NetworkClaw", "BubbleAI"),
    "system": ("系统", "BubbleAI"),
    "error": ("错误", "BubbleAI"),
}


class MessageBubble(QFrame):
    """一条消息：头部（角色/元信息）+ 正文 +（可选）思考过程折叠块"""

    def __init__(self, role: str, palette: Palette, meta: str = "",
                 parent: QWidget | None = None):
        super().__init__(parent)
        self.role = role
        self.palette_ref = palette
        self._answer = ""
        self._think = ""
        self._finished = False

        title, obj = ROLE_META.get(role, ("消息", "BubbleAI"))
        self.setObjectName(obj)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 9, 12, 11)
        outer.setSpacing(6)

        # 头部：角色名 + 元信息（模型/耗时/token）
        head = QHBoxLayout()
        head.setSpacing(8)
        self.title_label = QLabel(title)
        f = QFont()
        f.setBold(True)
        self.title_label.setFont(f)
        if role == "error":
            self.title_label.setStyleSheet(f"color:{palette.err};")
        head.addWidget(self.title_label)
        self.meta_label = QLabel(meta)
        self.meta_label.setObjectName("MsgHeader")
        head.addWidget(self.meta_label)
        head.addStretch(1)
        self.copy_btn = QPushButton("复制")
        self.copy_btn.setObjectName("IconButton")
        self.copy_btn.setToolTip("复制本条内容")
        self.copy_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.copy_btn.clicked.connect(self._copy)
        self.copy_btn.setVisible(False)
        head.addWidget(self.copy_btn)
        outer.addLayout(head)

        # 思考过程（默认隐藏，出现 thinking token 时自动展开）
        self.think_box = QTextEdit()
        self.think_box.setObjectName("ThinkBox")
        self.think_box.setReadOnly(True)
        self.think_box.setVisible(False)
        self.think_box.setMinimumHeight(60)
        self.think_box.setMaximumHeight(200)
        self.think_box.setPlaceholderText("（模型的思考过程）")
        outer.addWidget(self.think_box)
        self.think_toggle = QPushButton("▸ 思考过程")
        self.think_toggle.setObjectName("IconButton")
        self.think_toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self.think_toggle.clicked.connect(self._toggle_think)
        self.think_toggle.setVisible(False)
        outer.addWidget(self.think_toggle, 0, Qt.AlignmentFlag.AlignLeft)

        # 正文
        self.body = QLabel()
        self.body.setObjectName("MsgBody")
        self.body.setWordWrap(True)
        self.body.setTextFormat(Qt.TextFormat.PlainText)
        self.body.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.body.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        outer.addWidget(self.body)

    # -------------------------------------------------- 内容更新
    def set_meta(self, meta: str):
        self.meta_label.setText(meta)

    def append_think(self, piece: str):
        if not piece:
            return
        self._think += piece
        if not self.think_box.isVisible():
            self.think_box.setVisible(True)
            self.think_toggle.setVisible(True)
            self._set_think_expanded(True)
        self.think_box.moveCursor(QTextCursor.MoveOperation.End)
        self.think_box.insertPlainText(piece)

    def append_answer(self, piece: str):
        if not piece:
            return
        self._answer += piece
        if self.body.textFormat() != Qt.TextFormat.PlainText:
            self.body.setTextFormat(Qt.TextFormat.PlainText)
        self.body.setText(self._answer)

    def set_answer(self, text: str):
        self._answer = text or ""
        self.finalize()

    def finalize(self):
        """输出结束：切到富文本渲染，并显示复制按钮"""
        self._finished = True
        if self._think.strip() and self.think_box.isVisible():
            self._set_think_expanded(False)
        if self.role in ("user", "system", "error") or not self._answer.strip():
            self.body.setText(self._answer)
        else:
            self.body.setTextFormat(Qt.TextFormat.RichText)
            self.body.setText(mini_markdown(self._answer, self.palette_ref))
        self.copy_btn.setVisible(True)

    def text(self) -> str:
        return self._answer

    # -------------------------------------------------- 主题切换
    def retint(self, palette: Palette):
        """换主题：重画行内颜色与已经渲染过的富文本"""
        self.palette_ref = palette
        if self.role == "error":
            self.title_label.setStyleSheet(f"color:{palette.err};")
        if self._finished and self._answer.strip() and self.role == "assistant":
            self.body.setTextFormat(Qt.TextFormat.RichText)
            self.body.setText(mini_markdown(self._answer, palette))

    # -------------------------------------------------- 内部
    def _copy(self):
        QGuiApplication.clipboard().setText(self._answer)
        self.copy_btn.setText("已复制")
        from PyQt6.QtCore import QTimer
        QTimer.singleShot(1500, lambda: self.copy_btn.setText("复制"))

    def _toggle_think(self):
        self._set_think_expanded(not self.think_box.isVisible())

    def _set_think_expanded(self, expanded: bool):
        self.think_box.setVisible(expanded)
        self.think_toggle.setText("▾ 思考过程" if expanded else "▸ 思考过程")


# ---------------------------------------------------------------- 对话区

class ChatView(QScrollArea):
    """可滚动的消息列表；自动贴底（用户手动上滑时不打扰）"""

    def __init__(self, palette: Palette, parent: QWidget | None = None):
        super().__init__(parent)
        self.palette_ref = palette
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self._host = QWidget()
        self._layout = QVBoxLayout(self._host)
        self._layout.setContentsMargins(18, 14, 18, 14)
        self._layout.setSpacing(12)
        self._layout.addStretch(1)
        self.setWidget(self._host)

        self._bubbles: list[MessageBubble] = []
        self._auto_scroll = True
        self.verticalScrollBar().valueChanged.connect(self._on_scroll)

    def _on_scroll(self, value: int):
        bar = self.verticalScrollBar()
        self._auto_scroll = value >= bar.maximum() - 40

    def add_bubble(self, role: str, meta: str = "") -> MessageBubble:
        bubble = MessageBubble(role, self.palette_ref, meta)
        self._layout.insertWidget(self._layout.count() - 1, bubble)
        self._bubbles.append(bubble)
        self.scroll_to_bottom(force=True)
        return bubble

    def clear(self):
        for b in self._bubbles:
            self._layout.removeWidget(b)
            b.deleteLater()
        self._bubbles.clear()

    def bubble_count(self) -> int:
        return len(self._bubbles)

    def scroll_to_bottom(self, force: bool = False):
        if force or self._auto_scroll:
            bar = self.verticalScrollBar()
            bar.setValue(bar.maximum())


# ---------------------------------------------------------------- 侧边栏

class SessionList(QListWidget):
    """会话历史列表（右键可重命名 / 顶置 / 删除）"""

    rename_requested = pyqtSignal(str)
    delete_requested = pyqtSignal(str)
    pin_requested = pyqtSignal(str, bool)  # (sid, 是否顶置)

    #: 顶置状态存在这个角色里，菜单据此显示「顶置 / 取消顶置」
    PIN_ROLE = Qt.ItemDataRole.UserRole + 1

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("SessionList")
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._menu)

    def _menu(self, pos):
        item = self.itemAt(pos)
        if item is None:
            return
        from PyQt6.QtWidgets import QMenu

        # 先取出 sid / pinned 再建 lambda：菜单回调触发时 item 可能已被删除，
        # 直接捕获 item 引用会在延迟调用里踩到已释放的 C++ 对象
        sid = item.data(Qt.ItemDataRole.UserRole)
        pinned = bool(item.data(self.PIN_ROLE))

        menu = QMenu(self)
        menu.addAction("重命名", lambda: self.rename_requested.emit(sid))
        menu.addAction("📌 取消顶置" if pinned else "📌 顶置",
                       lambda: self.pin_requested.emit(sid, not pinned))
        menu.addAction("删除", lambda: self.delete_requested.emit(sid))
        menu.exec(self.mapToGlobal(pos))


# ---------------------------------------------------------------- 附件栏

class AttachmentBar(QWidget):
    """已附加图片的展示与移除（拓扑截图）"""

    remove_requested = pyqtSignal(str)

    def __init__(self, palette: Palette, parent: QWidget | None = None):
        super().__init__(parent)
        self.palette_ref = palette
        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(6)
        self._layout.addStretch(1)
        self.setVisible(False)

    def update_items(self, paths: list[str]):
        while self._layout.count() > 1:
            item = self._layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        for p in paths:
            name = p.replace("\\", "/").rsplit("/", 1)[-1]
            chip = QPushButton(f"🖼 {name}  ✕")
            chip.setObjectName("Chip")
            chip.setToolTip(p)
            chip.setCursor(Qt.CursorShape.PointingHandCursor)
            chip.clicked.connect(lambda _=False, path=p: self.remove_requested.emit(path))
            self._layout.insertWidget(self._layout.count() - 1, chip)
        self.setVisible(bool(paths))

    def retint(self, palette: Palette):
        self.palette_ref = palette


# ---------------------------------------------------------------- 状态行

class StatusRow(QWidget):
    """侧边栏底部的一行状态：● 名称 ········· 值"""

    def __init__(self, name: str, palette: Palette, parent: QWidget | None = None):
        super().__init__(parent)
        self.palette_ref = palette
        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 1, 6, 1)
        layout.setSpacing(4)
        self.dot = QLabel()
        self.dot.setObjectName("StatusDot")
        self.name = QLabel(name)
        self.name.setStyleSheet(f"color:{palette.text_dim};font-size:12px;")
        self.value = QLabel("—")
        self.value.setStyleSheet(f"color:{palette.text_faint};font-size:11px;")
        layout.addWidget(self.dot)
        layout.addWidget(self.name)
        layout.addStretch(1)
        layout.addWidget(self.value)

    def set_state(self, state: bool | None, value: str = ""):
        self.dot.setText("●")
        color = self.palette_ref.ok if state is True else (
            self.palette_ref.err if state is False else self.palette_ref.warn)
        self.dot.setStyleSheet(f"color:{color};font-size:13px;")
        self.value.setText(value)
