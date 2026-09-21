"""对话框：设置 / MCP 工具浏览器 / 命令审计查看。"""
from __future__ import annotations

import os
from pathlib import Path

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from core.command_guard import LEVEL_CN, audit_tail
from core.llama_start import find_mmproj, find_model, find_llama_server
from core.paths import BASE_DIR
from core.providers import configured_providers, probe, save_env_file
from gui.theme import Palette

WINDOW_FLAGS = Qt.WindowType.Dialog | Qt.WindowType.WindowCloseButtonHint


# ---------------------------------------------------------------- 设置

class ProbeThread(QThread):
    """提供方连通性探测（放到线程里，避免界面假死）"""

    sig_done = pyqtSignal(str)

    def __init__(self, names: list[str], parent=None):
        super().__init__(parent)
        self.names = names

    def run(self):
        from core.providers import get_provider

        lines = ["提供方可用性探测："]
        for name in self.names:
            try:
                p = get_provider(name)
            except KeyError as e:
                lines.append(f"[跳过] {name}：{e.args[0] if e.args else e}")
                continue
            if p.needs_key and not p.api_key_value:
                lines.append(f"[跳过] {p.name}：未配置 API Key（{p.api_key_env}）")
                continue
            r = probe(p)
            flag = "可用" if r["ok"] else "不可用"
            extra = f"（{r['latency']}s）" if r.get("latency") else ""
            lines.append(f"[{flag}] {p.name}  {p.model}  {extra} {r['detail']}")
        self.sig_done.emit("\n".join(lines))


