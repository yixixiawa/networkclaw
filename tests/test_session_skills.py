"""会话级设备技能测试：一个对话一套 skill，对话之间互不串味。

对应用户需求：「一个对话一个 skill，不将所有对话的设备记忆统一，
存放格式 session/<每个独立会话>/skill/<每个设备技能>」。

覆盖四类断言：
  ① 布局与命名安全（用户指定的目录结构 + 路径穿越防护 + Windows 保留名）；
  ② 隔离语义（A 对话的技能在 B 对话看不到；切回来还在；写也隔离）；
  ③ 跨进程一致性（.current 指针 / 环境变量兜底 / MCP 子进程视角）；
  ④ 下游接线（RAG 不再索引手册、运行日志摘要只取当前会话、
     agent 提示词直注、manual_server 新工具）。

注意：所有用例都在测试体里显式 `ss.use_session(...)`，不靠 fixture 顺序——
两个会话 fixture 会按依赖顺序先后执行，后跑的会把「当前会话」改掉，
测试体看到的就不是自己以为的那个对话了。
"""
import json
import os
from pathlib import Path

import pytest

from core import device_manual as dm
from core import run_log, session_skills as ss


def use(name: str) -> str:
    """切到指定对话（技能 + 运行日志一起切），返回 sid。"""
    ss.use_session(name)
    return name


# ---------------------------------------------------------------- 命名安全

@pytest.mark.parametrize("bad", ["", "   ", "../etc", "a/b", "a\\b", "..", ".hidden",
                                 "x" * 81, "con", "COM1", "lpt9", "nul"])
def test_safe_name_rejects_unsafe(bad):
    """会话标识与设备名都会直接当目录名，路径穿越/保留字符/保留设备名必须被拒。"""
    with pytest.raises(ss.SessionError):
        ss.safe_name(bad, "测试名")


@pytest.mark.parametrize("good", ["default", "cli-20261014-152000-ab12",
                                  "01-ACCESS端口配置", "a1b2c3d4e5f6",
                                  "LSW1", "AR_1-2", "CONsole"])
def test_safe_name_accepts_realistic(good):
    """GUI 的 uuid、实验的中文名、设备名都要能用（CONsole 不是保留名）。"""
    assert ss.safe_name(good) == good.strip()


def test_device_manual_safe_name_keeps_manual_error():
    """device_manual 的对外错误类型保持 ManualError（调用方按它捕获）。"""
    with pytest.raises(dm.ManualError):
        dm.safe_name("../越权")


def test_new_sid_unique_and_prefixed():
    a, b = ss.new_sid("cli"), ss.new_sid("cli")
    assert a != b and a.startswith("cli-") and b.startswith("cli-")


# ---------------------------------------------------------------- 布局（用户指定格式）

def test_layout_matches_user_spec():
    """存放格式必须是 session/<会话>/skill/<设备技能>/。"""
    use("对话A")
    dm.ensure_manual("SW1", vendor="Huawei", model="S5700-28C-HI")
    root = ss.SESSIONS_DIR
    manual = root / "对话A" / "skill" / "SW1" / "SKILL.md"
    hist = root / "对话A" / "skill" / "SW1" / "history.jsonl"
    assert manual.is_file() and hist.parent.is_dir()
    assert dm.manual_path("SW1") == manual
    assert dm.history_path("SW1") == hist


def test_pointer_file_written_atomically():
    use("对话A")
    ptr = ss.SESSIONS_DIR / ".current"
    assert ptr.read_text(encoding="utf-8").strip() == "对话A"
    assert not list(ss.SESSIONS_DIR.glob("*.tmp")), "临时文件应已被 os.replace 消费"


# ---------------------------------------------------------------- 隔离语义（核心）

def test_other_session_cannot_see_manual():
    """A 对话建的技能，B 对话看不到——这是需求的根本。"""
    use("对话A")
    dm.ensure_manual("SW1", model="S5700")
    use("对话B")
    assert dm.list_manuals() == []
    assert dm.read_manual("SW1") == ""
    assert dm.tail_history("SW1") == []


def test_switching_back_keeps_content():
    use("对话A")
    dm.ensure_manual("SW1", model="S5700")
    dm.update_section("SW1", "常用配置", "vlan batch 10 20")
    dm.append_history("SW1", "display version", "ok", executed=True)
    use("对话B")
    assert dm.list_manuals() == []
    use("对话A")
    assert [m["name"] for m in dm.list_manuals()] == ["SW1"]
    assert "vlan batch 10 20" in dm.read_manual("SW1")
    assert [r["command"] for r in dm.tail_history("SW1")] == ["display version"]


