"""Agent 模式：让模型在回答前自主调用 MCP 工具。

流程：
用户问题 → 带工具定义请求模型 → 模型返回 tool_calls
→ 通过 McpHub 执行工具 → 结果回填为 tool 消息 → 继续生成
→ 直到模型给出最终回答（最多 max_rounds 轮；轮次用尽则去掉工具强制收口）

与 core.rag 的分工：
- core.rag：固定「先检索知识库、再生成」的单轮问答
- core.agent：模型自主决定是否检索、检索什么（知识库 / 命令模板 / 联网 / 设备 / 识图）

多提供方：
- provider 参数决定这一轮用本地模型还是云端（DeepSeek 等）
- 若当前提供方不看图、但本轮带了图片，则先用「能看图的提供方」（本地多模态模型）
  把图转成文字结论再注入对话——这就是「多模态协作」的最小落地：
  视觉能力留在本地（拓扑图不外传），文本推理可以交给云端。
"""
from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable

from core.llm_client import print_stats, stream_chat
from core.providers import Provider, get_provider, vision_capable
from core.vision import VISION_BRIDGE_PREFIX, build_user_content, describe_images

SYSTEM_PROMPT = """你是 NetworkClaw 网络运维助手，服务对象是网络工程师。你可以调用以下工具：

【知识类】
- query_command_template：按厂商（Huawei/H3C/Cisco）、设备类型（switch/router/both）和意图检索命令模板
- search_knowledge：检索知识库中的设备介绍、配置说明
- search：联网搜索（仅在已接入时可用）

【设备操作类】
- list_serial_ports：列出可用串口（要用串口前先查）
- exec_command：通过**串口（Console）**在设备上执行一条命令
- check_telnet：探测设备 Telnet 端口是否可达（只读）
- exec_telnet_command：通过 **Telnet** 登录设备执行一条命令
- recent_audit：查看最近的命令执行审计记录

【设备手册类】（每台设备一份手册，由你在运行期自建自维护，保存在本机而非代码仓库）
- list_device_manuals：查看哪些设备已有手册、哪些还没建档
- read_device_manual：操作某台设备前先读它的手册（常用配置、注意事项）
- create_device_manual：首次接触某台设备时给它建档（骨架自动生成，你只需填已知信息）
- update_device_manual_section：把验证有效的命令序列、踩过的坑写回手册
- recent_device_history：查看某台设备最近的命令历史（命令执行后由工具自动记录，你不需要手写）
- list_session_skills：查看**所有对话**各自的设备技能分布（只读，用于回答「上次那个会话里」）

【数据报告类】（把一次工作流汇总成报告，跑完实验/配置后导出）
- export_workflow_report：导出**整个工作流**的报告（设备技能、逐条命令历史、
  逐步的工具调用与设备回显、验收结论），输出 Markdown / JSON 文件
- workflow_report_overview：只看统计摘要（设备数、手册数、命令数、调用次数），不写文件
- list_report_sessions：列出可导出报告的会话（哪些对话跑过）

【设备技能的隔离规则（一个对话一套技能，必须遵守）】
· 手册与命令历史按会话隔离存放：session/<当前会话>/skill/<设备名>/。
  你只能看到并维护**当前对话**里的设备记忆，其他对话的技能不会注入、也检索不到——
  这是刻意设计，避免把别处对话的结论当成本对话的经验。
· 因此：不要假设某台设备「以前配过」，以本会话里 read_device_manual 的实际内容为准；
  本会话没有该设备手册时，按首次接触处理（create_device_manual 建档）。
· 用户明确问「上次/另一个会话里」时，才用 list_session_skills 查看分布，
  并用 read_device_manual(device, session="<会话标识>") 显式读取那个会话的手册。

【拓扑发现类】（泛洪只读命令，自动发现设备之间的连线与上下级关系）
- discover_topology：逐台登录设备泛洪 display lldp neighbor / mac-address / arp，
  自动推导「谁连谁、谁是上级」并出 Mermaid 图（耗时较长，每台一次完整登录）
- load_discovered_topology：读取上次发现结果（不重新探测，秒回）
- topology_summary：只要紧凑摘要（层级 + 链路 + 上下级），适合直接引用
- topology_mermaid：只要 Mermaid 图源码，便于贴给用户渲染

【图像类】
- vision_ready：检查识图能力是否就绪
- list_local_images：用户提到截图但没给路径时，用它找图
- analyze_topology_image：识读用户提供的拓扑图，得到设备清单、连接关系、IP/网段与风险点
- capture_topology：实时查看当前拓扑——自动截取 eNSP/虚拟机窗口画面并识读
  （用户没给截图、或说拓扑已变化时用；会短暂占用目标窗口）
- get_topology_snapshot：读取最近一次自动巡检的拓扑结论（瞬时返回，优先用它）

工作方式：
1. 【配置前必查（硬性规则）】在执行/给出任何**配置类命令**（会改变设备状态的命令）之前，
   必须先做其中之一来确认命令写法正确：
   ① 调用 search_knowledge 检索知识库；② read_device_manual 读取该设备的 SKILL.md；
   ③ query_command_template 查权威命令模板。
   禁止凭记忆直接下发配置命令——写错的配置可能让设备失联。
   纯只读命令（display / show / ping / tracert）不受此限制。
2. 涉及具体配置命令的问题，先调用 query_command_template 取得权威命令模板，再组织答案；
3. 涉及设备型号、产品能力、功能原理的问题，先调用 search_knowledge；
4. 用户提到「当前拓扑 / 现在的网络 / 谁连谁 / 上下级关系」时，按可信度从高到低取用：
   ① 先用 topology_summary 或 load_discovered_topology 看有没有**实测**结论
      （由 discover_topology 泛洪 LLDP/MAC 得到，设备自己报的，最可信）；
   ② 没有实测结果、或实测明显过期（设备刚改过接线）时，用 discover_topology 重新探测
      —— **注意它是只读操作**（只下发 display/show），可以直接调用，无需用户确认；
      但每台设备要完整登录一次，较慢，所以优先复用已有结果；
   ③ 没有实测条件（设备够不着 / 未开 LLDP）才退到看图：get_topology_snapshot 取现成结论，
      过期或不全再用 capture_topology 实时识读；用户明确给了截图才用 analyze_topology_image；
   ④ 实测与图片结论冲突时**以实测为准**，并说明「LLDP 实测显示…，与图中标注不一致」；
   ⑤ 需要给用户看图时调 topology_mermaid 输出 Mermaid 源码（用户可直接渲染）。
5. 需要登录设备操作时，**连接参数（COM 口、IP、用户名、密码）必须由用户提供，不得自行猜测或臆造**；
6. 最终回答要给出可直接粘贴到设备上的命令，并标明配置视图（模式）；
7. 工具结果优先于你的自身记忆；工具没有结果时明确说明"模板库/知识库中未找到"，不要编造命令。

【设备手册工作流（先读手册 → 后动手 → 再沉淀）】
8. 要操作/配置某台设备时：
   ① 先 list_device_manuals 看它有没有手册；没有就用 create_device_manual 建档
      —— device 用设备名（用户没给名字时按型号命名：S57/S37 等交换机型为 SW<n>，AR 系列为 R<n>，
      n 接续已有最大编号），并传 transport/host/port（或 serial_port）把名字绑定到地址，
      这样后续命令历史会自动归到该设备名下；
   ② 动手前 read_device_manual 读它的「常用配置」与「注意事项」，避免重复试错；
   ③ 命令验证有效后，用 update_device_manual_section 把命令序列（含顺序与适用场景）
      写进「常用配置」，把发现的坑写进「注意事项」；
   ④ 每条命令的历史由工具自动写入当前会话的 session/<会话标识>/skill/<设备名>/history.jsonl，
      **不要手工造历史**。
9. 手册内容只能来自工具结果、用户提供的信息或拓扑识读结论；不确定的字段留空写成「待确认」，
   严禁编造型号、IP、接口号。

【数据报告工作流（跑完就导出）】
10. 当一个任务/实验**已经跑完**（配置下发完成、验证做过、结论已给）时：
   ① 用 workflow_report_overview 快速确认「这次涉及哪些设备、下发过多少命令」；
   ② 再用 export_workflow_report 导出完整报告（默认 markdown），
      并把返回的文件路径告诉用户——报告里含每台设备的命令序列与逐步回显，
      用户凭这份文件就能复盘整个过程，不需要你再复述细节。
   ③ 报告默认只覆盖**当前对话**；用户明确要求复盘别的对话时才传 session 参数。
   ④ 别在任务中途导出（内容不全）；也别反复导出（每次都会生成新文件）。

【设备命令安全红线（必须严格遵守）】
工具层对命令做了三级管控，你必须在规则内工作：
- **允许直接执行**：display / show / ping / tracert 等只读命令。可以自由调用，用于查看现状与验证。
- **必须先确认再执行**：sysname、vlan、interface、ip、ospf、acl、aaa 等一切会改变配置的命令。
  流程是：① 先把「要执行哪条命令、在哪台设备的什么视图下、会产生什么影响」讲给用户；
  ② GUI 展示待确认请求并取得用户明确同意后，使用一次性 confirmation_token 重试工具。
      单独设置 confirm=true 不能授权执行。
- **禁止执行**：undo、no、shutdown、delete、reset、reboot、reload、save/write 等破坏性或持久化命令。
  工具会直接拦截，**不要尝试改写、拼接、拆分或绕开**这些命令。
- 单次只执行一条命令，不要用分号把多条命令串起来下发（工具会按多命令逐条裁决，仍属违规用法）；
- 执行配置类命令后，建议用 display 类只读命令回读验证，并把结果告诉用户。
"""

