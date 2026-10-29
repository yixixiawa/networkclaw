"""界面主题：配色与全局 QSS。

风格取向（参考 CodeX / KUN 这类桌面 Agent 工具）：
- 左侧深色侧边栏 + 右侧内容区，层级用「背景深浅 + 1px 描边」区分，不用重投影
- 主色单一（蓝），强调色仅用于状态点与流式光标；正文与次要文字拉开对比
- 圆角统一 8px，控件高度统一，避免花哨的渐变与阴影

深浅两套配色都从这里出，切换主题只换 palette 重建 QSS，不改任何业务代码。
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Palette:
    name: str

    bg: str            # 窗口背景
    sidebar: str       # 侧边栏背景
    panel: str         # 面板/卡片
    elevated: str      # 悬浮/输入框
    border: str        # 描边
    border_strong: str

    text: str          # 主文字
    text_dim: str      # 次要文字
    text_faint: str    # 更弱的提示

    accent: str        # 主色
    accent_hover: str
    accent_text: str   # 主色上的文字

    user_bubble: str   # 用户消息气泡
    ai_bubble: str     # 助手消息气泡
    think_bubble: str  # 思考过程块

    ok: str
    warn: str
    err: str
    code_bg: str


DARK = Palette(
    name="dark",
    bg="#0f1117",
    sidebar="#14161f",
    panel="#171a24",
    elevated="#1e2230",
    border="#262b3a",
    border_strong="#333a4d",
    text="#e7e9f0",
    text_dim="#9aa3b8",
    text_faint="#6b7488",
    accent="#4c8dff",
    accent_hover="#6ba0ff",
    accent_text="#ffffff",
    user_bubble="#1d2740",
    ai_bubble="#171a24",
    think_bubble="#151a26",
    ok="#31c48d",
    warn="#e8b339",
    err="#f2606a",
    code_bg="#11141c",
)

LIGHT = Palette(
    name="light",
    bg="#ffffff",        # 主内容区纯白（白色主题为主）
    sidebar="#f2f3f6",   # 侧边栏浅灰，仅用于区分层级
    panel="#ffffff",
    elevated="#f4f5f8",
    border="#e3e6ec",
    border_strong="#c9ced9",
    text="#1c1f26",
    text_dim="#5b6376",
    text_faint="#8d94a4",
    accent="#2563eb",
    accent_hover="#3b7bf0",
    accent_text="#ffffff",
    user_bubble="#e3ecff",
    ai_bubble="#ffffff",
    think_bubble="#f1f3f8",
    ok="#0f9d58",
    warn="#b7791f",
    err="#d93a45",
    code_bg="#f6f7f9",
)

PALETTES = {"dark": DARK, "light": LIGHT}


def get_palette(name: str) -> Palette:
    return PALETTES.get((name or "").lower(), DARK)


def build_qss(p: Palette) -> str:
    """按配色生成全局 QSS"""
    return f"""
* {{ outline: none; }}

QWidget {{
    background: {p.bg};
    color: {p.text};
    font-family: "Microsoft YaHei UI", "Microsoft YaHei", "Segoe UI", sans-serif;
    font-size: 13px;
}}

QToolTip {{
    background: {p.elevated};
    color: {p.text};
    border: 1px solid {p.border_strong};
    padding: 4px 8px;
}}

/* ---------------------------------------------------------------- 侧边栏 */
#Sidebar {{
    background: {p.sidebar};
    border-right: 1px solid {p.border};
}}
#SidebarTitle {{
    color: {p.text_dim};
    font-size: 12px;
    font-weight: 600;
    padding: 4px 4px 2px 4px;
    letter-spacing: 0.5px;
}}
#AppTitle {{
    font-size: 16px;
    font-weight: 700;
    color: {p.text};
}}
#AppSubtitle {{
    font-size: 11px;
    color: {p.text_faint};
}}

QListWidget#SessionList {{
    background: transparent;
    border: none;
    padding: 2px;
}}
QListWidget#SessionList::item {{
    padding: 7px 9px;
    border-radius: 6px;
    color: {p.text_dim};
    margin: 1px 2px;
}}
QListWidget#SessionList::item:hover {{
    background: {p.elevated};
    color: {p.text};
}}
QListWidget#SessionList::item:selected {{
    background: {p.user_bubble};
    color: {p.text};
}}

/* ---------------------------------------------------------------- 按钮 */
QPushButton {{
    background: {p.elevated};
    color: {p.text};
    border: 1px solid {p.border};
    border-radius: 6px;
    padding: 6px 12px;
    min-height: 16px;
}}
QPushButton:hover {{ border-color: {p.border_strong}; background: {p.panel}; }}
QPushButton:pressed {{ background: {p.bg}; }}
QPushButton:disabled {{ color: {p.text_faint}; border-color: {p.border}; background: {p.panel}; }}

QPushButton#Primary {{
    background: {p.accent};
    color: {p.accent_text};
    border: 1px solid {p.accent};
    font-weight: 600;
}}
QPushButton#Primary:hover {{ background: {p.accent_hover}; border-color: {p.accent_hover}; }}
QPushButton#Primary:disabled {{ background: {p.border}; border-color: {p.border}; color: {p.text_faint}; }}

QPushButton#IconButton {{
    background: transparent;
    border: 1px solid transparent;
    padding: 4px 8px;
    color: {p.text_dim};
    font-size: 14px;
}}
QPushButton#IconButton:hover {{ background: {p.elevated}; color: {p.text}; }}

