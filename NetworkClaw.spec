# -*- mode: python ; coding: utf-8 -*-
"""NetworkClaw 的 PyInstaller 打包配置。

为什么打包入口是 launcher.py 而不是 main.py / gui.app：
    一份 exe 要能扮演三种身份（GUI / CLI / --serve-mcp 服务端），
    只有 launcher.py 同时认识这三种身份，见 launcher.py 的模块注释。

为什么 MCP 服务端模块必须写进 hiddenimports：
    launcher.serve_mcp() 用 runpy.run_module(动态字符串) 拉起服务端，
    PyInstaller 的静态分析看不见这种导入，漏掉就会出现
    「exe 能打开界面，但知识检索/串口/图像识别全部失效」。

为什么用 onedir（目录形态）做默认而不是 onefile（单文件）：
    主程序会把自身拉起 4~5 次来充当 MCP 服务端子进程。
    onefile 每次拉起都要把 ~300MB 解压到新的临时目录（每个子进程重复一次），
    启动会慢到不可用；onedir 只解一次，子进程秒开。
    确需单文件时设环境变量 NETWORKCLAW_ONEFILE=1 再跑 pyinstaller。

用法：
    .venv\\Scripts\\python.exe -m PyInstaller NetworkClaw.spec --noconfirm
    # 单文件版（不推荐，见上）：
    $env:NETWORKCLAW_ONEFILE = "1"; .venv\\Scripts\\python.exe -m PyInstaller NetworkClaw.spec --noconfirm
"""
from __future__ import annotations

import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_all

# PyInstaller 注入：SPECPATH=spec 所在目录, DISTPATH=dist 输出目录
PROJECT = Path(SPECPATH).resolve()
ONEFILE = os.environ.get("NETWORKCLAW_ONEFILE", "0") == "1"
NAME = "NetworkClaw"

ICON = PROJECT / "assets" / "networkclaw.ico"

# ---------------------------------------------------------------- 内置资源
# 只放「种子资源」：首次运行由 core.paths.ensure_user_data() 释放到 exe 旁边，
# 用户可以随手改；绝不打包 config/llm.json（里面有密钥）与 models/（好几 GB）。
_datas_spec = [
    (PROJECT / "knowledge", "knowledge"),          # 命令模板 CSV + 设备知识
    (PROJECT / "docs", "docs"),                    # 文档
    (PROJECT / "config" / "llm.example.json", "config"),
    (PROJECT / "README.md", "."),
]
if (PROJECT / "assets").is_dir():
    _datas_spec.append((PROJECT / "assets", "assets"))
datas = [[str(src), dst] for src, dst in _datas_spec if Path(src).exists()]

binaries: list = []

# ---------------------------------------------------------------- 隐式导入
hiddenimports = [
    # —— MCP 服务端（runpy 动态拉起，静态分析不可见，必须显式列出）
    "mcp_tools.template_server",
    "mcp_tools.device_server",
    "mcp_tools.telnet_server",
    "mcp_tools.manual_server",
    "mcp_tools.report_server",
    "mcp_tools.topology_server",
    "mcp_tools.vision_server",
    "mcp_tools.internet",
    "mcp_tools.search_client",
    "mcp_tools.client",
    # —— 单工具模块（一个工具一个文件，服务端注册中心里静态 import，
    #     但服务端本身是 runpy 拉起，保险起见逐个列出，避免漏打进包里）
    "mcp_tools.tools._archive",
    "mcp_tools.tools._bootstrap",
    "mcp_tools.tools._manual_common",
    "mcp_tools.tools.analyze_topology_image",
    "mcp_tools.tools.capture_topology",
    "mcp_tools.tools.check_telnet",
    "mcp_tools.tools.classify_command",
    "mcp_tools.tools.create_device_manual",
    "mcp_tools.tools.discover_topology",
    "mcp_tools.tools.exec_command",
    "mcp_tools.tools.exec_telnet_command",
    "mcp_tools.tools.export_workflow_report",
    "mcp_tools.tools.get_topology_snapshot",
    "mcp_tools.tools.list_device_manuals",
    "mcp_tools.tools.list_local_images",
    "mcp_tools.tools.list_report_sessions",
    "mcp_tools.tools.list_serial_ports",
    "mcp_tools.tools.list_session_skills",
    "mcp_tools.tools.load_discovered_topology",
    "mcp_tools.tools.query_command_template",
    "mcp_tools.tools.read_device_manual",
    "mcp_tools.tools.recent_audit",
    "mcp_tools.tools.recent_device_history",
    "mcp_tools.tools.search_knowledge",
    "mcp_tools.tools.topology_mermaid",
    "mcp_tools.tools.topology_summary",
    "mcp_tools.tools.update_device_manual_section",
    "mcp_tools.tools.vision_ready",
    "mcp_tools.tools.workflow_report_overview",
    # —— GUI / CLI（函数内 import 一般能被分析到，这里兜底）
    "gui.app", "gui.main_window", "gui.widgets", "gui.worker", "gui.store",
    "gui.theme", "gui.dialogs",
    "core.net", "core.local_service", "core.device_conn",
    "core.screen_capture", "core.auto_topology", "core.device_registry",
    "core.device_manual", "core.topology_flood", "core.data_report",
    # knowledge 包在 device_manual.skeleton() 里是函数内 try/except 导入，
    # 静态分析看不到；同时 knowledge/ 整体已作为 datas 打进包。
    "knowledge.device_profiles",
    "main", "launcher",
    # —— 依赖链里的动态导入
    "dotenv",
    "serial", "serial.tools", "serial.tools.list_ports",
    "PIL.Image", "PIL.ImageDraw", "PIL.ImageGrab",
    "cv2",                       # 窗口截图的 OpenCV 预处理（screen_capture 内部延迟导入）
    "win32gui", "win32ui", "win32con", "win32api", "win32process",
    "langchain_text_splitters", "langchain_core",
    "ollama", "openai",
]

