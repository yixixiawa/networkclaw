"""NetworkClaw 统一启动入口（对话 + MCP 工具 + 设备操作 + 图像识别 + 多模型并行）。

流程：
1. 加载模型提供方配置（本地 llama-server / DeepSeek 等），按需启动本地服务
2. 构建 / 校验知识库索引（按内容指纹判断，幂等）
3. 以 stdio 方式连接本地 MCP 服务端，聚合工具清单
   （知识检索 / 命令模板 / 串口 / Telnet / 图像识别）
4. 进入对话循环

三种问答模式（对话中可用 /agent、/rag、/parallel 切换）：
- agent（默认）：把 MCP 工具交给模型，由模型自主决定调用
- rag：固定走「知识库检索 + 流式生成」的单轮问答
- parallel：同一问题并行跑多个模型（本地 + DeepSeek…），必要时先识图，最后融合成一份答案

运行方式（项目根目录下）：
    python main.py                        # 默认 agent 模式，用当前激活的模型提供方
    python main.py --provider deepseek     # 直接用 DeepSeek（需 API Key）
    python main.py --deepseek-key sk-xxx   # 临时提供密钥（更推荐写进 .env 或环境变量）
    python main.py --parallel              # 每轮提问都走多模型并行 + 融合
    python main.py --mmproj                # 自动探测 models/ 下的 mmproj，启用图像识别
    python main.py --mmproj D:\\x\\mmproj-BF16.gguf   # 显式指定视觉投影文件
    python main.py --image topo.png        # 启动时就带上一张拓扑图
    python main.py --mode rag              # 直接进入 RAG 问答
    python main.py --with-search           # 额外接入联网搜索 MCP（需 npx + open-websearch）
    python main.py --no-thinking           # 不打印模型思考过程

设备命令安全（详见 core/command_guard.py）：
    allow   display / show / ping / tracert 等只读命令 → 直接执行
    confirm sysname / vlan / interface 等配置命令     → 需用户同意后使用 confirmation_token
    block   undo / shutdown / delete / reset / reboot → 直接拦截
"""
from __future__ import annotations


import argparse
import asyncio
import datetime
import json
import os
from pathlib import Path

from core.agent import run_agent
from core.conversation_service import ConversationService
from core.llama_start import (BASE_DIR, find_mmproj, is_server_running, mmproj_hint,
                              start_llama_server, stop_llama_server)
from core.llm_client import ProviderError
from core.parallel import run_multimodal_parallel
from core.providers import (describe_table, get_active, get_provider, list_providers,
                            load_env_file, load_providers, set_active)
from core.rag import ask, build_index
from core import device_manual, session_skills
from core.vision import vision_status
from core.local_service import LocalService
from core.session_export import build_document, export_markdown
from mcp_tools.client import DEFAULT_SERVERS, SEARCH_SERVER, McpHub

LOG_DIR = BASE_DIR / "logs"

HELP_TEXT = """
可用命令：
  /help               显示本帮助
  /model [名称]       查看/切换模型提供方（local / deepseek-flash / glm-4.6 / kimi-k2.5 …）
  /key                查看各云端提供方的主/备用 Key 状态（不回显）
  /key sk-xxx         设置 DeepSeek 主 Key（兼容旧用法；更推荐写进 .env 或环境变量）
  /key glm-4.6 sk-xxx 设置指定提供方的主 Key
  /key glm-4.6 alt sk-xxx  设置指定提供方的备用 Key（主 Key 被拒时自动启用）
  /parallel [列表]    开关多模型并行：不带参数切换；/parallel local,deepseek 指定组合；
                      /parallel off 关闭。开启时先识图（如有），再并行回答并融合
  /tools              列出已接入的 MCP 工具
  /call 工具名 {json}  直接调用某个 MCP 工具，例如：
                        /call exec_command {"command":"display version","port":"COM3"}
                        /call exec_telnet_command {"command":"display version","host":"192.168.183.200","username":"admin","password":"xxx"}
  /image [路径]       附加一张图片（拓扑截图）到后续提问；/image clear 取消
  /vision             查看图像识别能力状态（是否已加载 mmproj）
  /topology [关键字]  现在看一眼当前拓扑：截取 eNSP/虚拟机窗口并识读（结果自动入库）
  /autovision on|off  开关启动时的自动拓扑巡检（本次会话内生效）
  /audit [n]          查看最近的设备命令审计记录
  /sessions           查看所有对话各自的设备技能（一个对话一套技能，相互隔离）
  /agent              切换到 agent 模式（模型自主调用 MCP 工具）
  /rag                切换到 rag 模式（固定知识库检索问答）
  /thinking           开关模型思考过程显示
  /stream             开关流式打印（关闭后由主程序打印 ask 的返回值）
  /last               重新显示最近一次回答
  /save [路径]        把本次会话导出为 Markdown（默认 logs/session_<时间>.md）
  q / exit            退出
"""


