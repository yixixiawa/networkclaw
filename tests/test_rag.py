"""core/rag.py 单元测试：数据源装配、知识分级、检索降级、提示词组装。

全部离线可跑：不依赖 Ollama / 向量库——涉及检索的部分用 monkeypatch 替换
`get_collection`，模拟「集合正常 / 索引为空 / Embedding 挂掉 / 集合句柄取不到」
四种情况，验证 status 判定与提示词注入是否正确。
"""
import pytest

from core import rag


# ---------------------------------------------------------------- 数据源装配

def test_all_four_sources_are_loaded():
    """四个来源都要进知识库：设备介绍 / 实验文档 / 实验报告 / 运行日志摘要。

    设备手册**不在**索引里——它按会话隔离到 session/<sid>/skill/<设备>/，
    改为直注系统提示词（塞进全局索引会在切换会话时串味），见 test_session_skills.py。
    """
    texts = {
        "experiments": rag._experiment_texts(),
        "reports": rag._lab_report_texts(),
        "runlogs": rag._run_log_digests(),
    }
    # 实验文档是知识库的主体，仓库内必有
    assert len(texts["experiments"]) > 0, "实验文档数据源为空"
    # 每个来源的每段文字都非空，避免出现空块污染索引
    for name, items in texts.items():
        for t in items:
            assert t.strip(), f"{name} 来源里出现空文本"
    # 手册来源确认已移除（不是漏改）
    assert not hasattr(rag, "_manual_texts")


def test_experiment_source_skips_overview():
    """00-总览.md 是索引文件，应当被跳过以免噪声进入检索。"""
    for text in rag._experiment_texts():
        assert "00-总览" not in text.split("\n", 1)[0]


def test_runlog_digest_is_summary_not_raw_dump():
    """运行日志必须被摘要化：不能把整段设备回显原样塞进知识库。

    摘要里应当有会话标识与计数，且长度显著小于原始 JSONL 单行。
    """
    digests = rag._run_log_digests()
    if not digests:                      # 没有运行日志时不强求
        pytest.skip("本地没有 data/run_logs 数据")
    d = digests[0]
    assert "运行日志摘要" in d
    assert "LLM 调用" in d and "工具下发" in d
    # 摘要里不应出现典型的配置回显噪音（说明没做摘要、直接把回显灌进来）
    assert "display current-configuration" not in d or len(d) < 4000


def test_digest_session_dedupes_repeated_commands():
    """同一条**配置类**命令重复下发多次时，摘要里只保留一次。

    只读命令（display/show/ping）不进「配置类命令」那一行——摘要要突出
    「改了哪些配置」，而不是把每次查看都列一遍。
    """
    rows = [
        {"kind": "llm_call", "model": "Qwen3.5-9B"},
        {"kind": "tool_step", "round": 1, "tool": "exec_telnet_command",
         "args": {"command": "vlan 10"}, "output": "ok"},
        {"kind": "tool_step", "round": 2, "tool": "exec_telnet_command",
         "args": {"command": "vlan 10"}, "output": "ok"},
        {"kind": "tool_step", "round": 3, "tool": "exec_telnet_command",
         "args": {"command": "sysname SW1"}, "output": "ok"},
        {"kind": "tool_step", "round": 4, "tool": "exec_telnet_command",
         "args": {"command": "display version"}, "output": "VRP"},
    ]
    digest = rag._digest_session("2026-01-01", "t", rows)
    assert digest.count("vlan 10") == 1             # 去重
    assert "sysname SW1" in digest
    assert "display version" not in digest          # 只读命令不进配置类清单


def test_digest_session_readonly_only():
    """全程只读的会话要明确说明「没下发配置」，避免被误读成「配好了」。"""
    rows = [
        {"kind": "tool_step", "round": 1, "tool": "exec_telnet_command",
         "args": {"command": "display current-configuration"}, "output": "..."},
    ]
    digest = rag._digest_session("2026-01-01", "t", rows)
    assert "只读查看" in digest
    assert "没有下发配置类命令" in digest


def test_digest_session_captures_error_echo():
    """报错回显要被抓进摘要——这是「下次别再踩」的关键信息。"""
    rows = [
        {"kind": "tool_step", "round": 1, "tool": "exec_telnet_command",
         "args": {"command": "port link-type trunk"},
         "output": "Error: Please renew the default configuration"},
    ]
    digest = rag._digest_session("2026-01-01", "t", rows)
    assert "Error" in digest


def test_digest_session_empty_without_steps():
    """只有 LLM 调用、没有工具下发的会话不值得入库。"""
    assert rag._digest_session("2026-01-01", "t", [{"kind": "llm_call"}]) == ""


# ---------------------------------------------------------------- 知识分级

def test_tier_decoration_prefixes():
    """三类知识必须带不同前缀，否则模型无法区分「规则」与「历史记录」。"""
    rule = rag._decorate("正文", rag.TIER_RULE)
    hist = rag._decorate("正文", rag.TIER_HISTORY)
    inst = rag._decorate("正文", rag.TIER_INSTANCE)
    assert rule != hist != inst
    assert "现行规则" in rule
    assert "历史记录" in hist
    assert "实例数据" in inst
    # 未知 tier 不加前缀，正文原样返回
    assert rag._decorate("正文", "unknown-tier") == "正文"


def test_knowledge_sources_lists_tiers():
    """索引来源描述里应标出每个来源的可信度分级（便于追溯）。"""
    desc = rag.knowledge_sources()
    for tag in ("[rule]", "[history]", "[instance]"):
        assert tag in desc


# ---------------------------------------------------------------- 检索降级


