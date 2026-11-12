"""主窗口：侧边栏（历史 / 状态）+ 对话区 + 运行日志 + 命令控制台。

界面结构（参考 CodeX / KUN 的桌面 Agent 布局）：
    ┌────────────┬───────────────────────────────────────────────┐
    │ 会话历史    │ 顶栏：提供方 / 模式 / 思考 / 工具 / 审计 / 设置  │
    │ ＋ 新建     ├───────────────────────────────────────────────┤
    │  · 会话1    │ 对话 │ 运行日志 │ 命令     ← 页签               │
    │  · 会话2    │                                               │
    │ ─────────  │  （对话：气泡流 + 图片附件 + 输入框）           │
    │ 服务状态    │                                               │
    │ 启动/停止   │                                               │
    └────────────┴───────────────────────────────────────────────┘
                                    状态栏：状态 ｜ token 统计

线程约定：界面只与 AgentWorker 通过信号交互；模型/MCP 的一切耗时操作都在工作线程里。
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from PyQt6.QtCore import QBuffer, QIODevice, QObject, QPointF, QSettings, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import (
    QColor,
    QDragEnterEvent,
    QDropEvent,
    QFont,
    QImage,
    QKeyEvent,
    QPixmap,
    QTextCharFormat,
    QTextCursor,
)
from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QStackedWidget,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from core.llama_start import find_mmproj, find_model
from core.paste_store import save_bytes
from core.paths import BASE_DIR
from core.session_skills import use_session as use_skill_session
# StreamProxy 已迁到 core（与 Qt 无关，放这里会让测试被迫依赖 PyQt6，CI 不装）
from core.stream_proxy import StreamProxy
from core.vision import IMAGE_EXTS
from gui.dialogs import HELP_TEXT, AuditDialog, SettingsDialog, ToolsDialog, persist_api_key
from gui.store import SessionStore
from gui.theme import build_qss, get_palette
from gui.widgets import (
    AttachmentBar,
    ChatView,
    ImagePreviewPopup,
    MessageBubble,
    SessionList,
    StatusRow,
    WelcomePage,
    image_marker_text,
)
from gui.topology_view import TopologyCanvas
from gui.worker import AgentWorker

LOG_TAIL_LINES = 5000

#: 主区堆栈索引：0 = 欢迎页（未打开任何会话），1 = 对话页
PAGE_WELCOME = 0
PAGE_CHAT = 1


class _LogEmitter(QObject):
    """只用来承载日志信号（QObject 才能跨线程发信号）"""

    text = pyqtSignal(str)


# ---------------------------------------------------------------- 输入控件

#: 图片标记在输入框里的样式：主色文字 + 淡底纹 + 下划线（悬停出预览，
#: 判定命中靠 gui/main_window.py:InputEdit.marker_path_at 的 hitTest，不靠字符属性）


def _qimage_to_png(image: QImage) -> bytes:
    """QImage → PNG 字节（剪贴板里的图没有后缀，统一编码成 PNG 再落盘）"""
    buf = QBuffer()
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    ok = image.save(buf, "PNG")
    data = bytes(buf.data()) if ok else b""
    buf.close()
    return data


class InputEdit(QTextEdit):
    """输入框：回车发送、Shift+回车换行、可拖入/粘贴图片。

    粘贴/拖入图片的呈现约定（**不内联图像**）：
    - 光标处插入一行「文件名」文本（`🖼 paste-20261101-185512-a1b2c3d4.png`），
      路径同时交给上方附件栏；
    - 鼠标悬停在这段文件名上时弹出缩略图预览，移开即消失；
    - 把这段文件名文本删掉，等于取消了这张图的附件（发 image_removed 信号）。

    这样做的理由：内联图片会把输入框高度和宽度都撑爆，而「文件名」既保持了
    输入框的可读性，也把「这一句在说哪张图」写进了真正发给模型的问题文本里。
    """

    submitted = pyqtSignal()
    images_pasted = pyqtSignal(list)   # 粘贴/拖入的图片路径（由窗口加进附件栏）
    image_removed = pyqtSignal(str)    # 用户删掉了文本里的标记 → 取消该附件

    def __init__(self, palette=None, parent=None):
        super().__init__(parent)
        self.palette_ref = palette or get_palette("dark")
        self._quiet = 0              # >0：程序化改文本，不回发 image_removed
        self._markers: list[str] = []  # 文本里出现过的图片路径
        self._hover_path = ""
        self._preview = ImagePreviewPopup(self.palette_ref, self)
        # 不开 mouseTracking 的话只有按住鼠标才收到 move 事件，悬停预览就永远不触发
        self.viewport().setMouseTracking(True)
        self.textChanged.connect(self._on_text_changed)

    # -------------------------------------------------- 键盘
    def keyPressEvent(self, event: QKeyEvent):
        if event.key() == Qt.Key.Key_Escape and self._hover_path:
            self._hover_path = ""
            self._preview.hide_preview()
            return
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                super().keyPressEvent(event)
                return
            self.submitted.emit()
            return
        super().keyPressEvent(event)

    # -------------------------------------------------- 粘贴 / 拖入
    def canInsertFromMimeData(self, source) -> bool:
        if self._image_paths(source):
            return True
        return super().canInsertFromMimeData(source)

    def insertFromMimeData(self, source):
        paths = self._image_paths(source)
        if paths:
            cursor = self.textCursor()
            for p in paths:
                cursor = self.insert_image_marker(p, cursor)
            self.images_pasted.emit(paths)
            return
        super().insertFromMimeData(source)

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls() or event.mimeData().hasImage():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent):
        paths = self._image_paths(event.mimeData())
        if paths:
            cursor = self.cursorForPosition(event.position().toPoint())
            for p in paths:
                cursor = self.insert_image_marker(p, cursor)
            self.images_pasted.emit(paths)
            event.acceptProposedAction()
            return
        super().dropEvent(event)

    def _image_paths(self, source) -> list[str]:
        """从 MIME 里取出图片：优先「复制的图片文件」，其次「剪贴板里的位图」"""
        if source.hasUrls():
            out = []
            for u in source.urls():
                if not u.isLocalFile():
                    continue
                p = u.toLocalFile()
                if Path(p).suffix.lower() in IMAGE_EXTS and Path(p).is_file():
                    out.append(p)
            if out:
                return out
        if source.hasImage():
            image = source.imageData()
            if isinstance(image, QPixmap):
                image = image.toImage()
            if isinstance(image, QImage) and not image.isNull():
                try:
                    path = save_bytes(_qimage_to_png(image), suffix=".png")
                except (OSError, ValueError) as e:
                    # 落盘失败不阻断输入：把原因说清楚，让用户改用「图片」按钮选文件
                    self.setToolTip(f"粘贴图片失败：{e}")
                    return []
                return [str(path)]
        return []

    # -------------------------------------------------- 文件名标记
    def insert_image_marker(self, path: str, cursor: QTextCursor | None = None) -> QTextCursor:
        cur = QTextCursor(cursor) if cursor is not None else self.textCursor()
        cur.insertText(image_marker_text(path), self._marker_format(path))
        # 尾随空格用**空格式**插入：带标记属性的空格会让光标停在行尾时也算"指着图"，
        # 于是整行空白都弹预览
        cur.insertText(" ", QTextCharFormat())
        # 把后续输入格式还原成默认：否则接着打的字会继承蓝色底纹 + 图片路径属性
        cur.setCharFormat(QTextCharFormat())
        self.setTextCursor(cur)
        if path not in self._markers:
            self._markers.append(path)
        return cur

    def _marker_format(self, path: str) -> QTextCharFormat:
        p = self.palette_ref
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(p.accent))
        fmt.setBackground(QColor(p.user_bubble))
        fmt.setFontUnderline(True)
        return fmt

    def marker_path_at(self, pos) -> str:
        """控件内坐标 → 该位置图片标记的路径（不在标记上就返回空串）。

        用 ``documentLayout().hitTest(ExactHit)`` 拿到"鼠标正下方那个字符"的下标：
        点在空白处直接返回 -1。换 ``cursorForPosition`` 不行——它总会贴到最近的
        字符边界，于是行尾空白、下一行空白都会被判成"指着这张图"。命中字符下标后
        再与已知标记文本的区间比对（区间来自 ``document().find``，文本一改就自动对得上）。
        """
        layout = self.document().documentLayout()
        idx = int(layout.hitTest(QPointF(pos), Qt.HitTestAccuracy.ExactHit))
        if idx < 0:
            return ""
        for path in self._markers:
            label = image_marker_text(path)
            cur = self.document().find(label)
            while not cur.isNull():
                if cur.selectionStart() <= idx < cur.selectionEnd():
                    return path
                cur = self.document().find(label, cur)
        return ""

    def decorate_images(self, paths: list[str]) -> None:
        """给文本里已存在的文件名补上标记格式（草稿还原用：纯文本会丢字符格式）"""
        if not paths:
            return
        self._quiet += 1
        try:
            for p in paths:
                cur = self.document().find(image_marker_text(p))
                if cur.isNull():
                    continue
                cur.mergeCharFormat(self._marker_format(p))
                if p not in self._markers:
                    self._markers.append(p)
        finally:
            self._quiet -= 1

    def remove_marker(self, path: str) -> None:
        """移除指定图片的标记文本（附件栏点 ✕ 时同步，避免「附件没了但文件名还在」）"""
        label = image_marker_text(path)
        self._quiet += 1
        try:
            while True:
                cur = self.document().find(label)
                if cur.isNull():
                    break
                cur.removeSelectedText()
                # 标记后面跟着的那个空格一起删掉，否则输入框里会留一串空行尾
                nxt = QTextCursor(self.document())
                nxt.setPosition(cur.position())
                nxt.movePosition(QTextCursor.MoveOperation.NextCharacter,
                                 QTextCursor.MoveMode.KeepAnchor)
                if nxt.selectedText() == " ":
                    nxt.removeSelectedText()
        finally:
            self._quiet -= 1
        self._markers = [p for p in self._markers if p != path]
        if self._hover_path == path:
            self._hover_path = ""
            self._preview.hide_preview()

    # -------------------------------------------------- 悬停预览
    def mouseMoveEvent(self, event):
        super().mouseMoveEvent(event)
        path = self.marker_path_at(event.position().toPoint())
        if not path:
            if self._hover_path:
                self._hover_path = ""
                self._preview.hide_preview()
            return
        self._hover_path = path
        self._preview.show_for(path, event.globalPosition().toPoint())

    def leaveEvent(self, event):
        self._hover_path = ""
        self._preview.hide_preview()
        super().leaveEvent(event)

    def focusOutEvent(self, event):
        self._hover_path = ""
        self._preview.hide_preview()
        super().focusOutEvent(event)

    def wheelEvent(self, event):
        self._preview.hide_preview()
        super().wheelEvent(event)

    # -------------------------------------------------- 文本变更同步
    def _on_text_changed(self):
        if self._hover_path:
            self._hover_path = ""
            self._preview.hide_preview()
        if self._quiet:
            return
        text = self.toPlainText()
        removed = [p for p in self._markers if image_marker_text(p) not in text]
        if not removed:
            return
        self._markers = [p for p in self._markers if p not in removed]
        for p in removed:
            self.image_removed.emit(p)

    # -------------------------------------------------- 程序化清理（静默）
    def clear(self):
        self._quiet += 1
        try:
            super().clear()
        finally:
            self._quiet -= 1
        self._markers = []

    def setPlainText(self, text: str):
        self._quiet += 1
        try:
            super().setPlainText(text)
        finally:
            self._quiet -= 1
        self._markers = []

    def retint(self, palette):
        self.palette_ref = palette
        self._preview.retint(palette)
        if self._markers:  # 换主题后标记颜色要跟着变（字符格式是写死在文档里的）
            self.decorate_images(list(self._markers))


class CommandEdit(QLineEdit):
    """命令输入框（支持 ↑/↓ 调历史）"""

    submitted = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._history: list[str] = []
        self._cursor = 0
        self.returnPressed.connect(self.submit_current)

    def submit_current(self):
        text = self.text().strip()
        if not text:
            return
        if not self._history or self._history[-1] != text:
            self._history.append(text)
        self._cursor = len(self._history)
        self.clear()
        self.submitted.emit(text)

    def keyPressEvent(self, event: QKeyEvent):
        if event.key() == Qt.Key.Key_Up and self._history:
            self._cursor = max(0, self._cursor - 1)
            self.setText(self._history[self._cursor])
            return
        if event.key() == Qt.Key.Key_Down and self._history:
            self._cursor = min(len(self._history), self._cursor + 1)
            self.setText("" if self._cursor >= len(self._history) else self._history[self._cursor])
            return
        super().keyPressEvent(event)


# ---------------------------------------------------------------- 标准流转发

# StreamProxy 的实现已迁到 core/stream_proxy.py（本模块顶部 import）。
# 迁移原因见那边的模块文档：类本身只依赖 io，留在这里会让任何想测它的代码
# 被迫 import PyQt6，而 CI 不安装 PyQt6 → pytest collection 直接中断。


# ---------------------------------------------------------------- 主窗口

class MainWindow(QMainWindow):
    def __init__(self, settings: dict, parent=None):
        super().__init__(parent)
        self.settings = dict(settings)
        self.palette_ref = get_palette(self.settings.get("theme", "dark"))
        self.qsettings = QSettings("NetworkClaw", "Desktop")

        self.store = SessionStore()
        self.store.load()
        self.current_session = None
        self.images: list[str] = []
        self._pending_think: list[str] = []
        self._pending_answer: list[str] = []
        self._active_bubble: MessageBubble | None = None
        self._last_stats: dict = {}
        self._last_question = ""
        # 草稿缓存：未建会话的窗口里打了字/附了图又切走时暂存，回到草稿时还原。
        # 只存内存（不落盘）——没发出去的话本来就没进任何会话，重启丢弃是预期行为。
        self._draft_cache = {"text": "", "images": []}
        self._busy = False
        self.tools_cache: list[dict] = []
        self.providers_cache: list[dict] = []

        self.setWindowTitle("NetworkClaw · 网络运维智能助手")
        self.setMinimumSize(1080, 700)

        self._build_ui()
        self._restore_geometry()
        self._wire_stdout()

        # 启动**不打开任何会话**：主区落在欢迎页，历史只在用户点击侧边栏时才加载。
        # 但设备技能作用域（session/.current）仍指向最近的会话：worker 的索引构建
        # 与 MCP 子进程一启动就要读它，指向 default 会另起一套空目录。
        if self.store.sessions:
            self._apply_skill_session(self.store.sessions[0].sid)
        self.current_session = None

        self.worker = AgentWorker(self._worker_options(), self)
        self._connect_worker()
        self.worker.start()

        # 流式片段合并刷新（避免每个 token 都重排一遍控件）
        self._flush_timer = QTimer(self)
        self._flush_timer.setInterval(33)
        self._flush_timer.timeout.connect(self._flush_stream)
        self._flush_timer.start()

        # 服务状态轮询
        self._service_timer = QTimer(self)
        self._service_timer.setInterval(10000)
        self._service_timer.timeout.connect(lambda: self.worker.submit("services"))
        self._service_timer.start()

        # 设备在线状态轮询（设备管理页签）
        self._device_probed = False
        self._device_gen = 0          # 设备探测代号：只接受最新一代结果
        self._device_busy = False     # 探测中：忽略重复刷新请求
        # 拓扑 / 等保
        self._topo_model = None       # 最近一次拓扑数据（点击命中要查节点名）
        self._topo_loaded = False
        self._last_probe_devices = [] # 最近一次探测结果（安全检查据此选在线设备）
        self._last_compliance = None  # 最近一次等保报告（详情面板数据源）
        self._compliance_busy = False
        self._device_timer = QTimer(self)
        self._device_timer.setInterval(30000)
        self._device_timer.timeout.connect(self._refresh_devices)
        self._device_timer.start()

        self._show_welcome()
        self._append_log("NetworkClaw 已启动，正在初始化…\n")

    # ============================================================ 界面搭建
    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.addWidget(self._build_sidebar())
        self.splitter.addWidget(self._build_main())
        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setSizes([260, 900])
        self.splitter.setCollapsible(0, True)
        self.splitter.setCollapsible(1, False)
        root.addWidget(self.splitter)

        self.status = self.statusBar()
        self.status_left = QLabel("正在初始化…")
        self.status_right = QLabel("token：0")
        self.status.addWidget(self.status_left, 1)
        self.status.addPermanentWidget(self.status_right)

    def _build_sidebar(self) -> QWidget:
        bar = QFrame()
        bar.setObjectName("Sidebar")
        bar.setMinimumWidth(220)
        bar.setMaximumWidth(400)
        layout = QVBoxLayout(bar)
        layout.setContentsMargins(10, 12, 10, 10)
        layout.setSpacing(8)

        head = QVBoxLayout()
        head.setSpacing(0)
        title = QLabel("NetworkClaw")
        title.setObjectName("AppTitle")
        sub = QLabel("RAG · MCP · 设备运维 · 多模型")
        sub.setObjectName("AppSubtitle")
        head.addWidget(title)
        head.addWidget(sub)
        layout.addLayout(head)

        new_btn = QPushButton("＋  新建会话")
        new_btn.setObjectName("Primary")
        new_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        new_btn.clicked.connect(lambda: self._new_session())
        layout.addWidget(new_btn)

        label = QLabel("历史记录")
        label.setObjectName("SidebarTitle")
        layout.addWidget(label)

        self.session_list = SessionList()
        self.session_list.itemClicked.connect(self._on_session_clicked)
        self.session_list.rename_requested.connect(self._rename_session)
        self.session_list.delete_requested.connect(self._delete_session)
        self.session_list.pin_requested.connect(self._pin_session)
        layout.addWidget(self.session_list, 1)

        divider = QFrame()
        divider.setObjectName("Divider")
        layout.addWidget(divider)

        label2 = QLabel("服务状态")
        label2.setObjectName("SidebarTitle")
        layout.addWidget(label2)

        self.row_llama = StatusRow("本地模型", self.palette_ref)
        self.row_ollama = StatusRow("Ollama 向量", self.palette_ref)
        self.row_mcp = StatusRow("MCP 工具", self.palette_ref)
        self.row_vision = StatusRow("图像识别", self.palette_ref)
        for row in (self.row_llama, self.row_ollama, self.row_mcp, self.row_vision):
            layout.addWidget(row)

        row = QHBoxLayout()
        row.setSpacing(6)
        start = QPushButton("启动本地模型")
        start.setObjectName("Ghost")
        start.clicked.connect(self._start_local)
        stop = QPushButton("停止")
        stop.setObjectName("Ghost")
        stop.clicked.connect(lambda: self.worker.submit("stop_local"))
        row.addWidget(start, 1)
        row.addWidget(stop)
        layout.addLayout(row)

        return bar

    def _build_main(self) -> QWidget:
        host = QWidget()
        layout = QVBoxLayout(host)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        layout.addWidget(self._build_topbar())

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_chat_tab(), "对话")
        self.tabs.addTab(self._build_device_tab(), "设备")
        self.tabs.addTab(self._build_topology_tab(), "拓扑")
        self.tabs.addTab(self._build_log_tab(), "运行日志")
        self.tabs.addTab(self._build_command_tab(), "命令")
        self.tabs.currentChanged.connect(self._on_tab_changed)
        layout.addWidget(self.tabs, 1)
        return host

    def _build_topbar(self) -> QWidget:
        bar = QFrame()
        bar.setObjectName("TopBar")
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(8)

        layout.addWidget(QLabel("模型"))
        self.provider_box = QComboBox()
        self.provider_box.setMinimumWidth(210)
        self.provider_box.currentIndexChanged.connect(self._on_provider_changed)
        layout.addWidget(self.provider_box)

        layout.addWidget(QLabel("模式"))
        self.mode_box = QComboBox()
        # 统一对话入口：不再让用户手动挑 RAG / Agent（检索已并入 agent 的内置工具），
        # 只保留「普通对话 / 拓扑规划 / 多模型并行」三个入口
        for label, value in (("对话", "agent"),
                             ("plan 拓扑规划", "plan"),
                             ("parallel 多模型并行", "parallel")):
            self.mode_box.addItem(label, value)
        idx = self.mode_box.findData(self.settings.get("mode", "agent"))
        if idx >= 0:
            self.mode_box.setCurrentIndex(idx)
        self.mode_box.currentIndexChanged.connect(self._on_mode_changed)
        layout.addWidget(self.mode_box)

        self.think_btn = QPushButton("思考 ✓" if self.settings.get("show_thinking", True) else "思考 ✕")
        self.think_btn.setObjectName("Chip")
        self.think_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.think_btn.clicked.connect(self._toggle_thinking)
        layout.addWidget(self.think_btn)

        layout.addStretch(1)

        # 深 / 浅色一键切换（按钮显示的是「切换目标」主题）
        self.theme_btn = QPushButton()
        self.theme_btn.setObjectName("Ghost")
        self.theme_btn.setToolTip("切换深色 / 浅色主题")
        self.theme_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.theme_btn.clicked.connect(self._toggle_theme)
        self._sync_theme_btn()
        layout.addWidget(self.theme_btn)

        for text, tip, slot in (
            ("工具", "查看已接入的 MCP 工具", self._show_tools),
            ("审计", "查看设备命令审计记录", self._show_audit),
            ("导出", "把当前会话导出为 Markdown", self._export_session),
            ("帮助", "使用说明", self._show_help),
            ("设置", "模型、密钥、界面设置", self._show_settings),
        ):
            btn = QPushButton(text)
            btn.setObjectName("Ghost")
            btn.setToolTip(tip)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(slot)
            layout.addWidget(btn)
        return bar

    def _build_chat_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 主区两态：欢迎页（未打开会话）/ 对话页。输入区常驻在下方，
        # 这样在欢迎页直接提问也能用——发送时会自动建一个新会话。
        self.chat_stack = QStackedWidget()
        self.welcome = WelcomePage(self.palette_ref)
        self.welcome.new_session_requested.connect(self._new_session)
        self.welcome.session_requested.connect(self._switch_session)
        self.chat = ChatView(self.palette_ref)
        self.chat_stack.addWidget(self.welcome)   # PAGE_WELCOME
        self.chat_stack.addWidget(self.chat)      # PAGE_CHAT
        layout.addWidget(self.chat_stack, 1)

        bottom = QWidget()
        bl = QVBoxLayout(bottom)
        bl.setContentsMargins(14, 8, 14, 12)
        bl.setSpacing(6)

        self.attach_bar = AttachmentBar(self.palette_ref)
        self.attach_bar.remove_requested.connect(self._remove_image)
        bl.addWidget(self.attach_bar)

        row = QHBoxLayout()
        row.setSpacing(6)
        self.input = InputEdit(self.palette_ref)
        self.input.setObjectName("Input")
        self.input.setPlaceholderText(
            "输入问题，回车发送（Shift+Enter 换行）｜可拖入或粘贴截图，悬停文件名可预览")
        self.input.setFixedHeight(76)
        self.input.submitted.connect(self._send)
        self.input.images_pasted.connect(self._add_images)
        self.input.image_removed.connect(self._remove_image)
        row.addWidget(self.input, 1)

        col = QVBoxLayout()
        col.setSpacing(4)
        self.send_btn = QPushButton("发送")
        self.send_btn.setObjectName("Primary")
        self.send_btn.setMinimumHeight(34)
        self.send_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.send_btn.clicked.connect(self._send)
        img_btn = QPushButton("图片")
        img_btn.setObjectName("Ghost")
        img_btn.setToolTip("附加拓扑截图（可多选）")
        img_btn.clicked.connect(self._pick_images)
        col.addWidget(self.send_btn)
        col.addWidget(img_btn)
        row.addLayout(col)
        bl.addLayout(row)
        layout.addWidget(bottom)
        return page

    def _build_log_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(6)

        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(LOG_TAIL_LINES)
        self.log_view.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        layout.addWidget(self.log_view, 1)

        row = QHBoxLayout()
        clear = QPushButton("清空")
        clear.setObjectName("Ghost")
        clear.clicked.connect(self.log_view.clear)
        save = QPushButton("另存为…")
        save.setObjectName("Ghost")
        save.clicked.connect(self._save_log)
        row.addWidget(clear)
        row.addWidget(save)
        row.addStretch(1)
        hint = QLabel("这里显示检索过程、工具调用、连接状态等全部运行细节")
        hint.setObjectName("Hint")
        row.addWidget(hint)
        layout.addLayout(row)
        return page

    def _build_command_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(6)

        self.cmd_out = QPlainTextEdit()
        self.cmd_out.setReadOnly(True)
        self.cmd_out.setMaximumBlockCount(2000)
        self.cmd_out.setPlainText(HELP_TEXT)
        layout.addWidget(self.cmd_out, 1)

        row = QHBoxLayout()
        self.cmd_edit = CommandEdit()
        self.cmd_edit.setPlaceholderText(
            "输入命令，如 /tools 、/call query_command_template {\"intent\":\"配置OSPF\"}")
        self.cmd_edit.submitted.connect(self._run_command)
        run = QPushButton("执行")
        run.setObjectName("Primary")
        run.clicked.connect(self.cmd_edit.submit_current)
        row.addWidget(self.cmd_edit, 1)
        row.addWidget(run)
        layout.addLayout(row)
        return page

    # ============================================================ 设备管理
    DEVICE_LIGHT_ON = "#1fa34a"     # 绿灯：在线（SecureCRT 风格）
    DEVICE_LIGHT_OFF = "#8b9096"    # 灰灯：离线

    def _build_device_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(6)

        row = QHBoxLayout()
        self.device_refresh_btn = QPushButton("刷新状态")
        self.device_refresh_btn.setObjectName("Ghost")
        self.device_refresh_btn.clicked.connect(self._refresh_devices)
        row.addWidget(self.device_refresh_btn)

        self.device_auto_box = QComboBox()
        self.device_auto_box.addItem("自动刷新：30 秒", 30)
        self.device_auto_box.addItem("自动刷新：10 秒", 10)
        self.device_auto_box.addItem("自动刷新：60 秒", 60)
        self.device_auto_box.addItem("关闭自动刷新", 0)
        self.device_auto_box.currentIndexChanged.connect(self._on_device_interval)
        row.addWidget(self.device_auto_box)

        row.addStretch(1)
        self.device_summary = QLabel("设备状态待探测…")
        self.device_summary.setObjectName("AppSubtitle")
        row.addWidget(self.device_summary)
        layout.addLayout(row)

        self.device_table = QTableWidget(0, 7)
        self.device_table.setHorizontalHeaderLabels(
            ["状态", "设备", "型号", "地址", "通道", "最后访问", "说明"])
        self.device_table.verticalHeader().setVisible(False)
        self.device_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.device_table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows)
        self.device_table.setAlternatingRowColors(True)
        self.device_table.setColumnWidth(0, 52)
        self.device_table.setColumnWidth(1, 110)
        self.device_table.setColumnWidth(2, 130)
        self.device_table.setColumnWidth(3, 170)
        self.device_table.setColumnWidth(4, 70)
        self.device_table.setColumnWidth(5, 150)
        self.device_table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.device_table, 1)

        hint = QLabel("本页是**会话级**设备视图：只显示当前会话里出现过的设备"
                      "（session/<会话>/skill/ 下建过手册或有命令历史的，"
                      "助手连过并执行过命令就会出现在这里）。"
                      "绿点＝TCP/串口可达，不代表已登录可操作；"
                      "「最后访问」只在命令真正执行成功时更新。探测为只读，不下发任何命令。")
        hint.setObjectName("AppSubtitle")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        return page

    def _current_sid(self) -> str:
        return self.current_session.sid if self.current_session is not None else ""

    def _invalidate_session_views(self):
        """会话切换/新建/删除后：设备与拓扑页签的内容不再属于当前会话。

        作废「首次进入页签才加载」的缓存标记；如果此刻正停在这两个页签上，
        立即按新会话重载，否则页签上残留着上一个会话的设备表和拓扑图。
        """
        self._device_probed = False
        self._topo_loaded = False
        self._last_probe_devices = []
        self._topo_model = None
        text = self.tabs.tabText(self.tabs.currentIndex())
        if text == "设备":
            self._refresh_devices()
        elif text == "拓扑":
            self._refresh_topology()

    def _refresh_devices(self):
        # 未打开会话：设备页签是会话视图，没有会话就没有设备可显示。
        # 自动刷新定时器每 30 秒会进来一次，这里必须廉价返回，不能空转探测。
        if not self._current_sid():
            self._device_busy = False
            self.device_refresh_btn.setEnabled(True)
            self.device_table.setRowCount(0)
            self._last_probe_devices = []
            self.device_summary.setText(
                "未打开会话：本页只显示当前会话的设备，先新建或打开一个会话")
            return
        # 探测中不再叠加请求：自动刷新 + 手动点击很容易堆出几条并发探测，
        # 后到的旧结果会覆盖新结果（表格闪回旧状态）。这里直接忽略重复请求，
        # 且任何返回都带 generation，界面只认最新一代。
        if self._device_busy:
            return
        self._device_busy = True
        self._device_gen += 1
        self.device_summary.setText("探测中…")
        self.device_refresh_btn.setEnabled(False)
        self.worker.submit("device_probe", gen=self._device_gen,
                           session=self._current_sid())

    def _on_device_interval(self):
        sec = self.device_auto_box.currentData() or 0
        if sec > 0:
            self._device_timer.setInterval(sec * 1000)
            self._device_timer.start()
            self._refresh_devices()
        else:
            self._device_timer.stop()

    def _on_tab_changed(self, idx: int):
        # 第一次切到设备页签时立即探测一次；第一次切到拓扑页签时加载拓扑
        text = self.tabs.tabText(idx)
        if text == "设备" and not self._device_probed:
            self._device_probed = True
            self._refresh_devices()
        elif text == "拓扑" and not self._topo_loaded:
            self._topo_loaded = True
            self._refresh_topology()

    def _on_devices(self, payload, gen: int = 0):
        """填充设备表（绿点=在线，灰点=离线）。

        payload 为 {"ok","devices","error"}；gen 不是最新一代就直接丢弃——
        否则先发的慢探测会在后发的结果之后到达，把新状态盖回旧的。
        """
        if gen and gen != self._device_gen:
            return
        self._device_busy = False
        self.device_refresh_btn.setEnabled(True)

        if not isinstance(payload, dict):
            payload = {"ok": True, "devices": list(payload or []), "error": ""}
        if not payload.get("ok"):
            # 失败要清空表格：保留旧行会让人以为「刚刚探测过且都正常」
            self.device_table.setRowCount(0)
            self.device_summary.setText(f"探测失败：{payload.get('error') or '未知错误'}")
            return

        devices = payload.get("devices") or []
        self._last_probe_devices = devices   # 一键安全检查据此挑在线设备
        if not devices:
            # 会话视图下的空态：不是故障，是本会话还没碰过设备
            self.device_table.setRowCount(0)
            self.device_summary.setText(
                "本会话还没有设备记录：助手在本会话连接/建档过的设备会出现在这里"
                + ("" if self._current_sid() else "（当前未打开会话）"))
            return
        self.device_table.setRowCount(len(devices))
        online = 0
        for i, d in enumerate(devices):
            is_on = bool(d.get("online"))
            online += is_on

            light = QTableWidgetItem()
            light.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.device_table.setItem(i, 0, light)

            def _cell(text: str) -> QTableWidgetItem:
                it = QTableWidgetItem(str(text or "—"))
                it.setToolTip(str(text or ""))
                return it

            self.device_table.setItem(i, 1, _cell(d.get("name")))
            model = d.get("model") or (f"{d.get('vendor')}·{d.get('type')}" if d.get("type") else "")
            self.device_table.setItem(i, 2, _cell(model))
            addr = (f"{d['host']}:{d['port']}" if d.get("host")
                    else d.get("serial_port") or d.get("key"))
            self.device_table.setItem(i, 3, _cell(addr))
            self.device_table.setItem(i, 4, _cell(d.get("transport")))
            self.device_table.setItem(i, 5, _cell(d.get("last_seen")))
            # 说明列写清「在线」的语义来源：TCP/串口可达 ≠ 已登录可操作
            detail = str(d.get("detail") or "")
            src = "清单" if d.get("source") == "inventory" else "访问登记"
            self.device_table.setItem(i, 6, _cell(f"{detail}｜来源：{src}"))

            # 灯放最后涂色，行背景也跟着淡淡提示（避免整行扎眼）
            self._paint_device_row(i, is_on)
        self.device_summary.setText(
            f"共 {len(devices)} 台 · 在线 {online} · 离线 {len(devices) - online}"
            f"（在线 = TCP/串口可达，不等于已登录）")

    def _paint_device_row(self, row: int, is_on: bool):
        color = self.DEVICE_LIGHT_ON if is_on else self.DEVICE_LIGHT_OFF
        color = QColor(self.DEVICE_LIGHT_ON if is_on else self.DEVICE_LIGHT_OFF)
        light = self.device_table.item(row, 0)
        if light is not None:
            light.setText("●")
            light.setForeground(color)
            light.setToolTip("在线" if is_on else "离线")

    # ============================================================ 拓扑图
    CLICK_TEMPLATE = "请读取 {name} 的当前配置，并检查是否存在环路风险。"

    def _build_topology_tab(self) -> QWidget:
        page = QWidget()
        layout = QHBoxLayout(page)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        left = QVBoxLayout()
        row = QHBoxLayout()
        self.topo_refresh_btn = QPushButton("刷新拓扑")
        self.topo_refresh_btn.setObjectName("Ghost")
        self.topo_refresh_btn.setToolTip("重新加载最近一次拓扑发现的结果"
                                         "（discover_topology 工具落盘的快照）")
        self.topo_refresh_btn.clicked.connect(self._refresh_topology)
        row.addWidget(self.topo_refresh_btn)

        self.topo_scan_btn = QPushButton("🛡 一键安全检查")
        self.topo_scan_btn.setObjectName("Primary")
        self.topo_scan_btn.setToolTip("逐台 Telnet 拉取运行配置（只读 display），"
                                      "跑 dengbao_rules 等保规则，高危设备图标标红")
        self.topo_scan_btn.clicked.connect(self._run_compliance)
        row.addWidget(self.topo_scan_btn)

        row.addStretch(1)
        self.topo_status = QLabel("拓扑未加载：点「刷新拓扑」，或切到本页自动加载")
        self.topo_status.setObjectName("AppSubtitle")
        row.addWidget(self.topo_status)
        left.addLayout(row)

        self.topo_canvas = TopologyCanvas(self.palette_ref)
        self.topo_canvas.device_clicked.connect(self._on_topology_device_clicked)
        self.topo_canvas.finding_clicked.connect(self._on_topology_finding_clicked)
        # 画布按拓扑宽度自定最小尺寸，套滚动区防止大拓扑把右侧面板挤出去
        from PyQt6.QtWidgets import QScrollArea

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.topo_canvas)
        left.addWidget(scroll, 1)
        layout.addLayout(left, 1)

        # 右侧详情面板：点击红色警告气泡后显示修复建议
        right = QVBoxLayout()
        title = QLabel("检查详情")
        title.setObjectName("SidebarTitle")
        right.addWidget(title)
        self.topo_detail = QPlainTextEdit()
        self.topo_detail.setReadOnly(True)
        self.topo_detail.setPlaceholderText(
            "点击拓扑上带红色警告气泡的设备，这里显示\n"
            "具体违规项、等级判定依据与修复命令。")
        self.topo_detail.setMaximumWidth(360)
        right.addWidget(self.topo_detail, 1)
        tip = QLabel("点击设备图标：聊天框自动补全检查指令，\n"
                     "并在「设备」页签高亮该设备。悬停可看型号与检查摘要。")
        tip.setObjectName("Hint")
        tip.setWordWrap(True)
        right.addWidget(tip)
        layout.addLayout(right)
        return page

    def _refresh_topology(self):
        if not self._current_sid():
            # 拓扑页签是会话视图：没有会话时清掉画布，别残留上一个会话的图
            self._topo_model = None
            self.topo_canvas.set_model({"nodes": [], "edges": []})
            self.topo_status.setText(
                "未打开会话：拓扑只显示当前会话的拓扑，先新建或打开一个会话")
            return
        self.topo_status.setText("拓扑加载中…")
        self.worker.submit("topology_build", session=self._current_sid())

    def _on_topology_model(self, payload: dict):
        self._topo_model = payload
        nodes = payload.get("nodes") or []
        if not nodes:
            self.topo_status.setText(f"拓扑不可用：{payload.get('error') or '无设备'}")
            self._append_log(f"[拓扑] 加载失败：{payload.get('error')}\n")
            return
        self.topo_canvas.set_model(payload)
        edges = payload.get("edges") or []
        gen = payload.get("generated") or "未知时间"
        extra = ""
        if payload.get("filtered"):
            extra = f" · 已按会话过滤掉 {payload['filtered']} 台非本会话设备"
        self.topo_status.setText(
            f"{len(nodes)} 台设备 · {len(edges)} 条链路 · 发现于 {gen}{extra}"
            + ("（快照缺失，仅列设备清单）" if not edges else ""))

    def _on_topology_device_clicked(self, key: str):
        """拓扑点击 → 聊天框补全检查指令 + 设备表高亮（新手的两个去处都给）。"""
        node = next((n for n in (self._topo_model or {}).get("nodes", [])
                     if n.get("key") == key), None)
        name = node.get("name", key) if node else key
        self.input.setPlainText(self.CLICK_TEMPLATE.format(name=name))
        self.input.setFocus()
        self._highlight_device_row(name)

    def _highlight_device_row(self, name: str):
        for i in range(self.device_table.rowCount()):
            it = self.device_table.item(i, 1)
            if it is not None and it.text() == name:
                self.device_table.selectRow(i)
                self.device_table.scrollToItem(it)
                return

    def _on_topology_finding_clicked(self, key: str):
        """点红色警告气泡 → 右侧面板展开该设备的违规项与修复建议。"""
        report = self._last_compliance or {}
        row = next((r for r in report.get("results", []) if r.get("key") == key), None)
        if row is None:
            self.topo_detail.setPlainText("该设备暂无检查结果（可能未扫描或已下线）。")
            return
        lines = [f"{row['name']}（{row['model']}｜{row['kind']}）"]
        if row.get("error"):
            lines.append(f"检查未完成：{row['error']}")
        else:
            lines.append(f"高危 {row.get('high', 0)} · 中危 {row.get('medium', 0)} · "
                         f"通过 {row.get('passed', 0)} 项 · 需人工确认 "
                         f"{row.get('manual', 0)} 项")
            lines.append("")
            for f in row.get("failures", []):
                lines.append(f"［{f['severity']}］{f['id']}｜{f['control_point']}")
                lines.append(f"  要求：{f['requirement']}")
                if f.get("expect"):
                    lines.append(f"  判定：{f['expect']}")
                if f.get("evidence_hint"):
                    lines.append(f"  取证：{f['evidence_hint']}")
                rem = f.get("remediation") or []
                if rem:
                    lines.append("  修复参考命令：")
                    lines.extend(f"    {c}" for c in rem)
                lines.append("")
        self.topo_detail.setPlainText("\n".join(lines))

    def _run_compliance(self):
        if self._compliance_busy:
            return
        online = [d for d in (self._last_probe_devices or [])
                  if d.get("online") and d.get("transport") == "telnet"]
        n = len(online) if online else len(
            [d for d in (self._last_probe_devices or [])
             if d.get("transport") == "telnet"])
        if n == 0:
            QMessageBox.information(self, "一键安全检查",
                                    "没有可检查的 Telnet 设备（先到「设备」页签刷新状态）。")
            return
        if QMessageBox.question(
                self, "一键安全检查",
                f"将逐台登录 {n} 台设备执行 display current-configuration"
                "（只读命令，不改任何配置），然后运行等保规则检查。继续？"
        ) != QMessageBox.StandardButton.Yes:
            return
        self._compliance_busy = True
        self.topo_scan_btn.setEnabled(False)
        self.topo_status.setText(f"安全检查中…（{n} 台设备并发拉取配置）")
        self.worker.submit("compliance_scan",
                           keys=[f"{d.get('host')}:{d.get('port')}" for d in online],
                           session=self._current_sid())

    def _on_compliance(self, report: dict):
        self._compliance_busy = False
        self.topo_scan_btn.setEnabled(True)
        self._last_compliance = report
        self.topo_canvas.set_findings(report)
        results = report.get("results") or []
        highs = sum(r.get("high", 0) for r in results)
        errs = report.get("errors") or []
        failed = [r for r in results if r.get("error")]
        self.topo_status.setText(
            f"检查完成（{report.get('generated', '')}）：{len(results)} 台 · "
            f"高危 {highs} · {len(failed)} 台未完成"
            + ("；点红色气泡看修复建议" if highs else ""))
        for e in errs:
            self._append_log(f"[等保检查] {e}\n")
        for r in failed:
            self._append_log(f"[等保检查] {r['name']}：{r['error']}\n")

    # ============================================================ 标准流
    def _wire_stdout(self):
        self._log_signal = _LogEmitter()
        self._log_signal.text.connect(self._append_log)
        if self.settings.get("capture_stdout", True):
            for name in ("stdout", "stderr"):
                original = getattr(sys, name, None)
                if original is not None and not isinstance(original, StreamProxy):
                    setattr(sys, name, StreamProxy(original, self._log_signal.text.emit))

    def _append_log(self, text: str):
        if not text:
            return
        self.log_view.moveCursor(self.log_view.textCursor().MoveOperation.End)
        self.log_view.insertPlainText(text)
        bar = self.log_view.verticalScrollBar()
        bar.setValue(bar.maximum())

    def _save_log(self):
        path, _ = QFileDialog.getSaveFileName(self, "保存运行日志",
                                             str(BASE_DIR / "logs" / "gui_run.log"),
                                             "日志文件 (*.log);;文本文件 (*.txt)")
        if path:
            Path(path).write_text(self.log_view.toPlainText(), encoding="utf-8")
            self._append_log(f"\n[日志已保存] {path}\n")

    # ============================================================ Worker
    def _worker_options(self) -> dict:
        return {
            "provider": self.settings.get("provider"),
            "deepseek_key": self.settings.get("api_key"),
            "mmproj": self.settings.get("mmproj") or None,
            "with_search": bool(self.settings.get("with_search")),
            "auto_vision": bool(self.settings.get("auto_vision", True)),
            "capture_keyword": self.settings.get("capture_keyword") or None,
        }

    def _connect_worker(self):
        w = self.worker
        w.sig_log.connect(self._append_log)
        w.sig_state.connect(self._on_state)
        w.sig_ready.connect(self._on_ready)
        w.sig_think.connect(self._on_think)
        w.sig_answer.connect(self._on_answer)
        w.sig_output_begin.connect(self._on_output_begin)
        w.sig_answer_done.connect(self._on_answer_done)
        w.sig_stats.connect(self._on_stats)
        w.sig_error.connect(self._on_error)
        w.sig_confirmation_required.connect(self._on_confirmation_required)
        w.sig_busy.connect(self._on_busy)
        w.sig_result.connect(self._on_command_result)
        w.sig_services.connect(self._on_services)
        w.sig_providers.connect(self._apply_providers)
        w.sig_topology.connect(self._on_topology)
        w.sig_devices.connect(self._on_devices)
        w.sig_topology_model.connect(self._on_topology_model)
        w.sig_compliance.connect(self._on_compliance)

    def _on_state(self, text: str):
        self.status_left.setText(text)

    def _on_ready(self, info: dict):
        self._device_probed = True
        self._refresh_devices()   # 就绪即探测一轮，设备页签不用等 30 秒
        self._apply_providers(info.get("providers") or [])
        idx = self.provider_box.findData(info.get("active"))
        if idx >= 0:
            self.provider_box.blockSignals(True)
            self.provider_box.setCurrentIndex(idx)
            self.provider_box.blockSignals(False)
        self._on_services(info.get("services") or {})
        tools = info.get("tools") or []
        self.tools_cache = tools
        self._append_log(f"\n就绪：{len(tools)} 个 MCP 工具，"
                         f"{len(info.get('providers') or [])} 个模型提供方\n")

    def _apply_providers(self, providers: list[dict]):
        current = self.provider_box.currentData()
        self.provider_box.blockSignals(True)
        self.provider_box.clear()
        for p in providers:
            mark = "✓" if p.get("configured") else "✗"
            self.provider_box.addItem(
                f"{mark} {p['label']}（{p['name']}）", p["name"])
        target = current or self.settings.get("provider")
        idx = self.provider_box.findData(target)
        self.provider_box.setCurrentIndex(idx if idx >= 0 else 0)
        self.provider_box.blockSignals(False)
        self.providers_cache = providers

    def _on_services(self, snap: dict):
        if not snap:
            return
        self.row_llama.set_state(snap.get("llama"),
                                 "运行中" if snap.get("llama") else "未启动")
        self.row_ollama.set_state(snap.get("ollama"), snap.get("ollama_detail", "")[:16])
        self.row_mcp.set_state(len(snap.get("mcp_servers") or []) > 0,
                               f"{snap.get('mcp_tools', 0)} 个工具")
        vision = snap.get("vision")
        self.row_vision.set_state(vision, "可用" if vision else "不可用")
        if snap.get("mmproj"):
            self.row_vision.setToolTip(f"mmproj：{snap['mmproj']}")

    def _on_busy(self, busy: bool):
        self._busy = busy
        self.send_btn.setEnabled(not busy)
        self.send_btn.setText("生成中…" if busy else "发送")

    # -------------------------------------------------- 流式渲染
    def _on_output_begin(self, sid: str, kind: str):
        if self.current_session is None or sid != self.current_session.sid:
            return
        if self._active_bubble is None:
            self._active_bubble = self.chat.add_bubble("assistant", "生成中…")

    def _on_think(self, sid: str, piece: str):
        if self.current_session is None or sid != self.current_session.sid:
            return
        self._pending_think.append(piece)

    def _on_answer(self, sid: str, piece: str):
        if self.current_session is None or sid != self.current_session.sid:
            return
        if self._active_bubble is None:
            self._active_bubble = self.chat.add_bubble("assistant", "生成中…")
        self._pending_answer.append(piece)

    def _flush_stream(self):
        if self._pending_think and self._active_bubble is not None:
            self._active_bubble.append_think("".join(self._pending_think))
            self._pending_think.clear()
        if self._pending_answer and self._active_bubble is not None:
            self._active_bubble.append_answer("".join(self._pending_answer))
            self._pending_answer.clear()
            self.chat.scroll_to_bottom()

    def _on_answer_done(self, answer: str, meta: dict):
        sid = meta.get("sid", "")
        session = self.store.get(sid) if sid else None
        if session is None:
            return
        is_current = self.current_session is not None and sid == self.current_session.sid
        if not is_current:
            session.add_record(meta.get("mode", "agent"), meta.get("question", ""),
                               answer, meta.get("provider", ""), meta.get("elapsed", 0.0))
            self.store.touch(sid)
            self._refresh_session_list()
            return
        self._flush_stream()
        if self._active_bubble is None:
            self._active_bubble = self.chat.add_bubble("assistant", "")
        self._active_bubble.set_meta(self._meta_text(meta))
        if answer and answer != self._active_bubble.text():
            self._active_bubble.set_answer(answer)
        else:
            self._active_bubble.finalize()
        self.chat.scroll_to_bottom(force=True)
        self._active_bubble = None

        if session is not None:
            session.add_record(
                meta.get("mode", "agent"), meta.get("question", self._last_question), answer,
                meta.get("provider", ""), meta.get("elapsed", 0.0))
            self.store.touch(session.sid)
            self._refresh_session_list()

    def _on_stats(self, stats: dict):
        self._last_stats = stats
        cumulative = stats.get("cumulative") or {}
        note = "服务端统计" if stats.get("server_side") else "按输出块近似"
        self.status_right.setText(
            f"token：{cumulative.get('output_tokens', 0)}（本次 {stats.get('output_tokens', 0)}，"
            f"思考 {stats.get('think', 0)} ＋ 回答 {stats.get('answer', 0)}，{note}）")

    def _on_error(self, text: str):
        self._flush_stream()
        bubble = self.chat.add_bubble("error", "")
        bubble.append_answer(text)
        bubble.finalize()
        self.chat.scroll_to_bottom(force=True)
        if self._active_bubble is not None:
            self._active_bubble.finalize()
        self._active_bubble = None

    def _on_confirmation_required(self, pending: dict):
        command = str(pending.get("command", ""))
        target = str(pending.get("target", ""))
        session = str(pending.get("session", ""))
        detail = f"设备：{target}\n会话：{session}\n\n命令：\n{command}"
        approved = QMessageBox.question(
            self, "确认执行配置命令", detail + "\n\n确认后仅允许执行这一条命令，且 token 只可使用一次。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        ) == QMessageBox.StandardButton.Yes
        self.worker.resolve_confirmation(str(pending.get("request_id", "")), approved)

    @staticmethod
    def _meta_text(meta: dict) -> str:
        bits = []
        if meta.get("provider"):
            bits.append(str(meta["provider"]))
        if meta.get("model"):
            bits.append(str(meta["model"]))
        if meta.get("kind"):
            bits.append(str(meta["kind"]))
        if meta.get("elapsed"):
            bits.append(f"{meta['elapsed']}s")
        return " ｜ ".join(bits)

    # ============================================================ 提问
    def _send(self):
        text = self.input.toPlainText().strip()
        if self._busy:
            return
        if not text and not self.images:
            return
        # 先把附件拍个快照：下面 clear() 会让输入框里已消失的图片标记回发
        # image_removed，若不提前复制，本轮提交的 images 会被清成空列表。
        images = list(self.images)
        # 欢迎页 / 空白草稿窗口里发出的第一段对话：此刻才真正创建 session。
        # 创建失败时保持草稿态、输入还原，用户改完可直接重试，消息不丢。
        if self.current_session is None:
            session, err = self._ensure_session(text or "（仅图片的会话）")
            if session is None:
                bubble = self.chat.add_bubble("error", "")
                bubble.append_answer(f"会话创建失败，消息未发送：{err}\n"
                                     "输入框已还原，可重试或先检查磁盘/权限。")
                bubble.finalize()
                self.input.setPlainText(text)
                self.input.decorate_images(images)
                self.chat.scroll_to_bottom(force=True)
                return
        mode = self.mode_box.currentData()
        if mode == "parallel":
            provs = [s.strip() for s in
                     (self.settings.get("parallel_providers") or "").split(",") if s.strip()]
        else:
            provs = []
        if not provs:
            provs = [self.provider_box.currentData()] if mode != "parallel" else []

        self._last_question = text
        sid = self.current_session.sid if self.current_session is not None else "default"
        bubble = self.chat.add_bubble("user", "")
        display = text or "（仅图片，无文字）"
        # 粘贴/拖入的图片已经在正文里以文件名出现过了，别重复罗列（只有用「图片」
        # 按钮附加、正文里没写的那些才补一行 📎 说明）
        extra = [Path(p).name for p in images if Path(p).name not in text]
        if extra:
            display += "\n\n📎 " + "、".join(extra)
        bubble.append_answer(display)
        bubble.finalize()

        self.input.clear()
        self.images.clear()
        self.attach_bar.update_items(self.images)
        self.worker.submit(
            "ask", sid=sid, text=text, mode=mode,
            provider=self.provider_box.currentData(),
            parallel=(mode == "parallel"),
            parallel_providers=provs,
            images=images,
            show_thinking=bool(self.settings.get("show_thinking", True)),
            max_rounds=int(self.settings.get("max_rounds", 4)),
        )
        self.tabs.setCurrentIndex(0)

    # ============================================================ 会话
    def _refresh_session_list(self):
        # 不再以 current_session 是否为空做早退：删除当前会话后会短暂为 None，
        # 此时也必须刷新，否则列表里残留已删除的项（表现为「删不掉」）
        self.session_list.blockSignals(True)
        self.session_list.clear()
        cur_sid = self.current_session.sid if self.current_session is not None else None
        bold = QFont()
        bold.setBold(True)
        for s in self.store.sessions:
            title = ("📌 " if s.pinned else "") + s.title
            item = QListWidgetItem(f"{title}\n{s.preview}")
            item.setToolTip(f"{title} ｜ {s.preview}")
            item.setData(Qt.ItemDataRole.UserRole, s.sid)
            item.setData(SessionList.PIN_ROLE, s.pinned)
            if s.pinned:
                item.setFont(bold)
            self.session_list.addItem(item)
            if s.sid == cur_sid:
                self.session_list.setCurrentItem(item)
        self.session_list.blockSignals(False)
        # 欢迎页的「最近会话」也跟同一份清单走（增删/改名/顶置后立即同步）
        self._refresh_welcome()

    def _refresh_welcome(self):
        """欢迎页的「最近会话」跟 store 同步（顶置在前，其余按最近使用）。"""
        welcome = getattr(self, "welcome", None)
        if welcome is None:
            return
        items = [(s.sid, s.title, s.preview) for s in self.store.sessions]
        welcome.set_recent(items)

    def _stash_draft(self) -> None:
        """草稿态（未建会话）切走：把输入框文本与附件暂存，回草稿时还原。

        只在草稿态生效——已持有会话时输入框内容不绑会话，维持原样。
        """
        if self.current_session is not None:
            return
        text = self.input.toPlainText()
        if text or self.images:
            self._draft_cache = {"text": text, "images": list(self.images)}
            self.input.clear()
            self.images = []
            self.attach_bar.update_items(self.images)

    def _restore_draft(self) -> None:
        """回到草稿窗口：还原上次暂存的输入（有暂存才动输入框）。"""
        cache = self._draft_cache
        if cache.get("text") or cache.get("images"):
            self.input.setPlainText(cache.get("text", ""))
            self.images = list(cache.get("images") or [])
            # setPlainText 只还原纯文本，图片标记的字符格式（路径属性/配色）会丢，
            # 这里按已知路径把标记补回去，悬停预览才不会失效
            self.input.decorate_images(self.images)
            self.attach_bar.update_items(self.images)
            self._draft_cache = {"text": "", "images": []}

    def _show_welcome(self) -> None:
        """回到欢迎页：不持有任何会话（启动、删光会话时用）。"""
        self._stash_draft()
        self.current_session = None
        self._active_bubble = None
        self.chat.clear()
        self._refresh_session_list()
        self._refresh_welcome()
        if getattr(self, "chat_stack", None) is not None:
            self.chat_stack.setCurrentIndex(PAGE_WELCOME)
        # 模型端不留上一个会话的上下文；真正打开会话时再由 restore_history 回灌
        self.worker.submit("command", name="reset_history")

    def _new_session(self):
        """进入空白会话窗口（草稿态）：此刻**不创建** session。

        只有用户发出第一段对话（_send → _ensure_session）才真正落一个会话——
        点了「新建」又没说话就切走的话，什么痕迹都不留。
        """
        if self.current_session is not None:
            if self.current_session.records:
                self.store.save()
            else:
                # 旧会话一条记录都没有 → 直接清掉，不留空 session
                self.store.delete(self.current_session.sid)
        self.current_session = None            # 草稿态：不持有任何会话
        self.chat.clear()
        self._active_bubble = None
        if getattr(self, "chat_stack", None) is not None:
            self.chat_stack.setCurrentIndex(PAGE_CHAT)
        self._refresh_session_list()
        # 模型上下文清空；设备技能作用域（session/.current）保持最近会话不动，
        # 等第一条消息真正建会话时再随 _ensure_session 切过去
        self.worker.submit("command", name="reset_history")
        self._restore_draft()                  # 上次没说完的话接回去
        self.input.setFocus()

    def _ensure_session(self, first_question: str = ""):
        """草稿态 → 真会话。返回 (session, 错误信息)；已持有会话时直接返回。

        创建失败（磁盘满/权限等）不抛异常：调用方保持草稿态、把用户输入
        还原到输入框并明确报错，消息不丢。
        """
        if self.current_session is not None:
            return self.current_session, ""
        try:
            session = self.store.create()
            self.store.save()
        except Exception as e:  # noqa: BLE001  创建失败要给用户看得见的回退
            return None, f"{type(e).__name__}: {e}"
        self.current_session = session
        # 设备技能作用域跟到新会话（MCP 子进程每次工具调用前读 .current）
        self._apply_skill_session(session.sid)
        # 设备/拓扑页签是会话视图：新会话还没有自己的数据，作废旧页签缓存
        self._invalidate_session_views()
        # 从欢迎页/草稿态走来的：把主区切到对话页（_new_session 已在对话页则无感）
        if getattr(self, "chat_stack", None) is not None:
            self.chat_stack.setCurrentIndex(PAGE_CHAT)
        title = " ".join((first_question or "").split())[:16]
        if title:
            self.store.rename(session.sid, title)
        # 草稿内容此刻已落进真会话（输入框内容随本次发送走），缓存作废
        self._draft_cache = {"text": "", "images": []}
        self._refresh_session_list()
        return session, ""

    @staticmethod
    def _apply_skill_session(sid: str) -> None:
        """切换当前对话的设备技能作用域（失败不能影响界面，仅记日志）。"""
        try:
            d = use_skill_session(sid)
            print(f"[会话] 设备技能作用域 → session/{sid}/skill/（{d}）")
        except Exception as e:
            print(f"[警告] 切换设备技能作用域失败：{type(e).__name__}: {e}")

    def _on_session_clicked(self, item):
        sid = item.data(Qt.ItemDataRole.UserRole)
        self._switch_session(sid)

    def _switch_session(self, sid: str):
        session = self.store.get(sid)
        if session is None:
            # 点击的 sid 在本地清单里不存在：明确不动、不新建，
            # 并刷新列表清掉这条幽灵条目（绝不凭空造一个新会话出来）
            self._refresh_session_list()
            return
        # 草稿态切走：暂存输入框内容，回来时还原
        self._stash_draft()
        # 切走前清理：原会话一条对话记录都没有 → 直接删掉，不留空 session
        old = self.current_session
        if (old is not None and old.sid != sid and not old.records
                and self.store.get(old.sid) is not None):
            self.store.delete(old.sid)
        self.current_session = session
        # 设备技能跟随对话切换（与 _new_session 同一入口）
        self._apply_skill_session(sid)
        # 设备/拓扑页签跟着会话换数据：作废旧页签缓存，正停在页签上就立刻重载
        self._invalidate_session_views()
        self.chat.clear()
        self._active_bubble = None
        if getattr(self, "chat_stack", None) is not None:
            self.chat_stack.setCurrentIndex(PAGE_CHAT)
        for rec in session.records:
            q = self.chat.add_bubble("user", "")
            q.append_answer(rec.get("question", ""))
            q.finalize()
            a = self.chat.add_bubble("assistant", f"{rec.get('provider', '')} ｜ {rec.get('mode', '')}")
            a.set_answer(rec.get("answer", ""))
        self.chat.scroll_to_bottom(force=True)
        # 列表同步（选中态 + 空会话已被上面清掉），否则启动恢复后侧边栏是空的
        self._refresh_session_list()
        # 模型端上下文跟着切：回灌该会话的历史消息，避免切回旧会话后「失忆」
        self.worker.submit("restore_history", records=list(session.records))

    def _rename_session(self, sid: str):
        session = self.store.get(sid)
        if session is None:
            return
        text, ok = QInputDialog.getText(self, "重命名会话", "新名称：", text=session.title)
        if ok and text.strip():
            self.store.rename(sid, text)
            self._refresh_session_list()

    def _delete_session(self, sid: str):
        session = self.store.get(sid)
        if session is None:
            return
        if QMessageBox.question(self, "删除会话", f"确定删除「{session.title}」？") \
                != QMessageBox.StandardButton.Yes:
            return
        was_current = self.current_session is not None and self.current_session.sid == sid
        self.store.delete(sid)
        if not was_current:
            self._refresh_session_list()
            return
        # 删除的是当前会话（通常就是列表最顶端的那个）。
        # 根因修复：原来这里直接 _new_session() 又建一个「新会话」插到顶端，
        # 看起来就像「最顶端的会话删不掉」。正确做法是选中剩余会话，
        # 只有全部删光时才新建。
        self.current_session = None
        self._active_bubble = None
        if self.store.sessions:
            self._switch_session(self.store.sessions[0].sid)
            self._refresh_session_list()
        else:
            # 全部删光 → 回欢迎页（不凭空造一个空会话出来）
            self._invalidate_session_views()
            self._show_welcome()

    def _pin_session(self, sid: str, pinned: bool):
        self.store.set_pinned(sid, pinned)
        self._refresh_session_list()

    def _export_session(self):
        if self.current_session is None:
            return
        default = str(BASE_DIR / "logs" / f"session_{self.current_session.sid}.md")
        path, _ = QFileDialog.getSaveFileName(self, "导出会话", default,
                                              "Markdown (*.md);;所有文件 (*)")
        if not path:
            return
        try:
            out = self.current_session.export_markdown(path)
            QMessageBox.information(self, "导出成功", f"已导出到：\n{out}")
        except OSError as e:
            QMessageBox.warning(self, "导出失败", str(e))

    # ============================================================ 图片
    def _add_images(self, paths: list[str]):
        for p in paths:
            if p not in self.images:
                self.images.append(p)
        self.attach_bar.update_items(self.images)
        self._append_log(f"[附件] 已附加 {len(self.images)} 张图片\n")

    def _remove_image(self, path: str):
        self.images = [p for p in self.images if p != path]
        self.attach_bar.update_items(self.images)
        # 附件栏点 ✕ 与「删掉正文里的文件名」是同一个动作的两面：两条路都要清干净，
        # 否则会出现「附件栏已空、正文还挂着一张图的文件名」的错觉
        self.input.remove_marker(path)

    def _pick_images(self):
        exts = " ".join(f"*{e}" for e in sorted(IMAGE_EXTS))
        paths, _ = QFileDialog.getOpenFileNames(
            self, "选择拓扑截图", str(Path.home()),
            f"图片文件 ({exts});;所有文件 (*)")
        if paths:
            self._add_images(paths)

    # ============================================================ 命令控制台
    def _echo(self, text: str):
        self.cmd_out.moveCursor(self.cmd_out.textCursor().MoveOperation.End)
        self.cmd_out.insertPlainText(text + "\n")
        bar = self.cmd_out.verticalScrollBar()
        bar.setValue(bar.maximum())

    def _run_command(self, raw: str):
        self._echo(f"> {raw}")
        if not raw.startswith("/"):
            self.worker.submit("command", name="call", tool=raw,
                               args={})
            return
        cmd, _, rest = raw[1:].partition(" ")
        cmd = cmd.strip().lower()
        rest = rest.strip()

        if cmd == "help":
            self._echo(HELP_TEXT)
        elif cmd == "model":
            if not rest:
                self.worker.submit("command", name="providers")
            else:
                self.worker.submit("set_provider", name=rest)
        elif cmd == "key":
            self.worker.submit("set_key", key=rest)
        elif cmd == "tools":
            self.worker.submit("command", name="tools")
        elif cmd == "call":
            tool, _, arg_text = rest.partition(" ")
            if not tool:
                self._echo("用法：/call 工具名 {\"参数\":\"值\"}")
                return
            try:
                args = json.loads(arg_text) if arg_text.strip() else {}
            except json.JSONDecodeError as e:
                self._echo(f"参数不是合法 JSON：{e}")
                return
            self.worker.submit("command", name="call", tool=tool, args=args)
        elif cmd == "audit":
            self.worker.submit("command", name="audit", arg=rest or "10")
        elif cmd == "vision":
            self.worker.submit("command", name="vision")
        elif cmd == "topology":
            # 手动触发自动巡检（force=True：无视画面差分，重新识读）
            self._echo("自动拓扑巡检：截取 eNSP/虚拟机窗口并识读…")
            self.worker.submit("auto_vision", force=True,
                               keyword=rest or None)
        elif cmd == "autovision":
            arg = rest.lower()
            if arg in ("on", "开", "1", "true"):
                self.settings["auto_vision"] = True
                self._echo("自动拓扑巡检：已开启（下次启动生效；本次可用 /topology 立即执行）")
            elif arg in ("off", "关", "0", "false"):
                self.settings["auto_vision"] = False
                self._echo("自动拓扑巡检：已关闭（下次启动不再自动执行；可在设置里改回）")
            else:
                self._echo("用法：/autovision on|off")
        elif cmd in ("rebuild", "reindex"):
            self.worker.submit("command", name="rebuild")
        elif cmd == "probe":
            self.worker.submit("command", name="probe")
        elif cmd == "image":
            if rest.lower() in ("clear", "none", "-"):
                self.images.clear()
                self.attach_bar.update_items(self.images)
                self._echo("已取消附加图片")
            elif rest:
                p = Path(rest.strip('"').strip("'")).expanduser()
                if p.is_file():
                    self._add_images([str(p)])
                    self._echo(f"已附加图片：{p}")
                else:
                    self._echo(f"图片不存在：{p}")
            else:
                self._echo("已附加图片：" + ("、".join(self.images) or "（无）"))
        elif cmd in ("agent", "rag", "plan", "对话"):
            # rag 是旧模式名，已并入统一入口；这里仅作兼容别名
            target = "agent" if cmd in ("agent", "rag", "对话") else "plan"
            idx = self.mode_box.findData(target)
            if idx >= 0:
                self.mode_box.setCurrentIndex(idx)
            self._echo(f"已切换到 {target} 模式")
        elif cmd == "export":
            if self.current_session is None:
                self._echo("还没有打开会话（先点侧边栏历史或新建一个）")
            elif rest:
                try:
                    self.current_session.export_markdown(rest)
                    self._echo(f"已导出：{rest}")
                except (OSError, AttributeError) as e:
                    self._echo(f"导出失败：{e}")
            else:
                self._export_session()
        elif cmd == "clear":
            self.cmd_out.clear()
        else:
            self._echo(f"未知命令：/{cmd}（输入 /help 查看全部）")

    def _on_command_result(self, name: str, text: str):
        self._echo(f"[{name}]\n{text}\n")

    def _on_topology(self, text: str):
        """自动拓扑巡检结果 → 对话区气泡（用户可见、可追溯）"""
        bubble = self.chat.add_bubble("assistant", "")
        bubble.append_answer(text)
        bubble.set_meta("自动拓扑巡检")
        bubble.finalize()
        self.chat.scroll_to_bottom(force=True)

    # ============================================================ 其它交互
    def _on_provider_changed(self, _index: int):
        name = self.provider_box.currentData()
        if name:
            self.settings["provider"] = name
            self.worker.submit("set_provider", name=name)

    def _on_mode_changed(self, _index: int):
        mode = self.mode_box.currentData()
        self.settings["mode"] = mode
        if mode == "parallel":
            self._append_log("[模式] 多模型并行：同一问题交给多个模型并融合\n")
        elif mode == "plan":
            self._append_log("[模式] 拓扑规划：只读探测各设备并生成拓扑信息沉淀进手册"
                             "（不改配置）\n")
        else:
            self._append_log("[模式] 对话：知识检索内置，MCP 工具按需调用\n")

    def _toggle_thinking(self):
        value = not bool(self.settings.get("show_thinking", True))
        self.settings["show_thinking"] = value
        self.think_btn.setText("思考 ✓" if value else "思考 ✕")
        self._save_settings()

    def _start_local(self):
        vision = bool(self.settings.get("mmproj"))
        if not find_model():
            QMessageBox.warning(self, "未找到模型",
                                f"请在下面的目录放入 gguf 模型文件：\n{BASE_DIR / 'models'}")
            return
        if vision and not find_mmproj():
            vision = False
            self._append_log("[警告] 未找到 mmproj 视觉投影文件，本次以文本模式启动本地服务\n")
        self.worker.submit("start_local", vision=vision)
        self.tabs.setCurrentIndex(1)

    def _show_tools(self):
        ToolsDialog(getattr(self, "tools_cache", []), self.palette_ref, self).exec()

    def _show_audit(self):
        AuditDialog(self.palette_ref, self).exec()

    def _show_help(self):
        box = QMessageBox(self)
        box.setWindowTitle("使用说明")
        box.setText(HELP_TEXT)
        box.exec()

    def _show_settings(self):
        dialog = SettingsDialog(self.settings, self.palette_ref, self)
        if dialog.exec() != SettingsDialog.DialogCode.Accepted:
            return
        new = dialog.result_settings()
        # 模型与密钥默认持久化到 %USERPROFILE%\.networkclaw\networkclaw.json
        # （用户级、与仓库无关）；勾选「同时写入 .env」时才另外落一份 .env 供脚本复用。
        try:
            from core import user_config
            from core.providers import get_provider

            if new.get("provider"):
                user_config.set_active_model(new["provider"])
            # 主 Key / 备用 Key 都存到**所选提供方**名下（智谱、Kimi 各一套，互不覆盖）；
            # 这也让「换个提供方再填 Key」不会把原来那家的密钥冲掉。
            if new.get("api_key") or new.get("api_key_alt"):
                try:
                    prov = get_provider(new.get("provider") or "")
                except KeyError:
                    prov = None
                if prov is None or not prov.needs_key:
                    self._append_log("[设置] 本地提供方无需密钥，填写的 Key 已忽略\n")
                else:
                    if new.get("api_key"):
                        user_config.set_api_key(prov.name, new["api_key"],
                                                api_key_env=prov.api_key_env)
                    if new.get("api_key_alt"):
                        user_config.set_api_key_alt(prov.name, new["api_key_alt"],
                                                    api_key_alt_env=prov.api_key_alt_env)
            saved = user_config.config_path()
            self._append_log(f"[设置] 模型与密钥已保存到 {saved}\n")
            if new.get("api_key") and new.get("save_key") \
                    and (new.get("provider") or "").startswith("deepseek"):
                path = persist_api_key(new["api_key"])
                self._append_log(f"[设置] API Key 另已写入 {path}\n")
        except OSError as e:
            QMessageBox.warning(self, "保存失败", f"写入用户配置失败：{e}")
        old_theme = self.settings.get("theme")
        old_mmproj = bool(self.settings.get("mmproj"))
        old_search = bool(self.settings.get("with_search"))
        self.settings.update({k: v for k, v in new.items() if k != "save_key"})
        self._save_settings()
        if new["theme"] != old_theme:
            self._apply_theme(get_palette(new["theme"]))
        self.worker.submit("set_provider", name=new["provider"])
        self.worker.submit("set_key", key=new["api_key"],
                           alt_key=new.get("api_key_alt", ""),
                           provider=new["provider"])
        self._append_log(
            f"[设置] 已保存：提供方={new['provider']} 模式={new['mode']} "
            f"mmproj={'开' if new['mmproj'] else '关'} 联网搜索={'开' if new['with_search'] else '关'} "
            f"自动巡检={'开' if new.get('auto_vision') else '关'}\n")
        if bool(new["with_search"]) != old_search or bool(new.get("mmproj")) != old_mmproj:
            self._append_log("[设置] 联网搜索 / mmproj 的变更在下次启动时生效\n")

    def _toggle_theme(self):
        name = "light" if self.palette_ref.name == "dark" else "dark"
        self.settings["theme"] = name
        self._apply_theme(get_palette(name))
        self._save_settings()

    def _sync_theme_btn(self):
        btn = getattr(self, "theme_btn", None)
        if btn is not None:
            btn.setText("☀️ 浅色" if self.palette_ref.name == "dark" else "🌙 深色")

    def _apply_theme(self, palette):
        self.palette_ref = palette
        QApplication.instance().setStyleSheet(build_qss(palette))
        for widget in (self.chat, self.attach_bar, self.input):
            if hasattr(widget, "retint"):
                widget.retint(palette)
        topo = getattr(self, "topo_canvas", None)
        if topo is not None:
            topo.retint(palette)
        for row in (self.row_llama, self.row_ollama, self.row_mcp, self.row_vision):
            row.palette_ref = palette
        self._sync_theme_btn()
        self._append_log(f"[界面] 已切换到{'深色' if palette.name == 'dark' else '浅色'}主题\n")

    # ============================================================ 设置持久化
    def _save_settings(self):
        self.qsettings.setValue("settings", json.dumps(self.settings, ensure_ascii=False))

    def _restore_geometry(self):
        geo = self.qsettings.value("geometry")
        if geo:
            self.restoreGeometry(geo)

    def closeEvent(self, event):
        try:
            # 退出前清掉空会话（含当前没聊过天的这个），只把有对话历史的落盘
            self.store.prune_empty()
            self.store.save()
            self.qsettings.setValue("geometry", self.saveGeometry())
            self._save_settings()
        except Exception:
            pass
        if getattr(self, "worker", None) is not None and self.worker.isRunning():
            self.worker.stop()
            if not self.worker.wait(6000):
                self.worker.terminate()
                self.worker.wait(2000)
        event.accept()
