"""MCP 连接自检与计时（排查「GUI 初始化卡住」这类问题）。

按启动顺序逐步执行并记录耗时，把结果写到 logs/mcp_probe_result.txt：

    1. 模型提供方配置加载（含 .env / config/llm.json）
    2. 知识库索引（幂等检查；Ollama 不可用时应快速失败而不是卡住）
    3. MCP 服务端连接（4 个子进程）+ 工具清单
    4. 一次工具调用（query_command_template，验证端到端）

用法：
    .venv/Scripts/python.exe tools/mcp_probe.py
    .venv/Scripts/python.exe tools/mcp_probe.py --skip-tool   # 跳过第 4 步
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

RESULT = ROOT / "logs" / "mcp_probe_result.txt"
lines: list[str] = []


def log(text: str) -> None:
    lines.append(text)
    try:
        RESULT.parent.mkdir(parents=True, exist_ok=True)
        RESULT.write_text("\n".join(lines), encoding="utf-8")
    except OSError:
        pass


class Timer:
    def __init__(self, label: str):
        self.label = label

    def __enter__(self):
        self.t0 = time.time()
        log(f"→ {self.label} …")
        return self

    def __exit__(self, exc_type, exc, tb):
        dt = time.time() - self.t0
        if exc_type is None:
            log(f"  ✓ {self.label} 用时 {dt:.2f}s")
        else:
            log(f"  ✗ {self.label} 失败（{dt:.2f}s）：{exc_type.__name__}: {exc}")
        return False  # 不吞异常，由调用处决定


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-tool", action="store_true")
    args = parser.parse_args()

    log(f"==== MCP 自检 {time.strftime('%Y-%m-%d %H:%M:%S')} ====")
    log(f"python：{sys.executable}")

    from core.llama_start import BASE_DIR, find_llama_server, find_model
    from core.providers import active_name, describe_table, load_providers

    log(f"BASE_DIR：{BASE_DIR}")
    log(f"主模型：{find_model() or '未找到'}")
    log(f"llama-server：{find_llama_server() or '未找到'}")

    with Timer("加载提供方配置"):
        load_providers(refresh=True)
    log(describe_table(active=active_name()))

    with Timer("知识库索引（幂等）"):
        try:
            from core.rag import build_index

            count = await asyncio.to_thread(build_index)
            log(f"  文本块：{count}")
        except Exception as e:
            log(f"  （索引不可用，按预期继续）{type(e).__name__}: {e}")

    from mcp_tools.client import DEFAULT_SERVERS, McpHub

    hub = McpHub(DEFAULT_SERVERS)
    with Timer("MCP 服务端连接"):
        await hub.__aenter__()
    log(f"  已连接：{hub.connected_servers}")
    log(f"  失败：{hub.failed_servers}")
    log(hub.describe_tools())

    if not args.skip_tool:
        with Timer("工具调用 query_command_template"):
            out = await hub.call_tool("query_command_template", {
                "intent": "配置OSPF宣告网段", "vendor": "Huawei", "device_type": "router"})
            log("  " + (out or "").strip().replace("\n", "\n  ")[:1200])

    with Timer("关闭 MCP"):
        await hub.__aexit__(None, None, None)

    log("")
    log("==== 完成 ====")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(main()))
    except BaseException:
        log(traceback.format_exc())
        raise
