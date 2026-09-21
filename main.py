"""NetworkClaw 统一启动入口（对话 + MCP 工具）。

流程：
1. 启动 llama-server（单实例，已有健康实例直接复用）
2. 构建 / 校验知识库索引（按内容指纹判断，幂等）
3. 以 stdio 方式连接本地 MCP 服务端，聚合工具清单
4. 进入对话循环

两种模式（对话中可用 /rag、/agent 随时切换）：
- agent（默认）：把 MCP 工具交给模型，由模型自主决定调用（命令模板检索 / 知识检索 / 联网搜索）
- rag：固定走「知识库检索 + 流式生成」的单轮问答（原行为）

运行方式（项目根目录下）：
    python main.py                  # 默认 agent 模式（带 MCP 工具）
    python main.py --mode rag       # 直接进入 RAG 问答
    python main.py --with-search    # 额外接入联网搜索 MCP（需 npx + open-websearch）
    python main.py --no-thinking    # 不打印模型思考过程
"""
import argparse
import asyncio
import datetime
import json
from pathlib import Path

from core.agent import run_agent
from core.llama_start import start_llama_server, stop_llama_server
from core.rag import ask, build_index
from mcp_tools.client import DEFAULT_SERVERS, SEARCH_SERVER, McpHub

BASE_DIR = Path(__file__).resolve().parent
LOG_DIR = BASE_DIR / "logs"

HELP_TEXT = """
可用命令：
  /help               显示本帮助
  /tools              列出已接入的 MCP 工具
  /call 工具名 {json}  直接调用某个 MCP 工具，例如：
                        /call query_command_template {"intent":"配置SSH登录","vendor":"H3C","device_type":"router"}
  /agent              切换到 agent 模式（模型自主调用 MCP 工具）
  /rag                切换到 rag 模式（固定知识库检索问答）
  /thinking           开关模型思考过程显示
  /stream             开关流式打印（关闭后由主程序打印 ask 的返回值）
  /last               重新显示最近一次回答
  /save [路径]        把本次会话导出为 Markdown（默认 logs/session_<时间>.md）
  q / exit            退出
"""


def parse_args():
    parser = argparse.ArgumentParser(description="NetworkClaw 对话入口（RAG + MCP）")
    parser.add_argument("--mode", choices=["agent", "rag"], default="agent",
                        help="启动模式，默认 agent（模型自主调用 MCP 工具）")
    parser.add_argument("--with-search", action="store_true",
                        help="额外接入联网搜索 MCP 服务端（需 npx + open-websearch）")
    parser.add_argument("--no-thinking", action="store_true", help="不打印模型思考过程")
    parser.add_argument("--max-rounds", type=int, default=3, help="agent 模式最多工具调用轮次")
    return parser.parse_args()


def print_answer(answer: str, streamed: bool):
    """统一处理 ask / run_agent 的返回值。

    流式模式下回答已逐 token 实时打印过，这里只兜底检查空回答；
    非流式模式（/stream 关闭）则由本函数把返回值打印出来。
    """
    if answer and not streamed:
        print("\n———— 回答 ————")
        print(answer)
    if not answer.strip():
        print("\n（模型没有返回内容：可检查 logs/llama_server.log，或确认模型与上下文配置是否正常）")


def save_session(records: list[tuple[str, str, str]], path: str | None = None) -> Path:
    """把会话记录导出为 Markdown"""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    out = Path(path) if path else LOG_DIR / f"session_{datetime.datetime.now():%Y%m%d_%H%M%S}.md"
    lines = [f"# NetworkClaw 会话记录（{datetime.datetime.now():%Y-%m-%d %H:%M:%S}）", ""]
    for mode, question, answer in records:
        lines += [f"## [{mode}] {question}", "", answer or "（无回答）", ""]
    out.write_text("\n".join(lines), encoding="utf-8")
    return out