# 动态导入重灾区：整包收集（子模块 + 数据文件 + 二进制）
for _pkg in ("chromadb", "fastmcp", "mcp", "pydantic", "anyio"):
    try:
        _d, _b, _h = collect_all(_pkg)
        datas += _d
        binaries += _b
        hiddenimports += _h
    except Exception as exc:  # 收集失败不阻塞打包，构建日志会有 Warning 可查
        print(f"[spec] collect_all({_pkg}) 失败，已跳过：{exc}")

# ---------------------------------------------------------------- 排除
# 原则：只排「确定用不到的大块头」。chromadb 对这些全是 try/except 惰性导入
# （已在开发环境模拟 ImportError 验证过，详见 docs/packaging.md）。
excludes = [
    # 本项目不用 llama-index（RAG 走 chromadb + 自研检索）
    "llama_index", "llama_index_core", "llama_index_embeddings_openai",
    "llama_index_instrumentation", "llama_index_llms_openai", "llama_index_workflows",
    # chromadb 分布式/测试专用（单机模式不触达）
    "kubernetes",
    # 嵌入函数可选项（用的是 Ollama 嵌入；onnxruntime 仅默认嵌入惰性引用，省 44MB）
    "onnxruntime", "onnx", "sentence_transformers", "transformers", "torch", "torchvision",
    "open_clip", "fastembed", "instructor", "cohere", "voyageai", "mistralai",
    "roboflow", "baseten", "databricks", "chromadb.db.impl.grpc",
    # 其他云 SDK
    "boto3", "botocore", "google.cloud", "google.generativeai",
    # 与本项目无关的常见大件
    "tkinter", "matplotlib", "IPython", "pytest", "notebook", "jupyter",
    "pandas", "nltk", "tokenizers", "huggingface_hub", "llama_cpp",
    "setuptools", "pip", "wheel", "distutils",
]

# 分析中的二进制依赖（pywin32 的 DLL 等）保持默认收集；上面排掉的包若携带 DLL，
# PyInstaller 会按 excludes 一并跳过。

a = Analysis(
    [str(PROJECT / "launcher.py")],
    pathex=[str(PROJECT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
    optimize=1,
)

pyz = PYZ(a.pure)

if ONEFILE:
    exe = EXE(
        pyz,
        a.scripts,
        a.binaries,
        a.datas,
        [],
        name=NAME,
        icon=str(ICON) if ICON.is_file() else None,
        console=False,          # 窗口程序；--cli/--serve-mcp 的流已在代码内兜底
        disable_windowed_traceback=False,
        upx=False,              # UPX 压缩易触发杀软误报，且收益有限
        exclude_binaries=False,
    )
else:
    exe = EXE(
        pyz,
        a.scripts,
        [],
        exclude_binaries=True,
        name=NAME,
        icon=str(ICON) if ICON.is_file() else None,
        console=False,
        disable_windowed_traceback=False,
        upx=False,
    )
    coll = COLLECT(
        exe,
        a.binaries,
        a.datas,
        strip=False,
        upx=False,
        name=NAME,
    )
