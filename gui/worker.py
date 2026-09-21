"""后台工作线程：把 asyncio 事件循环与常驻 MCP 连接封进一个 QThread。

为什么必须这么做：
    - Qt 的界面只能在主线程碰；而模型调用（requests 阻塞）与 MCP 通信（asyncio）
      都不能在界面线程里跑，否则窗口直接卡死。
    - MCP 服务端是 4 个常驻子进程，**不能每问一句就重连一次**（每次都要重新拉起
      4 个进程，代价极高），所以这里让一个线程长期持有事件循环与 McpHub。

结构：
    GUI 线程  --submit(Job)-->  线程安全队列  --call_soon_threadsafe 唤醒-->
    工作线程的事件循环  --处理任务-->  通过 Qt 信号把结果回传 GUI（跨线程自动排队）

任务类型（Job.kind）：
    ask          一次提问（agent / rag / parallel 三种模式）
    command      控制台命令（tools / call / audit / vision / rebuild / probe / …）
    start_local  启动本地 llama-server
    stop_local   关闭本地 llama-server
    set_provider 切换提供方
    set_key      设置 DeepSeek API Key
    services     刷新服务状态快照
    shutdown     退出（关闭 MCP 连接、回收自己拉起的本地服务）

流式输出的两种通道（缺一不可）：
    1. 模型 token 走 on_think / on_answer 回调 → sig_think / sig_answer（打字机效果）
    2. 其余 print（检索过程、工具调用、警告）走 GUI 的 stdout 重定向 → 运行日志页签
"""
from __future__ import annotations

import asyncio
import contextlib
import os
import queue
import time
import traceback
from dataclasses import dataclass, field

from PyQt6.QtCore import QThread, pyqtSignal

from core.agent import run_agent
from core.llama_start import find_mmproj, is_server_running
from core.llm_client import ChatResult, ProviderError, set_stats_hook
from core.local_service import LocalService
from core.ollama_interface import check_embedder
from core.parallel import run_multimodal_parallel
from core.providers import (
    active_name,
    configured_providers,
    describe_table,
    get_provider,
    list_providers,
    load_env_file,
    load_providers,
    probe,
    set_active,
)
from core.rag import ask as rag_ask
from core.rag import build_index as build_knowledge_index
from core.template_search import build_index as build_template_index
from core.vision import describe_images, vision_status
from mcp_tools.client import DEFAULT_SERVERS, SEARCH_SERVER, McpHub


@dataclass
class Job:
    kind: str
    payload: dict = field(default_factory=dict)


def provider_summary() -> list[dict]:
    """提供方摘要（供界面下拉框与设置页展示）"""
    out: list[dict] = []
    for p in __import__("core.providers", fromlist=["list_providers"]).list_providers():
        out.append({
            "name": p.name,
            "label": p.label,
            "kind": p.kind,
            "model": p.model,
            "vision": bool(p.supports_vision),
            "tools": bool(p.supports_tools),
            "thinking": bool(p.supports_thinking),
            "configured": bool(p.is_configured),
            "needs_key": bool(p.needs_key),
            "key_env": p.api_key_env,
            "note": p.note,
        })
    return out