VISION_BRIDGE_PREFIX = VISION_BRIDGE_PREFIX  # 兼容旧引用（实现在 core/vision.py）


# ---------------------------------------------------------------- PLAN 模式
PLAN_SYSTEM_PROMPT = """你是 NetworkClaw 的拓扑规划助手（PLAN 模式）。你的任务是**为各台设备
预先准备拓扑信息**，为后续配置对话打底，本轮不做任何配置变更。

目标（按顺序执行，全部是只读操作）：
1. 清点设备：列出本次要规划的设备（用户提供名单；没给就用 list_device_manuals +
   注册表里可查询的设备），逐台确认连接方式（Telnet 地址 / 串口）。
2. 发现拓扑：用 discover_topology 做一次完整探测（LLDP/MAC 泛洪，只读），
   得到「谁连谁、谁是上级」；已有新鲜快照时用 topology_summary / load_discovered_topology 复用。
3. 逐台抓配置：对每台设备执行只读命令 `display current-configuration`
   （以及需要时的 `display lldp neighbor brief` / `display version`），
   摸清每台设备的 VLAN、接口、IP 与角色。
4. 沉淀到手册：对每台设备确保建档（没有就 create_device_manual），然后用
   update_device_manual_section 把本次得到的结论写进「拓扑关系」小节：
   - 上下游邻居（上级是谁、下级是谁、互联接口）
   - 本设备承担的角色（接入/汇聚/出口…）与关键 VLAN/网段
   - 与实测拓扑、图片拓扑不一致的地方要明确标注
5. 收口：输出一份紧凑的规划摘要——层级图（Mermaid 源码）、每台设备一句话角色、
   建议的下一步配置顺序（只建议，不执行）。

约束：
- 本轮只允许只读命令（display / show / ping / tracert）与手册读写工具；
  任何配置类命令都不要执行，也不要建议用户立即执行——给用户留确认空间。
- 手册内容只能来自工具回显与实测结果，不得臆造；不确定写「待确认」。
- 每台设备的手册写完一句即可，避免重复贴大段配置原文（配置原文在 history.jsonl 可查）。
"""