def parse_args():
    parser = argparse.ArgumentParser(description="NetworkClaw 对话入口（RAG + MCP + 设备 + 视觉 + 多模型）")
    parser.add_argument("--mode", choices=["agent", "plan"], default="agent",
                        help="启动模式，默认 agent（统一对话入口：模型自主调用工具 + 内置知识检索）"
                             "；plan 为拓扑规划模式（只读探测 + 手册沉淀）")
    parser.add_argument("--provider", default=None, metavar="名称",
                        help="模型提供方：local / deepseek-flash / deepseek-pro，默认用配置里的激活项")
    parser.add_argument("--deepseek-key", default=None, metavar="sk-xxx",
                        help="临时指定 DeepSeek API Key（未设置 DEEPSEEK_API_KEY 时用）")
    parser.add_argument("--deepseek-model", default=None, metavar="模型名",
                        help="覆盖 DeepSeek Flash 模型名（默认 deepseek-flash）")
    parser.add_argument("--parallel", action="store_true",
                        help="每轮提问都走多模型并行 + 融合（等效于启动后执行 /parallel）")
    parser.add_argument("--parallel-providers", default=None, metavar="列表",
                        help="并行使用的提供方，逗号分隔，如 local,deepseek")
    parser.add_argument("--mmproj", nargs="?", const="auto", default=None, metavar="路径",
                        help="启用图像识别：加载视觉投影文件（mmproj）。"
                             "不带值表示自动探测 models/ 下的 *mmproj*.gguf")
    parser.add_argument("--image", action="append", default=[], metavar="路径",
                        help="启动时预载图片（拓扑截图），可多次指定；等效于先执行 /image")
    parser.add_argument("--with-search", action="store_true",
                        help="额外接入联网搜索 MCP 服务端（需 npx + open-websearch）")
    parser.add_argument("--no-thinking", action="store_true", help="不打印模型思考过程")
    parser.add_argument("--no-auto-vision", action="store_true",
                        help="关闭启动时的自动拓扑巡检（默认开启：自动截取 eNSP/虚拟机窗口"
                             "并识读当前拓扑，结论供后续对话引用）")
    parser.add_argument("--capture-keyword", default=None, metavar="关键字",
                        help="自动巡检的目标窗口关键字（如 vmware / ensp），默认按内置表匹配")
    parser.add_argument("--max-rounds", type=int, default=4,
                        help="agent 模式最多工具调用轮次，默认 4（设备操作需要更多轮）")
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
    document = build_document(records, title="NetworkClaw 会话记录")
    return export_markdown(document, out)


# 本地 llama-server 的按需管理（LocalService）已抽到 core/local_service.py，
# 与 GUI 共用同一套「复用已有实例、退出只关自己拉起的那个」语义。
# 本模块通过上面的 import 继续对外提供 main.LocalService（向后兼容）。


def _provider_tag(name: str) -> str:
    try:
        return get_provider(name).name
    except KeyError:
        return name