def test_writes_are_isolated_too():
    """不仅读隔离，写也隔离：B 里给同名设备建档不会污染 A。"""
    use("对话A")
    dm.ensure_manual("SW1", model="S5700")
    dm.update_section("SW1", "注意事项", "A 对话的坑")
    use("对话B")
    dm.ensure_manual("SW1", model="S5700")
    dm.update_section("SW1", "注意事项", "B 对话的坑")
    use("对话A")
    assert "A 对话的坑" in dm.read_manual("SW1")
    assert "B 对话的坑" not in dm.read_manual("SW1")


def test_explicit_cross_session_read_is_possible():
    """显式带 session 参数可跨对话只读（回答「上次那个会话」用）。"""
    use("对话A")
    dm.ensure_manual("SW1", model="S5700")
    dm.update_section("SW1", "常用配置", "A 的配置")
    use("对话B")
    assert "A 的配置" in dm.read_manual("SW1", "对话A")
    assert dm.tail_history("SW1", session="对话A") == []
    assert dm.manual_path("SW1", "对话A").parent == ss.SESSIONS_DIR / "对话A" / "skill" / "SW1"


def test_history_appends_to_session_file():
    use("对话A")
    p = dm.append_history("R1", "display ip interface brief", "up",
                          transport="telnet", target="1.2.3.4", executed=True)
    assert Path(p) == ss.history_path("R1")
    row = json.loads(ss.history_path("R1").read_text(encoding="utf-8").splitlines()[0])
    assert row["command"] == "display ip interface brief" and row["executed"] is True


def test_history_device_name_is_validated():
    """设备名非法时不能落盘（路径穿越防护），但也不能抛异常打断工具调用。"""
    use("对话A")
    assert dm.append_history("../越权", "x") == ""
    with pytest.raises(dm.ManualError):
        dm.tail_history("../越权")


# ---------------------------------------------------------------- 当前会话解析

def test_current_prefers_pinned_then_pointer(monkeypatch):
    use("对话A")
    assert ss.current() == "对话A"
    # 清掉进程内钉住值后，应退回到读指针文件
    ss._pinned = None
    assert ss.current() == "对话A"
    # 指针文件被外部改写（模拟另一个进程开了新对话）→ 跟随
    (ss.SESSIONS_DIR / ".current").write_text("外部对话\n", encoding="utf-8")
    assert ss.current() == "外部对话"


@pytest.mark.parametrize("bad", ["../逃逸", "C:/逃逸", "a/b", "a\\b"])
def test_pointer_rejects_unsafe_session(monkeypatch, bad):
    ss._pinned = None
    ss.SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    (ss.SESSIONS_DIR / ".current").write_text(bad + "\n", encoding="utf-8")
    monkeypatch.delenv("NETWORKCLAW_SESSION", raising=False)
    assert ss.current() == ss.DEFAULT_SID


@pytest.mark.parametrize("bad", ["../逃逸", "C:/逃逸", "a/b", "a\\b"])
def test_explicit_session_path_rejects_unsafe_name(bad):
    with pytest.raises(ss.SessionError):
        ss.session_dir(bad)


def test_current_falls_back_to_env(monkeypatch):
    """没有指针文件时用环境变量（父进程派生 MCP 子进程的兜底）。"""
    monkeypatch.setenv("NETWORKCLAW_SESSION", "env-会话")
    assert ss.current() == "env-会话"
    monkeypatch.setenv("NETWORKCLAW_SESSION", "../非法")
    assert ss.current() == ss.DEFAULT_SID, "非法 env 值不能当成路径用"


def test_use_session_syncs_environment(monkeypatch):
    monkeypatch.setenv("NETWORKCLAW_SESSION", "before")
    use("环境同步会话")
    assert os.environ["NETWORKCLAW_SESSION"] == "环境同步会话"


def test_host_port_fallback_is_safe():
    from core.device_registry import resolve_name

    name = resolve_name("telnet", host="host:2000", port=23)
    assert ":" not in name
    assert ss.safe_name(name) == name


def test_current_defaults_when_nothing_set():
    assert ss.current() == ss.DEFAULT_SID


def test_use_session_syncs_run_log():
    """技能与运行日志必须是同一个 sid，否则「本对话的记忆」被拆成两半。"""
    use("对话A")
    assert run_log.session() == "对话A"
    assert run_log.path().is_relative_to(run_log.LOG_ROOT)


# ---------------------------------------------------------------- 清单与总览