# ---------------------------------------------------------------- 内置工具
#: search_knowledge 的内置定义。search_knowledge 本身是 MCP 工具
#（Network-Knowledge 服务端），但「统一对话入口」要求它在任何情况下都可用：
# hub 未连接 / MCP 子进程启动失败 / 服务端被裁剪时，问答仍必须能检索知识库，
# 否则「配置前必查」这条硬性规则就没有抓手。因此这里内置一份兜底实现。
BUILTIN_SEARCH_KNOWLEDGE = {
    "type": "function",
    "function": {
        "name": "search_knowledge",
        "description": "检索知识库中的设备介绍、配置说明与实验规则。"
                       "在执行配置类命令前应先调用本工具或读取设备 SKILL.md 确认命令写法。"
                       "（内置兜底：即使 MCP 服务端不可用也可用）",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string",
                          "description": "检索问题，例如“S5700 适用什么场景”"},
                "top": {"type": "integer", "description": "返回片段数，默认 3"},
            },
            "required": ["query"],
        },
    },
}


def _builtin_search_knowledge(query: str, top: int = 3) -> str:
    """search_knowledge 的本地兜底实现：与 MCP 工具同一套检索逻辑（core.rag）。"""
    from core.rag import build_index as build_knowledge_index
    from core.rag import retrieve_ex

    try:
        if not str(query).strip():
            return "query 不能为空"
        build_knowledge_index()  # 幂等：指纹一致时自动跳过
        res = retrieve_ex(str(query).strip(), n_results=max(1, int(top or 3)))
        if not res.ok:
            if res.degraded:
                return (f"⚠ 知识库检索不可用（{res.status}）：{res.reason}\n"
                        f"这不是「知识库中没有相关内容」，而是检索链路故障。"
                        f"请明确告知用户检索失败，不要凭记忆编造命令或结论。"
                        f"（修复：启动 Ollama 并执行 ollama pull nomic-embed-text）")
            return f"知识库中没有找到与「{query}」相关的内容（{res.reason}）"
        lines = [f"问题「{query}」检索到 {len(res.chunks)} 个知识片段："]
        for i, doc in enumerate(res.chunks, 1):
            lines.append(f"[{i}] {doc}")
        return "\n\n".join(lines)
    except Exception as e:  # noqa: BLE001  兜底工具不抛异常
        return f"知识库检索失败：{type(e).__name__}: {e}"