async def chat_loop(hub: McpHub, mode: str, show_thinking: bool, stream: bool,
                    max_rounds: int, local: LocalService,
                    provider_name: str, parallel: bool = False,
                    parallel_providers: list[str] | None = None,
                    images: list[str] | None = None) -> list[tuple[str, str, str]]:
    """交互式对话循环，返回本次会话记录"""
    records: list[tuple[str, str, str]] = []   # [(mode, question, answer)]
    history: list[dict] = []                   # agent 模式的多轮上下文
    conversation = ConversationService(hub)
    last_answer = ""
    images = list(images or [])                # 附加图片（拓扑截图），随每次提问送出
    parallel_providers = list(parallel_providers or [])

    def current_mode() -> str:
        return "parallel" if parallel else mode

    while True:
        tag = f"[{current_mode()}·{_provider_tag(provider_name)}·{'流式' if stream else '整段'}]"
        if images:
            tag += f"[已附图片 {len(images)}]"
        try:
            raw = input(f"\n{tag} 请输入问题（/help 查看命令，q 退出）：").strip()
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
            elif cmd == "model":
                target = rest.strip()
                if not target:
                    print(describe_table(active=provider_name))
                    print(f"\n当前激活：{provider_name}")
                else:
                    try:
                        prov = set_active(target)
                    except KeyError as e:
                        print(f"{e.args[0] if e.args else e}")
                        continue
                    provider_name = prov.name
                    try:
                        from core import user_config

                        user_config.set_active_model(prov.name)
                    except OSError:
                        pass
                    print(f"已切换到 {prov.label}（{prov.model}）")
                    if prov.needs_key and not prov.api_key_value:
                        print(f"[警告] 该提供方还没有 API Key：请设置环境变量 "
                              f"{prov.api_key_env or 'DEEPSEEK_API_KEY'}，"
                              f"或在对话中用 /key sk-xxx 临时设置")
                    if prov.kind == "local" and not local.running:
                        print("本地 llama-server 未运行，正在启动…")
                        try:
                            local.ensure()
                        except Exception as e:
                            print(f"[警告] 本地服务启动失败：{type(e).__name__}: {e}")
                    if prov.supports_vision is False and images:
                        print(f"[提示] {prov.name} 不看图；已附图片将由本地视觉模型识读后"
                              f"以文字形式提供给它（多模态桥接）")
            elif cmd == "key":
                # 用法：
                #   /key                     看各云端提供方的主/备用 Key 状态（不回显）
                #   /key sk-xxx              兼容旧用法：设置 DeepSeek 主 Key
                #   /key glm-4.6 sk-xxx      设置指定提供方的主 Key
                #   /key glm-4.6 alt sk-xxx  设置指定提供方的备用 Key
                parts = rest.split()
                if not parts:
                    for p in list_providers():
                        if not p.needs_key:
                            continue
                        main = "✓" if p.api_key_value else "✗"
                        alt = "✓" if p.api_key_alt_value else "✗"
                        print(f"  {p.name:<16} 主{main} 备用{alt}"
                              f"（{p.api_key_env or '—'} / {p.api_key_alt_env or '—'}）")
                    print("用法：/key <提供方> [alt] <密钥>；不带参数看状态")
                else:
                    if len(parts) == 1:
                        target, key, is_alt = "deepseek-flash", parts[0], False
                    elif parts[1].lower() in ("alt", "backup", "备用") and len(parts) >= 3:
                        target, key, is_alt = parts[0], parts[2], True
                    else:
                        target, key, is_alt = parts[0], parts[1], False
                    try:
                        prov = get_provider(target)
                    except KeyError as e:
                        print(e.args[0] if e.args else e)
                        prov = None
                    if prov is not None and not prov.needs_key:
                        print(f"{prov.label} 无需密钥")
                    elif prov is not None:
                        slot = "备用" if is_alt else "主"
                        try:
                            from core import user_config

                            if is_alt:
                                path = user_config.set_api_key_alt(
                                    prov.name, key, api_key_alt_env=prov.api_key_alt_env)
                            else:
                                path = user_config.set_api_key(
                                    prov.name, key, api_key_env=prov.api_key_env)
                            print(f"已保存 {prov.name} 的{slot} Key"
                                  f"（持久化到 {path}，不回显）")
                        except OSError as e:
                            print(f"密钥已用于本次运行，但持久化失败：{e}")
                        load_providers(refresh=True)
            elif cmd == "parallel":
                target = rest.strip().lower()
                if target in ("off", "close", "0"):
                    parallel = False
                    print("已关闭多模型并行")
                elif target:
                    names = [s.strip() for s in rest.split(",") if s.strip()]
                    bad = []
                    for n in names:
                        try:
                            get_provider(n)
                        except KeyError:
                            bad.append(n)
                    if bad:
                        print(f"未知的提供方：{', '.join(bad)}（可用："
                              f"{', '.join(p.name for p in list_providers())}）")
                        continue
                    parallel_providers = names
                    parallel = True
                    print(f"已开启多模型并行：{', '.join(names)}（每轮提问都会并行调用并融合）")
                else:
                    parallel = not parallel
                    if parallel:
                        print("已开启多模型并行（/parallel local,deepseek 可指定组合；"
                              "/parallel off 关闭）")
                    else:
                        print("已关闭多模型并行")
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
            elif cmd == "image":
                target = rest.strip()
                if not target:
                    print("已附加图片：" + ("\n  ".join(images) if images else "（无）"))
                elif target.lower() in ("clear", "none", "-", "off"):
                    images.clear()
                    print("已取消附加图片")
                else:
                    p = Path(target.strip('"').strip("'")).expanduser()
                    if not p.is_file():
                        print(f"图片不存在：{p}")
                    else:
                        images.append(str(p))
                        print(f"已附加图片：{p}（对后续每个问题生效，/image clear 取消）")
                        status = vision_status()
                        if status["available"] is not True:
                            print(f"[提示] 图像识别能力状态：{status['detail']}")
                            if status["available"] is False:
                                print(f"[提示] {mmproj_hint()}")
            elif cmd == "vision":
                status = vision_status()
                found = find_mmproj()
                active = get_provider(provider_name)
                print(f"图像识别：{'可用' if status['available'] else ('待确认' if status['available'] is None else '不可用')}")
                print(f"  判据：{status['detail']}")
                print(f"  mmproj：{found if found else '未找到'}")
                print(f"  当前模型 {active.name}：{'支持图片' if active.supports_vision else '不支持图片（走多模态桥接）'}")
                if not found:
                    print("  " + mmproj_hint().replace("\n", "\n  "))
            elif cmd == "topology":
                # 现场看一眼当前拓扑：截图 → 本地识读 → 快照落盘（自动注入后续对话）
                from core import auto_topology

                if find_mmproj() is None:
                    print(f"[提示] {mmproj_hint()}")
                    continue
                try:
                    local.ensure(require_vision=True)
                    kw = rest.strip() or None
                    r = await asyncio.to_thread(
                        auto_topology.auto_inspect, kw, None, True, show_thinking)
                    print(auto_topology.render_result(r))
                except Exception as e:
                    print(f"[失败] {type(e).__name__}: {e}")
            elif cmd == "autovision":
                arg = rest.strip().lower()
                if arg in ("on", "开", "1", "true"):
                    print("自动拓扑巡检：已开启（下次启动时生效；本次可用 /topology 立即执行）")
                elif arg in ("off", "关", "0", "false"):
                    print("自动拓扑巡检：已关闭（本次会话不再自动执行；"
                          "持久关闭请启动时加 --no-auto-vision）")
                else:
                    print("用法：/autovision on|off（持久配置用 --no-auto-vision 或设置项）")
            elif cmd == "audit":
                n = rest.strip() or "10"
                print("[审计] " + (await hub.call_tool("recent_audit", {"n": int(n) if n.isdigit() else 10})))
            elif cmd == "sessions":
                # 设备技能按对话隔离：这里看所有对话各有什么，以及当前对话的技能
                print(f"[当前会话] {session_skills.describe()}")
                rows = device_manual.sessions_overview()
                if not rows:
                    print("  （还没有任何对话产生过设备技能）")
                for s in rows:
                    mark = "← 当前" if s["current"] else ""
                    devs = "、".join(s["detail"]) or "（无设备技能）"
                    print(f"  [{s['sid']}] 更新于 {s['updated']} {mark}")
                    print(f"      {devs}")
                manuals = device_manual.list_manuals()
                if manuals:
                    print("本对话已建档设备："
                          + ", ".join(f"{m['name']}（{m['history_lines']} 条历史）" for m in manuals))
                else:
                    print("本对话暂未建档任何设备（首次接触设备时会自动建档）")
            elif cmd in ("agent", "rag", "plan"):
                # rag 已并入统一入口（agent 内置知识检索），保留 /rag 仅作兼容别名
                mode = "agent" if cmd == "rag" else cmd
                parallel = False
                print(f"已切换到 {mode} 模式（已关闭并行）")
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
        try:
            async def request_confirmation(pending: dict) -> str | None:
                print("\n[需要确认] 目标：" + str(pending.get("target", "")))
                print("命令：" + str(pending.get("command", "")))
                choice = await asyncio.to_thread(input, "确认执行？输入 yes 执行，其它取消：")
                if choice.strip().lower() not in {"y", "yes", "是"}:
                    return None
                from core.confirmation import approve_request

                return approve_request(str(pending.get("request_id", "")))

            result = await conversation.run(
                raw, mode=mode, provider=provider_name, history=history,
                images=images, parallel_providers=parallel_providers,
                max_rounds=max_rounds, show_thinking=show_thinking,
                parallel=parallel, stream=stream, on_log=print,
                on_confirmation=request_confirmation,
            )
            answer = result.answer
            if result.meta.get("kind") in ("agent", "plan"):
                history += [{"role": "user", "content": raw},
                            {"role": "assistant", "content": answer}]
                del history[:-8]
            print_answer(answer, streamed=stream)
        except ProviderError as e:
            # 模型侧失败（密钥/余额/限流/断网）不应打断会话，提示后继续下一轮
            print(f"\n[调用失败] {e}")
            print("（本次不计入会话记录；可用 /model 换提供方，或检查密钥与网络后重试）")
            continue
        except Exception as e:
            print(f"\n[出错] {type(e).__name__}: {e}")
            print("（本次不计入会话记录，可重试或换个问题）")
            continue

        last_answer = answer
        records.append((current_mode(), raw, answer))


