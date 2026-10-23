"""数据报告导出：把一次完整工作流（会话 → 设备 → 逐轮调用 → 命令 → 验收）汇总成报告。

存在的意义：
    用户要求「本地模型跑完后输出整个工作流的内容」。一次实验/一次对话产生的信息
    散落在多个地方——会话技能目录（手册 + 命令历史）、运行日志（逐轮 LLM 调用与
    工具调用）、实验报告（验收比对）。人工拼接既慢又容易漏。

    本模块把它们按**确定的顺序**汇总成一份自包含报告：谁在哪个会话里、对哪些设备、
    依次做了什么、设备回了什么、最终验收如何。既可给人看，也可作为复盘/微调语料。

数据来源（都只读，不产生副作用）：
    session/<会话>/skill/<设备>/SKILL.md          设备手册（模型自建）
    session/<会话>/skill/<设备>/history.jsonl     命令历史（工具层自动记录）
    data/run_logs/<日期>/<会话>.jsonl             LLM 调用与工具调用逐条记录
    data/run_logs/<日期>/<会话>.events.jsonl      过程事件（探测/验收/开始结束）
    data/lab_reports/<实验>.md                    实验报告（含验收比对表）

落盘位置：
    data/data_reports/<时间戳>-<会话>.md           汇总报告（Markdown）
    data/data_reports/<时间戳>-<会话>.json        结构化数据（供程序再加工）

用法（工具层）：
    from core import data_report
    path = data_report.export()                    # 导出当前会话
    path = data_report.export(session="01-xxx")    # 指定会话
"""
from __future__ import annotations

import datetime
import json
import re
from pathlib import Path

from core import device_manual, run_log, session_skills
from core.paths import BASE_DIR

REPORT_DIR = BASE_DIR / "data" / "data_reports"

# 报告里逐轮工具调用的回显上限（太长会淹没结构，完整内容仍在原始 jsonl 里）
OUTPUT_HEAD = 400
OUTPUT_TAIL = 200


# ---------------------------------------------------------------- 采集

def _read_jsonl(fp: Path) -> list[dict]:
    if not fp.exists():
        return []
    rows: list[dict] = []
    for line in fp.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def _collect_devices(sid: str) -> list[dict]:
    """当前会话里每台设备的：手册要点 + 命令历史条数 + 关键命令。

    跳过以 `_` 开头的目录（如 `_misnamed_backup` 这类人工备份/中间产物），
    它们不是设备，混进报告会让统计与设备清单失真。
    """
    out: list[dict] = []
    try:
        skill_root = session_skills.skill_dir("x", sid).parent
    except session_skills.SessionError:
        return out
    if not skill_root.is_dir():
        return out
    for d in sorted(skill_root.iterdir()):
        if not d.is_dir() or d.name.startswith("_"):
            continue
        manual_fp = d / "SKILL.md"
        hist_fp = d / "history.jsonl"
        rows = _read_jsonl(hist_fp)
        executed = [r for r in rows if r.get("executed")]
        cmds = [str(r.get("command", "")).strip() for r in executed]
        out.append({
            "device": d.name,
            "has_manual": manual_fp.is_file(),
            "manual_bytes": manual_fp.stat().st_size if manual_fp.is_file() else 0,
            "manual": (manual_fp.read_text(encoding="utf-8", errors="replace")
                       if manual_fp.is_file() else ""),
            "history_total": len(rows),
            "history_executed": len(executed),
            "commands": cmds,
        })
    return out


def _collect_run_log(sid: str, days: int = 3) -> dict:
    """取最近 days 天里该会话的运行日志（模型调用 + 工具调用 + 事件）。"""
    today = datetime.date.today()
    calls: list[dict] = []
    events: list[dict] = []
    used_days: list[str] = []
    for delta in range(days):
        day = (today - datetime.timedelta(days=delta)).isoformat()
        c = run_log.read_session(day, sid)
        e = _read_jsonl(run_log.LOG_ROOT / day / f"{run_log._safe(sid)}.events.jsonl")
        if c or e:
            used_days.append(day)
            calls.extend(c)
            events.extend(e)
    return {"calls": calls, "events": events, "days": used_days}


def _find_lab_report(sid: str) -> Path | None:
    """会话标识形如 `01-实验名`，映射到 data/lab_reports/<NN-实验名>.md。"""
    m = re.match(r"^(\d+)-(.+)$", sid)
    if not m:
        return None
    num, name = m.group(1), m.group(2)
    cand = BASE_DIR / "data" / "lab_reports" / f"{num}-{name}.md"
    if cand.is_file():
        return cand
    # 编号前缀 + 模糊匹配（sid 清洗过，名字可能与文件名不完全一致）
    for fp in (BASE_DIR / "data" / "lab_reports").glob(f"{num}-*.md"):
        return fp
    return None


