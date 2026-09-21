"""路径与运行环境适配层：让同一套代码既能在源码目录里跑，也能在打包成 exe 后跑。

为什么要单独一层：
    打包（PyInstaller）后 `__file__` 指向的是解包出来的临时目录（onefile 时更是每次
    都不同的临时目录），如果各模块继续用 `Path(__file__).parent.parent` 当项目根，
    就会出现「模型找不到」「索引写进临时目录、重启就没了」这类问题。

因此把「路径」拆成两个概念，全项目统一从这里取：

    BASE_DIR      可写工作目录（用户数据所在）
                  - 源码运行：项目根目录
                  - 打包运行：exe 所在目录（用户把 models/ 放在 exe 旁边即可）
                  用于：models/、data/、logs/、config/llm.json、.env

    RESOURCE_DIR  只读资源目录（随程序一起被塞进 exe 的静态文件）
                  - 源码运行：项目根目录
                  - 打包运行：PyInstaller 解包目录（sys._MEIPASS）
                  用于：knowledge/ 里的初始数据、config/llm.example.json、docs/

    首次运行时 `ensure_user_data()` 会把 RESOURCE_DIR 里的「种子文件」复制到
    BASE_DIR，这样用户拿到的 exe 旁边会自动出现可编辑的 knowledge/ 与 config/，
    而不是一堆只能看不能改的内嵌文件。

另外这里还统一了「外部可执行文件」的查找（llama-server.exe）与模型文件探测，
使得打包后的程序不必依赖开发机上写死的绝对路径。
"""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

# ---------------------------------------------------------------- 运行形态

# 冻结（打包）后由 launcher 用这个参数把自己当成 MCP 服务端进程来跑
SERVE_FLAG = "--serve-mcp"
CLI_FLAG = "--cli"


def is_frozen() -> bool:
    """是否运行在 PyInstaller 打包出的可执行文件里"""
    return bool(getattr(sys, "frozen", False))


def app_dir() -> Path:
    """可写工作目录（用户数据目录）"""
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def resource_dir() -> Path:
    """只读资源目录（打包内置文件的解包位置）"""
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return Path(meipass)
    return Path(__file__).resolve().parent.parent


BASE_DIR = app_dir()
RESOURCE_DIR = resource_dir()

# 首次运行需要释放到 BASE_DIR 的种子资源（相对路径；存在则不覆盖，保护用户改动）
SEED_FILES: tuple[str, ...] = (
    "knowledge/command_templates.csv",
    "knowledge/huawei_devices_introduce.txt",
    "config/llm.example.json",
    "docs/phase3_extraction_plan.md",
    "README.md",
)


def ensure_user_data(verbose: bool = False) -> list[Path]:
    """把内置的种子资源释放到工作目录（仅缺失时复制），返回本次新写出的文件。

    设计成幂等：已经存在的文件绝不覆盖，用户改过的内容不会被升级覆盖掉。
    """
    written: list[Path] = []
    if RESOURCE_DIR == BASE_DIR:
        return written  # 源码模式：本来就是同一个目录
    for rel in SEED_FILES:
        src = RESOURCE_DIR / rel
        dst = BASE_DIR / rel
        if not src.is_file() or dst.exists():
            continue
        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            written.append(dst)
            if verbose:
                print(f"[初始化] 已释放 {rel} → {dst}")
        except OSError as e:  # 只读目录等情况：不影响运行，只提示
            if verbose:
                print(f"[初始化] 释放 {rel} 失败：{type(e).__name__}: {e}")
    for sub in ("logs", "data", "models"):
        try:
            (BASE_DIR / sub).mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
    return written


# 冻结模式：任何进程（主程序 / MCP 服务端子进程）导入本模块时就保证目录齐全
if is_frozen():
    try:
        ensure_user_data()
    except Exception:
        pass


# ---------------------------------------------------------------- 标准流修复

def ensure_standard_streams() -> None:
    """打包成窗口程序（无控制台）时修复 sys.stdin/stdout/stderr。

    窗口模式（PyInstaller --windowed）下 Python 拿不到控制台，会把这三个流设为
    None；而 MCP 服务端要通过 stdout 收发 JSON-RPC、日志代码会直接 write，
    一旦是 None 就会抛 AttributeError。这里用文件描述符重新包一层：
    - MCP 子进程由父进程用管道拉起，fd 0/1/2 有效 → 恢复正常收发
    - 双击启动的 GUI 进程 fd 无效 → 退化为 devnull，程序照常运行
    """
    for fd, name, mode in ((0, "stdin", "r"), (1, "stdout", "w"), (2, "stderr", "w")):
        stream = getattr(sys, name, None)
        if stream is not None:
            continue
        target = None
        try:
            target = open(fd, mode, encoding="utf-8", errors="replace",
                          buffering=1, closefd=False)
        except OSError:
            try:
                target = open(os.devnull, mode, encoding="utf-8")
            except OSError:
                continue
        setattr(sys, name, target)


# ---------------------------------------------------------------- 外部程序查找

LLAMA_SERVER_ENV = "NETWORKCLAW_LLAMA_SERVER"

# llama-server.exe 的候选位置（按优先级）：环境变量 > exe 同级 > 常见子目录 > 开发机 winget 安装位置
_LLAMA_SERVER_FALLBACKS: tuple[str, ...] = (
    "llama-server.exe",
    "bin/llama-server.exe",
    "tools/llama-server.exe",
    "llama.cpp/llama-server.exe",
    r"C:\Users\yixixiawa\AppData\Local\Microsoft\WinGet\Packages"
    r"\ggml.llamacpp_Microsoft.Winget.Source_8wekyb3d8bbwe\llama-server.exe",
)


def find_llama_server() -> Path | None:
    """定位 llama-server 可执行文件（打包后不再依赖开发机硬编码路径）"""
    candidates: list[Path] = []
    env = os.environ.get(LLAMA_SERVER_ENV)
    if env:
        candidates.append(Path(env).expanduser())
    for rel in _LLAMA_SERVER_FALLBACKS:
        p = Path(rel)
        candidates.append(p if p.is_absolute() else BASE_DIR / rel)

    seen: set[str] = set()
    for c in candidates:
        key = str(c).lower()
        if key in seen:
            continue
        seen.add(key)
        if c.is_file():
            return c
    return None


def llama_server_path() -> str:
    """返回 llama-server 路径字符串；找不到时仍返回首选名（由调用方给出可读报错）"""
    found = find_llama_server()
    if found is not None:
        return str(found)
    return str(Path(_LLAMA_SERVER_FALLBACKS[0]))


def human_size(num_bytes: float) -> str:
    """把字节数格式化成可读字符串（GUI 里显示模型大小用）"""
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(num_bytes) < 1024 or unit == "TB":
            return f"{num_bytes:.0f} {unit}" if unit == "B" else f"{num_bytes:.1f} {unit}"
        num_bytes /= 1024.0
    return f"{num_bytes:.1f} TB"