async def chat_loop(hub: McpHub, mode: str, show_thinking: bool, stream: bool,
                    max_rounds: int) -> list[tuple[str, str, str]]:
    """交互式对话循环，返回本次会话记录"""
    records: list[tuple[str, str, str]] = []   # [(mode, question, answer)]
    history: list[dict] = []                   # agent 模式的多轮上下文
    last_answer = ""

    while True:
        try:
            raw = input(f"\n[{mode}·{'流式' if stream else '整段'}] 请输入问题（/help 查看命令，q 退出）：").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return records
        if not raw:
            continue
        if raw.lower() in ("q", "quit", "exit"):
            return records

        # ---------------------------------------------------- 斜杠命令
        if raw.startswith("/"):
            cmd, _, rest = raw[1:].partition(" ")
            cmd = cmd.strip().lower()
            if cmd == "help":
                print(HELP_TEXT)
            elif cmd == "tools":
                print(hub.describe_tools())
            elif cmd == "call":
                name, _, arg_text = rest.strip().partition(" ")
                if not name:
                    print('用法：/call 工具名 {"参数": "值"}')
                    continue
                try:
                    args = json.loads(arg_text) if arg_text.strip() else {}
                except json.JSONDecodeError as e:
                    print(f"参数不是合法 JSON：{e}")
                    continue
                print(f"\n[工具结果] {await hub.call_tool(name, args)}")
            elif cmd in ("agent", "rag"):
                mode = cmd
                print(f"已切换到 {mode} 模式")
            elif cmd == "thinking":
                show_thinking = not show_thinking
                print(f"思考过程显示：{'开' if show_thinking else '关'}")
            elif cmd == "stream":
                stream = not stream
                print(f"流式打印：{'开（逐 token 实时打印）' if stream else '关（由主程序打印返回值）'}")
            elif cmd == "last":
                print("\n———— 最近一次回答 ————")
                print(last_answer or "（还没有回答）")
            elif cmd == "save":
                print(f"会话已导出：{save_session(records, rest.strip() or None)}")
            else:
                print(f"未知命令：{raw}（/help 查看全部命令）")
            continue

        # ---------------------------------------------------- 正常提问
        use_agent = mode == "agent" and bool(hub.tools)
        if mode == "agent" and not hub.tools:
            print("（没有可用的 MCP 工具，本次改用 RAG 问答）")

        if use_agent:
            answer = await run_agent(raw, hub, history=history,
                                    max_rounds=max_rounds, show_thinking=show_thinking)
            history += [{"role": "user", "content": raw},
                        {"role": "assistant", "content": answer}]
            del history[:-8]  # 只保留最近 4 轮，避免上下文无限增长
            print_answer(answer, streamed=True)
        else:
            # ask 是同步阻塞调用，放到线程里执行，避免卡住事件循环（MCP 连接保持可用）
            answer = await asyncio.to_thread(ask, raw, show_thinking, stream)
            print_answer(answer, streamed=stream)

        last_answer = answer
        records.append((mode, raw, answer))


async def main():
    args = parse_args()
    proc = None
    try:
        proc = start_llama_server()
        try:
            build_index()
        except RuntimeError as e:
            # 索引不可用不应直接崩掉入口：检索类工具会各自返回错误说明
            print(f"\n[警告] 知识库索引不可用：{e}")
            print("[警告] 本次仍可对话，但知识库 / 命令模板检索会失败；修复后请重启。")

        servers = dict(DEFAULT_SERVERS)
        if args.with_search:
            servers.update(SEARCH_SERVER)

        async with McpHub(servers) as hub:
            print(f"\nMCP 服务端已连接：{', '.join(hub.connected_servers) or '无'}")
            print(hub.describe_tools())
            if args.mode == "rag":
                print("\n当前为 rag 模式：固定知识库检索问答（输入 /agent 可切换到工具模式）")
            print("输入 /help 查看命令，q 退出")

            records = await chat_loop(
                hub, mode=args.mode, show_thinking=not args.no_thinking,
                stream=True, max_rounds=args.max_rounds,
            )
            if records:
                print(f"\n会话已自动保存：{save_session(records)}")
    finally:
        stop_llama_server(proc)
        if proc is not None:
            print("llama-server 已关闭")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print()