class AgentWorker(QThread):
    """常驻后台线程（GUI 只通过信号与它交互）"""

    sig_log = pyqtSignal(str)                 # 运行日志（含被重定向的 print）
    sig_state = pyqtSignal(str)               # 状态栏文字
    sig_ready = pyqtSignal(dict)              # 初始化完成（工具清单/提供方/服务状态）
    sig_think = pyqtSignal(str)               # 思考片段
    sig_answer = pyqtSignal(str)              # 回答片段
    sig_output_begin = pyqtSignal(str)        # "think" | "answer"：新一段输出开始
    sig_answer_done = pyqtSignal(str, dict)   # 最终回答 + 元信息
    sig_stats = pyqtSignal(dict)              # 一次生成的 token 统计
    sig_error = pyqtSignal(str)
    sig_busy = pyqtSignal(bool)
    sig_result = pyqtSignal(str, str)         # (命令名, 文本结果) → 控制台
    sig_services = pyqtSignal(dict)           # 服务状态快照
    sig_providers = pyqtSignal(list)          # 提供方列表

    def __init__(self, options: dict | None = None, parent=None):
        super().__init__(parent)
        self.options = dict(options or {})
        self._inbox: queue.Queue[Job] = queue.Queue()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._wake: asyncio.Event | None = None
        self._done: asyncio.Event | None = None
        self._hub: McpHub | None = None
        self._local = LocalService(self.options.get("mmproj"))
        self._history: list[dict] = []
        self._last_answer = ""
        self._stats_total = {"output_tokens": 0, "think": 0, "answer": 0}
        self.booted = False

    # ------------------------------------------------------------ 对外接口
    def submit(self, kind: str, **payload) -> None:
        """从 GUI 线程投递一个任务"""
        self._inbox.put(Job(kind, payload))
        loop, wake = self._loop, self._wake
        if loop is not None and wake is not None:
            with contextlib.suppress(RuntimeError):
                loop.call_soon_threadsafe(wake.set)

    def stop(self) -> None:
        """请求退出（幂等）"""
        self.submit("shutdown")
        loop, done = self._loop, self._done
        if loop is not None and done is not None:
            with contextlib.suppress(RuntimeError):
                loop.call_soon_threadsafe(done.set)

    @property
    def last_answer(self) -> str:
        return self._last_answer

    @property
    def history(self) -> list[dict]:
        return self._history

    # ------------------------------------------------------------ 线程主体
    def run(self) -> None:
        try:
            asyncio.run(self._main())
        except Exception as e:  # 线程级异常：报给界面，不要静默死掉
            self.sig_error.emit(f"后台线程异常退出：{type(e).__name__}: {e}")
            self.sig_log.emit(traceback.format_exc())
        finally:
            set_stats_hook(None)
            self.sig_state.emit("已停止")

    async def _main(self) -> None:
        self._loop = asyncio.get_running_loop()
        self._wake = asyncio.Event()
        self._done = asyncio.Event()
        set_stats_hook(self._on_stats)

        pump = asyncio.create_task(self._pump())
        try:
            await self._boot()
        except Exception as e:
            self.sig_error.emit(f"初始化失败：{type(e).__name__}: {e}")
            self.sig_log.emit(traceback.format_exc())
            self.sig_state.emit("初始化失败（仍可尝试提问）")
            self.booted = True

        await self._done.wait()
        pump.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await pump
        await self._teardown()

    async def _pump(self) -> None:
        assert self._wake is not None
        while True:
            await self._wake.wait()
            self._wake.clear()
            while True:
                try:
                    job = self._inbox.get_nowait()
                except queue.Empty:
                    break
                if job.kind == "shutdown":
                    if self._done is not None:
                        self._done.set()
                    return
                try:
                    await self._handle(job)
                except Exception as e:
                    self.sig_error.emit(f"{type(e).__name__}: {e}")
                    self.sig_log.emit(traceback.format_exc())

    async def _handle(self, job: Job) -> None:
        if job.kind == "ask":
            await self._ask(job.payload)
        elif job.kind == "command":
            await self._command(job.payload)
        elif job.kind == "set_provider":
            self._set_provider(job.payload.get("name", ""))
        elif job.kind == "set_key":
            self._set_key(job.payload.get("key", ""))
        elif job.kind == "start_local":
            await self._start_local(bool(job.payload.get("vision")))
        elif job.kind == "stop_local":
            await asyncio.to_thread(self._local.stop)
            await self._emit_services()
        elif job.kind == "reload_providers":
            load_providers(refresh=True)
            self.sig_providers.emit(provider_summary())
        else:
            self.sig_log.emit(f"[警告] 未知任务：{job.kind}")

    # ------------------------------------------------------------ 初始化
    async def _boot(self) -> None:
        self.sig_state.emit("加载模型提供方配置…")
        await asyncio.to_thread(load_env_file)
        load_providers(refresh=True)
        if self.options.get("deepseek_key"):
            os.environ["DEEPSEEK_API_KEY"] = str(self.options["deepseek_key"]).strip()
            load_providers(refresh=True)
        if self.options.get("provider"):
            with contextlib.suppress(KeyError):
                set_active(self.options["provider"])
        self.sig_log.emit(describe_table(active=active_name()))
        self.sig_providers.emit(provider_summary())

        self.sig_state.emit("检查知识库索引…")
        try:
            count = await asyncio.to_thread(build_knowledge_index)
            self.sig_log.emit(f"知识库索引就绪（{count} 个文本块）")
        except Exception as e:
            self.sig_log.emit(f"[警告] 知识库索引不可用：{e}")
            self.sig_log.emit("[警告] 检索类工具会返回错误说明，但不影响对话；"
                              "修复 Ollama 后重启本程序即可")

        self.sig_state.emit("连接 MCP 服务端…")
        servers = dict(DEFAULT_SERVERS)
        if self.options.get("with_search"):
            servers.update(SEARCH_SERVER)
        self._hub = McpHub(servers)
        await self._hub.__aenter__()
        self.sig_log.emit(f"MCP 服务端已连接：{', '.join(self._hub.connected_servers) or '无'}")
        if self._hub.failed_servers:
            self.sig_log.emit(f"[警告] MCP 连接失败：{', '.join(self._hub.failed_servers)}")
        self.sig_log.emit(self._hub.describe_tools())

        self.booted = True
        self.sig_ready.emit({
            "tools": [{"name": t["name"], "server": t["server"],
                       "description": t["description"],
                       "params": list((t["input_schema"].get("properties") or {}).keys())}
                      for t in self._hub.tools],
            "servers": self._hub.connected_servers,
            "failed": self._hub.failed_servers,
            "providers": provider_summary(),
            "active": active_name(),
            "services": await self._services_snapshot(),
        })
        self.sig_state.emit("就绪")

    async def _teardown(self) -> None:
        self.sig_state.emit("正在关闭…")
        if self._hub is not None:
            with contextlib.suppress(Exception):
                await self._hub.__aexit__(None, None, None)
            self._hub = None
        with contextlib.suppress(Exception):
            await asyncio.to_thread(self._local.stop)

    # ------------------------------------------------------------ 服务状态
    async def _services_snapshot(self) -> dict:
        """本地服务 / Ollama / MCP / 视觉 的状态快照（供侧边栏状态灯）"""
        def _probe() -> dict:
            snap: dict = {}
            snap["llama"] = bool(is_server_running())
            snap["llama_owned"] = self._local.owned
            mmproj = find_mmproj()
            snap["mmproj"] = str(mmproj) if mmproj else ""
            try:
                check_embedder()
                snap["ollama"] = True
                snap["ollama_detail"] = "nomic-embed-text 可用"
            except Exception as e:
                snap["ollama"] = False
                snap["ollama_detail"] = str(e).splitlines()[0][:80]
            state = vision_status()
            snap["vision"] = state["available"]
            snap["vision_detail"] = state["detail"]
            return snap

        snap = await asyncio.to_thread(_probe)
        snap["mcp_servers"] = list(self._hub.connected_servers) if self._hub else []
        snap["mcp_tools"] = len(self._hub.tools) if self._hub else 0
        snap["active"] = active_name()
        return snap

    async def _emit_services(self) -> None:
        self.sig_services.emit(await self._services_snapshot())

    # ------------------------------------------------------------ 流式回调
    def _on_think(self, piece: str) -> None:
        self.sig_think.emit(piece)

    def _on_answer(self, piece: str) -> None:
        self.sig_answer.emit(piece)

    def _on_stats(self, result: ChatResult) -> None:
        self._stats_total["output_tokens"] += result.output_tokens
        self._stats_total["think"] += result.think_chunks
        self._stats_total["answer"] += result.answer_chunks
        self.sig_stats.emit({
            "tag": result.tag,
            "output_tokens": result.output_tokens,
            "think": result.think_chunks,
            "answer": result.answer_chunks,
            "total_tokens": result.total_tokens,
            "server_side": bool(result.usage),
            "cumulative": dict(self._stats_total),
        })

    # ------------------------------------------------------------ 提问
    async def _ask(self, p: dict) -> None:
        text = (p.get("text") or "").strip()
        images = [str(i) for i in (p.get("images") or []) if i]
        if not text and not images:
            return

        self.sig_busy.emit(True)
        started = time.time()
        pname = p.get("provider") or active_name()
        mode = p.get("mode") or "agent"
        show_thinking = bool(p.get("show_thinking", True))
        self.sig_output_begin.emit("answer")
        try:
            prov = get_provider(pname)
        except KeyError as e:
            self.sig_error.emit(str(e.args[0] if e.args else e))
            self.sig_busy.emit(False)
            return

        # 不看图的提供方 + 有图片 → 先本地识图，把结论以文字形式注入（多模态桥接）
        if images and not prov.supports_vision:
            self.sig_state.emit("本地视觉模型识读拓扑图…")
            await self._ensure_vision()
            bridge = await asyncio.to_thread(describe_images, images, text, None, show_thinking)
            if bridge:
                text = f"{text}\n\n{bridge}".strip()
                images = []
            else:
                self.sig_log.emit("[警告] 识图未成功，本轮将忽略图片（请检查 mmproj 与本地模型）")
                images = []

        try:
            if p.get("parallel"):
                answer, meta = await self._run_parallel(text, images, p, show_thinking)
            else:
                answer, meta = await self._run_single(text, images, p, mode, pname, show_thinking)
        except ProviderError as e:
            self.sig_error.emit(str(e))
            self.sig_log.emit("（本次不计入会话记录，可换提供方或检查密钥/网络后重试）")
            return
        except Exception as e:
            self.sig_error.emit(f"{type(e).__name__}: {e}")
            self.sig_log.emit(traceback.format_exc())
            return
        finally:
            self.sig_busy.emit(False)
            self.sig_state.emit("就绪")

        meta = {**meta, "elapsed": round(time.time() - started, 1), "mode": mode}
        self._last_answer = answer
        self.sig_answer_done.emit(answer, meta)
        self.submit("services") if False else None

    async def _run_single(self, text: str, images: list[str], p: dict, mode: str,
                          pname: str, show_thinking: bool) -> tuple[str, dict]:
        use_agent = (mode == "agent" and self._hub is not None
                     and bool(self._hub.tools) and get_provider(pname).supports_tools)
        if mode == "agent" and not use_agent:
            self.sig_log.emit("（agent 模式不可用：无 MCP 工具或该模型不支持工具调用，"
                              "本次改用知识库问答）")

        if use_agent:
            self.sig_log.emit(f"[agent] 模型 {pname} 自主调用 MCP 工具…")
            assert self._hub is not None
            answer = await run_agent(
                text, self._hub, history=self._history,
                max_rounds=int(p.get("max_rounds") or 4),
                show_thinking=show_thinking, images=images or None,
                provider=pname, on_think=self._on_think, on_answer=self._on_answer)
            self._history += [{"role": "user", "content": text},
                              {"role": "assistant", "content": answer}]
            del self._history[:-8]  # 只保留最近 4 轮
            return answer, {"provider": pname, "model": get_provider(pname).model,
                            "kind": "agent"}

        answer = await asyncio.to_thread(
            rag_ask, text, show_thinking, True, images or None, pname,
            self._on_think, self._on_answer)
        return answer, {"provider": pname, "model": get_provider(pname).model,
                        "kind": "rag"}

    async def _run_parallel(self, text: str, images: list[str], p: dict,
                            show_thinking: bool) -> tuple[str, dict]:
        self.sig_log.emit("[parallel] 多模型并行 + 融合开始…")
        report = await asyncio.to_thread(
            run_multimodal_parallel, text, images or None,
            p.get("parallel_providers") or None, "parallel", True, None,
            False, None, self._on_think, self._on_answer)
        self.sig_log.emit(report.render())

        if report.synthesis:
            answer = report.synthesis
        else:
            answer = "\n\n".join(
                (o.result.content if o.ok else f"[{o.label} 失败] {o.error}")
                for o in report.outcomes) or "（没有拿到任何回答）"
            self.sig_log.emit("（未生成融合答案，以上为各路原始回答）")
        return answer, {"provider": report.synth_label or "parallel",
                        "model": "", "kind": "parallel",
                        "elapsed": report.elapsed}

    async def _ensure_vision(self) -> None:
        """需要识图时确保本地服务带 mmproj 在跑"""
        if self._local.running:
            state = vision_status()
            if state["available"] is True:
                return
        try:
            await asyncio.to_thread(self._local.ensure, True)
        except Exception as e:
            self.sig_log.emit(f"[警告] 本地视觉服务启动失败：{type(e).__name__}: {e}")

    # ------------------------------------------------------------ 控制台命令
    async def _command(self, p: dict) -> None:
        name = p.get("name", "")
        arg = p.get("arg", "")
        try:
            if name == "tools":
                text = self._hub.describe_tools() if self._hub else "（MCP 未连接）"
            elif name == "call":
                if self._hub is None:
                    text = "（MCP 未连接）"
                else:
                    tool = p.get("tool", "")
                    text = await self._hub.call_tool(tool, p.get("args") or {})
            elif name == "audit":
                if self._hub is None:
                    text = "（MCP 未连接）"
                else:
                    n = int(arg) if str(arg).isdigit() else 10
                    text = await self._hub.call_tool("recent_audit", {"n": n})
            elif name == "vision":
                text = await self._vision_report()
            elif name == "rebuild":
                self.sig_state.emit("重建索引…")
                k = await asyncio.to_thread(build_knowledge_index, True)
                t = await asyncio.to_thread(build_template_index, True)
                text = f"索引已重建：知识库 {k} 个文本块，命令模板 {t} 条"
                await self._emit_services()
            elif name == "probe":
                text = await self._probe_report()
            elif name == "reset_history":
                self._history.clear()
                return
            elif name == "providers":
                text = describe_table(active=active_name())
            elif name == "services":
                snap = await self._services_snapshot()
                text = "\n".join(f"{k}: {v}" for k, v in snap.items())
            elif name == "tools_json":
                import json as _json
                text = _json.dumps(
                    [{"name": t["name"], "server": t["server"], "params":
                      list((t["input_schema"].get("properties") or {}).keys())}
                     for t in (self._hub.tools if self._hub else [])],
                    ensure_ascii=False, indent=2)
            else:
                text = f"未知命令：{name}"
            self.sig_result.emit(name, text)
        except Exception as e:
            self.sig_result.emit(name, f"命令执行失败：{type(e).__name__}: {e}")

    async def _vision_report(self) -> str:
        def _collect() -> str:
            status = vision_status()
            found = find_mmproj()
            lines = [f"视觉能力：{'可用' if status['available'] else ('待确认' if status['available'] is None else '不可用')}",
                     f"判据：{status['detail']}",
                     f"mmproj：{found if found else '未找到'}"]
            for p in list_providers():
                lines.append(f"  {p.name}：{'支持图片' if p.supports_vision else '不支持图片（走多模态桥接）'}")
            if not found:
                from core.llama_start import mmproj_hint
                lines.append(mmproj_hint())
            return "\n".join(lines)
        return await asyncio.to_thread(_collect)

    async def _probe_report(self) -> str:
        def _run() -> str:
            lines = ["提供方可用性探测："]
            for p in configured_providers():
                r = probe(p)
                flag = "可用" if r["ok"] else "不可用"
                extra = f"（{r['latency']}s）" if r.get("latency") else ""
                lines.append(f"[{flag}] {p.name:<18} {p.model:<20} {extra} {r['detail']}")
            return "\n".join(lines)
        return await asyncio.to_thread(_run)

    # ------------------------------------------------------------ 其它
    async def _start_local(self, with_vision: bool) -> None:
        self.sig_state.emit("启动本地 llama-server（加载模型可能较慢）…")
        try:
            started = await asyncio.to_thread(self._local.ensure, with_vision)
            self.sig_log.emit("本地 llama-server 已就绪" if self._local.running
                              else "本地 llama-server 启动未成功")
            if not started and self._local.running:
                self.sig_log.emit("（复用了已在运行的实例）")
        except Exception as e:
            self.sig_error.emit(f"本地服务启动失败：{type(e).__name__}: {e}")
        await self._emit_services()

    def _set_provider(self, name: str) -> None:
        try:
            prov = set_active(name)
        except KeyError as e:
            self.sig_error.emit(str(e.args[0] if e.args else e))
            return
        self.sig_log.emit(f"已切换到 {prov.label}（{prov.model}）")
        self.sig_providers.emit(provider_summary())
        if prov.needs_key and not prov.api_key_value:
            self.sig_log.emit(f"[警告] 该提供方还没有 API Key，请设置环境变量 "
                              f"{prov.api_key_env or 'DEEPSEEK_API_KEY'}，或在设置里填写")
        if prov.kind == "local" and not self._local.running:
            self.sig_log.emit("[提示] 本地模型尚未启动，可在侧边栏点「启动本地模型」")

    def _set_key(self, key: str) -> None:
        key = (key or "").strip()
        if not key:
            self.sig_result.emit("key", "密钥为空，未做修改")
            return
        os.environ["DEEPSEEK_API_KEY"] = key
        load_providers(refresh=True)
        self.sig_providers.emit(provider_summary())
        self.sig_result.emit("key", "已设置本次运行的 DeepSeek API Key（建议写入 .env 持久保存）")
