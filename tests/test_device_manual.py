"""设备手册冷启动测试：型号基线画像 + 骨架预填 + 小节读写。

背景：`session/<会话>/skill/<设备名>/SKILL.md` 是运行期产物（按对话隔离），
第 N 台新设备第一次出现时手册为空。本测试确保「新设备建档即带有该型号的
通用要点」，而不是三段空占位符。

技能根目录由 tests/conftest.py 的 autouse 夹具隔离到临时目录，这里再显式
钉一个测试会话，保证读写都落在 `session/<测试会话>/skill/` 下。
"""
import pytest

from core import device_manual as dm
from core import session_skills as ss
from knowledge import device_profiles as dp


@pytest.fixture()
def manual_root():
    """把当前会话钉到测试会话（根目录已被 conftest 隔离），返回技能目录。"""
    ss.use_session("test-session")
    return ss.session_dir() / "skill"


# ---------------------------------------------------------------- 型号画像

@pytest.mark.parametrize("model,expect_kind", [
    ("AR2220", "router"),
    ("S5700-28C-HI", "switch"),
    ("S3700", "switch"),
    ("NE40E", "router"),
    ("USG6000", "firewall"),
])
def test_profile_matches_common_models(model, expect_kind):
    assert dp.device_kind(model) == expect_kind


def test_profile_unknown_model_is_empty():
    """未知型号返回空串——不编造，也不写"未知"占位。"""
    assert dp.baseline_tips("完全不存在的型号") == ""
    assert dp.device_kind("完全不存在的型号") == ""
    assert dp.match("") == (None, None)


def test_profile_longest_key_wins():
    """AR2220 不能被更短的 key 抢走匹配。"""
    key, _ = dp.match("AR2220")
    assert key == "AR2220"


def test_router_profile_warns_about_zero_based_port():
    """路由器画像必须包含「0 基编号」这个最高频错误的提示。"""
    tips = dp.baseline_tips("AR2220")
    assert "0 基" in tips or "GE0/0/0" in tips


def test_switch_profile_warns_about_undo_linktype():
    """交换机画像必须包含改接口类型前要先 undo 的提示。"""
    tips = dp.baseline_tips("S5700")
    assert "undo port link-type" in tips


# ---------------------------------------------------------------- 骨架预填

def test_skeleton_prefills_baseline_for_known_model():
    text = dm.skeleton("SW7", vendor="Huawei", model="S5700-28C-HI",
                       address="192.168.10.130:2020")
    assert "SW7" in text
    assert "# 注意事项" in text
    assert "型号基线" in text, "已知型号应预填基线要点"
    assert "1 基编号" in text


def test_skeleton_falls_back_to_placeholder_for_unknown_model():
    """未知型号要退回占位说明，而不是留一段空白。"""
    text = dm.skeleton("X1", model="莫名其妙型号")
    assert "执行过程中发现的坑" in text
    assert "型号基线" not in text


def test_skeleton_marks_unknown_fields():
    text = dm.skeleton("D1")
    assert "（待确认）" in text
    assert "密码不写入本文件" in text


def test_ensure_manual_creates_with_baseline(manual_root):
    """建档走 ensure_manual 时同样带上基线（这是模型实际调用的入口）。"""
    text, created = dm.ensure_manual("R7", vendor="Huawei", model="AR2220",
                                     address="192.168.10.130:2030")
    assert created is True
    assert "型号基线" in text
    assert "0 基" in text or "GE0/0/0" in text
    # 落盘
    assert dm.manual_path("R7").is_file()


def test_ensure_manual_does_not_overwrite(manual_root):
    dm.ensure_manual("R7", model="AR2220")
    dm.update_section("R7", "常用配置", "interface g0/0/0\n ip address 1.1.1.1 24")
    text, created = dm.ensure_manual("R7", model="AR2220")
    assert created is False
    assert "ip address 1.1.1.1" in text, "已有手册不能被骨架覆盖"


# ---------------------------------------------------------------- 小节读写

def test_update_section_appends_and_creates(manual_root):
    dm.ensure_manual("SW1", model="S5700")
    dm.update_section("SW1", "注意事项", "本机 Trunk 口需要显式放行 VLAN")
    text = dm.read_manual("SW1")
    assert "本机 Trunk 口需要显式放行 VLAN" in text
    # 基线内容仍在（append 不是覆盖）
    assert "1 基编号" in text


def test_update_section_on_missing_manual_builds_skeleton(manual_root):
    """对手册不存在的设备直接写小节时，应先自动建档再写。"""
    dm.update_section("SW9", "常用配置", "vlan batch 10 20")
    text = dm.read_manual("SW9")
    assert "vlan batch 10 20" in text
    # 骨架的大标题带设备名（"# SW9 设备信息"），不是固定的 "# 设备信息"
    assert "SW9 设备信息" in text