def _loads_arguments(raw: str) -> dict:
    """工具参数由模型生成，是 JSON 字符串，需要容错解析"""
    if not raw or not raw.strip():
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {"_raw": raw}
    return data if isinstance(data, dict) else {"value": data}


def _preview(text: str, limit: int = 300) -> str:
    """工具结果预览：过长则截断显示（完整内容仍会回填给模型）"""
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return text[:limit] + f"...（共 {len(text)} 字，此处截断显示）"


def _confirmation_request(text: str) -> dict | None:
    marker = "__NETWORKCLAW_CONFIRM__"
    if marker not in (text or ""):
        return None
    raw = text.split(marker, 1)[1].strip()
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) and value.get("request_id") else None


def _flooded_topology_context(max_chars: int = 1200) -> str:
    """注入「实测拓扑」——由 core/topology_flood 泛洪 LLDP/MAC 发现的结果。

    与 auto_topology（图片识读）的区别：那是"看图猜的"，这是"设备自己报的"，
    可信度更高。两者都注入时，提示词里明确要求模型以实测为准。
    """
    try:
        from core import topology_flood

        topo = topology_flood.load_snapshot()
        if topo is None or not topo.devices:
            return ""
        age = topology_flood.snapshot_age_min()
        body = topology_flood.context_for_model(topo, max_chars=max_chars)
        head = ("\n\n【实测拓扑（LLDP/MAC 泛洪发现，可信度高于图片识读；"
                "与图片结论冲突时以本段为准）】\n")
        if age is not None:
            body += f"\n（快照约 {age} 分钟前生成；需要最新状态时调用 discover_topology 重新探测）"
        return head + body
    except Exception:
        return ""


