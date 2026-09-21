"""Agent 模式：让本地模型在回答前自主调用 MCP 工具。

流程：
用户问题 → 带工具定义请求本地模型 → 模型返回 tool_calls
→ 通过 McpHub 执行工具 → 结果回填为 tool 消息 → 继续生成
→ 直到模型给出最终回答（最多 max_rounds 轮；轮次用尽则去掉工具强制收口）

与 core.rag 的分工：
- core.rag：固定「先检索知识库、再生成」的单轮问答
- core.agent：模型自主决定是否检索、检索什么（知识库 / 命令模板 / 联网）
"""
import json

from core.llm_client import print_stats, stream_chat
from core.vision import build_user_content

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

【图像类】
- vision_ready：检查识图能力是否就绪
- list_local_images：用户提到截图但没给路径时，用它找图
- analyze_topology_image：识读网络拓扑图，得到设备清单、连接关系、IP/网段与风险点

工作方式：
1. 涉及具体配置命令的问题，先调用 query_command_template 取得权威命令模板，再组织答案；
2. 涉及设备型号、产品能力、功能原理的问题，先调用 search_knowledge；
3. 用户给出拓扑截图或提到「当前拓扑」时，先调用 analyze_topology_image 看清现状，再给建议；
4. 需要登录设备操作时，**连接参数（COM 口、IP、用户名、密码）必须由用户提供，不得自行猜测或臆造**；
5. 最终回答要给出可直接粘贴到设备上的命令，并标明配置视图（模式）；
6. 工具结果优先于你的自身记忆；工具没有结果时明确说明"模板库/知识库中未找到"，不要编造命令。

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


async def run_agent(query: str, hub, history: list[dict] | None = None,
                    max_rounds: int = 3, show_thinking: bool = True,
                    images: list[str] | None = None) -> str:
    """带工具调用的问答循环，返回最终回答文本。

    Args:
        query: 用户问题
        hub: McpHub 实例（已连接）
        history: 之前的对话消息（{"role","content"} 列表），用于多轮上下文
        max_rounds: 最多允许的工具调用轮次
        show_thinking: 是否实时打印模型思考过程
        images: 随本轮问题一起送入模型的图片路径（拓扑截图等），需 llama-server 带 --mmproj
    """
    tools = hub.openai_tools()
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages.extend(history or [])

    # 有图片时用 OpenAI 视觉格式的多段 content（文本 + image_url）
    text = query
    if images:
        try:
            text = build_user_content(query, images)
        except Exception as e:
            print(f"[警告] 图片读取失败，本轮按纯文本提问：{type(e).__name__}: {e}")
            text = query
    messages.append({"role": "user", "content": text})

    for round_no in range(1, max_rounds + 1):
        result = stream_chat(messages, tools=tools or None, show_thinking=show_thinking)

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
            messages.append({"role": "tool", "tool_call_id": call["id"], "content": output})

    # 轮次用尽仍未收口：去掉工具再问一次，强制给出最终回答
    print(f"\n[已达最大工具轮次 {max_rounds}] 去掉工具，强制生成最终回答")
    result = stream_chat(messages, tools=None, show_thinking=show_thinking)
    print_stats(result)
    return result.content