def test_list_sessions_skips_dotfiles_and_empty():
    use("对话A")
    dm.ensure_manual("SW1", model="S5700")     # 有内容才会被列出
    (ss.SESSIONS_DIR / "空对话").mkdir(parents=True)
    (ss.SESSIONS_DIR / ".current.tmp").write_text("x", encoding="utf-8")
    rows = ss.list_sessions()
    sids = [r["sid"] for r in rows]
    assert "对话A" in sids and "空对话" not in sids and ".current" not in sids


def test_list_sessions_marks_current():
    use("对话A")
    dm.ensure_manual("SW1", model="S5700")     # 有内容才会被列出
    use("对话B")
    dm.ensure_manual("SW2", model="S5700")
    rows = {r["sid"]: r for r in ss.list_sessions()}
    assert rows["对话B"]["current"] is True and rows["对话A"]["current"] is False


def test_sessions_overview_includes_history_only():
    """只有历史没有手册的设备（旧版两套命名不一致的产物）也要列出来。"""
    use("对话A")
    dm.append_history("SW9", "display version", "ok", executed=True)
    rows = {r["sid"]: r for r in dm.sessions_overview()}
    detail = " ".join(rows["对话A"]["detail"])
    assert "SW9（仅历史 1 条）" in detail


# ---------------------------------------------------------------- 提示词直注

def test_context_for_model_lists_current_session_only():
    use("对话A")
    dm.ensure_manual("SW1", vendor="Huawei", model="S5700-28C-HI", role="接入交换机")
    ctx = dm.context_for_model()
    assert "SW1" in ctx and "S5700-28C-HI" in ctx and "接入交换机" in ctx
    assert "坑：" in ctx, "至少带一条该设备的注意事项"
    # 本对话新学到的坑应当出现在摘要里（取注意事项的最后一条）
    dm.update_section("SW1", "注意事项", "接口需先 shutdown")
    assert "接口需先 shutdown" in dm.context_for_model()
    use("对话B")
    assert dm.context_for_model() == "", "没有技能的对话不该往提示词里塞噪声"


def test_context_for_model_caps_device_count():
    use("对话A")
    for i in range(12):
        dm.ensure_manual(f"SW{i}", model="S5700")
    ctx = dm.context_for_model(max_devices=3, max_chars=100000)
    listed = sum(1 for i in range(12) if f"SW{i}｜" in ctx)
    assert listed == 3
    assert "还有 9 台设备" in ctx


def test_context_for_model_extracts_meta_without_colon_noise():
    """摘要里不能出现「｜：型号」这种没剥干净的冒号。"""
    use("对话A")
    dm.ensure_manual("SW1", model="S5700-28C-HI", role="接入交换机")
    ctx = dm.context_for_model()
    assert "｜：" not in ctx and "｜S5700-28C-HI｜接入交换机｜" in ctx


# ---------------------------------------------------------------- 旧版迁移

@pytest.fixture()
def legacy_dirs(tmp_path, monkeypatch):
    """造一套旧版全局布局：skills/<设备>/SKILL.md + data/device_history/<设备>.jsonl"""
    skills = tmp_path / "legacy_skills"
    hist = tmp_path / "legacy_hist"
    (skills / "AR1").mkdir(parents=True)
    (skills / "AR1" / "SKILL.md").write_text("# AR1 手册\n", encoding="utf-8")
    (skills / "LSW1").mkdir(parents=True)
    (skills / "LSW1" / "SKILL.md").write_text("# LSW1 手册\n", encoding="utf-8")
    hist.mkdir(parents=True)
    (hist / "AR1.jsonl").write_text('{"command":"display version"}\n', encoding="utf-8")
    (hist / "SW1.jsonl").write_text('{"command":"vlan 10"}\n' * 3, encoding="utf-8")
    monkeypatch.setattr(dm, "SKILLS_DIR", skills)
    monkeypatch.setattr(dm, "HISTORY_DIR", hist)
    return skills, hist


def test_migrate_legacy_copies_manuals_and_orphan_history(legacy_dirs):
    rep = dm.migrate_legacy("旧版汇总")
    assert sorted(rep["migrated"]) == ["AR1", "LSW1"]
    assert rep["history_only"] == ["SW1"], "只有历史没有手册的设备也要搬"
    root = ss.SESSIONS_DIR / "旧版汇总" / "skill"
    assert (root / "AR1" / "SKILL.md").read_text(encoding="utf-8") == "# AR1 手册\n"
    assert (root / "AR1" / "history.jsonl").is_file()
    assert len((root / "SW1" / "history.jsonl").read_text(encoding="utf-8").splitlines()) == 3


