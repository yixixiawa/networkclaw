"""桌面端冒烟测试（离屏运行，不需要显示器、不需要真实模型）。

验证五件事：
1. 主窗口能构建、主题能套用（QT_QPA_PLATFORM=offscreen）
2. 后台线程能完成初始化：加载提供方、检查索引、并行连接 4 个 MCP 服务端并拿到工具清单
3. 命令链路可用：/tools、/vision 能拿到有效结果
4. 流式生成链路可用：能收到逐块回答、思考过程与 token 统计（没有真实模型时
   自动起一个内置「假模型服务」，见 tools/fake_llm_server.py）
5. 单 exe 复用的关键前提成立：能以「launcher.py --serve-mcp <标识>」拉起 MCP 服务端
   并完成握手（打包后就是 exe --serve-mcp，所以这一步必须先过）

用法：
    .venv/Scripts/python.exe tools/gui_smoke_test.py
结果同时写入 logs/gui_smoke_result.txt（本机终端 stdout 常被吞，落文件更可靠）。
"""
from __future__ import annotations

import asyncio
import os
import sys
import time
import traceback
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parent.parent
for extra in (ROOT, ROOT / "tools"):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

RESULT = ROOT / "logs" / "gui_smoke_result.txt"
QUESTION = "用一句话说明 VLAN 的作用"
lines: list[str] = []


def log(text: str) -> None:
    lines.append(text)
    try:
        RESULT.parent.mkdir(parents=True, exist_ok=True)
        RESULT.write_text("\n".join(lines), encoding="utf-8")
    except OSError:
        pass


def probe_environment() -> dict:
    """把运行环境现状记录下来（只报告，不影响结论）"""
    env: dict = {}
    env["python"] = sys.executable
    try:
        import requests

        from core.ollama_interface import OLLAMA_URL

        r = requests.get(f"{OLLAMA_URL}/api/tags", timeout=3)
        tags = [m.get("name") for m in (r.json().get("models") or [])]
        if r.status_code == 200 and any("nomic-embed-text" in (t or "") for t in tags):
            env["ollama"] = True
            log(f"[环境] Ollama：可用，模型 {tags}")
        else:
            env["ollama"] = False
            log(f"[环境] Ollama：在跑但缺少 nomic-embed-text（当前模型 {tags}）；"
                "检索会降级，不影响对话")
    except Exception as e:
        env["ollama"] = False
        log(f"[环境] Ollama：不可用（{type(e).__name__}）；检索会降级，不影响对话")

    from core.llama_start import find_llama_server, find_mmproj, find_model, is_server_running

    log(f"[环境] 主模型：{find_model() or '未找到'}")
    log(f"[环境] llama-server：{find_llama_server() or '未找到'}")
    log(f"[环境] mmproj：{find_mmproj() or '未找到'}")
    env["llama"] = is_server_running()
    log(f"[环境] llama-server 运行中：{env['llama']}")
    return env


def start_fallback_model() -> str:
    """没有真实模型时起一个假模型服务，并为 local 提供方指向它"""
    from fake_llm_server import start_fake_server

    _server, port = start_fake_server()
    os.environ["NETWORKCLAW_LOCAL_BASE_URL"] = f"http://127.0.0.1:{port}/v1"
    note = f"内置假模型服务 127.0.0.1:{port}"
    log(f"[环境] 真实生成测试：使用{note}")
    return note


