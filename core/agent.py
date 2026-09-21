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

SYSTEM_PROMPT = """你是 NetworkClaw 网络运维助手，服务对象是网络工程师。你可以调用以下工具：
- query_command_template：按厂商（Huawei/H3C/Cisco）、设备类型（switch/router/both）和意图检索命令模板
- search_knowledge：检索知识库中的设备介绍、配置说明
- search：联网搜索（仅在已接入时可用）

工作方式：
1. 涉及具体配置命令的问题，先调用 query_command_template 取得权威命令模板，再组织答案；
2. 涉及设备型号、产品能力、功能原理的问题，先调用 search_knowledge；
3. 最终回答要给出可直接粘贴到设备上的命令，并标明配置视图（模式）；
4. 工具结果优先于你的自身记忆；工具没有结果时明确说明“模板库/知识库中未找到”，不要编造命令。
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
                    max_rounds: int = 3, show_thinking: bool = True) -> str:
    """带工具调用的问答循环，返回最终回答文本。

    Args:
        query: 用户问题
        hub: McpHub 实例（已连接）
        history: 之前的对话消息（{"role","content"} 列表），用于多轮上下文
        max_rounds: 最多允许的工具调用轮次
        show_thinking: 是否实时打印模型思考过程
    """
    tools = hub.openai_tools()
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages.extend(history or [])
    messages.append({"role": "user", "content": query})

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
