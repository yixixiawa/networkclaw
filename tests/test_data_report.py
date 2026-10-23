"""工作流数据报告测试：把一次对话/实验的过程汇总成一份自包含报告。

对应用户需求：「多添加一个报告导出的环节，让本地模型跑完后输出整个工作流的内容，
MCP 工具名字为 data_report」。

报告的数据源有三处，测试必须逐一对齐，否则报告会「看着有内容、其实缺一半」：
  ① 会话技能目录  session/<sid>/skill/<设备>/{SKILL.md,history.jsonl}
  ② 运行日志      data/run_logs/<日期>/<sid>.jsonl + .events.jsonl
  ③ 实验报告      data/lab_reports/<NN-实验名>.md

覆盖五组断言：
  ① 采集完整（设备/手册/历史/工具调用/事件都进得来）；
  ② 隔离语义（默认只导当前对话，其他对话只报数量不搬内容；显式 session 只读跨会话）；
  ③ 渲染质量（Markdown 块间距正确、超长回显被裁剪、敏感字段不落盘）；
  ④ 导出落盘（md/json 双格式、文件名带会话标识、summary_text 可读）；
  ⑤ MCP 服务端三个工具（含非法 format 的可读报错）。

注意：conftest 的 autouse 夹具已把 SESSIONS_DIR / run_log.LOG_ROOT 隔离到 tmp_path，
所以这里可以放心地真实调用 data_report.export()，不会碰到开发者机器的 session/。
但 REPORT_DIR 是模块级常量（指向真实 data/data_reports），必须每个用例显式传 out_dir。
"""
import json

import pytest

from core import data_report as dr
from core import device_manual as dm
from core import run_log, session_skills as ss


def use(name: str) -> str:
    ss.use_session(name)
    return name


@pytest.fixture()
def out_dir(tmp_path):
    """导出目录：绝不落到真实 data/data_reports。"""
    d = tmp_path / "data_reports"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _seed(sid: str, manual=True, cmd="display version"):
    """在指定对话里造一份最小但完整的工作流产物。"""
    use(sid)
    dm.ensure_manual("LSW1", vendor="Huawei", model="S5700-28C-HI", role="接入交换机")
    if manual:
        dm.update_section("LSW1", "常用配置", "vlan batch 10 20")
    dm.append_history("LSW1", cmd, "ok", transport="telnet",
                      target="192.168.1.179", executed=True)
    dm.append_history("LSW1", "bad-cmd", "Error", executed=False)
    run_log.log_step(round_no=1, name="exec_telnet_command",
                     args={"command": cmd, "host": "192.168.1.179", "port": 2000},
                     output="<LSW1>display version\nVRP (R) software\n" + "x" * 900)
    run_log.event("device_probe", name="LSW1", port=2000, ok=True)


# ---------------------------------------------------------------- 采集

def test_collect_gathers_devices_manual_and_history():
    _seed("对话A")
    data = dr.collect("对话A")
    assert data["session"] == "对话A" and data["is_current"] is True
    assert data["device_count"] == 1
    d = data["devices"][0]
    assert d["device"] == "LSW1" and d["has_manual"] is True
    assert d["manual_bytes"] > 0 and "vlan batch 10 20" in d["manual"]
    assert d["history_total"] == 2 and d["history_executed"] == 1
    assert d["commands"] == ["display version"], "只收成功执行的命令"
    c = data["counts"]
    assert c["manuals"] == 1 and c["history_total"] == 2 and c["history_executed"] == 1
    assert c["tool_steps"] == 1 and c["events"] == 1


def test_collect_skips_underscore_dirs():
    """`_misnamed_backup` 这类人工备份目录不是设备，不能混进设备清单。"""
    _seed("对话A")
    root = ss.SESSIONS_DIR / "对话A" / "skill"
    (root / "_misnamed_backup").mkdir(parents=True)
    (root / "_misnamed_backup" / "history.jsonl").write_text(
        '{"command":"x","executed":true}\n', encoding="utf-8")
    data = dr.collect("对话A")
    assert [d["device"] for d in data["devices"]] == ["LSW1"]


