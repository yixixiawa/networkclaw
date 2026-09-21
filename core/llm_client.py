"""LLM 客户端层：多提供方（本地 llama-server / DeepSeek 等）的流式对话调用。

职责：
- 统一 LLM 调用出口：端点、鉴权、请求体组装都按 core/providers.py 的 Provider 决定，
  其他模块不再各自硬编码 base_url / model 名
- 流式调用 chat/completions，实时打印「思考过程」与「回答」，并统计输出 token 数
- 支持 OpenAI 风格工具调用（tools / tool_calls），供 Agent 模式使用
- 提供 ThinkStreamSplitter：把 <think>...</think> 从正文流中拆出来
- 提供 run_parallel()：同一问题并行跑多个提供方（本地 + 云端 + 视觉），为「多模态并行」打底

被 core.rag（RAG 问答）、core.agent（工具调用循环）、core.vision（图像识别）共用。
"""
from __future__ import annotations

import json
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

import requests

from core.providers import Provider, get_provider

THINK_TAGS = ("<think>", "</think>")

# 各提供方实际可用的请求地址（首次成功后缓存，避免每次都先撞 404）
_resolved_url: dict[str, str] = {}
# 记录哪些提供方不接受 stream_options.include_usage / temperature（400 回退后记住）
_no_stream_options: set[str] = set()
_no_sampling: set[str] = set()


class ProviderError(RuntimeError):
    """调用模型提供方失败，message 里带用户可读的原因与修复建议"""


# 统计钩子：GUI 用它在每次生成结束后拿到 token 统计，而不用解析 stdout
_stats_hook: "Callable[[ChatResult], None] | None" = None


def set_stats_hook(hook: "Callable[[ChatResult], None] | None") -> None:
    """注册/清除统计钩子（每进程一个，传 None 清除）"""
    global _stats_hook
    _stats_hook = hook


def _provider_tag(provider: Provider) -> str:
    return f"{provider.label}（{provider.model}）"


def _friendly_http_error(provider: Provider, status: int, body: str) -> ProviderError:
    """把 HTTP 错误翻译成可操作的提示（密钥、余额、限流、端点）"""
    snippet = (body or "").strip()[:300]
    if status in (401, 403):
        tip = (f"鉴权失败（HTTP {status}）。请检查 API Key：环境变量 "
               f"{provider.api_key_env or 'DEEPSEEK_API_KEY'} 或 config/llm.json 中的 api_key。")
    elif status == 402:
        tip = "账户余额不足（HTTP 402），请到平台充值后重试。"
    elif status == 429:
        tip = "请求过于频繁（HTTP 429），请稍后重试或降低并发。"
    elif status == 404:
        tip = (f"接口地址不存在（HTTP 404）：{provider.chat_urls[0]}。"
               "请核对 config/llm.json 里的 base_url。")
    elif status == 400:
        tip = "请求被拒绝（HTTP 400），通常是参数不被该模型支持。"
    elif status >= 500:
        tip = f"服务端错误（HTTP {status}），可稍后重试。"
    else:
        tip = f"请求失败（HTTP {status}）。"
    return ProviderError(f"{_provider_tag(provider)}：{tip}\n服务端返回：{snippet}")


class ThinkStreamSplitter:
    """把流式输出的 content 按 <think>...</think> 标签拆成「思考」与「回答」两部分。

    兼容标签被拆散在多个 chunk 之间的情况。
    """

    def __init__(self):
        self.in_think = False
        self._pending = ""  # 可能是不完整标签的尾巴

    def feed(self, text: str):
        """输入一段 content，返回 [(is_thinking, piece), ...]"""
        pieces = []
        buf = self._pending + text
        pos = 0
        while pos < len(buf):
            if self.in_think:
                idx = buf.find(THINK_TAGS[1], pos)
                if idx == -1:
                    # 没找到闭合标签；若尾部可能是不完整标签则先扣留
                    safe, hold = self._split_safe(buf, pos)
                    if safe:
                        pieces.append((True, safe))
                    self._pending = hold
                    return pieces
                if idx > pos:
                    pieces.append((True, buf[pos:idx]))
                self.in_think = False
                pos = idx + len(THINK_TAGS[1])
            else:
                idx = buf.find(THINK_TAGS[0], pos)
                if idx == -1:
                    safe, hold = self._split_safe(buf, pos)
                    if safe:
                        pieces.append((False, safe))
                    self._pending = hold
                    return pieces
                if idx > pos:
                    pieces.append((False, buf[pos:idx]))
                self.in_think = True
                pos = idx + len(THINK_TAGS[0])
        self._pending = ""
        return pieces

    @staticmethod
    def _split_safe(buf: str, start: int):
        """从 start 开始，把可能是不完整标签前缀的尾部扣留住"""
        tail_candidates = max(len(THINK_TAGS[1]), len(THINK_TAGS[0])) - 1
        end = len(buf)
        for k in range(1, min(tail_candidates, len(buf) - start) + 1):
            tail = buf[end - k:]
            if THINK_TAGS[0].startswith(tail) or THINK_TAGS[1].startswith(tail):
                end = end - k
                break
        if end <= start:
            return "", buf[start:]
        return buf[start:end], buf[end:]