def check_serve_dispatch() -> bool:
    """验证 MCP 服务端可由 launcher 以 --serve-mcp 拉起（打包模式的核心前提）"""
    from fastmcp import Client
    from fastmcp.client.transports import StdioTransport

    async def _run() -> tuple[bool, str]:
        transport = StdioTransport(
            command=sys.executable,
            args=[str(ROOT / "launcher.py"), "--serve-mcp", "knowledge"],
            cwd=str(ROOT),
            env={**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONPATH": str(ROOT)},
        )
        async with Client(transport) as client:
            tools = await client.list_tools()
            names = sorted(t.name for t in tools)
            return bool(names), f"工具：{', '.join(names)}"

    try:
        ok, detail = asyncio.run(_run())
        log(f"[5] launcher --serve-mcp 派发：{'通过' if ok else '失败'} —— {detail}")
        return ok
    except Exception as e:
        log(f"[5] launcher --serve-mcp 派发：失败 —— {type(e).__name__}: {e}")
        log(traceback.format_exc())
        return False


def main() -> int:
    log(f"==== NetworkClaw GUI 冒烟测试 {time.strftime('%Y-%m-%d %H:%M:%S')} ====")
    env = probe_environment()

    can_ask = bool(os.environ.get("DEEPSEEK_API_KEY")) or env["llama"]
    if can_ask:
        log("[环境] 真实生成测试：使用本机可用提供方")
    else:
        start_fallback_model()

    # ---------------------------------------------------------- 构建窗口
    from PyQt6.QtCore import QTimer
    from PyQt6.QtWidgets import QApplication

    from gui.app import install_excepthook, load_settings
    from gui.main_window import MainWindow
    from gui.theme import build_qss, get_palette

    app = QApplication.instance() or QApplication(["smoke"])
    settings = load_settings()
    settings["capture_stdout"] = False  # 测试时别把 print 转进界面
    settings["provider"] = "local"
    app.setStyleSheet(build_qss(get_palette(settings.get("theme", "dark"))))

    window = MainWindow(settings)
    install_excepthook(window)  # 与正式入口一致：槽里抛异常也不能让进程 abort
    window.show()
    log("[1] 主窗口构建：通过")

    state = {"ready": None, "result": {}, "elapsed": 0, "finished": False,
             "cmd_sent": False, "ask_started": False, "ask_done": None,
             "answer": "", "think": "", "chunks": {"answer": 0, "think": 0, "stats": 0}}

    window.worker.sig_ready.connect(lambda info: state.__setitem__("ready", info))
    window.worker.sig_result.connect(
        lambda name, text: state["result"].__setitem__(name, text))
    window.worker.sig_answer.connect(lambda p: (
        state["chunks"].__setitem__("answer", state["chunks"]["answer"] + 1),
        state.__setitem__("answer_live", state.get("answer_live", "") + p)))
    window.worker.sig_think.connect(lambda p: (
        state["chunks"].__setitem__("think", state["chunks"]["think"] + 1),
        state.__setitem__("think", state.get("think", "") + p)))
    window.worker.sig_stats.connect(
        lambda s: state["chunks"].__setitem__("stats", state["chunks"]["stats"] + 1))
    window.worker.sig_answer_done.connect(
        lambda answer, meta: (state.__setitem__("answer", answer),
                             state.__setitem__("ask_done", meta)))
    window.worker.sig_error.connect(lambda text: log(f"    [错误] {text}"))

    def finish() -> None:
        if state["finished"]:
            return
        state["finished"] = True
        info = state["ready"] or {}
        tools = info.get("tools") or []
        log(f"[2] 初始化：{'通过' if info else '超时未完成'}（等待 {state['elapsed'] / 1000:.1f}s）")
        log(f"    MCP 服务端：{info.get('servers')}；失败：{info.get('failed')}")
        log(f"    工具数：{len(tools)} —— {', '.join(t['name'] for t in tools)}")
        log(f"    提供方：{[p['name'] for p in (info.get('providers') or [])]}")
        services = info.get("services") or {}
        log(f"    服务状态：llama={services.get('llama')} ollama={services.get('ollama')} "
            f"tools={services.get('mcp_tools')} vision={services.get('vision')}")

        results = state["result"]
        ok_cmd = "个 MCP 工具" in results.get("tools", "")
        log(f"[3] 命令链路：{'通过' if ok_cmd else '未取到有效结果'}")
        for name, text in results.items():
            first = (text or "").strip().splitlines()
            log(f"    /{name} → {first[0] if first else '(空)'}")

        joined = (state.get("answer_live") or "").strip()
        ok_ask = bool(state["answer"].strip())
        log(f"[4] 流式生成（{state['chunks']['answer']} 个回答块 / "
            f"{state['chunks']['think']} 个思考块 / {state['chunks']['stats']} 次统计）："
            f"{'通过' if ok_ask else '未拿到回答'}")
        if state["answer"]:
            log(f"    思考过程：{state['think'].strip()[:100]}…")
            log(f"    回答预览：{state['answer'].strip().replace(chr(10), ' ')[:160]}")
            log(f"    流式拼接与最终回答一致：{joined == state['answer'].strip()}")
        log(f"    元信息：{state['ask_done']}")

        state["ok_ask"] = ok_ask
        window.close()

    def poll() -> None:
        """自适应等待：初始化 → 命令 → 真实提问 → 收工（最长 90 秒）"""
        if state["finished"]:
            return
        if state["ready"] is not None and not state["cmd_sent"]:
            state["cmd_sent"] = True
            window.worker.submit("command", name="tools")
            window.worker.submit("command", name="vision")
        if (state["ready"] is not None and state["result"] and not state["ask_started"]):
            state["ask_started"] = True
            log(f"[4] 提交一次提问（rag 模式）：{QUESTION}")
            window.worker.submit("ask", text=QUESTION, mode="rag", provider="local",
                                 parallel=False, show_thinking=True)
        if state["ready"] is not None and state["result"] and state["ask_done"] is not None:
            finish()
            return
        state["elapsed"] += 500
        if state["elapsed"] >= 90000:
            finish()

    poll_timer = QTimer()
    poll_timer.setInterval(500)
    poll_timer.timeout.connect(poll)
    poll_timer.start()
    app.exec()
    poll_timer.stop()

    ok_dispatch = check_serve_dispatch()

    info = state["ready"] or {}
    ok_all = (bool(info) and bool(info.get("tools"))
              and "个 MCP 工具" in state["result"].get("tools", "")
              and bool(state.get("ok_ask"))
              and ok_dispatch)
    log("")
    log(f"==== 结论：{'全部通过' if ok_all else '存在失败项'} ====")
    return 0 if ok_all else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except BaseException:
        log(traceback.format_exc())
        sys.exit(1)
