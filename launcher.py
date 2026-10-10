"""NetworkClaw 统一入口（一份代码，三种身份）。

打包成 exe 后没有可用的 Python 解释器，于是让 exe 学会「复用自身」：
    NetworkClaw.exe                          → 打开桌面应用（GUI，默认）
    NetworkClaw.exe --serve-mcp knowledge    → 当作某个 MCP 服务端进程运行（stdio）
    NetworkClaw.exe --cli [main.py 的参数]    → 以命令行方式运行（等价于 python main.py）
    NetworkClaw.exe --provider deepseek ...   → 未识别的参数一律转给命令行入口

为什么需要 `--serve-mcp`：
    本项目用 MCP（stdio）把「知识检索 / 串口 / Telnet / 图像识别」拆成 4 个子进程。
    源码模式下拉起它们很简单（python mcp_tools/xxx.py），但打包后 sys.executable
    指向 exe 自身，直接拉起会变成「又打开一个 GUI」。因此约定用 `--serve-mcp <标识>`
    让同一个 exe 切到服务端角色，标识 → 模块的映射见 mcp_tools/__init__.py。

打包入口（PyInstaller）指向本文件，而不是 main.py 或 gui/app.py —— 只有这里能
同时容纳上面三种身份。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path


def _bootstrap_import_path() -> None:
    """让 core / mcp_tools 可被导入（源码模式与打包模式都要成立）。

    打包后 PyInstaller 已把包放进 sys.path（_MEIPASS），但**工作目录**可能是任意位置；
    源码模式下则依赖于「以项目根为起点运行」，这里主动兜底，避免 python launcher.py
    从别处启动时找不到 core。
    """
    if getattr(sys, "frozen", False):
        base = Path(sys.executable).resolve().parent
    else:
        base = Path(__file__).resolve().parent
    base_str = str(base)
    if base_str not in sys.path:
        sys.path.insert(0, base_str)


_bootstrap_import_path()

# 导入顺序有讲究：paths 必须先于其他 core 模块（它负责创建目录、修标准流）
from core.paths import (  # noqa: E402
    CLI_FLAG,
    SERVE_FLAG,
    ensure_standard_streams,
    ensure_user_data,
    is_frozen,
)

APP_TITLE = "NetworkClaw"


def _fatal(exc: BaseException) -> int:
    """启动阶段就崩了：写日志 + 尽力弹个提示框（窗口模式下没有控制台可看）"""
    import traceback

    detail = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    log_path = Path("logs") / "launcher_error.log"
    try:
        from core.paths import BASE_DIR

        log_path = BASE_DIR / "logs" / "launcher_error.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text(detail, encoding="utf-8")
    except Exception:
        pass

    sys.stderr.write(detail)
    if os.name == "nt":
        try:
            import ctypes

            ctypes.windll.user32.MessageBoxW(
                None,
                f"NetworkClaw 启动失败：\n\n{type(exc).__name__}: {exc}\n\n"
                f"详细信息已写入：\n{log_path}",
                f"{APP_TITLE} 启动失败",
                0x10,  # MB_ICONERROR
            )
        except Exception:
            pass
    return 1


# ---------------------------------------------------------------- 三种身份

def serve_mcp(name: str) -> int:
    """以 MCP 服务端身份运行（stdio 收发 JSON-RPC）。

    用 runpy 以 `__main__` 名字执行目标模块，等价于 `python mcp_tools/xxx.py`，
    因此各服务端文件底部的 `if __name__ == "__main__": mcp.run()` 无需改动。
    """
    import runpy

    from mcp_tools import SERVERS, module_for

    module = module_for(name)
    if not module:
        sys.stderr.write(
            f"[launcher] 未知的 MCP 服务端：{name!r}；"
            f"可用标识：{', '.join(SERVERS)}\n"
        )
        return 2
    try:
        runpy.run_module(module, run_name="__main__", alter_sys=True)
    except KeyboardInterrupt:
        pass
    return 0


def run_cli(args: list[str]) -> int:
    """命令行身份：参数原样交给 main.py。

    打包成窗口程序时没有控制台，`print` 会落到空处；此时额外把输出同时写进
    `logs/cli_output.log`，否则 `--cli` 会「看起来什么都没发生」。
    """
    import asyncio

    if is_frozen():
        _tee_stdout_to_log()

    sys.argv = [sys.argv[0], *args]
    from main import main as cli_main

    try:
        asyncio.run(cli_main())
    except KeyboardInterrupt:
        pass
    return 0


def _tee_stdout_to_log() -> None:
    """把标准输出同时写一份到日志文件（仅打包模式需要）"""
    from core.paths import BASE_DIR

    log_path = BASE_DIR / "logs" / "cli_output.log"
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        handle = open(log_path, "a", encoding="utf-8", buffering=1)
    except OSError:
        return

    class _Tee:
        def __init__(self, original, sink):
            self._original = original
            self._sink = sink

        def write(self, text):
            try:
                if self._original is not None:
                    self._original.write(text)
            except Exception:
                pass
            try:
                self._sink.write(text)
            except Exception:
                pass
            return len(text or "")

        def flush(self):
            for stream in (self._original, self._sink):
                try:
                    if stream is not None:
                        stream.flush()
                except Exception:
                    pass

        def isatty(self):
            return False

        @property
        def buffer(self):
            return getattr(self._original, "buffer", None)

    sys.stdout = _Tee(sys.stdout, handle)
    sys.stderr = _Tee(sys.stderr, handle)


def run_gui(args: list[str]) -> int:
    """桌面应用身份"""
    from gui.app import run as gui_run

    return gui_run(args)


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)

    # 窗口模式（无控制台）下 Python 会把标准流置为 None：
    # 主程序靠 GUI 显示，但 MCP 服务端子进程必须靠 stdout 收发，所以先修复。
    ensure_standard_streams()
    ensure_user_data()

    # --- 身份派发：顺序即优先级，越靠前越特殊
    if argv and argv[0] == SERVE_FLAG:
        return serve_mcp(argv[1] if len(argv) > 1 else "")

    if argv and argv[0] == CLI_FLAG:
        return run_cli(argv[1:])

    if argv and argv[0] in ("--help", "-h", "--version"):
        _print_usage()
        return 0

    # 无参数 = 双击启动 → GUI；`--gui` 可显式指定，其后参数透传给桌面端
    if not argv or argv[0] in ("--gui", "-g"):
        return run_gui(argv[1:] if argv else [])

    # 其余参数按命令行模式处理（与源码下 `python main.py …` 的习惯一致）
    return run_cli(argv)


def _print_usage() -> None:
    print(f"""{APP_TITLE} 统一入口