class _FakeColl:
    def __init__(self, n=10, docs=None, raise_on_query=False):
        self._n, self._docs, self._raise = n, docs, raise_on_query

    def count(self):
        return self._n

    def query(self, query_texts=None, n_results=3):
        if self._raise:
            raise ConnectionError("Failed to connect to Ollama")
        return {"documents": [self._docs if self._docs is not None else ["片段A", "片段B"]]}


def test_retrieve_ok(monkeypatch):
    monkeypatch.setattr(rag, "get_collection", lambda *a, **k: _FakeColl())
    res = rag.retrieve_ex("任意问题")
    assert res.status == "ok" and res.ok and not res.degraded
    assert res.chunks == ["片段A", "片段B"]
    assert res.notice() == ""


def test_retrieve_empty_index(monkeypatch):
    """索引为空是正常状态，不是故障——notice 里不应吓唬模型。"""
    monkeypatch.setattr(rag, "get_collection", lambda *a, **k: _FakeColl(n=0))
    res = rag.retrieve_ex("任意问题")
    assert res.status == "empty"
    assert not res.ok and not res.degraded
    assert "为空" in res.notice()


def test_retrieve_no_match(monkeypatch):
    monkeypatch.setattr(rag, "get_collection", lambda *a, **k: _FakeColl(docs=[]))
    res = rag.retrieve_ex("任意问题")
    assert res.status == "no_match"
    assert not res.degraded
    assert "没有找到" in res.notice()


def test_retrieve_embed_failed_is_degraded(monkeypatch):
    """Embedding 服务不可用 → 必须判为 degraded，并被写进提示词。"""
    monkeypatch.setattr(rag, "get_collection",
                        lambda *a, **k: _FakeColl(raise_on_query=True))
    res = rag.retrieve_ex("任意问题")
    assert res.status == "embed_failed"
    assert res.degraded and not res.ok
    notice = res.notice()
    assert "检索不可用" in notice
    assert "没有" in notice            # 明确告知「没有知识库依据」


def test_retrieve_collection_unavailable(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("chroma 打不开")
    monkeypatch.setattr(rag, "get_collection", boom)
    res = rag.retrieve_ex("任意问题")
    assert res.status == "unavailable" and res.degraded


def test_retrieve_wrapper_still_returns_list(monkeypatch):
    """兼容旧接口：retrieve() 只返回片段列表，不破坏既有调用方。"""
    monkeypatch.setattr(rag, "get_collection",
                        lambda *a, **k: _FakeColl(raise_on_query=True))
    assert rag.retrieve("x") == []


# ---------------------------------------------------------------- 提示词


def test_build_prompt_marks_degradation():
    """降级提示必须出现在 prompt 里，且要求模型如实告知用户。"""
    notice = "⚠ 知识库检索不可用（embed_failed）：连接失败。"
    prompt = rag._build_prompt("BGP 邻居起不来怎么办", "", notice)
    assert "检索不可用" in prompt
    assert "BGP 邻居起不来怎么办" in prompt
    assert "没有可用的知识片段" in prompt


def test_build_prompt_normal_has_no_warning():
    prompt = rag._build_prompt("问题", "片段正文")
    assert "检索不可用" not in prompt
    assert "片段正文" in prompt


# ---------------------------------------------------------------- 知识清洗（2026-11 职责分离）

def test_looks_like_command_detects_vrp_lines():
    assert rag._looks_like_command("[SW1-GigabitEthernet0/0/1]")
    assert rag._looks_like_command("vlan batch 10 20")
    assert rag._looks_like_command("interface GigabitEthernet0/0/1")
    assert rag._looks_like_command("undo shutdown")
    # 自然语言句子不能被误判成命令
    assert not rag._looks_like_command("交换机上电后需要先做基础配置，再接入业务。")
    assert not rag._looks_like_command("display 命令用于查看设备状态，不改变配置。")


def test_clean_chunks_drops_fragments_syntax_and_duplicates():
    """清洗三件事：碎片、纯命令语法块、重复块。"""
    long_desc = ("接入层交换机负责把终端接入网络，通常配置 VLAN 划分、"
                 "接口模式与生成树保护，避免环路影响整个园区。")
    syntax = "\n".join([
        "system-view",
        "vlan batch 10 20",
        "interface GigabitEthernet0/0/1",
        "port link-type trunk",
        "port trunk allow-pass vlan 10 20",
        "quit",
    ])
    chunks = [
        long_desc,
        "太短的碎片。",
        syntax,
        long_desc,                       # 重复
        long_desc + "（不同内容）",       # 不是重复，保留
    ]

    out = rag._clean_chunks(chunks)

    assert out[0] == long_desc
    assert all(len(c) >= 40 for c in out)
    assert syntax not in out, "纯命令语法块应交给 command_templates.csv，不进知识库"
    assert len(out) == 2


def test_clean_chunks_keeps_command_block_with_explanation():
    """命令 + 解释混排的块要保留（它教的是做法，不只是语法）。"""
    mixed = ("在接入交换机上创建 VLAN 并把端口加入的命令如下，"
             "注意先 system-view 再进入接口视图：\n"
             "system-view\nvlan 10\ninterface GigabitEthernet0/0/1\n"
             "port link-type access\nport default vlan 10\n"
             "下发后用 display vlan 10 验证端口是否真的加入了该 VLAN。")
    out = rag._clean_chunks([mixed])
    assert out == [mixed]


def test_load_chunks_is_cleaned():
    """真实知识库走一遍：清洗后无碎片、无纯命令块、无重复。"""
    chunks = rag.load_chunks()
    assert chunks, "知识库不应为空"
    assert len({c for c in chunks}) == len(chunks), "重复块未去净"
    for c in chunks:
        assert len(c.strip()) >= 40, "碎片块未去净"