async def main():
    args = parse_args()

    # ---------------------------------------------------------- 提供方准备
    load_env_file()
    if args.deepseek_key:
        os.environ["DEEPSEEK_API_KEY"] = args.deepseek_key.strip()
    if args.deepseek_model:
        os.environ["DEEPSEEK_MODEL"] = args.deepseek_model.strip()
    load_providers(refresh=True)

    if args.provider:
        try:
            set_active(args.provider)
        except KeyError as e:
            print(f"[错误] {e.args[0] if e.args else e}")
            return
    active = get_active()
    print(describe_table(active=active.name))
    if active.needs_key and not active.api_key_value:
        print(f"\n[提示] 当前提供方 {active.name} 还没有 API Key。"
              f"设置方法：项目根 .env 写入 DEEPSEEK_API_KEY=sk-xxx，"
              f"或对话中用 /key sk-xxx，或启动时加 --deepseek-key sk-xxx")

    parallel_providers = ([s.strip() for s in args.parallel_providers.split(",") if s.strip()]
                          if args.parallel_providers else [])

    # ---------------------------------------------------------- 会话（一个对话一套技能）
    # 设备技能按会话隔离：session/<sid>/skill/<设备名>/。每次启动就是一个新对话，
    # 因此这里现开一个 sid 并写进 session/.current——MCP 服务端是独立子进程，
    # 它们每次工具调用前读同一份指针，读写立刻落到本会话的技能目录上。
    # 运行日志也切到同一 sid（tools/lab_run_agent.py 跑实验时同样处理）。
    chat_sid = session_skills.new_sid("cli")
    session_skills.use_session(chat_sid)
    print(f"[会话] 本次对话标识 {chat_sid}；设备技能存放于 "
          f"session/{chat_sid}/skill/<设备名>/（与其他对话相互隔离，可用 /sessions 查看）")

    # ---------------------------------------------------------- 本地服务准备
    want_vision = args.mmproj is not None
    if want_vision and find_mmproj(args.mmproj) is None:
        print(f"\n[警告] {mmproj_hint()}")
        print("[警告] 本次无图像识别能力（多模态桥接与 /image 会失败）。")

    need_local = (active.kind == "local") or want_vision or bool(args.image)
    local = LocalService(args.mmproj)
    if need_local:
        local.ensure(require_vision=want_vision)
    else:
        print(f"\n当前提供方为云端模型（{active.name}），跳过启动本地 llama-server 以节省内存。\n"
              "如需图像识别或本地模型：/model local（会按需启动），或启动时加 --mmproj")

    try:
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
            if hub.failed_servers:
                print(f"MCP 连接失败：{', '.join(hub.failed_servers)}")
            print(hub.describe_tools())

            images = []
            for item in args.image or []:
                p = Path(item).expanduser()
                if p.is_file():
                    images.append(str(p))
                    print(f"\n已预载图片：{p}")
                else:
                    print(f"\n[警告] --image 指定的图片不存在：{p}")

            if want_vision:
                status = vision_status()
                print(f"图像识别状态：{'可用' if status['available'] else ('待确认' if status['available'] is None else '不可用')}"
                      f"（{status['detail']}）")

            # ------------------------------------------------ 自动拓扑巡检
            # 默认开启（--no-auto-vision 关闭）：截取 eNSP/虚拟机窗口 → 本地模型
            # 识读 → 快照落盘。执行前打印 notice 明确告知用户，保证自动化透明。
            if not args.no_auto_vision:
                if find_mmproj(args.mmproj) is None:
                    print(f"\n[自动拓扑巡检] 未执行：{mmproj_hint()}")
                else:
                    from core import auto_topology

                    print("\n" + auto_topology.notice(args.capture_keyword))
                    try:
                        local.ensure(require_vision=True)
                        state = vision_status()
                        if state["available"] is False:
                            print(f"[自动拓扑巡检] 跳过：当前 llama-server 未加载 mmproj"
                                  f"（{state['detail']}）。kill 旧实例后重启本程序即可。")
                        else:
                            r = auto_topology.auto_inspect(
                                keyword=args.capture_keyword,
                                show_thinking=not args.no_thinking)
                            print(auto_topology.render_result(r))
                    except Exception as e:
                        print(f"[自动拓扑巡检] 失败：{type(e).__name__}: {e}（不影响后续对话）")

            if args.mode == "plan":
                print("\n当前为 plan 模式：为各设备预先准备拓扑信息（只读探测 + 手册沉淀，"
                      "输入 /agent 可切回普通对话）")
            if args.parallel:
                print(f"已开启多模型并行"
                      f"{'：' + ', '.join(parallel_providers) if parallel_providers else ''}"
                      f"（/parallel off 关闭）")
            print("输入 /help 查看命令，q 退出")

            records = await chat_loop(
                hub, mode=args.mode, show_thinking=not args.no_thinking,
                stream=True, max_rounds=args.max_rounds, local=local,
                provider_name=active.name, parallel=args.parallel,
                parallel_providers=parallel_providers, images=images,
            )
            if records:
                print(f"\n会话已自动保存：{save_session(records)}")
    finally:
        local.stop()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print()