def collect(session: str = "", days: int = 3) -> dict:
    """采集指定会话（默认当前会话）的全部工作流数据。只读。"""
    sid = (session or "").strip() or session_skills.current()
    if session:
        session_skills.safe_name(sid, "会话标识")
    devices = _collect_devices(sid)
    logs = _collect_run_log(sid, days)

    # 会话目录概览（其他会话只报数量，不搬内容——保持隔离语义）
    others = [s for s in session_skills.list_sessions() if s["sid"] != sid]

    lab_report_fp = _find_lab_report(sid)
    lab_report = ""
    if lab_report_fp:
        lab_report = lab_report_fp.read_text(encoding="utf-8", errors="replace")

    calls = logs["calls"]
    events = logs["events"]
    tool_steps = [r for r in calls if r.get("kind") == "tool_step"]
    llm_calls = [r for r in calls if r.get("kind") == "llm_call"]

    return {
        "generated_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "session": sid,
        "is_current": sid == session_skills.current(),
        "days": logs["days"],
        "device_count": len(devices),
        "devices": devices,
        "counts": {
            "llm_calls": len(llm_calls),
            "tool_steps": len(tool_steps),
            "events": len(events),
            "manuals": sum(1 for d in devices if d["has_manual"]),
            "history_total": sum(d["history_total"] for d in devices),
            "history_executed": sum(d["history_executed"] for d in devices),
        },
        "tool_steps": tool_steps,
        "events": events,
        "lab_report": lab_report,
        "lab_report_path": str(lab_report_fp) if lab_report_fp else "",
        "other_sessions": [{"sid": s["sid"], "files": s["files"]} for s in others],
    }


# ---------------------------------------------------------------- 渲染

def _clip(text: str, head: int = OUTPUT_HEAD, tail: int = OUTPUT_TAIL) -> str:
    text = (text or "").rstrip()
    if len(text) <= head + tail:
        return text
    return (text[:head] + f"\n…（中间省略 {len(text) - head - tail} 字）…\n"
            + text[-tail:])


def render_markdown(data: dict) -> str:
    """把采集结果渲染成一份人可读的完整报告。

    拼接策略：先用块级列表收集，再用 `_join_blocks()` 规范化空行——
    直接 "\n".join 会让标题/表格/代码块粘连（Markdown 渲染会错乱）。
    """
    c = data["counts"]
    L: list[str] = [
        f"# 工作流数据报告：{data['session']}",
        "",
        f"- 生成时间：{data['generated_at']}",
        f"- 会话标识：`{data['session']}`"
        + ("（当前对话）" if data["is_current"] else "（指定会话）"),
        f"- 数据日期：{'、'.join(data['days']) or '（无运行日志）'}",
        "",
        "## 一、总览",
        "",
        "| 指标 | 数值 |",
        "|---|---|",
        f"| 涉及设备 | {data['device_count']} 台 |",
        f"| 已建设备手册 | {c['manuals']} 份 |",
        f"| 命令历史 | {c['history_total']} 条（成功执行 {c['history_executed']} 条） |",
        f"| 模型调用 | {c['llm_calls']} 次 |",
        f"| 工具调用 | {c['tool_steps']} 次 |",
        f"| 过程事件 | {c['events']} 条 |",
        "",
    ]

    # 二、设备
    L += ["## 二、设备与技能", ""]
    if not data["devices"]:
        L += ["（本会话尚未产生任何设备技能）", ""]
    else:
        L += ["| 设备 | 手册 | 命令历史 | 成功执行 |", "|---|---|---|---|"]
        for d in data["devices"]:
            L.append(f"| {d['device']} | "
                     f"{'✅ ' + str(d['manual_bytes']) + 'B' if d['has_manual'] else '—'} | "
                     f"{d['history_total']} | {d['history_executed']} |")
        L.append("")

        for d in data["devices"]:
            if d["manual"]:
                L += [f"### {d['device']} 手册（模型自建）", "", d["manual"].strip(), ""]

        for d in data["devices"]:
            if not d["commands"]:
                continue
            L += [f"### {d['device']} 执行过的命令（{len(d['commands'])} 条）", ""]
            L += ["```"]
            L += [f"  {i}. {cmd}" for i, cmd in enumerate(d["commands"], 1)]
            L += ["```", ""]

    # 三、工作流逐步
    L += ["## 三、工作流逐步记录", ""]
    if not data["tool_steps"]:
        L += ["（无工具调用记录）", ""]
    else:
        for i, s in enumerate(data["tool_steps"], 1):
            args = s.get("args") or {}
            cmd = args.get("command") or args.get("device") or json.dumps(
                {k: v for k, v in args.items() if k != "password"},
                ensure_ascii=False)[:200]
            target = args.get("host", "")
            if target and args.get("port"):
                target = f"{target}:{args['port']}"
            L += [
                f"### 第 {s.get('round', i)} 步 · {s.get('tool', '?')}"
                + (f" → {target}" if target else ""),
                "",
                f"- 时间：{s.get('ts', '')}",
                f"- 输入：`{cmd}`",
                "",
            ]
            out = s.get("output", "")
            if out:
                L += ["```", _clip(out), "```", ""]

    # 四、过程事件
    if data["events"]:
        L += ["## 四、过程事件", "", "| 时间 | 类型 | 摘要 |", "|---|---|---|"]
        for e in data["events"]:
            kind = e.get("kind", "")
            rest = {k: v for k, v in e.items()
                    if k not in ("kind", "ts", "seq", "session")}
            summary = json.dumps(rest, ensure_ascii=False)[:180]
            L.append(f"| {e.get('ts', '')} | {kind} | {summary} |")
        L.append("")

    # 五、实验报告（若存在）
    if data["lab_report"]:
        L += ["## 五、实验报告（验收比对）", "",
              f"来源：`{Path(data['lab_report_path']).name}`", "",
              data["lab_report"].strip(), ""]

    if data["other_sessions"]:
        L += ["## 附：其他对话",
              "",
              f"另有 {len(data['other_sessions'])} 个对话拥有各自的设备技能"
              f"（相互隔离，本报告不包含其内容）：",
              ""]
        for s in data["other_sessions"][:20]:
            L.append(f"- `{s['sid']}`（{s['files']} 个文件）")
        L.append("")

    return _join_blocks(L)


