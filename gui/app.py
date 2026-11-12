"""桌面应用入口：创建 QApplication、载入配置与主题、打开主窗口。

被两种方式调用：
    - 双击打包后的 exe（launcher.py 无参数 → GUI）
    - 源码运行：python -m gui.app  或  python launcher.py

可选启动参数（与命令行入口保持一致的语义）：
    --provider local|deepseek-flash|deepseek-pro   指定默认提供方
    --mode agent|plan|parallel                   指定默认模式
    --parallel-providers local,deepseek           并行模式参与方
    --mmproj [路径]                                启用图像识别（留空自动探测）
    --image 图片路径                               预载拓扑截图（可多次）
    --with-search                                 接入联网搜索 MCP
    --no-thinking                                 默认不显示思考过程
    --light / --dark                              指定主题
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QApplication

from core.paths import BASE_DIR, RESOURCE_DIR, ensure_user_data
from gui.theme import build_qss, get_palette

SETTINGS_DEFAULTS: dict = {
    "provider": None,
    "mode": "agent",
    "parallel_providers": "",
    "mmproj": None,
    "with_search": False,
    "show_thinking": True,
    "max_rounds": 4,
    "theme": "dark",
    "capture_stdout": True,
    "auto_vision": True,       # 启动时自动巡检拓扑（截取 eNSP/虚拟机窗口并识读）
    "capture_keyword": "",     # 巡检目标窗口关键字（空 = 按内置关键字表匹配）
}


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="NetworkClaw", add_help=True,
                                     description="NetworkClaw 桌面端")
    parser.add_argument("--provider", default=None)
    parser.add_argument("--mode", choices=["agent", "plan", "parallel"], default=None)
    parser.add_argument("--parallel-providers", default=None)
    parser.add_argument("--mmproj", nargs="?", const="auto", default=None)
    parser.add_argument("--image", action="append", default=[])
    parser.add_argument("--with-search", action="store_true")
    parser.add_argument("--no-thinking", action="store_true")
    parser.add_argument("--theme", choices=["dark", "light"], default=None)
    parser.add_argument("--dark", action="store_true")
    parser.add_argument("--light", action="store_true")
    parser.add_argument("--no-auto-vision", action="store_true",
                        help="关闭启动时的自动拓扑巡检（默认开启）")
    parser.add_argument("--capture-keyword", default=None, metavar="关键字",
                        help="自动巡检的目标窗口关键字（如 vmware / ensp）")
    parser.add_argument("--reset-settings", action="store_true",
                        help="忽略上次保存的设置，使用默认值启动")
    return parser.parse_args(argv)


def load_settings(reset: bool = False) -> dict:
    """读取上次保存的界面设置（QSettings：Windows 下存注册表，跨用户配置不污染项目目录）"""
    from PyQt6.QtCore import QSettings

    settings = dict(SETTINGS_DEFAULTS)
    if not reset:
        raw = QSettings("NetworkClaw", "Desktop").value("settings")
        if raw:
            try:
                saved = json.loads(raw)
                if isinstance(saved, dict):
                    settings.update({k: v for k, v in saved.items()
                                     if k in SETTINGS_DEFAULTS})
            except (json.JSONDecodeError, TypeError):
                pass
    return settings


def _app_icon() -> QIcon | None:
    for rel in ("assets/networkclaw.ico", "assets/networkclaw.png"):
        for base in (BASE_DIR, RESOURCE_DIR):
            p = base / rel
            if p.is_file():
                return QIcon(str(p))
    return None


def install_excepthook(window=None) -> None:
    """安装全局异常兜底，避免「槽函数里一个异常 → 整个界面进程被干掉」。

    PyQt 对未处理异常有一套很激进的默认行为：默认 excepthook 下会直接终止进程
    （Windows 上表现为 0xC0000409 静默崩溃，用户什么提示都看不到）。实测只要把
    sys.excepthook 换成自己的实现且不重新抛出，事件循环就会继续跑下去。

    这里做两件事：完整堆栈落盘到 logs/gui_error.log；摘要显示到界面运行日志。
    """
    import datetime
    import traceback

    def hook(exc_type, exc, tb):
        detail = "".join(traceback.format_exception(exc_type, exc, tb))
        try:
            path = BASE_DIR / "logs" / "gui_error.log"
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "a", encoding="utf-8") as f:
                f.write(f"\n==== {datetime.datetime.now():%Y-%m-%d %H:%M:%S} ====\n{detail}")
        except OSError:
            pass
        try:
            if window is not None:
                window._append_log(f"\n[界面异常] {exc_type.__name__}: {exc}\n{detail}\n")
        except Exception:
            pass
        try:
            sys.stderr.write(detail)
        except Exception:
            pass

    sys.excepthook = hook


def run(argv: list[str] | None = None) -> int:
    args = parse_args(list(argv if argv is not None else sys.argv[1:]))
    ensure_user_data(verbose=True)

    app = QApplication.instance() or QApplication([sys.argv[0] if sys.argv else "NetworkClaw"])
    app.setApplicationName("NetworkClaw")
    app.setApplicationDisplayName("NetworkClaw")
    app.setOrganizationName("NetworkClaw")
    icon = _app_icon()
    if icon is not None:
        app.setWindowIcon(icon)

    settings = load_settings(reset=args.reset_settings)
    # 用户级配置里的激活模型优先（%USERPROFILE%\.networkclaw\networkclaw.json）：
    # 上次退出前用的模型，重启后原样还原；命令行 --provider 仍然最高优先。
    if not args.provider:
        try:
            from core import user_config

            saved_model = user_config.get_active_model()
        except Exception:  # noqa: BLE001  用户配置读不出就按默认走
            saved_model = ""
        if saved_model:
            settings["provider"] = saved_model
    # 命令行参数只影响「本次运行」，不写回设置
    if args.provider:
        settings["provider"] = args.provider
    if args.mode:
        settings["mode"] = args.mode
    if args.parallel_providers:
        settings["parallel_providers"] = args.parallel_providers
        settings["mode"] = "parallel"
    if args.mmproj:
        settings["mmproj"] = "" if args.mmproj == "auto" else args.mmproj
    if args.with_search:
        settings["with_search"] = True
    if args.no_thinking:
        settings["show_thinking"] = False
    if args.dark:
        settings["theme"] = "dark"
    if args.light:
        settings["theme"] = "light"
    if args.theme:
        settings["theme"] = args.theme
    if args.no_auto_vision:
        settings["auto_vision"] = False
    if args.capture_keyword is not None:
        settings["capture_keyword"] = args.capture_keyword

    app.setStyleSheet(build_qss(get_palette(settings.get("theme", "dark"))))

    from gui.main_window import MainWindow

    window = MainWindow(settings)
    if icon is not None:
        window.setWindowIcon(icon)
    install_excepthook(window)
    window.show()

    # --image 预载图片（在窗口显示后投递，确保附件栏已建好）
    images = [str(Path(p).expanduser()) for p in (args.image or [])]
    images = [p for p in images if Path(p).is_file()]
    if images:
        window._add_images(images)

    return app.exec()


if __name__ == "__main__":
    sys.exit(run())