def _session_skill_context(max_chars: int = 4000) -> str:
    """注入「本会话已积累的设备技能」——按对话隔离的设备记忆。

    为什么不走向量库检索：手册按会话隔离（session/<sid>/skill/<设备>/），而
    索引是全局单份，塞进去就会在切换会话后串味。因此这里直注当前会话的摘要，
    全文按需用 MCP 工具 read_device_manual 读。
    """
    try:
        from core import device_manual

        return device_manual.context_for_model(max_chars=max_chars)
    except Exception:
        return ""


def _bridge_images(images: list[str], provider: Provider,
                   question: str, vision_prov: Provider | None = None) -> str:
    """用能看图的提供方把图片转成文字描述（多模态桥接）。

    具体实现在 core/vision.describe_images（GUI 也用同一份逻辑）；
    返回空串表示桥接失败（调用方会退化为纯文本提问）。
    """
    if vision_prov is None and not provider.supports_vision:
        vision_prov = vision_capable()
    if vision_prov is None:
        print("[警告] 当前提供方不看图，且没有可用的视觉提供方，本轮忽略图片")
        return ""
    print(f"[多模态桥接] 目标模型 {provider.name} 不看图，改由 {vision_prov.name} 识读")
    return describe_images(images, question=question, provider=vision_prov)