def _join_blocks(lines: list[str]) -> str:
    """规范化 Markdown 块间距：连续空行折叠成一个，并保证块与块之间恰好一个空行。

    直接 "\\n".join 会让 `### 标题` 紧贴上一段（渲染成正文而非标题）、
    表格紧贴段落（渲染成普通文本）。这里统一收口。
    """
    out: list[str] = []
    for raw in lines:
        for ln in raw.split("\n"):
            if ln.strip() == "":
                if out and out[-1] != "":
                    out.append("")
            else:
                out.append(ln.rstrip())
    while out and out[-1] == "":
        out.pop()
    return "\n".join(out) + "\n"


# ---------------------------------------------------------------- 导出入口

def export(session: str = "", days: int = 3, fmt: str = "md",
           out_dir: Path | None = None) -> dict:
    """导出报告，返回 {md_path, json_path, session, counts}。

    Args:
        session: 会话标识；留空=当前会话
        days: 回溯运行日志的天数
        fmt: "md"（默认，Markdown）/ "json"（结构化）/ "both"
        out_dir: 自定义输出目录
    """
    data = collect(session, days)
    target_dir = Path(out_dir) if out_dir else REPORT_DIR
    target_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_sid = run_log._safe(data["session"])
    base = target_dir / f"{stamp}-{safe_sid}"

    md_path = json_path = None
    if fmt in ("md", "both"):
        md_path = base.with_suffix(".md")
        md_path.write_text(render_markdown(data), encoding="utf-8")
    if fmt in ("json", "both"):
        json_path = base.with_suffix(".json")
        slim = {k: v for k, v in data.items() if k not in ("lab_report",)}
        slim["lab_report_path"] = data["lab_report_path"]
        json_path.write_text(json.dumps(slim, ensure_ascii=False, indent=2),
                             encoding="utf-8")

    return {
        "session": data["session"],
        "md_path": str(md_path) if md_path else "",
        "json_path": str(json_path) if json_path else "",
        "counts": data["counts"],
        "device_count": data["device_count"],
    }


def summary_text(result: dict) -> str:
    """给模型/终端看的简短回执。"""
    c = result["counts"]
    return (f"已导出会话「{result['session']}」的工作流报告：\n"
            f"  设备 {result['device_count']} 台｜手册 {c['manuals']} 份｜"
            f"命令 {c['history_total']} 条（执行 {c['history_executed']}）｜"
            f"模型调用 {c['llm_calls']} 次｜工具调用 {c['tool_steps']} 次\n"
            + (f"  Markdown：{result['md_path']}\n" if result["md_path"] else "")
            + (f"  JSON：{result['json_path']}" if result["json_path"] else ""))


# ---------------------------------------------------------------- CLI

def _main(argv: list[str]) -> int:
    import argparse

    ap = argparse.ArgumentParser(prog="python -m core.data_report",
                                 description="导出工作流数据报告")
    ap.add_argument("--session", default="", help="会话标识（默认当前会话）")
    ap.add_argument("--days", type=int, default=3, help="回溯运行日志天数")
    ap.add_argument("--format", dest="fmt", default="md",
                    choices=["md", "json", "both"])
    ap.add_argument("--list", action="store_true", help="列出所有会话")
    args = ap.parse_args(argv)

    if args.list:
        for s in session_skills.list_sessions():
            mark = " ←当前" if s["current"] else ""
            print(f"  {s['sid']}（{s['files']} 个文件，更新于 {s['updated']}）{mark}")
        return 0

    res = export(args.session, args.days, args.fmt)
    print(summary_text(res))
    return 0


if __name__ == "__main__":
    import sys

    sys.path.insert(0, str(BASE_DIR))
    raise SystemExit(_main(sys.argv[1:]))