@dataclass
class ChatResult:
    """一次（流式）对话的结果"""

    content: str
    tool_calls: list[dict]
    usage: dict | None
    think_chunks: int
    answer_chunks: int
    provider: str = ""          # 提供方标识（local / deepseek …）
    model: str = ""             # 实际调用的模型名
    tools_dropped: bool = False  # 该提供方不支持工具调用，已忽略 tools 参数

    @property
    def output_tokens(self) -> int:
        """输出 token 数：优先服务端 usage，否则用输出块数近似"""
        if self.usage:
            return self.usage.get("completion_tokens", self.think_chunks + self.answer_chunks)
        return self.think_chunks + self.answer_chunks

    @property
    def total_tokens(self) -> int:
        if self.usage:
            return self.usage.get("total_tokens", 0) or 0
        return 0

    @property
    def stats_note(self) -> str:
        return "（服务端统计）" if self.usage else "（按输出块近似）"

    @property
    def tag(self) -> str:
        return f"{self.provider}/{self.model}" if self.provider else self.model


def _build_payload(messages: list[dict], provider: Provider, tools: list[dict] | None,
                   temperature: float | None, tools_dropped: list[bool]) -> dict:
    """按提供方能力组装请求体（不支持的能力一律不塞进去，避免 400）"""
    payload: dict = {
        "model": provider.model,
        "messages": messages,
        "stream": True,
    }
    if provider.supports_sampling and temperature is not None and provider.name not in _no_sampling:
        # 降低随机性，让回答更忠实于检索内容
        payload["temperature"] = temperature
    if provider.supports_stream_options and provider.name not in _no_stream_options:
        payload["stream_options"] = {"include_usage": True}

    if tools:
        if provider.supports_tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        else:
            tools_dropped.append(True)

    if provider.extra_body:
        for k, v in provider.extra_body.items():
            payload.setdefault(k, v)
    return payload


def _payload_variants(payload: dict, provider: Provider) -> list[dict]:
    """400 时的降级候选：先去掉 stream_options，再去掉 temperature"""
    variants = [payload]
    if "stream_options" in payload:
        v = {k: val for k, val in payload.items() if k != "stream_options"}
        variants.append(v)
    if "temperature" in payload:
        base = variants[-1]
        variants.append({k: val for k, val in base.items() if k != "temperature"})
    # 去重
    seen, out = set(), []
    for v in variants:
        key = json.dumps(sorted(v.keys()))
        if key not in seen:
            seen.add(key)
            out.append(v)
    return out


def _post_stream(provider: Provider, payload: dict, timeout: int):
    """带端点回退与参数降级的一次流式请求，返回已确认可用的响应对象"""
    urls = provider.chat_urls
    cached = _resolved_url.get(provider.name)
    if cached:
        urls = [cached] + [u for u in urls if u != cached]

    last_error: ProviderError | None = None
    for url in urls:
        variants = _payload_variants(payload, provider)
        for idx, body in enumerate(variants):
            try:
                resp = requests.post(url, json=body, headers=provider.headers(),
                                     stream=True, timeout=timeout)
            except requests.RequestException as e:
                hint = ""
                if provider.kind == "local":
                    hint = ("\n本地 llama-server 未启动？请运行 `python main.py`，"
                            "或先执行 `python -m core.llama_start` 启动服务。")
                raise ProviderError(f"{_provider_tag(provider)}：连接失败 "
                                    f"{type(e).__name__}: {e}{hint}") from e

            if resp.status_code == 200:
                _resolved_url[provider.name] = url
                if idx > 0:  # 降级生效，记住别再塞不被支持的参数
                    if "stream_options" in payload and "stream_options" not in body:
                        _no_stream_options.add(provider.name)
                        print(f"[提示] {provider.name} 不接受 stream_options，已自动降级")
                    if "temperature" in payload and "temperature" not in body:
                        _no_sampling.add(provider.name)
                        print(f"[提示] {provider.name} 不接受 temperature，已自动降级")
                return resp

            text = ""
            try:
                text = resp.text
            except Exception:
                pass
            resp.close()

            if resp.status_code == 400 and idx < len(variants) - 1:
                continue  # 换一种参数组合再试
            if resp.status_code == 404 and url != urls[-1]:
                last_error = _friendly_http_error(provider, 404, text)
                break  # 换下一个端点
            raise _friendly_http_error(provider, resp.status_code, text)

    raise last_error or ProviderError(f"{_provider_tag(provider)}：没有可用的请求地址")


