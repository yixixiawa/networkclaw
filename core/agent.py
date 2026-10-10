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

import json
from collections.abc import Callable

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
1. 涉及具体配置命令的问题，先调用 query_command_template 取得权威命令模板，再组织答案；
2. 涉及设备型号、产品能力、功能原理的问题，先调用 search_knowledge；
3. 用户提到「当前拓扑 / 现在的网络 / 谁连谁 / 上下级关系」时，按可信度从高到低取用：
   ① 先用 topology_summary 或 load_discovered_topology 看有没有**实测**结论
      （由 discover_topology 泛洪 LLDP/MAC 得到，设备自己报的，最可信）；
   ② 没有实测结果、或实测明显过期（设备刚改过接线）时，用 discover_topology 重新探测
      —— **注意它是只读操作**（只下发 display/show），可以直接调用，无需用户确认；
      但每台设备要完整登录一次，较慢，所以优先复用已有结果；
   ③ 没有实测条件（设备够不着 / 未开 LLDP）才退到看图：get_topology_snapshot 取现成结论，
      过期或不全再用 capture_topology 实时识读；用户明确给了截图才用 analyze_topology_image；
   ④ 实测与图片结论冲突时**以实测为准**，并说明「LLDP 实测显示…，与图中标注不一致」；
   ⑤ 需要给用户看图时调 topology_mermaid 输出 Mermaid 源码（用户可直接渲染）。
4. 需要登录设备操作时，**连接参数（COM 口、IP、用户名、密码）必须由用户提供，不得自行猜测或臆造**；
5. 最终回答要给出可直接粘贴到设备上的命令，并标明配置视图（模式）；
6. 工具结果优先于你的自身记忆；工具没有结果时明确说明"模板库/知识库中未找到"，不要编造命令。

【设备手册工作流（先读手册 → 后动手 → 再沉淀）】
7. 要操作/配置某台设备时：
   ① 先 list_device_manuals 看它有没有手册；没有就用 create_device_manual 建档
      —— device 用设备名（用户没给名字时按型号命名：S57/S37 等交换机型为 SW<n>，AR 系列为 R<n>，
      n 接续已有最大编号），并传 transport/host/port（或 serial_port）把名字绑定到地址，
      这样后续命令历史会自动归到该设备名下；
   ② 动手前 read_device_manual 读它的「常用配置」与「注意事项」，避免重复试错；
   ③ 命令验证有效后，用 update_device_manual_section 把命令序列（含顺序与适用场景）
      写进「常用配置」，把发现的坑写进「注意事项」；
   ④ 每条命令的历史由工具自动写入 data/device_history/<设备名>.jsonl，**不要手工造历史**。
8. 手册内容只能来自工具结果、用户提供的信息或拓扑识读结论；不确定的字段留空写成「待确认」，
   严禁编造型号、IP、接口号。

【设备命令安全红线（必须严格遵守）】
工具层对命令做了三级管控，你必须在规则内工作：
- **允许直接执行**：display / show / ping / tracert 等只读命令。可以自由调用，用于查看现状与验证。
- **必须先确认再执行**：sysname、vlan、interface、ip、ospf、acl、aaa 等一切会改变配置的命令。
  流程是：① 先把「要执行哪条命令、在哪台设备的什么视图下、会产生什么影响」讲给用户；
  ② 用户明确同意后，才可以带 confirm=true 重新调用工具。**绝不允许未获同意就带 confirm=true。**
- **禁止执行**：undo、no、shutdown、delete、reset、reboot、reload、save/write 等破坏性或持久化命令。
  工具会直接拦截，**不要尝试改写、拼接、拆分或绕开**这些命令。
- 单次只执行一条命令，不要用分号把多条命令串起来下发（工具会按多命令逐条裁决，仍属违规用法）；
- 执行配置类命令后，建议用 display 类只读命令回读验证，并把结果告诉用户。
"""

VISION_BRIDGE_PREFIX = VISION_BRIDGE_PREFIX  # 兼容旧引用（实现在 core/vision.py）


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
                    on_step: Callable[[dict], None] | None = None) -> str:
    """带工具调用的问答循环，返回最终回答文本。

    Args:
        query: 用户问题
        hub: McpHub 实例（已连接）
        history: 之前的对话消息（{"role","content"} 列表），用于多轮上下文
        max_rounds: 最多允许的工具调用轮次
        show_thinking: 是否实时打印模型思考过程
        images: 随本轮问题一起送入模型的图片路径（拓扑截图等）
        provider: 本轮使用的模型提供方（默认当前激活的）；不看图时会自动走视觉桥接
        vision_provider: 识图时使用的提供方（默认自动挑选本地视觉模型）
        on_think / on_answer: 流式片段回调（GUI 用）；给出后对应内容不再打印到 stdout
        system_prompt: 覆盖默认系统提示词（跑批量实验时用实验专用提示词，
            比如放开「配置类命令需人工确认」的限制）
        on_step: 每执行完一个工具回调一次，参数是
            {"round","tool","args","output"}——批量实验靠它把命令与回显写进运行日志
    """
    prov = provider if isinstance(provider, Provider) else get_provider(provider)
    tools = hub.openai_tools()
    if tools and not prov.supports_tools:
        print(f"[提示] {prov.name} 不支持工具调用，本轮 MCP 工具不可用（如需工具请用 /model local）")
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
    messages = [{"role": "system", "content": system_text}]
    messages.extend(history or [])

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
                output = await hub.call_tool(name, args)
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
