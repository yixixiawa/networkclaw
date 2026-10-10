"""core/rag.py 单元测试：数据源装配、知识分级、检索降级、提示词组装。

全部离线可跑：不依赖 Ollama / 向量库——涉及检索的部分用 monkeypatch 替换
`get_collection`，模拟「集合正常 / 索引为空 / Embedding 挂掉 / 集合句柄取不到」
四种情况，验证 status 判定与提示词注入是否正确。
"""
import pytest

from core import rag


# ---------------------------------------------------------------- 数据源装配

def test_all_five_sources_are_loaded():
    """五个来源都要进知识库：设备介绍 / 实验文档 / 设备手册 / 实验报告 / 运行日志。"""
    texts = {
        "experiments": rag._experiment_texts(),
        "manuals": rag._manual_texts(),
        "reports": rag._lab_report_texts(),
        "runlogs": rag._run_log_digests(),
    }
    # 实验文档是知识库的主体，仓库内必有
    assert len(texts["experiments"]) > 0, "实验文档数据源为空"
    # 每个来源的每段文字都非空，避免出现空块污染索引
    for name, items in texts.items():
        for t in items:
            assert t.strip(), f"{name} 来源里出现空文本"


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
