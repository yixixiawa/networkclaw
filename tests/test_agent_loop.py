"""core/agent.py 工具调用循环测试：用假 hub + 假 LLM，无需真模型/真设备。

覆盖 agent 循环里最容易出问题、又最难手工复现的几处：
  ① 工具结果按 OpenAI 协议正确回填（role=tool + tool_call_id 对齐）；
  ② 参数不是合法 JSON 时给出可读提示而不是崩掉；
  ③ 达到最大轮次后去掉工具强制收口（不能无限循环）；
  ④ on_step 回调把每一轮的命令与回显交给调用方（批量实验的记录通道）；
  ⑤ 模型不支持工具调用时不携带 tools（云端退化场景）。
"""
import json

import pytest

from core import agent as ag
from core.agent import run_agent


class FakeHub:
    """记录调用并返回预置结果的假 McpHub。"""

    def __init__(self, outputs=None, tools=None):
        self.outputs = outputs or {}
        self.calls = []
        self._tools = tools if tools is not None else [
            {"type": "function",
             "function": {"name": "exec_telnet_command", "parameters": {}}},
        ]

    def openai_tools(self):
        return self._tools

    async def call_tool(self, name, args):
        self.calls.append({"name": name, "args": args})
        return self.outputs.get(name, f"结果:{name}")


class FakeResult:
    def __init__(self, content="", tool_calls=None, model="Qwen3.5-9B",
                 provider="local", usage=None):
        self.content = content
        self.tool_calls = tool_calls or []
        self.model = model
        self.provider = provider
        self.think_chunks = 0
        self.answer_chunks = 1
        self.usage = usage or {}


def _tool_call(name="exec_telnet_command", args=None, call_id="c1"):
    return {
        "id": call_id,
        "type": "function",
        "function": {"name": name,
                     "arguments": args if isinstance(args, str)
                     else json.dumps(args or {"command": "display version"}, ensure_ascii=False)},
    }


@pytest.fixture()
def patch_llm(monkeypatch):
    """把 stream_chat 换成脚本化的假实现；按调用次序返回预设结果。"""
    def make(script):
        calls = []

        def fake_stream_chat(messages, tools=None, show_thinking=True, provider=None,
                             on_think=None, on_answer=None):
            calls.append({"messages": [dict(m) for m in messages], "tools": tools})
            idx = min(len(calls) - 1, len(script) - 1)
            return script[idx]

        monkeypatch.setattr(ag, "stream_chat", fake_stream_chat)
        monkeypatch.setattr(ag, "print_stats", lambda r: None)
        return calls

    return make


@pytest.fixture(autouse=True)
def quiet_runlog(monkeypatch):
    """测试不落盘运行日志。"""
    monkeypatch.setenv("NETWORKCLAW_RUNLOG", "0")


@pytest.mark.anyio
async def test_no_tool_calls_returns_directly(patch_llm):
    """模型直接回答（不调工具）时立刻返回，不进入工具循环。"""
    calls = patch_llm([FakeResult(content="直接答案")])
    hub = FakeHub()
    out = await run_agent("你好", hub)
    assert out == "直接答案"
    assert hub.calls == []
    assert len(calls) == 1


@pytest.mark.anyio
async def test_tool_call_cycle_feeds_result_back(patch_llm):
    """一轮工具调用：结果必须以 role=tool + 对应 tool_call_id 回填。"""
    calls = patch_llm([
        FakeResult(content="", tool_calls=[_tool_call(args={"command": "display version"})]),
        FakeResult(content="最终答案"),
    ])
    hub = FakeHub(outputs={"exec_telnet_command": "VRP (R) software, Version 5.130"})
    out = await run_agent("查版本", hub)

    assert out == "最终答案"
    assert hub.calls == [{"name": "exec_telnet_command",
                          "args": {"command": "display version"}}]
    # 第二次调用时，历史里应含 assistant(tool_calls) 与 tool 结果
    msgs = calls[1]["messages"]
    assistant = [m for m in msgs if m.get("role") == "assistant" and m.get("tool_calls")]
    tool_msg = [m for m in msgs if m.get("role") == "tool"]
    assert assistant and assistant[0]["tool_calls"][0]["id"] == "c1"
    assert tool_msg and tool_msg[0]["tool_call_id"] == "c1"
    assert "Version 5.130" in tool_msg[0]["content"]


@pytest.mark.anyio
async def test_invalid_json_args_gives_readable_hint(patch_llm):
    """工具参数不是合法 JSON 时不能崩：应提示模型重发，且不真的调用工具。"""
    calls = patch_llm([
        FakeResult(content="", tool_calls=[_tool_call(args="{不是JSON")]),
        FakeResult(content="重试后答案"),
    ])
    hub = FakeHub()
    out = await run_agent("配置", hub)

    assert out == "重试后答案"
    assert hub.calls == [], "参数非法时不应调用工具"
    tool_msg = [m for m in calls[1]["messages"] if m.get("role") == "tool"][0]
    assert "合法 JSON" in tool_msg["content"]


@pytest.mark.anyio
async def test_max_rounds_forces_final_answer(patch_llm):
    """模型一直想调工具时，跑满 max_rounds 必须去掉工具强制收口（不能无限循环）。"""
    looping = FakeResult(content="", tool_calls=[_tool_call()])
    calls = patch_llm([looping, looping, FakeResult(content="强制收口的答案")])
    hub = FakeHub()
    out = await run_agent("不停调工具", hub, max_rounds=2)

    assert out == "强制收口的答案"
    assert len(hub.calls) == 2                      # 正好 max_rounds 次工具调用
    assert calls[-1]["tools"] is None               # 收口那次不带工具