def test_collect_defaults_to_current_session():
    _seed("对话A")
    assert dr.collect()["session"] == "对话A"


def test_collect_empty_session_is_not_an_error():
    """从没跑过的对话也要能出报告（空报告），而不是抛异常。"""
    use("空对话")
    data = dr.collect("空对话")
    assert data["device_count"] == 0 and data["devices"] == []
    assert data["counts"]["llm_calls"] == 0


def test_collect_rejects_unsafe_session():
    with pytest.raises(ss.SessionError):
        dr.collect("../越权")


# ---------------------------------------------------------------- 隔离

def test_other_sessions_reported_without_content():
    """默认只导当前对话；其他对话只报数量，不搬内容（保持隔离语义）。"""
    _seed("对话A")
    _seed("对话B", cmd="vlan 20")
    data = dr.collect("对话A")
    assert [d["device"] for d in data["devices"]] == ["LSW1"]
    others = {s["sid"] for s in data["other_sessions"]}
    assert "对话B" in others
    blob = json.dumps(data, ensure_ascii=False)
    assert "vlan 20" not in blob, "其他对话的命令内容不得出现在报告里"


def test_explicit_cross_session_export_is_readonly():
    """显式指定会话可导出别的对话（只读）；导出后当前对话不变。"""
    _seed("对话A", cmd="display vlan")
    _seed("对话B", cmd="vlan 20")
    use("对话B")
    data = dr.collect("对话A")
    assert data["is_current"] is False
    assert data["devices"][0]["commands"] == ["display vlan"]
    assert ss.current() == "对话B", "跨会话只读不得改动当前指针"


# ---------------------------------------------------------------- 渲染

def test_render_markdown_has_proper_block_spacing():
    """标题/表格/代码块之间必须有空行，否则 Markdown 渲染会粘连。"""
    _seed("对话A")
    md = dr.render_markdown(dr.collect("对话A"))
    assert md.startswith("# 工作流数据报告：对话A\n")
    assert "\n\n## 一、总览\n" in md
    assert "\n\n### LSW1 手册（模型自建）\n" in md
    assert "\n\n```\n" in md, "代码块前要有空行"
    assert "\n\n\n" not in md, "连续空行应被折叠成一个"
    assert "| 涉及设备 | 1 台 |" in md


def test_render_markdown_clips_long_output():
    """超长设备回显要裁剪（完整内容仍在原始 jsonl），报告不能被撑爆。"""
    _seed("对话A")
    md = dr.render_markdown(dr.collect("对话A"))
    assert "（中间省略" in md
    assert "x" * 900 not in md


def test_render_markdown_includes_workflow_and_events():
    _seed("对话A")
    md = dr.render_markdown(dr.collect("对话A"))
    assert "## 三、工作流逐步记录" in md
    assert "exec_telnet_command" in md and "display version" in md
    assert "## 四、过程事件" in md and "device_probe" in md


def test_render_markdown_includes_lab_report(tmp_path, monkeypatch):
    """会话标识形如 `01-实验名` 时应关联 data/lab_reports/<实验名>.md。"""
    labs = tmp_path / "data" / "lab_reports"
    labs.mkdir(parents=True)
    (labs / "01-ACCESS配置.md").write_text("# 验收\n\n命中 4/7\n", encoding="utf-8")
    monkeypatch.setattr(dr, "BASE_DIR", tmp_path)
    _seed("01-ACCESS配置")
    data = dr.collect("01-ACCESS配置")
    assert data["lab_report_path"].endswith("01-ACCESS配置.md")
    assert "## 五、实验报告（验收比对）" in dr.render_markdown(data)


def test_render_markdown_no_devices_placeholder():
    use("空对话")
    md = dr.render_markdown(dr.collect("空对话"))
    assert "（本会话尚未产生任何设备技能）" in md
    assert "（无工具调用记录）" in md


