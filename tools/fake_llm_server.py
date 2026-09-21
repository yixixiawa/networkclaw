"""内置「假模型服务」：一个最小的 OpenAI 兼容端点，只用于测试，不依赖任何真实模型。

为什么需要：
    GUI 的流式渲染、思考过程拆分（<think>…</think>）、token 统计都依赖真实的服务端
    行为（SSE 分片、usage 字段）。开发机上 llama-server / DeepSeek 不一定随时可用，
    于是用这个假服务把这些链路固定下来，让自动化测试可重复。

它模拟的行为（与 llama-server 的 OpenAI 兼容接口一致）：
    GET  /v1/models            返回模型列表（供 core/providers.probe 探测）
    POST /v1/chat/completions  以 text/event-stream 逐块返回 content，
                               content 里内嵌 <think>…</think> 思考段，
                               最后一个 chunk 带 usage（prompt/completion/total tokens）

用法（两种）：
    1) 独立启动：.venv/Scripts/python.exe tools/fake_llm_server.py --port 8099
       然后设置 NETWORKCLAW_LOCAL_BASE_URL=http://127.0.0.1:8099/v1 让程序连它
    2) 作为库：from fake_llm_server import start_fake_server
              server, port = start_fake_server()   # port=0 时自动选空闲端口
"""
from __future__ import annotations

import argparse
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

MODEL_ID = "fake-Qwen3.5-9B"

THINK_TEXT = ("用户想知道 VLAN 的作用。先想清楚：VLAN 是二层概念，"
              "作用是把一个物理交换机划分成多个广播域，从而隔离广播、便于管理与安全控制。")
ANSWER_TEXT = ("VLAN（虚拟局域网）的核心作用是**隔离二层广播域**："
               "把一台物理交换机在逻辑上切成多个互不干扰的网络，"
               "从而限制广播范围、便于按部门划分网段并施加访问控制。\n\n"
               "华为设备上的基本配置：\n\n"
               "```\n"
               "system-view\n"
               "vlan 100\n"
               "interface GigabitEthernet0/0/1\n"
               "port link-type access\n"
               "port default vlan 100\n"
               "quit\n"
               "```\n\n"
               "要点：VLAN 间的互通需要三层转发（VLANIF 接口或三层路由）。")

CHUNK_SIZE = 12


def _chunks(text: str, size: int = CHUNK_SIZE) -> list[str]:
    return [text[i:i + size] for i in range(0, len(text), size)]


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):  # noqa: D102  静默：测试时不需要访问日志
        pass

    # -------------------------------------------------- 探测用
    def do_GET(self):  # noqa: N802
        if self.path.rstrip("/").endswith("/models"):
            self._json({"object": "list",
                        "data": [{"id": MODEL_ID, "object": "model", "owned_by": "fake"}]})
            return
        self._json({"error": "not found"}, status=404)

    # -------------------------------------------------- 流式对话
    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length") or 0)
        try:
            json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            pass

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True

        payload = ("<think>" + THINK_TEXT + "</think>" + ANSWER_TEXT)
        for piece in _chunks(payload):
            self._sse({"object": "chat.completion.chunk", "model": MODEL_ID,
                       "choices": [{"index": 0, "delta": {"content": piece},
                                    "finish_reason": None}]})
        self._sse({"object": "chat.completion.chunk", "model": MODEL_ID,
                   "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]})
        self._sse({"object": "chat.completion.chunk", "model": MODEL_ID, "choices": [],
                   "usage": {"prompt_tokens": 42, "completion_tokens": 128,
                             "total_tokens": 170}})
        self.wfile.write(b"data: [DONE]\n\n")
        self.wfile.flush()

    # -------------------------------------------------- 工具
    def _json(self, data: dict, status: int = 200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)
        self.close_connection = True

    def _sse(self, data: dict):
        line = ("data: " + json.dumps(data, ensure_ascii=False) + "\n\n").encode("utf-8")
        self.wfile.write(line)
        self.wfile.flush()


def start_fake_server(port: int = 0) -> tuple[ThreadingHTTPServer, int]:
    """启动假服务（守护线程），返回 (server, 实际端口)。port=0 时自动挑空闲端口。"""
    server = ThreadingHTTPServer(("127.0.0.1", port), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True,
                              name="fake-llm-server")
    thread.start()
    return server, server.server_address[1]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="假 OpenAI 兼容服务（仅测试用）")
    parser.add_argument("--port", type=int, default=8099)
    args = parser.parse_args()
    srv, real_port = start_fake_server(args.port)
    print(f"假模型服务已启动：http://127.0.0.1:{real_port}/v1   （Ctrl+C 退出）")
    print("让程序连它的方式：")
    print(f"  set NETWORKCLAW_LOCAL_BASE_URL=http://127.0.0.1:{real_port}/v1")
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        srv.shutdown()