class SettingsDialog(QDialog):
    """设置：模型提供方与密钥、本地运行环境、界面偏好"""

    def __init__(self, settings: dict, palette: Palette, parent: QWidget | None = None):
        super().__init__(parent)
        self.palette_ref = palette
        self.settings = dict(settings)
        self.setWindowTitle("设置")
        self.setWindowFlags(WINDOW_FLAGS)
        self.setMinimumWidth(620)
        self._probe_thread: ProbeThread | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(12)

        tabs = QTabWidget()
        tabs.addTab(self._tab_model(), "模型与密钥")
        tabs.addTab(self._tab_runtime(), "本地运行环境")
        tabs.addTab(self._tab_ui(), "界面与行为")
        root.addWidget(tabs)

        self.status = QLabel("")
        self.status.setObjectName("Hint")
        self.status.setWordWrap(True)
        root.addWidget(self.status)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("保存")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    # -------------------------------------------------- 各页签
    def _tab_model(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form.setSpacing(9)

        self.provider_box = QComboBox()
        from core.providers import list_providers

        for p in list_providers():
            mark = "" if p.is_configured else "（未配置密钥）"
            self.provider_box.addItem(f"{p.label}  ·  {p.name}{mark}", p.name)
        idx = self.provider_box.findData(self.settings.get("provider", "local"))
        if idx >= 0:
            self.provider_box.setCurrentIndex(idx)
        form.addRow("默认提供方", self.provider_box)

        self.key_edit = QLineEdit()
        self.key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.key_edit.setPlaceholderText("sk-… （留空表示不改动）")
        self.key_edit.setText(os.environ.get("DEEPSEEK_API_KEY", ""))
        form.addRow("DeepSeek API Key", self.key_edit)

        self.save_key_check = QCheckBox("写入项目 .env（持久保存，推荐）")
        self.save_key_check.setChecked(True)
        form.addRow("", self.save_key_check)

        self.mode_box = QComboBox()
        for label, value in (("agent（模型自主调用工具）", "agent"),
                             ("rag（固定知识库问答）", "rag"),
                             ("parallel（多模型并行 + 融合）", "parallel")):
            self.mode_box.addItem(label, value)
        i = self.mode_box.findData(self.settings.get("mode", "agent"))
        if i >= 0:
            self.mode_box.setCurrentIndex(i)
        form.addRow("默认模式", self.mode_box)

        self.parallel_edit = QLineEdit(self.settings.get("parallel_providers", ""))
        self.parallel_edit.setPlaceholderText("留空 = 全部已配置的提供方，如 local,deepseek")
        form.addRow("并行提供方", self.parallel_edit)

        probe_btn = QPushButton("测试提供方连通性")
        probe_btn.setObjectName("Ghost")
        probe_btn.clicked.connect(self._probe)
        form.addRow("", probe_btn)
        return page

    def _tab_runtime(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setSpacing(10)

        info = QGroupBox("当前环境探测结果")
        info_form = QFormLayout(info)
        model = find_model()
        server = find_llama_server()
        mmproj = find_mmproj()
        info_form.addRow("工作目录", self._ro(str(BASE_DIR)))
        info_form.addRow("主模型", self._ro(str(model) if model else "未找到（请放入 models/）"))
        info_form.addRow("llama-server", self._ro(str(server) if server else "未找到"))
        info_form.addRow("视觉投影 mmproj", self._ro(str(mmproj) if mmproj else "未找到"))
        layout.addWidget(info)

        group = QGroupBox("多模态与联网")
        gform = QFormLayout(group)
        self.mmproj_check = QCheckBox("启用图像识别（启动本地服务时加载 mmproj）")
        self.mmproj_check.setChecked(bool(self.settings.get("mmproj")))
        gform.addRow("", self.mmproj_check)

        row = QHBoxLayout()
        self.mmproj_edit = QLineEdit(self.settings.get("mmproj") or "")
        self.mmproj_edit.setPlaceholderText("留空 = 自动探测 models/ 下的 *mmproj*.gguf")
        browse = QPushButton("浏览…")
        browse.setObjectName("Ghost")
        browse.clicked.connect(self._pick_mmproj)
        row.addWidget(self.mmproj_edit, 1)
        row.addWidget(browse)
        holder = QWidget()
        holder.setLayout(row)
        gform.addRow("mmproj 路径", holder)

        self.search_check = QCheckBox("接入联网搜索 MCP（需要 npx 与 open-websearch）")
        self.search_check.setChecked(bool(self.settings.get("with_search")))
        gform.addRow("", self.search_check)
        layout.addWidget(group)

        hint = QLabel("提示：模型、llama-server 与 mmproj 的查找顺序见 docs/packaging.md；"
                      "联网搜索与 mmproj 的改动在下次启动时生效。")
        hint.setObjectName("Hint")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        layout.addStretch(1)
        return page

    def _tab_ui(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self.thinking_check = QCheckBox("显示模型思考过程（可随时在工具栏切换）")
        self.thinking_check.setChecked(bool(self.settings.get("show_thinking", True)))
        form.addRow("", self.thinking_check)

        self.rounds_spin = QSpinBox()
        self.rounds_spin.setRange(1, 12)
        self.rounds_spin.setValue(int(self.settings.get("max_rounds", 4)))
        form.addRow("agent 最大工具轮次", self.rounds_spin)

        self.theme_box = QComboBox()
        self.theme_box.addItem("深色", "dark")
        self.theme_box.addItem("浅色", "light")
        i = self.theme_box.findData(self.settings.get("theme", "dark"))
        if i >= 0:
            self.theme_box.setCurrentIndex(i)
        form.addRow("界面主题", self.theme_box)

        self.autolog_check = QCheckBox("把运行日志同步显示在「运行日志」页签")
        self.autolog_check.setChecked(bool(self.settings.get("capture_stdout", True)))
        form.addRow("", self.autolog_check)
        return page

    # -------------------------------------------------- 交互
    def _ro(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("Hint")
        label.setWordWrap(True)
        label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        return label

    def _pick_mmproj(self):
        path, _ = QFileDialog.getOpenFileName(self, "选择 mmproj 视觉投影文件", str(BASE_DIR),
                                              "GGUF 模型 (*.gguf);;所有文件 (*)")
        if path:
            self.mmproj_edit.setText(path)
            self.mmproj_check.setChecked(True)

    def _probe(self):
        names = [self.provider_box.currentData()]
        extra = self.parallel_edit.text().strip()
        if extra:
            names += [s.strip() for s in extra.split(",") if s.strip()]
        names = list(dict.fromkeys([n for n in names if n]))
        self.status.setText("正在探测，请稍候…")
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        self._probe_thread = ProbeThread(names, self)
        self._probe_thread.sig_done.connect(self._probe_done)
        self._probe_thread.start()

    def _probe_done(self, text: str):
        QApplication.restoreOverrideCursor()
        self.status.setText(text.replace("\n", "　｜　"))
        QMessageBox.information(self, "提供方探测结果", text)

    # -------------------------------------------------- 结果
    def result_settings(self) -> dict:
        """读取界面上的配置（不含密钥落盘逻辑，由调用方决定）"""
        return {
            "provider": self.provider_box.currentData(),
            "api_key": self.key_edit.text().strip(),
            "save_key": self.save_key_check.isChecked(),
            "mode": self.mode_box.currentData(),
            "parallel_providers": self.parallel_edit.text().strip(),
            "mmproj": self.mmproj_edit.text().strip() if self.mmproj_check.isChecked() else "",
            "with_search": self.search_check.isChecked(),
            "show_thinking": self.thinking_check.isChecked(),
            "max_rounds": self.rounds_spin.value(),
            "theme": self.theme_box.currentData(),
            "capture_stdout": self.autolog_check.isChecked(),
        }


def persist_api_key(key: str) -> Path | None:
    """把密钥写入 .env（供调用方在用户勾选时使用）"""
    if not key:
        return None
    return save_env_file({"DEEPSEEK_API_KEY": key})


# ---------------------------------------------------------------- 工具浏览器

class ToolsDialog(QDialog):
    """MCP 工具清单（名称 / 服务端 / 参数 / 说明）"""

    def __init__(self, tools: list[dict], palette: Palette, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle(f"MCP 工具（{len(tools)} 个）")
        self.setWindowFlags(WINDOW_FLAGS)
        self.resize(880, 540)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)

        table = QTableWidget(len(tools), 4)
        table.setHorizontalHeaderLabels(["工具名", "服务端", "参数", "说明"])
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        table.setWordWrap(True)
        header = table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        for r, t in enumerate(tools):
            table.setItem(r, 0, QTableWidgetItem(t.get("name", "")))
            table.setItem(r, 1, QTableWidgetItem(t.get("server", "")))
            table.setItem(r, 2, QTableWidgetItem(", ".join(t.get("params") or []) or "无"))
            desc = (t.get("description") or "").splitlines()[0]
            table.setItem(r, 3, QTableWidgetItem(desc))
        table.resizeRowsToContents()
        layout.addWidget(table)

        hint = QLabel("提示：在「命令」页签可用 /call 工具名 {\"参数\":\"值\"} 直接调用任意工具。")
        hint.setObjectName("Hint")
        layout.addWidget(hint)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.button(QDialogButtonBox.StandardButton.Close).setText("关闭")
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)


# ---------------------------------------------------------------- 审计

class AuditDialog(QDialog):
    """设备命令审计记录（logs/command_audit.log）"""

    def __init__(self, palette: Palette, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("设备命令审计")
        self.setWindowFlags(WINDOW_FLAGS)
        self.resize(940, 520)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)

        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(
            ["时间", "通道", "目标", "命令", "分级", "是否执行", "说明"])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setWordWrap(False)
        header = self.table.horizontalHeader()
        for i in (0, 1, 2, 4, 5):
            header.setSectionResizeMode(i, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(6, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.table)

        row = QHBoxLayout()
        refresh = QPushButton("刷新")
        refresh.setObjectName("Ghost")
        refresh.clicked.connect(self.reload)
        row.addWidget(refresh)
        self.count = QLabel("")
        self.count.setObjectName("Hint")
        row.addWidget(self.count)
        row.addStretch(1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.button(QDialogButtonBox.StandardButton.Close).setText("关闭")
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        row.addWidget(buttons)
        layout.addLayout(row)

        self.reload()

    def reload(self):
        rows = list(reversed(audit_tail(200)))
        self.table.setRowCount(len(rows))
        for r, rec in enumerate(rows):
            level = rec.get("level")
            self.table.setItem(r, 0, QTableWidgetItem(str(rec.get("time", ""))))
            self.table.setItem(r, 1, QTableWidgetItem(str(rec.get("transport", ""))))
            self.table.setItem(r, 2, QTableWidgetItem(str(rec.get("target", ""))))
            self.table.setItem(r, 3, QTableWidgetItem(str(rec.get("command", ""))))
            self.table.setItem(r, 4, QTableWidgetItem(LEVEL_CN.get(level, str(level))))
            self.table.setItem(r, 5, QTableWidgetItem("已执行" if rec.get("executed") else "未执行"))
            self.table.setItem(r, 6, QTableWidgetItem(str(rec.get("reason", ""))))
        self.count.setText(f"共 {len(rows)} 条（最多显示最近 200 条）")


# ---------------------------------------------------------------- 帮助

HELP_TEXT = """NetworkClaw 桌面端 使用说明
────────────────────────────────────────────
1. 左侧新建会话，中间对话；顶部切换模型 / 模式；底部输入框回车发送（Shift+Enter 换行）。
2. 三种模式：
   agent     模型自主调用 MCP 工具（查命令模板、知识库、串口/Telnet、识图）
   rag       固定走知识库检索问答，答案更贴近资料
   parallel  同一问题并行交给多个模型，最后融合成一份答案（可配合识图）
3. 图像识别：点「图片」附加拓扑截图；若当前模型不看图（如 DeepSeek），
   程序会先用本地多模态模型识读，再把文字结论交给它。
4. 设备操作安全：只读命令（display/show/ping/tracert）直接放行；
   配置类命令需在对话中明确同意；undo/shutdown/reset/reboot 等一律硬拦，
   全部裁决记录在 logs/command_audit.log，可在「审计」中查看。
5. 「命令」页签支持：
   /help /model [名称] /key sk-xxx /tools /call 工具名 {"参数":"值"}
   /audit [n] /vision /rebuild /probe /rag /agent /parallel [on|off|a,b]
   /image <路径>|clear /export [路径]
────────────────────────────────────────────
"""