def test_manual_survives_roundtrip(manual_root):
    dm.ensure_manual("AR9", model="AR2220")
    original = dm.read_manual("AR9")
    dm.save_manual("AR9", original)
    assert dm.read_manual("AR9") == original


def test_tail_history_zero_returns_empty(manual_root):
    dm.append_history("AR9", "display version", "ok", executed=True)
    assert dm.tail_history("AR9", 0) == []


# ---------------------------------------------------------------- Wiki 化（LLM 说明书）

def test_skeleton_has_topology_section(manual_root):
    """骨架要有「拓扑关系」小节——Wiki 生成与 PLAN 模式都往这里写。"""
    text, created = dm.ensure_manual("SW9", model="S5700")
    assert created
    assert "# 拓扑关系" in text
    assert dm.SECTIONS == ("设备信息", "拓扑关系", "常用配置", "注意事项")


def test_generate_wiki_prompt_carries_config_and_topology():
    """生成提示词必须带配置回显与实测拓扑，否则模型只能编。"""
    sent = {}

    def fake_chat(messages):
        sent["messages"] = messages
        return "# 拓扑关系\n- 上级 AR1\n# 配置基线\n- VLAN 10"

    out = dm.generate_wiki_markdown(
        "SW1", "sysname SW1\nvlan batch 10 20", "- 上级设备（生成树推导）：AR1",
        chat=fake_chat)

    assert "# 拓扑关系" in out
    user = sent["messages"][-1]["content"]
    assert "vlan batch 10 20" in user
    assert "AR1" in user
    assert "SW1" in user


def test_split_wiki_topics_tolerates_extra_headings():
    text = ("# 设备信息\n（忽略）\n# 拓扑关系\n- 上级 AR1\n"
            "# 配置基线\n- VLAN 10\n# 其它\n（忽略）")
    topics = dm._split_wiki_topics(text)
    assert topics["拓扑关系"] == "- 上级 AR1"
    assert topics["配置基线"] == "- VLAN 10"
    assert "其它" not in topics


def test_wiki_enrich_writes_sections_into_manual(manual_root):
    """Wiki 生成后要真正写进手册，并且后续摘要能读到拓扑一行。"""
    dm.ensure_manual("SW1", model="S5700")

    def fake_chat(messages):
        return ("# 拓扑关系\n\n- 实测邻居：GE0/0/1 ↔ AR1 的 GE0/0/0\n"
                "- 上级设备（生成树推导）：AR1\n\n"
                "# 配置基线\n\n- VLAN 10 / 20 已创建\n- GE0/0/1 为 trunk\n")

    res = dm.wiki_enrich("SW1", "sysname SW1", "- 上级：AR1", chat=fake_chat)

    assert res["ok"] and res["written"] == ["拓扑关系", "配置基线"]
    text = dm.read_manual("SW1")
    assert "AR1" in text and "trunk" in text
    assert "（建档后由 PLAN/Wiki 生成流程自动补全" not in text   # 占位被替换

    meta = dm._extract_meta(text)
    assert "AR1" in meta["topo"]


def test_wiki_enrich_degrades_on_empty_generation(manual_root):
    """模型返回空内容时不能清空手册，只能如实报「未完成」。"""
    before, _ = dm.ensure_manual("SW2")
    res = dm.wiki_enrich("SW2", "config", chat=lambda messages: "")
    assert res["ok"] is False and "空" in res["note"]
    assert dm.read_manual("SW2") == before


def test_wiki_enrich_falls_back_when_model_ignores_format(manual_root):
    """模型没按小节输出时整篇落到拓扑关系，好过丢掉内容。"""
    dm.ensure_manual("SW3")
    res = dm.wiki_enrich("SW3", "cfg", chat=lambda messages: "- GE0/0/1 接 AR1")
    assert res["ok"] and res["written"] == ["拓扑关系"]
    assert "GE0/0/1" in dm.read_manual("SW3")


def test_topology_for_device_extracts_neighbors(monkeypatch):
    """实测拓扑里有本设备时，要能抽出「接口 ↔ 邻居」与上级。"""
    from core import topology_flood as tf

    topo = tf.Topology(
        devices=["SW1", "AR1"],
        links=[tf.Link(a_device="SW1", a_interface="GE0/0/1",
                       b_device="AR1", b_interface="GE0/0/0",
                       evidence="lldp", confidence="high")],
        parents={"SW1": "AR1"},
        generated="2026-11-12 20:00:00",
    )
    monkeypatch.setattr(tf, "load_snapshot", lambda path=None: topo)

    text = dm.topology_for_device("SW1")

    assert "GE0/0/1" in text and "AR1" in text
    assert "上级设备" in text
    assert dm.topology_for_device("不存在的设备") == ""