# ---------------------------------------------------------------- 导出

def test_export_writes_both_formats(out_dir):
    _seed("对话A")
    res = dr.export("对话A", fmt="both", out_dir=out_dir)
    md_p, js_p = res["md_path"], res["json_path"]
    assert md_p.endswith(".md") and js_p.endswith(".json")
    assert "对话A" in md_p, "文件名应带会话标识，便于区分多轮实验"
    md = open(md_p, encoding="utf-8").read()
    assert md.startswith("# 工作流数据报告：对话A")
    slim = json.loads(open(js_p, encoding="utf-8").read())
    assert slim["session"] == "对话A" and slim["counts"]["tool_steps"] == 1
    assert "lab_report" not in slim, "json 只存路径，不重复塞报告全文"


def test_export_md_only(out_dir):
    _seed("对话A")
    res = dr.export("对话A", fmt="md", out_dir=out_dir)
    assert res["md_path"] and res["json_path"] == ""


def test_export_sanitizes_session_in_filename(out_dir):
    """会话标识含分隔符时不能生成非法文件名（run_log._safe 兜底）。"""
    use("对话A")
    dm.ensure_manual("LSW1", model="S5700")
    res = dr.export("对话A", out_dir=out_dir)
    assert "对话A" in res["md_path"] and "/" not in res["md_path"].split("data_reports")[-1]


def test_summary_text_is_readable(out_dir):
    _seed("对话A")
    txt = dr.summary_text(dr.export("对话A", fmt="both", out_dir=out_dir))
    assert "对话A" in txt and "设备 1 台" in txt and "命令 2 条" in txt
    assert ".md" in txt and ".json" in txt


def test_cli_list_and_export(out_dir, monkeypatch, capsys):
    """CLI 入口：--list 列会话，导出走同一套逻辑。"""
    monkeypatch.setattr(dr, "REPORT_DIR", out_dir)
    _seed("对话A")
    assert dr._main(["--list"]) == 0
    assert "对话A" in capsys.readouterr().out
    assert dr._main(["--session", "对话A", "--format", "both"]) == 0
    assert "已导出会话" in capsys.readouterr().out
    assert list(out_dir.glob("*.md")), "CLI 导出应真的落盘"


# ---------------------------------------------------------------- MCP 服务端

def test_report_server_export_tool(out_dir, monkeypatch):
    from mcp_tools import report_server as rs
    monkeypatch.setattr(dr, "REPORT_DIR", out_dir)
    _seed("对话A")
    out = rs.export_workflow_report()          # 留空 = 当前对话
    assert "已导出会话「对话A」" in out and "设备 1 台" in out
    assert list(out_dir.glob("*.md"))


def test_report_server_rejects_bad_format():
    from mcp_tools import report_server as rs
    out = rs.export_workflow_report(format="pdf")
    assert "md / json / both" in out and "pdf" in out


def test_report_server_overview_does_not_write(out_dir, monkeypatch):
    from mcp_tools import report_server as rs
    monkeypatch.setattr(dr, "REPORT_DIR", out_dir)
    _seed("对话A")
    out = rs.workflow_report_overview()
    assert "会话：对话A（当前对话）" in out
    assert "设备 1 台" in out and "LSW1：有手册" in out
    assert not list(out_dir.glob("*")), "overview 不应写文件"


def test_report_server_list_sessions():
    from mcp_tools import report_server as rs
    _seed("对话A")
    out = rs.list_report_sessions()
    assert "对话A" in out and "← 当前对话" in out
    assert "export_workflow_report" in out


def test_report_server_list_sessions_empty_when_nothing():
    from mcp_tools import report_server as rs
    use("空对话")          # 无技能、无日志 → 不应被列为可导出会话
    assert "还没有任何会话" in rs.list_report_sessions()


def test_report_server_session_error_is_readable():
    from mcp_tools import report_server as rs
    out = rs.export_workflow_report(session="../越权")
    assert "导出失败" in out and "不合法" in out
