"""LLM 客户端层：llama-server 的流式对话调用。

职责：
- 统一 LLM 端点与模型名（取自 core/llama_start.py 的端口配置），其他模块不再各自硬编码
- 流式调用 /v1/chat/completions，实时打印「思考过程」与「回答」，并统计输出 token 数
- 支持 OpenAI 风格工具调用（tools / tool_calls），供 Agent 模式使用
- 提供 ThinkStreamSplitter：把 <think>...</think> 从正文流中拆出来

被 core.rag（RAG 问答）与 core.agent（工具调用循环）共用。
"""
import json

import requests

from core.llama_start import BASE_URL

CHAT_API_URL = f"{BASE_URL}/v1/chat/completions"
MODEL_NAME = "Qwen3.5-9B"

THINK_TAGS = ("<think>", "</think>")


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


class ChatResult:
    """一次（流式）对话的结果"""

    def __init__(self, content: str, tool_calls: list[dict], usage: dict | None,
                 think_chunks: int, answer_chunks: int):
        self.content = content
        self.tool_calls = tool_calls
        self.usage = usage
        self.think_chunks = think_chunks
        self.answer_chunks = answer_chunks

    @property
    def output_tokens(self) -> int:
        """输出 token 数：优先服务端 usage，否则用输出块数近似"""
        if self.usage:
            return self.usage.get("completion_tokens", self.think_chunks + self.answer_chunks)
        return self.think_chunks + self.answer_chunks

    @property
    def stats_note(self) -> str:
        return "（服务端统计）" if self.usage else "（按输出块近似）"


def stream_chat(messages: list[dict], tools: list[dict] | None = None,
                temperature: float = 0.1, show_thinking: bool = True,
                show_answer: bool = True, timeout: int = 600) -> ChatResult:
    """流式对话调用。

    Args:
        messages: OpenAI 风格消息列表
        tools: OpenAI 风格工具定义；为空则不传（模型无法调用工具）
        show_thinking: 是否实时打印思考过程（reasoning_content 字段或 <think> 标签）
        show_answer: 是否实时逐 token 打印回答正文（False 时只收集不打印）

    Returns:
        ChatResult：最终回答文本、模型请求的工具调用、token 统计
    """
    payload = {
        "model": MODEL_NAME,
        "messages": messages,
        "temperature": temperature,  # 降低随机性，让回答更忠实于检索内容
        "stream": True,
        "stream_options": {"include_usage": True},
    }
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"

    answer_parts: list[str] = []
    think_chunks = 0
    answer_chunks = 0
    usage = None
    tool_buf: dict[int, dict] = {}  # index -> {"id", "name", "arguments"}
    printed_header = {"think": False, "answer": False}
    tag_splitter = ThinkStreamSplitter()

    def _emit_thinking(piece: str):
        if not show_thinking or not piece:
            return
        if not printed_header["think"]:
            print("\n———— 模型思考过程 ————")
            printed_header["think"] = True
        print(piece, end="", flush=True)

    def _emit_answer(piece: str):
        if not piece:
            return
        if show_answer:
            if not printed_header["answer"]:
                print("\n\n———— 回答 ————" if printed_header["think"] else "\n———— 回答 ————")
                printed_header["answer"] = True
            print(piece, end="", flush=True)

    with requests.post(CHAT_API_URL, json=payload, stream=True, timeout=timeout) as resp:
        resp.raise_for_status()
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

            # 方式一：reasoning_content 字段（llama.cpp --jinja / 官方 reasoning 格式）
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

    return ChatResult("".join(answer_parts), tool_calls, usage, think_chunks, answer_chunks)


def print_stats(result: ChatResult):
    """统一打印输出统计行（思考 / 回答 token 数）"""
    print(
        f"\n\n[输出 token 数：{result.output_tokens}{result.stats_note}"
        f" ｜ 思考 {result.think_chunks} ＋ 回答 {result.answer_chunks}]"
    )