# ---------------------------------------------------------------- Wiki 化（LLM 说明书）

def test_skeleton_has_topology_section(manual_root):
    """骨架要有「拓扑关系」小节——Wiki 生成与 PLAN 模式都往这里写。"""
    text, created = dm.ensure_manual("SW9", model="S5700")
    assert created
    assert "# 拓扑关系" in text
    assert dm.SECTIONS == ("设备信息", "拓扑关系", "常用配置", "注意事项")


def test_generate_wiki_prompt_carries_config_and_topology():
    """生成提示词必须带配置回显与实测拓扑，否则模型只能编。"""
    sent = {}

    def fake_chat(messages):
        sent["messages"] = messages
        return "# 拓扑关系\n- 上级 AR1\n# 配置基线\n- VLAN 10"

    out = dm.generate_wiki_markdown(
        "SW1", "sysname SW1\nvlan batch 10 20", "- 上级设备（生成树推导）：AR1",
        chat=fake_chat)

    assert "# 拓扑关系" in out
    user = sent["messages"][-1]["content"]
    assert "vlan batch 10 20" in user
    assert "AR1" in user
    assert "SW1" in user


def test_split_wiki_topics_tolerates_extra_headings():
    text = ("# 设备信息\n（忽略）\n# 拓扑关系\n- 上级 AR1\n"
            "# 配置基线\n- VLAN 10\n# 其它\n（忽略）")
    topics = dm._split_wiki_topics(text)
    assert topics["拓扑关系"] == "- 上级 AR1"
    assert topics["配置基线"] == "- VLAN 10"
    assert "其它" not in topics


def test_wiki_enrich_writes_sections_into_manual(manual_root):
    """Wiki 生成后要真正写进手册，并且后续摘要能读到拓扑一行。"""
    dm.ensure_manual("SW1", model="S5700")

    def fake_chat(messages):
        return ("# 拓扑关系\n\n- 实测邻居：GE0/0/1 ↔ AR1 的 GE0/0/0\n"
                "- 上级设备（生成树推导）：AR1\n\n"
                "# 配置基线\n\n- VLAN 10 / 20 已创建\n- GE0/0/1 为 trunk\n")

    res = dm.wiki_enrich("SW1", "sysname SW1", "- 上级：AR1", chat=fake_chat)

    assert res["ok"] and res["written"] == ["拓扑关系", "配置基线"]
    text = dm.read_manual("SW1")
    assert "AR1" in text and "trunk" in text
    assert "（建档后由 PLAN/Wiki 生成流程自动补全" not in text   # 占位被替换

    meta = dm._extract_meta(text)
    assert "AR1" in meta["topo"]


def test_wiki_enrich_degrades_on_empty_generation(manual_root):
    """模型返回空内容时不能清空手册，只能如实报「未完成」。"""
    before, _ = dm.ensure_manual("SW2")
    res = dm.wiki_enrich("SW2", "config", chat=lambda messages: "")
    assert res["ok"] is False and "空" in res["note"]
    assert dm.read_manual("SW2") == before


def test_wiki_enrich_falls_back_when_model_ignores_format(manual_root):
    """模型没按小节输出时整篇落到拓扑关系，好过丢掉内容。"""
    dm.ensure_manual("SW3")
    res = dm.wiki_enrich("SW3", "cfg", chat=lambda messages: "- GE0/0/1 接 AR1")
    assert res["ok"] and res["written"] == ["拓扑关系"]
    assert "GE0/0/1" in dm.read_manual("SW3")


def test_topology_for_device_extracts_neighbors(monkeypatch):
    """实测拓扑里有本设备时，要能抽出「接口 ↔ 邻居」与上级。"""
    from core import topology_flood as tf

    topo = tf.Topology(
        devices=["SW1", "AR1"],
        links=[tf.Link(a_device="SW1", a_interface="GE0/0/1",
                       b_device="AR1", b_interface="GE0/0/0",
                       evidence="lldp", confidence="high")],
        parents={"SW1": "AR1"},
        generated="2026-11-12 20:00:00",
    )
    monkeypatch.setattr(tf, "load_snapshot", lambda path=None: topo)

    text = dm.topology_for_device("SW1")

    assert "GE0/0/1" in text and "AR1" in text
    assert "上级设备" in text
    assert dm.topology_for_device("不存在的设备") == ""