def stream_chat(messages: list[dict], tools: list[dict] | None = None,
                temperature: float | None = 0.1, show_thinking: bool = True,
                show_answer: bool = True, timeout: int | None = None,
                provider: str | Provider | None = None,
                on_think: "Callable[[str], None] | None" = None,
                on_answer: "Callable[[str], None] | None" = None) -> ChatResult:
    """流式对话调用（支持本地与云端提供方）。

    Args:
        messages: OpenAI 风格消息列表
        tools: OpenAI 风格工具定义；提供方不支持工具调用时会被忽略并置 tools_dropped
        temperature: 采样温度；None 或不支持采样的模型会省略该参数
        show_thinking: 是否实时打印思考过程（reasoning_content 字段或 <think> 标签）
        show_answer: 是否实时逐 token 打印回答正文（False 时只收集不打印）
        timeout: 请求超时秒数；默认取提供方配置
        provider: 提供方名称或对象；默认用当前激活的提供方
        on_think: 思考片段的回调（GUI 用）。**给了回调就不再往 stdout 打印**，
                  由调用方决定怎么呈现（避免同一份内容既上屏又进日志）
        on_answer: 回答片段的回调（GUI 用），语义同上

    Returns:
        ChatResult：最终回答文本、模型请求的工具调用、token 统计、提供方与模型名

    Raises:
        ProviderError: 调用失败（含鉴权、余额、限流、端点、连接等可读原因）
    """
    prov = provider if isinstance(provider, Provider) else get_provider(provider)
    timeout = timeout or prov.timeout
    tools_dropped: list[bool] = []
    payload = _build_payload(messages, prov, tools, temperature, tools_dropped)
    if tools_dropped:
        print(f"[提示] {prov.name} 不支持工具调用，本次已忽略 tools（将直接回答）")

    answer_parts: list[str] = []
    think_chunks = 0
    answer_chunks = 0
    usage = None
    tool_buf: dict[int, dict] = {}  # index -> {"id", "name", "arguments"}
    printed_header = {"think": False, "answer": False}
    tag_splitter = ThinkStreamSplitter()

    def _emit_thinking(piece: str):
        if not piece:
            return
        if on_think is not None:
            on_think(piece)
            return
        if not show_thinking:
            return
        if not printed_header["think"]:
            print("\n———— 模型思考过程 ————")
            printed_header["think"] = True
        print(piece, end="", flush=True)

    def _emit_answer(piece: str):
        if not piece:
            return
        if on_answer is not None:
            on_answer(piece)
            return
        if not show_answer:
            return
        if not printed_header["answer"]:
            print("\n\n———— 回答 ————" if printed_header["think"] else "\n———— 回答 ————")
            printed_header["answer"] = True
        print(piece, end="", flush=True)

    resp = _post_stream(prov, payload, timeout)
    with resp:
        # 流式响应头多为 text/event-stream 且不带 charset，requests 会按 ISO-8859-1 解码，
        # 导致中文（模型回答、思考过程、工具参数）全部乱码，因此这里按字节读取自行解码。
        for raw_line in resp.iter_lines(decode_unicode=False):
            if not raw_line:
                continue
            line = (raw_line.decode("utf-8", errors="replace")
                    if isinstance(raw_line, bytes) else raw_line)
            if not line.startswith("data:"):
                continue
            data = line[len("data:"):].strip()
            if data == "[DONE]":
                break
            try:
                chunk = json.loads(data)
            except json.JSONDecodeError:
                continue

            if chunk.get("usage"):
                usage = chunk["usage"]

            choices = chunk.get("choices") or []
            if not choices:
                continue
            delta = choices[0].get("delta") or {}

            # 工具调用：流式分片累积（同一 index 的 arguments 需要拼接）
            for call in delta.get("tool_calls") or []:
                idx = call.get("index", 0)
                slot = tool_buf.setdefault(idx, {"id": "", "name": "", "arguments": ""})
                if call.get("id"):
                    slot["id"] = call["id"]
                func = call.get("function") or {}
                if func.get("name"):
                    slot["name"] = func["name"]
                if func.get("arguments"):
                    slot["arguments"] += func["arguments"]

            # 方式一：reasoning_content 字段（DeepSeek 思考模式 / llama.cpp --jinja）
            reasoning = delta.get("reasoning_content")
            if reasoning:
                think_chunks += 1
                _emit_thinking(reasoning)

            content = delta.get("content")
            if content:
                # 方式二：思考内容以 <think>...</think> 内嵌在 content 中
                for is_think, piece in tag_splitter.feed(content):
                    if is_think:
                        think_chunks += 1
                        _emit_thinking(piece)
                    else:
                        answer_chunks += 1
                        answer_parts.append(piece)
                        _emit_answer(piece)

    tool_calls = [
        {
            "id": slot["id"] or f"call_{idx}",
            "type": "function",
            "function": {"name": slot["name"], "arguments": slot["arguments"] or "{}"},
        }
        for idx, slot in sorted(tool_buf.items())
        if slot["name"]
    ]

    return ChatResult(
        content="".join(answer_parts),
        tool_calls=tool_calls,
        usage=usage,
        think_chunks=think_chunks,
        answer_chunks=answer_chunks,
        provider=prov.name,
        model=prov.model,
        tools_dropped=bool(tools_dropped),
    )