用法：
  {APP_TITLE}.exe                              打开桌面应用（GUI）
  {APP_TITLE}.exe --gui [参数…]                 打开桌面应用并指定默认项
  {APP_TITLE}.exe --cli [参数…]                 命令行模式（参数同 main.py）
  {APP_TITLE}.exe --serve-mcp <标识>            以 MCP 服务端身份运行（内部使用）
  {APP_TITLE}.exe --provider deepseek …         参数直接透传给命令行模式

桌面端参数（--gui 之后）：
  --provider local|deepseek-flash|deepseek-pro  默认模型提供方
  --mode agent|rag|parallel                    默认模式
  --parallel-providers local,deepseek          并行模式参与方
  --mmproj [路径]                               启用图像识别（留空自动探测）
  --image 图片路径                              预载拓扑截图
  --no-auto-vision                              关闭启动时的自动拓扑巡检
  --capture-keyword 关键字                      巡检目标窗口关键字（如 vmware）
  --with-search                                接入联网搜索 MCP
  --light / --dark                             主题
  --reset-settings                             忽略上次保存的设置

命令行参数（等价于 python main.py …）：
  --provider / --mode / --parallel / --mmproj / --image / --with-search / --no-thinking

运行环境：
  模型文件      models/（放在程序同目录）
  llama-server  程序同目录 / bin / 环境变量
                {os.environ.get('NETWORKCLAW_LLAMA_SERVER', 'NETWORKCLAW_LLAMA_SERVER')}
  密钥          .env 或 config/llm.json
  Embedding     本机 Ollama（127.0.0.1:11434）需拉取 nomic-embed-text
""")


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except BaseException as e:  # noqa: BLE001 启动期兜底，必须让用户看到原因
        sys.exit(_fatal(e))
