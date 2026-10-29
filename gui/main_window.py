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

from PyQt6.QtCore import QObject, QSettings, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QDragEnterEvent, QDropEvent, QFont, QKeyEvent
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
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from core.llama_start import find_mmproj, find_model
from core.paths import BASE_DIR
from core.session_skills import use_session as use_skill_session
# StreamProxy 已迁到 core（与 Qt 无关，放这里会让测试被迫依赖 PyQt6，CI 不装）
from core.stream_proxy import StreamProxy
from core.vision import IMAGE_EXTS
from gui.dialogs import HELP_TEXT, AuditDialog, SettingsDialog, ToolsDialog, persist_api_key
from gui.store import SessionStore
from gui.theme import build_qss, get_palette
from gui.widgets import AttachmentBar, ChatView, MessageBubble, SessionList, StatusRow
from gui.worker import AgentWorker

LOG_TAIL_LINES = 5000


class _LogEmitter(QObject):
    """只用来承载日志信号（QObject 才能跨线程发信号）"""

    text = pyqtSignal(str)


# ---------------------------------------------------------------- 输入控件

class InputEdit(QTextEdit):
    """输入框：回车发送、Shift+回车换行、可拖入图片"""

    submitted = pyqtSignal()
    images_dropped = pyqtSignal(list)

    def keyPressEvent(self, event: QKeyEvent):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                super().keyPressEvent(event)
                return
            self.submitted.emit()
            return
        super().keyPressEvent(event)

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent):
        paths = [u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile()]
        images = [p for p in paths if Path(p).suffix.lower() in IMAGE_EXTS]
        if images:
            self.images_dropped.emit(images)
            event.acceptProposedAction()


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
        self._busy = False
        self.tools_cache: list[dict] = []
        self.providers_cache: list[dict] = []

        self.setWindowTitle("NetworkClaw · 网络运维智能助手")
        self.setMinimumSize(1080, 700)

        self._build_ui()
        self._restore_geometry()
        self._wire_stdout()

        # 先开出第一个对话：设备技能按会话隔离（session/<sid>/skill/<设备>/），
        # worker 里的索引构建与 MCP 工具调用都要读 session/.current，
        # 必须在 worker 启动前把作用域钉住。
        self.current_session = self.store.create()
        self._apply_skill_session(self.current_session.sid)

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
        self._device_timer = QTimer(self)
        self._device_timer.setInterval(30000)
        self._device_timer.timeout.connect(self._refresh_devices)
        self._device_timer.start()

        self._new_session(first=True)
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
        for label, value in (("agent 工具调用", "agent"),
                             ("rag 知识库", "rag"),
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

        self.chat = ChatView(self.palette_ref)
        layout.addWidget(self.chat, 1)

        bottom = QWidget()
        bl = QVBoxLayout(bottom)
        bl.setContentsMargins(14, 8, 14, 12)
        bl.setSpacing(6)

        self.attach_bar = AttachmentBar(self.palette_ref)
        self.attach_bar.remove_requested.connect(self._remove_image)
        bl.addWidget(self.attach_bar)

        row = QHBoxLayout()
        row.setSpacing(6)
        self.input = InputEdit()
        self.input.setObjectName("Input")
        self.input.setPlaceholderText(
            "输入问题，回车发送（Shift+Enter 换行）｜可直接拖入拓扑截图")
        self.input.setFixedHeight(76)
        self.input.submitted.connect(self._send)
        self.input.images_dropped.connect(self._add_images)
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

        hint = QLabel("清单来源：data/device_inventory.json + 智能体实际访问过的设备"
                      "（Telnet/串口工具连接成功即登记）。状态探测为只读 TCP/串口枚举，不下发任何命令。")
        hint.setObjectName("AppSubtitle")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        return page

    def _refresh_devices(self):
        self.device_summary.setText("探测中…")
        self.worker.submit("device_probe")

    def _on_device_interval(self):
        sec = self.device_auto_box.currentData() or 0
        if sec > 0:
            self._device_timer.setInterval(sec * 1000)
            self._device_timer.start()
            self._refresh_devices()
        else:
            self._device_timer.stop()

    def _on_tab_changed(self, idx: int):
        # 第一次切到设备页签时立即探测一次
        if self.tabs.tabText(idx) == "设备" and not self._device_probed:
            self._device_probed = True
            self._refresh_devices()

    def _on_devices(self, devices: list):
        """填充设备表（绿点=在线，灰点=离线）"""
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
            self.device_table.setItem(i, 6, _cell(d.get("detail")))

            # 灯放最后涂色，行背景也跟着淡淡提示（避免整行扎眼）
            self._paint_device_row(i, is_on)
        self.device_summary.setText(
            f"共 {len(devices)} 台 · 在线 {online} · 离线 {len(devices) - online}")

    def _paint_device_row(self, row: int, is_on: bool):
        color = self.DEVICE_LIGHT_ON if is_on else self.DEVICE_LIGHT_OFF
        color = QColor(self.DEVICE_LIGHT_ON if is_on else self.DEVICE_LIGHT_OFF)
        light = self.device_table.item(row, 0)
        if light is not None:
            light.setText("●")
            light.setForeground(color)
            light.setToolTip("在线" if is_on else "离线")

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
        if self.images:
            display += "\n\n📎 " + "、".join(Path(p).name for p in self.images)
        bubble.append_answer(display)
        bubble.finalize()

        self.input.clear()
        self.worker.submit(
            "ask", sid=sid, text=text, mode=mode,
            provider=self.provider_box.currentData(),
            parallel=(mode == "parallel"),
            parallel_providers=provs,
            images=list(self.images),
            show_thinking=bool(self.settings.get("show_thinking", True)),
            max_rounds=int(self.settings.get("max_rounds", 4)),
        )
        self.images.clear()
        self.attach_bar.update_items(self.images)
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

    def _new_session(self, first: bool = False):
        if not first and self.current_session is not None and self.current_session.records:
            self.store.save()
        if not (first and self.current_session is not None):
            # 首次启动时 __init__ 已预先建好会话（worker 启动前要钉住技能作用域），
            # 这里不重复创建，避免列表里留下一个空会话
            self.current_session = self.store.create()
            # 一个对话一套技能：把设备技能与会话日志都切到这个 sid。
            # MCP 服务端是子进程，读 session/.current 指针，无需重连即可跟随。
            self._apply_skill_session(self.current_session.sid)
        self.chat.clear()
        self._active_bubble = None
        self.worker.submit("command", name="reset_history")
        self._refresh_session_list()
        if not first:
            self._switch_session(self.current_session.sid)

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
            return
        self.current_session = session
        # 设备技能跟随对话切换（与 _new_session 同一入口）
        self._apply_skill_session(sid)
        self.chat.clear()
        self._active_bubble = None
        for rec in session.records:
            q = self.chat.add_bubble("user", "")
            q.append_answer(rec.get("question", ""))
            q.finalize()
            a = self.chat.add_bubble("assistant", f"{rec.get('provider', '')} ｜ {rec.get('mode', '')}")
            a.set_answer(rec.get("answer", ""))
        self.chat.scroll_to_bottom(force=True)
        self.worker.submit("command", name="reset_history")

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
            self.chat.clear()
            self._new_session()

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
        elif cmd in ("agent", "rag", "parallel"):
            if cmd == "parallel":
                idx = self.mode_box.findData("parallel")
            else:
                idx = self.mode_box.findData(cmd)
            if idx >= 0:
                self.mode_box.setCurrentIndex(idx)
            self._echo(f"已切换到 {cmd} 模式")
        elif cmd == "export":
            if rest:
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
        elif mode == "rag":
            self._append_log("[模式] 知识库问答：固定走检索 + 生成\n")
        else:
            self._append_log("[模式] agent：模型自主调用 MCP 工具\n")

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
        if new.get("api_key") and new.get("save_key"):
            try:
                path = persist_api_key(new["api_key"])
                self._append_log(f"[设置] API Key 已写入 {path}\n")
            except OSError as e:
                QMessageBox.warning(self, "保存失败", f"写入 .env 失败：{e}")
        old_theme = self.settings.get("theme")
        old_mmproj = bool(self.settings.get("mmproj"))
        old_search = bool(self.settings.get("with_search"))
        self.settings.update({k: v for k, v in new.items() if k != "save_key"})
        self._save_settings()
        if new["theme"] != old_theme:
            self._apply_theme(get_palette(new["theme"]))
        self.worker.submit("set_provider", name=new["provider"])
        self.worker.submit("set_key", key=new["api_key"])
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
        for widget in (self.chat, self.attach_bar):
            if hasattr(widget, "retint"):
                widget.retint(palette)
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
            if self.current_session is not None and self.current_session.records:
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