def test_migrate_legacy_skips_existing_without_force(legacy_dirs):
    dm.migrate_legacy("旧版汇总")
    (ss.SESSIONS_DIR / "旧版汇总" / "skill" / "AR1" / "SKILL.md").write_text(
        "我改过的内容\n", encoding="utf-8")
    rep = dm.migrate_legacy("旧版汇总")
    assert "AR1" in rep["skipped"] and rep["migrated"] == []
    assert (ss.SESSIONS_DIR / "旧版汇总" / "skill" / "AR1" / "SKILL.md").read_text(
        encoding="utf-8") == "我改过的内容\n", "不加 --force 不能覆盖用户改过的手册"
    rep = dm.migrate_legacy("旧版汇总", force=True)
    assert "AR1" in rep["migrated"]


def test_migrate_legacy_noop_when_no_legacy(tmp_path, monkeypatch):
    monkeypatch.setattr(dm, "SKILLS_DIR", tmp_path / "不存在")
    monkeypatch.setattr(dm, "HISTORY_DIR", tmp_path / "也不存在")
    assert dm.migrate_legacy()["missing"] is True


# ---------------------------------------------------------------- MCP 服务端

def test_manual_server_list_session_skills():
    from mcp_tools import manual_server as ms
    use("对话A")
    dm.ensure_manual("SW1", model="S5700")
    dm.append_history("SW1", "display version", "ok", executed=True)
    use("对话B")
    dm.ensure_manual("R1", model="AR2220")     # B 也要有内容才会被列出
    out = ms.list_session_skills()
    assert "对话A" in out and "对话B" in out
    assert "SW1（手册" in out and "R1（手册" in out and "← 当前对话" in out


def test_manual_server_read_with_explicit_session():
    from mcp_tools import manual_server as ms
    use("对话A")
    dm.ensure_manual("SW1", model="S5700")
    dm.update_section("SW1", "常用配置", "A 对话的配置")
    use("对话B")
    out = ms.read_device_manual("SW1", session="对话A")
    assert "A 对话的配置" in out
    # 不带 session 时只看到当前对话（读不到 A 的内容）
    assert "还没有手册" in ms.read_device_manual("SW1")
    # 不存在的会话要给出可读提示，而不是崩
    assert "没有设备" in ms.read_device_manual("SW1", session="不存在的对话")


def test_manual_server_history_with_explicit_session():
    from mcp_tools import manual_server as ms
    use("对话A")
    dm.append_history("R1", "display version", "ok", executed=True)
    use("对话B")
    out = ms.recent_device_history("R1", session="对话A")
    assert "display version" in out and "非当前会话" in out
    assert "暂无命令历史" in ms.recent_device_history("R1")


def test_manual_server_list_mentions_isolation():
    from mcp_tools import manual_server as ms
    use("对话A")
    out = ms.list_device_manuals()
    assert "当前会话" in out and "session/" in out


# ---------------------------------------------------------------- RAG / agent 接线

def test_rag_no_longer_indexes_manuals():
    """手册移出全局索引（按会话隔离后，塞索引会在切换会话时串味）。"""
    from core import rag
    assert not hasattr(rag, "_manual_texts"), "手册来源应已从 RAG 移除"
    use("对话A")
    dm.ensure_manual("SW1", model="S5700")
    dm.update_section("SW1", "常用配置", "会话隔离专用标记串ZZZ")
    chunks = rag.load_chunks()
    assert not any("会话隔离专用标记串ZZZ" in c for c in chunks), "手册内容不该进索引"
    assert "设备手册按会话隔离" in rag.knowledge_sources()


def test_run_log_digests_scoped_to_current_session():
    """运行日志摘要只取当前会话——别处对话发生过什么不该渗进来。"""
    from core import rag
    use("对话A")
    run_log.log_step(round_no=1, name="exec_telnet_command",
                     args={"command": "vlan 10"}, output="ok")
    assert any("vlan 10" in d for d in rag._run_log_digests())
    use("对话B")
    run_log.log_step(round_no=1, name="exec_telnet_command",
                     args={"command": "vlan 20"}, output="ok")
    digests = rag._run_log_digests()
    assert any("vlan 20" in d for d in digests)
    assert not any("vlan 10" in d for d in digests), "B 对话不该检索到 A 对话的日志"


def test_agent_prompt_includes_session_skills():
    from core.agent import _session_skill_context
    use("对话A")
    dm.ensure_manual("SW1", vendor="Huawei", model="S5700-28C-HI", role="接入交换机")
    ctx = _session_skill_context()
    assert "本会话已积累的设备技能" in ctx and "SW1" in ctx
    use("对话B")
    assert _session_skill_context() == ""
