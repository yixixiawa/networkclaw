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
from core.conversation_service import ConversationService
from core.llama_start import find_mmproj, is_server_running, mmproj_hint
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
from gui.command_dispatcher import CommandDispatcher
from gui.service_coordinator import ServiceCoordinator
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
    sig_think = pyqtSignal(str, str)          # (sid, 思考片段)
    sig_answer = pyqtSignal(str, str)         # (sid, 回答片段)
    sig_output_begin = pyqtSignal(str, str)   # (sid, "think" | "answer")
    sig_answer_done = pyqtSignal(str, dict)   # 最终回答 + 元信息
    sig_stats = pyqtSignal(dict)              # 一次生成的 token 统计
    sig_error = pyqtSignal(str)
    sig_confirmation_required = pyqtSignal(dict)
    sig_busy = pyqtSignal(bool)
    sig_result = pyqtSignal(str, str)         # (命令名, 文本结果) → 控制台
    sig_services = pyqtSignal(dict)           # 服务状态快照
    sig_providers = pyqtSignal(list)          # 提供方列表
    sig_topology = pyqtSignal(str)            # 自动拓扑巡检结果（显示为对话气泡）
    sig_devices = pyqtSignal(list)            # 设备清单+在线状态（设备管理页签）

    def __init__(self, options: dict | None = None, parent=None):
        super().__init__(parent)
        self.options = dict(options or {})
        self._inbox: queue.Queue[Job] = queue.Queue()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._wake: asyncio.Event | None = None
        self._done: asyncio.Event | None = None
        self._hub: McpHub | None = None
        self._local = LocalService(self.options.get("mmproj"))
        self._services = ServiceCoordinator(self._local)
        self._commands = CommandDispatcher(None, self._services)
        self._history: list[dict] = []
        self._last_answer = ""
        self._stats_total = {"output_tokens": 0, "think": 0, "answer": 0}
        self.booted = False
        self._stop_requested = False
        self._confirmation_waiters: dict[str, asyncio.Future] = {}

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
        self._stop_requested = True
        self.submit("shutdown")
        loop, done = self._loop, self._done
        if loop is not None and done is not None:
            with contextlib.suppress(RuntimeError):
                loop.call_soon_threadsafe(done.set)
                loop.call_soon_threadsafe(self._cancel_confirmations)

    def resolve_confirmation(self, request_id: str, approved: bool) -> None:
        """Resolve a GUI confirmation prompt from the main Qt thread."""
        loop = self._loop
        if loop is not None:
            with contextlib.suppress(RuntimeError):
                loop.call_soon_threadsafe(self._finish_confirmation,
                                          request_id, approved)

    def _finish_confirmation(self, request_id: str, approved: bool) -> None:
        future = self._confirmation_waiters.get(request_id)
        if future is None or future.done():
            return
        token = None
        if approved:
            from core.confirmation import approve_request

            token = approve_request(request_id)
        future.set_result(token)

    def _cancel_confirmations(self) -> None:
        for future in self._confirmation_waiters.values():
            if not future.done():
                future.set_result(None)

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
            if not self._stop_requested:
                await self._boot()
        except Exception as e:
            self.sig_error.emit(f"初始化失败：{type(e).__name__}: {e}")
            self.sig_log.emit(traceback.format_exc())
            self.sig_state.emit("初始化失败（仍可尝试提问）")
            self.booted = True

        if self._stop_requested and self._done is not None:
            self._done.set()
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
            await self._services.stop_local()
            await self._emit_services()
        elif job.kind == "auto_vision":
            await self._auto_vision(force=bool(job.payload.get("force")),
                                    keyword=job.payload.get("keyword") or None)
        elif job.kind == "reload_providers":
            load_providers(refresh=True)
            self.sig_providers.emit(provider_summary())
        elif job.kind == "device_probe":
            await self._device_probe()
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
        self._commands.hub = self._hub
        await self._hub.__aenter__()
        self._services.hub = self._hub
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

        # 自动拓扑巡检（默认开启，设置里可关）：先「看一眼」当前拓扑再开始对话。
        # 放在就绪之后投递，由任务队列接手，不阻塞界面。
        if self.options.get("auto_vision", True):
            self.submit("auto_vision", keyword=self.options.get("capture_keyword"))

    async def _teardown(self) -> None:
        self.sig_state.emit("正在关闭…")
        if self._hub is not None:
            with contextlib.suppress(Exception):
                await self._hub.__aexit__(None, None, None)
            self._hub = None
            self._services.hub = None
            self._commands.hub = None
        with contextlib.suppress(Exception):
            await self._services.stop_local()

    # ------------------------------------------------------------ 服务状态
    async def _services_snapshot(self) -> dict:
        snap = await self._services.services_snapshot()
        snap["active"] = active_name()
        return snap

    async def _emit_services(self) -> None:
        self.sig_services.emit(await self._services_snapshot())

    # ------------------------------------------------------------ 流式回调
    def _on_think(self, sid: str, piece: str) -> None:
        self.sig_think.emit(sid, piece)

    def _on_answer(self, sid: str, piece: str) -> None:
        self.sig_answer.emit(sid, piece)

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
        sid = str(p.get("sid") or "default")
        pname = p.get("provider") or active_name()
        mode = p.get("mode") or "agent"
        show_thinking = bool(p.get("show_thinking", True))
        self.sig_output_begin.emit(sid, "answer")
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
                answer, meta = await self._run_parallel(sid, text, images, p, show_thinking)
            else:
                answer, meta = await self._run_single(
                    sid, text, images, p, mode, pname, show_thinking)
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

        meta = {**meta, "elapsed": round(time.time() - started, 1),
            "mode": mode, "sid": sid, "question": text}
        self._last_answer = answer
        self.sig_answer_done.emit(answer, meta)
        self.submit("services") if False else None

    async def _run_single(self, sid: str, text: str, images: list[str], p: dict, mode: str,
                          pname: str, show_thinking: bool) -> tuple[str, dict]:
        service = ConversationService(self._hub)
        result = await service.run(
            text, mode=mode, provider=pname, history=self._history,
            images=images, max_rounds=int(p.get("max_rounds") or 4),
            show_thinking=show_thinking, session=sid,
            on_think=lambda piece: self._on_think(sid, piece),
            on_answer=lambda piece: self._on_answer(sid, piece),
            on_log=self.sig_log.emit, on_confirmation=self._request_confirmation)
        if result.meta.get("kind") == "agent":
            self._history += [{"role": "user", "content": text},
                              {"role": "assistant", "content": result.answer}]
            del self._history[:-8]
        return result.answer, result.meta

    async def _request_confirmation(self, pending: dict) -> str | None:
        request_id = str(pending.get("request_id", ""))
        if not request_id or self._loop is None:
            return None
        future = self._loop.create_future()
        self._confirmation_waiters[request_id] = future
        self.sig_confirmation_required.emit(pending)
        try:
            return await future
        finally:
            self._confirmation_waiters.pop(request_id, None)

    async def _run_parallel(self, sid: str, text: str, images: list[str], p: dict,
                            show_thinking: bool) -> tuple[str, dict]:
        service = ConversationService(self._hub)
        result = await service.run(
            text, provider=p.get("provider") or "", images=images,
            parallel_providers=p.get("parallel_providers") or None,
            show_thinking=show_thinking, parallel=True,
            on_think=lambda piece: self._on_think(sid, piece),
            on_answer=lambda piece: self._on_answer(sid, piece),
            on_log=self.sig_log.emit)
        return result.answer, result.meta

    async def _ensure_vision(self) -> None:
        try:
            await self._services.ensure_vision()
        except Exception as e:
            self.sig_log.emit(f"[警告] 本地视觉服务启动失败：{type(e).__name__}: {e}")

    # ------------------------------------------------------------ 自动拓扑巡检
    async def _auto_vision(self, force: bool = False, keyword: str | None = None) -> None:
        """启动时/手动触发的拓扑巡检：截图 → 本地识读 → 快照落盘 → 界面播报。

        透明化（用户要求）：执行前先把「要做什么、图存哪、怎么关」发到运行日志，
        结果以对话气泡呈现，用户始终知道程序看了什么、得出了什么结论。
        """
        from core import auto_topology

        if find_mmproj() is None:
            self.sig_log.emit("[自动拓扑巡检] 未执行：" + mmproj_hint())
            return
        self.sig_log.emit(auto_topology.notice(keyword))
        self.sig_state.emit("自动拓扑巡检：截取窗口并识读…")
        try:
            await self._ensure_vision()
            result = await asyncio.to_thread(
                auto_topology.auto_inspect, keyword, None, force, False)
            self.sig_topology.emit(auto_topology.render_result(result))
        except Exception as e:
            self.sig_log.emit(f"[自动拓扑巡检] 失败：{type(e).__name__}: {e}（不影响对话）")
        finally:
            self.sig_state.emit("就绪")
            await self._emit_services()

    # ------------------------------------------------------------ 设备管理
    async def _device_probe(self) -> None:
        """设备清单 + 在线探测（只读 TCP/串口枚举），结果发设备页签"""
        try:
            self.sig_devices.emit(await self._services.device_probe())
        except Exception as e:
            self.sig_log.emit(f"[设备管理] 探测失败：{type(e).__name__}: {e}")

    # ------------------------------------------------------------ 控制台命令
    async def _command(self, p: dict) -> None:
        name = p.get("name", "")
        try:
            if name == "rebuild":
                self.sig_state.emit("重建索引…")
            result = await self._commands.dispatch(
                name, arg=p.get("arg", ""), tool=p.get("tool", ""),
                args=p.get("args") or {})
            if result.reset_history:
                self._history.clear()
                return
            self.sig_result.emit(result.name, result.text)
            if result.refresh_services:
                await self._emit_services()
        except Exception as e:
            self.sig_result.emit(name, f"命令执行失败：{type(e).__name__}: {e}")

    async def _vision_report(self) -> str:
        return await self._services.vision_report()

    async def _probe_report(self) -> str:
        return await self._services.provider_probe_report()

    # ------------------------------------------------------------ 其它
    async def _start_local(self, with_vision: bool) -> None:
        self.sig_state.emit("启动本地 llama-server（加载模型可能较慢）…")
        try:
            started, running = await self._services.start_local(with_vision)
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