async def run_agent(query: str, hub, history: list[dict] | None = None,
                    max_rounds: int = 4, show_thinking: bool = True,
                    images: list[str] | None = None,
                    provider: str | Provider | None = None,
                    vision_provider: str | Provider | None = None,
                    on_think: Callable[[str], None] | None = None,
                    on_answer: Callable[[str], None] | None = None,
                    system_prompt: str | None = None,
                    on_step: Callable[[dict], None] | None = None,
                    session: str = "",
                    on_confirmation: Callable[[dict], Awaitable[str | None]] | None = None) -> str:
    """带工具调用的问答循环，返回最终回答文本。

    Args:
        query: 用户问题
        hub: McpHub 实例（已连接）。**允许为 None**：统一对话入口要求问答在任何
            环境都能走 agent 通路，此时仅挂载内置 search_knowledge 兜底工具。
        history: 之前的对话消息（{"role","content"} 列表），用于多轮上下文
        max_rounds: 最多允许的工具调用轮次
        show_thinking: 是否实时打印模型思考过程
        images: 随本轮问题一起送入模型的图片路径（拓扑截图等）
        provider: 本轮使用的模型提供方（默认当前激活的）；不看图时会自动走视觉桥接
        vision_provider: 识图时使用的提供方（默认自动挑选本地视觉模型）
        on_think / on_answer: 流式片段回调（GUI 用）；给出后对应内容不再打印到 stdout
        system_prompt: 覆盖默认系统提示词（PLAN 模式 / 跑批量实验时用专用提示词）
        on_step: 每执行完一个工具回调一次，参数是
            {"round","tool","args","output"}——批量实验靠它把命令与回显写进运行日志
    """
    prov = provider if isinstance(provider, Provider) else get_provider(provider)
    hub_tools = hub.openai_tools() if hub is not None else []
    tools = list(hub_tools)
    hub_names = {t["function"]["name"] for t in hub_tools}
    if "search_knowledge" not in hub_names:
        tools.append(BUILTIN_SEARCH_KNOWLEDGE)  # 默认挂载（内置兜底）
    if tools and not prov.supports_tools:
        print(f"[提示] {prov.name} 不支持工具调用，本轮工具不可用（知识检索退化为模型自身知识）")
        tools = []

    base_prompt = system_prompt or SYSTEM_PROMPT
    # 拓扑快照注入：启动时的自动巡检结论（若有且新鲜）追加到系统提示词，
    # 让模型「开局就知道当前拓扑长什么样」，无需用户重复描述。
    if system_prompt:
        # 实验专用的提示词自带完整上下文，不再叠加实时拓扑（避免冲突与超长）
        system_text = system_prompt
    else:
        system_text = base_prompt
        # 图片巡检得到的拓扑快照（视觉识读结论）
        try:
            from core.auto_topology import context_for_model

            system_text += context_for_model()
        except Exception:
            pass
        # 实测拓扑（LLDP/MAC 泛洪发现，比图片识读更可信）
        system_text += _flooded_topology_context()
        # 本会话已积累的设备技能（按对话隔离，不与别处对话共享）
        system_text += _session_skill_context()
    messages = [{"role": "system", "content": system_text}]
    messages.extend(history or [])

    async def _call_tool(name: str, args: dict) -> str:
        """工具执行路由：hub 有的走 MCP，没有的走内置兜底（目前仅 search_knowledge）。"""
        if hub is not None and name in hub_names:
            if session:
                return await hub.call_tool(name, args, session=session)
            return await hub.call_tool(name, args)
        if name == "search_knowledge":
            return await asyncio.to_thread(
                _builtin_search_knowledge,
                str(args.get("query", "")), int(args.get("top") or 3))
        return f"工具 {name} 不可用：MCP 服务端未连接，且没有内置实现。"

    # 图片处理：能看图 → 按 OpenAI 视觉格式直接送；不能看图 → 先让本地视觉模型识读再注入文字
    text = query
    if images:
        if prov.supports_vision:
            try:
                text = build_user_content(query, images)
            except Exception as e:
                print(f"[警告] 图片读取失败，本轮按纯文本提问：{type(e).__name__}: {e}")
                text = query
        else:
            bridge = _bridge_images(images, prov, query, vision_provider)
            text = f"{query}\n\n{bridge}" if bridge else query
    messages.append({"role": "user", "content": text})

    for round_no in range(1, max_rounds + 1):
        result = stream_chat(messages, tools=tools or None, show_thinking=show_thinking,
                             provider=prov, on_think=on_think, on_answer=on_answer)

        if not result.tool_calls:
            print_stats(result)
            return result.content

        print(f"\n[第 {round_no} 轮] 模型请求调用 {len(result.tool_calls)} 个工具")
        messages.append({
            "role": "assistant",
            "content": result.content or "",
            "tool_calls": result.tool_calls,
        })

        for call in result.tool_calls:
            name = call["function"]["name"]
            args = _loads_arguments(call["function"]["arguments"])
            if "_raw" in args:
                output = f"工具参数不是合法 JSON，请重新调用 {name} 并输出合法 JSON 参数。"
                print(f"  → {name} 参数解析失败")
            else:
                print(f"  → {name} {json.dumps(args, ensure_ascii=False)}")
                output = await _call_tool(name, args)
                pending = _confirmation_request(output)
                if pending and on_confirmation is not None:
                    token = await on_confirmation(pending)
                    if token:
                        args["confirmation_token"] = token
                        output = await _call_tool(name, args)
                    else:
                        output = "用户未确认该配置命令，工具未执行。"
                print(f"    结果：{_preview(output)}")
            # 运行日志 + 调用方回调：命令与设备回显是复盘/微调数据集的核心原料
            try:
                from core import run_log

                run_log.log_step(round_no=round_no, name=name, args=args, output=output)
            except Exception:
                pass
            if on_step is not None:
                try:
                    on_step({"round": round_no, "tool": name, "args": args, "output": output})
                except Exception:
                    pass
            messages.append({"role": "tool", "tool_call_id": call["id"], "content": output})

    # 轮次用尽仍未收口：去掉工具再问一次，强制给出最终回答
    print(f"\n[已达最大工具轮次 {max_rounds}] 去掉工具，强制生成最终回答")
    result = stream_chat(messages, tools=None, show_thinking=show_thinking, provider=prov,
                         on_think=on_think, on_answer=on_answer)
    print_stats(result)
    return result.content