@pytest.mark.anyio
async def test_on_step_callback_receives_command_and_output(patch_llm):
    """on_step 是批量实验记录「命令 + 回显」的通道，字段必须齐全。"""
    patch_llm([
        FakeResult(content="", tool_calls=[_tool_call(args={"command": "sysname SW1"})]),
        FakeResult(content="done"),
    ])
    hub = FakeHub(outputs={"exec_telnet_command": "ok"})
    steps = []
    await run_agent("改名", hub, on_step=steps.append)

    assert len(steps) == 1
    s = steps[0]
    assert s["round"] == 1
    assert s["tool"] == "exec_telnet_command"
    assert s["args"] == {"command": "sysname SW1"}
    assert s["output"] == "ok"


@pytest.mark.anyio
async def test_provider_without_tools_drops_tools(patch_llm, monkeypatch):
    """提供方不支持工具调用时不携带 tools（否则部分云端会直接报错）。"""
    from core.providers import Provider
    no_tools = Provider(name="cloud-text", label="x", base_url="http://x",
                        model="m", kind="cloud", supports_tools=False)
    monkeypatch.setattr(ag, "get_provider", lambda p=None: no_tools)
    calls = patch_llm([FakeResult(content="无工具回答", provider="cloud-text")])
    hub = FakeHub()
    out = await run_agent("问题", hub)
    assert out == "无工具回答"
    assert calls[0]["tools"] in (None, [])          # 未携带工具


@pytest.mark.anyio
async def test_history_is_prepended(patch_llm):
    """多轮上下文：传入的 history 应出现在 messages 里（system 之后）。"""
    calls = patch_llm([FakeResult(content="答")])
    hub = FakeHub()
    history = [{"role": "user", "content": "上一轮问题"},
               {"role": "assistant", "content": "上一轮回答"}]
    await run_agent("新问题", hub, history=history)
    msgs = calls[0]["messages"]
    assert msgs[0]["role"] == "system"
    assert msgs[1]["content"] == "上一轮问题"
    assert msgs[-1]["content"] == "新问题"


@pytest.mark.anyio
async def test_custom_system_prompt_overrides_default(patch_llm):
    """批量实验用实验专用提示词时，不应再叠加实时拓扑（避免冲突与超长）。"""
    calls = patch_llm([FakeResult(content="答")])
    hub = FakeHub()
    await run_agent("问题", hub, system_prompt="实验专用提示词")
    assert calls[0]["messages"][0]["content"] == "实验专用提示词"


# ---------------------------------------------------------------- 统一入口：内置 search_knowledge

@pytest.mark.anyio
async def test_search_knowledge_always_mounted(patch_llm):
    """MCP 服务端没提供 search_knowledge 时也要挂上内置兜底（统一入口的抓手）。"""
    calls = patch_llm([FakeResult(content="答")])
    hub = FakeHub()                                  # 只有 exec_telnet_command
    await run_agent("问题", hub)

    names = [t["function"]["name"] for t in calls[0]["tools"]]
    assert "exec_telnet_command" in names
    assert "search_knowledge" in names


@pytest.mark.anyio
async def test_no_duplicate_search_knowledge_when_hub_has_it(patch_llm):
    calls = patch_llm([FakeResult(content="答")])
    hub = FakeHub(tools=[{"type": "function",
                          "function": {"name": "search_knowledge", "parameters": {}}}])
    await run_agent("问题", hub)

    names = [t["function"]["name"] for t in calls[0]["tools"]]
    assert names.count("search_knowledge") == 1


@pytest.mark.anyio
async def test_builtin_search_knowledge_used_without_hub(patch_llm, monkeypatch):
    """hub=None（MCP 不可用）时，模型的 search_knowledge 调用走内置实现。"""
    seen = {}

    def fake_builtin(query, top=3):
        seen["query"], seen["top"] = query, top
        return "内置检索结果"

    monkeypatch.setattr(ag, "_builtin_search_knowledge", fake_builtin)
    calls = patch_llm([
        FakeResult(content="", tool_calls=[
            _tool_call(name="search_knowledge", args={"query": "S5700", "top": 2})]),
        FakeResult(content="最终答案"),
    ])

    out = await run_agent("S5700 是什么", None)

    assert out == "最终答案"
    assert seen == {"query": "S5700", "top": 2}
    tool_msg = [m for m in calls[1]["messages"] if m.get("role") == "tool"][0]
    assert tool_msg["content"] == "内置检索结果"


@pytest.mark.anyio
async def test_unknown_tool_without_hub_returns_readable_error(patch_llm):
    """hub 缺失且工具没有内置实现时，要如实告诉模型不可用（不静默失败）。"""
    calls = patch_llm([
        FakeResult(content="", tool_calls=[
            _tool_call(name="exec_telnet_command", args={"command": "display version"})]),
        FakeResult(content="答"),
    ])
    await run_agent("查版本", None)

    tool_msg = [m for m in calls[1]["messages"] if m.get("role") == "tool"][0]
    assert "不可用" in tool_msg["content"]


def test_system_prompt_requires_knowledge_before_config():
    """硬性规则必须写进系统提示词：配置前先检索/读 SKILL.md。"""
    from core.agent import SYSTEM_PROMPT

    assert "搜" in SYSTEM_PROMPT or "search_knowledge" in SYSTEM_PROMPT
    assert "SKILL.md" in SYSTEM_PROMPT
    assert "配置前必查" in SYSTEM_PROMPT


def test_plan_prompt_is_readonly():
    """PLAN 模式提示词要明确「只读探测 + 手册沉淀」。"""
    from core.agent import PLAN_SYSTEM_PROMPT

    assert "只读" in PLAN_SYSTEM_PROMPT
    assert "display current-configuration" in PLAN_SYSTEM_PROMPT
    assert "拓扑关系" in PLAN_SYSTEM_PROMPT