QPushButton#Ghost {{
    background: transparent;
    border: 1px solid {p.border};
    color: {p.text_dim};
}}
QPushButton#Ghost:hover {{ color: {p.text}; border-color: {p.border_strong}; }}

QPushButton#Chip {{
    background: {p.elevated};
    border: 1px solid {p.border};
    border-radius: 12px;
    padding: 3px 10px;
    color: {p.text_dim};
    font-size: 12px;
}}

/* ---------------------------------------------------------------- 输入类 */
QComboBox, QLineEdit, QSpinBox, QDoubleSpinBox, QPlainTextEdit, QTextEdit {{
    background: {p.elevated};
    border: 1px solid {p.border};
    border-radius: 6px;
    padding: 5px 8px;
    color: {p.text};
    selection-background-color: {p.accent};
    selection-color: {p.accent_text};
}}
QComboBox:hover, QLineEdit:hover, QPlainTextEdit:hover, QTextEdit:hover {{
    border-color: {p.border_strong};
}}
QComboBox::drop-down {{ border: none; width: 18px; }}
QComboBox QAbstractItemView {{
    background: {p.panel};
    border: 1px solid {p.border_strong};
    selection-background-color: {p.user_bubble};
    selection-color: {p.text};
    padding: 3px;
}}

QPlainTextEdit#Input {{
    background: {p.elevated};
    border: 1px solid {p.border};
    border-radius: 8px;
    padding: 8px 10px;
    font-size: 13px;
}}

/* ---------------------------------------------------------------- 标签页 */
QTabWidget::pane {{
    border: none;
    border-top: 1px solid {p.border};
    background: {p.bg};
}}
QTabBar::tab {{
    background: transparent;
    color: {p.text_dim};
    padding: 8px 16px;
    border: none;
    border-bottom: 2px solid transparent;
    margin-right: 2px;
}}
QTabBar::tab:hover {{ color: {p.text}; }}
QTabBar::tab:selected {{
    color: {p.text};
    border-bottom: 2px solid {p.accent};
    font-weight: 600;
}}

/* ---------------------------------------------------------------- 滚动条 */
QScrollArea {{ border: none; background: transparent; }}
QScrollBar:vertical {{
    background: transparent; width: 10px; margin: 2px;
}}
QScrollBar::handle:vertical {{
    background: {p.border_strong}; border-radius: 5px; min-height: 28px;
}}
QScrollBar::handle:vertical:hover {{ background: {p.text_faint}; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: {p.border_strong}; border-radius: 5px; min-width: 28px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

/* ---------------------------------------------------------------- 消息气泡 */
#MsgHeader {{ color: {p.text_faint}; font-size: 11px; }}
#MsgBody {{
    background: transparent;
    font-size: 13px;
    line-height: 150%;
}}
#BubbleUser {{
    background: {p.user_bubble};
    border: 1px solid {p.border};
    border-radius: 10px;
}}
#BubbleAI {{
    background: {p.ai_bubble};
    border: 1px solid {p.border};
    border-radius: 10px;
}}
#ThinkBox {{
    background: {p.think_bubble};
    border: 1px solid {p.border};
    border-radius: 8px;
    color: {p.text_dim};
    font-size: 12px;
}}

/* ---------------------------------------------------------------- 状态与杂项 */
#TopBar {{
    background: {p.panel};
    border-bottom: 1px solid {p.border};
}}
#Card {{
    background: {p.panel};
    border: 1px solid {p.border};
    border-radius: 8px;
}}
#Hint {{ color: {p.text_faint}; font-size: 12px; }}
#StatusDot {{ font-size: 14px; }}
#Divider {{ background: {p.border}; max-height: 1px; min-height: 1px; }}

QStatusBar {{
    background: {p.panel};
    border-top: 1px solid {p.border};
    color: {p.text_dim};
}}
QStatusBar::item {{ border: none; }}

QSplitter::handle {{ background: {p.border}; }}
QSplitter::handle:horizontal {{ width: 1px; }}
QSplitter::handle:hover {{ background: {p.accent}; }}

QMenu {{
    background: {p.panel};
    border: 1px solid {p.border_strong};
    padding: 4px;
}}
QMenu::item {{ padding: 6px 22px 6px 12px; border-radius: 5px; }}
QMenu::item:selected {{ background: {p.user_bubble}; color: {p.text}; }}

QCheckBox, QRadioButton {{ spacing: 6px; }}
QCheckBox::indicator, QRadioButton::indicator {{
    width: 14px; height: 14px;
    border: 1px solid {p.border_strong};
    border-radius: 3px;
    background: {p.elevated};
}}
QCheckBox::indicator:checked {{
    background: {p.accent};
    border-color: {p.accent};
}}
QRadioButton::indicator {{ border-radius: 7px; }}

QGroupBox {{
    border: 1px solid {p.border};
    border-radius: 8px;
    margin-top: 12px;
    padding: 12px 10px 10px 10px;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 4px;
    color: {p.text_dim};
    font-weight: 600;
}}

QListWidget, QTableWidget {{
    background: {p.panel};
    border: 1px solid {p.border};
    border-radius: 6px;
}}
QTableWidget::item {{ padding: 4px; }}
QHeaderView::section {{
    background: {p.elevated};
    color: {p.text_dim};
    border: none;
    border-bottom: 1px solid {p.border};
    padding: 5px 6px;
}}

QProgressBar {{
    background: {p.elevated};
    border: 1px solid {p.border};
    border-radius: 5px;
    height: 8px;
    text-align: center;
}}
QProgressBar::chunk {{ background: {p.accent}; border-radius: 4px; }}
"""