# ---------------------------------------------------------------- 并行调用

@dataclass
class ParallelTask:
    """并行调用中的一路任务（一个提供方 + 一组消息）"""

    provider: str                      # 提供方名称
    messages: list[dict]
    label: str = ""                    # 结果展示用标题，默认取提供方名
    tools: list[dict] | None = None
    temperature: float | None = 0.1
    timeout: int | None = None
    _extra: dict = field(default_factory=dict)


@dataclass
class ParallelOutcome:
    """并行调用中一路的结果（成功或失败都在这）"""

    label: str
    provider: str
    model: str = ""
    result: ChatResult | None = None
    error: str = ""
    elapsed: float = 0.0

    @property
    def ok(self) -> bool:
        return self.result is not None


def chat_once(prompt: str | list[dict], provider: str | Provider | None = None,
              timeout: int | None = None, show_thinking: bool = False,
              temperature: float | None = 0.1, tools: list[dict] | None = None,
              show_answer: bool = False,
              on_think: "Callable[[str], None] | None" = None,
              on_answer: "Callable[[str], None] | None" = None) -> ParallelOutcome:
    """单次调用（默认不实时打印），任何异常都收敛进 ParallelOutcome，便于并行编排。

    Args:
        prompt: 纯文本问题，或完整的 OpenAI 风格消息列表
        provider: 提供方名称或对象；默认当前激活的
        on_think / on_answer: 流式片段回调，默认无（并行时多路输出会交错，通常不接）
    """
    messages = [{"role": "user", "content": prompt}] if isinstance(prompt, str) else prompt
    label = provider if isinstance(provider, str) or provider is None else provider.name
    start = time.time()
    try:
        prov = provider if isinstance(provider, Provider) else get_provider(provider)
        label = prov.name
        res = stream_chat(messages, tools=tools, temperature=temperature,
                          show_thinking=show_thinking, show_answer=show_answer,
                          timeout=timeout, provider=prov,
                          on_think=on_think, on_answer=on_answer)
        return ParallelOutcome(label=label, provider=prov.name, model=prov.model,
                               result=res, elapsed=round(time.time() - start, 1))
    except Exception as e:
        return ParallelOutcome(label=str(label), provider=str(label), error=f"{type(e).__name__}: {e}",
                               elapsed=round(time.time() - start, 1))


def run_parallel(tasks: list[ParallelTask], max_workers: int | None = None,
                 show_thinking: bool = False) -> list[ParallelOutcome]:
    """并行调用多个提供方，返回与 tasks 顺序一致的结果列表。

    用于「多模态并行」：例如让本地视觉模型读拓扑图、同时让 DeepSeek 起草配置方案，
    两路互不阻塞。注意各路回答统一不实时打印（避免输出交错），由调用方按序渲染。
    """
    outcomes: list[ParallelOutcome | None] = [None] * len(tasks)

    def _run(i: int, task: ParallelTask) -> None:
        outcome = chat_once(task.messages, provider=task.provider, timeout=task.timeout,
                            tools=task.tools, temperature=task.temperature,
                            show_thinking=show_thinking)
        if not task.label:
            outcome.label = outcome.provider
        else:
            outcome.label = task.label
        outcomes[i] = outcome

    if not tasks:
        return []
    workers = max_workers or min(len(tasks), 4)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for i, task in enumerate(tasks):
            pool.submit(_run, i, task)
    return [o for o in outcomes if o is not None]


def render_parallel(outcomes: list[ParallelOutcome]) -> str:
    """把并行调用结果渲染成带标题的文本（供 main.py 打印/存档）"""
    blocks: list[str] = []
    for o in outcomes:
        head = f"———— [{o.label}] {o.provider}/{o.model or '?'} ｜ {o.elapsed}s ————"
        if not o.ok:
            blocks.append(f"{head}\n[失败] {o.error}")
            continue
        res = o.result
        body = (res.content or "").strip() or "（无内容）"
        if res.tools_dropped:
            body += "\n（注：该模型不支持工具调用，本轮未使用 MCP 工具）"
        if res.usage:
            body += (f"\n\n[token：输入 {res.usage.get('prompt_tokens', '?')} ＋ "
                     f"输出 {res.usage.get('completion_tokens', '?')} ＝ "
                     f"{res.usage.get('total_tokens', '?')}]")
        blocks.append(f"{head}\n{body}")
    return "\n\n".join(blocks)


def print_stats(result: ChatResult):
    """统一打印输出统计行（提供方 / 思考 / 回答 token 数）。

    同时触发可选的统计钩子：桌面端靠它拿到 token 数据直接显示在界面上，
    而不必去解析 stdout 文本（GUI 的 print 还会被重定向，解析不可靠）。
    """
    if _stats_hook is not None:
        try:
            _stats_hook(result)
        except Exception:
            pass  # 统计不该影响任何主流程
    tag = f"{result.tag} ｜ " if result.tag else ""
    print(
        f"\n\n[{tag}输出 token 数：{result.output_tokens}{result.stats_note}"
        f" ｜ 思考 {result.think_chunks} ＋ 回答 {result.answer_chunks}]"
    )


if __name__ == "__main__":
    # 单模型连通性自检（不启动 main.py，用来快速验证 DeepSeek 密钥是否可用）
    #   python -m core.llm_client --ask "你好"
    #   python -m core.llm_client --provider deepseek --ask "用一句话说明 VLAN 的作用"
    #   python -m core.llm_client --all --ask "1+1=?"        # 所有已配置的提供方各问一次
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="LLM 单模型自检（验证提供方与密钥）")
    parser.add_argument("--provider", default=None, help="提供方名称，默认当前激活项")
    parser.add_argument("--all", action="store_true", help="对所有已配置的提供方各问一次")
    parser.add_argument("--ask", default="用一句话介绍你自己", help="要提问的内容")
    parser.add_argument("--no-thinking", action="store_true", help="不打印思考过程")
    args = parser.parse_args()

    from core.providers import configured_providers, get_provider, list_providers

    if args.all:
        targets = configured_providers()
        if not targets:
            print("没有已配置可用的提供方")
            sys.exit(1)
    else:
        try:
            targets = [get_provider(args.provider)]
        except KeyError as e:
            print(e.args[0] if e.args else e)
            print("可用：", ", ".join(p.name for p in list_providers()))
            sys.exit(1)

    failed = 0
    for prov in targets:
        print(f"\n================ {prov.name}（{prov.model}）================")
        if prov.needs_key and not prov.api_key_value:
            print(f"[跳过] 未配置 API Key（环境变量 {prov.api_key_env or 'DEEPSEEK_API_KEY'}）")
            failed += 1
            continue
        try:
            result = stream_chat(
                [{"role": "user", "content": args.ask}],
                show_thinking=not args.no_thinking, show_answer=True, provider=prov)
            print_stats(result)
            print(f"[OK] {prov.name} 调用成功")
        except ProviderError as e:
            print(f"[失败] {e}")
            failed += 1
        except Exception as e:
            print(f"[失败] {type(e).__name__}: {e}")
            failed += 1
    sys.exit(1 if failed else 0)
