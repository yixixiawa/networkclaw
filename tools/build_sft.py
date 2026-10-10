"""从运行日志里导出微调（SFT）数据集。

原料是 data/run_logs/<日期>/<实验>.jsonl：里面既有模型每次调用的完整输出，
也有它实际下发的每条命令与设备回显（core/run_log.py 写的两份日志）。

导出策略：
- **正样本**：验收命中率达到阈值（默认 60%）的实验，把
  「任务书（instruction）→ 模型实际下发的命令序列（output）」作为一条 SFT 样本。
  命令序列比模型的自然语言总结更适合微调——它是可执行的、可验证的。
- **负样本标记**：命中率低的实验单独落到 `low.jsonl`，不参与训练，
  留给人工复核或下一轮提示词改进后重跑。
- **假阳性剔除**：命中率 100% 但净提升 0 的（设备开机就自带参考答案）
  同样落 `low.jsonl`——它的"满分"与模型无关（见 issues.md P1）。

用法：
    python tools/build_sft.py                       # 导出今天的所有实验
    python tools/build_sft.py --day 2026-09-30
    python tools/build_sft.py --min-pct 80 --out data/finetune/sft_v1.jsonl
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from core.run_log import LOG_ROOT  # noqa: E402
from tools.lab_run_agent import parse_doc  # noqa: E402

OUT_DIR = BASE_DIR / "data" / "finetune"

# 只看这几个工具的下发命令（display 类只读命令不入训练集，
# 但会保留成 output 里的注释——因为「先查看再配置」是我们要保留的好习惯）
CONFIG_TOOLS = {"exec_telnet_command", "exec_command"}


def load_session(day: str, stem: str) -> tuple[list[dict], list[dict]]:
    d = LOG_ROOT / day
    calls, events = [], []
    fp = d / f"{stem}.jsonl"
    if fp.exists():
        calls = [json.loads(x) for x in fp.read_text(encoding="utf-8").splitlines() if x.strip()]
    fe = d / f"{stem}.events.jsonl"
    if fe.exists():
        events = [json.loads(x) for x in fe.read_text(encoding="utf-8").splitlines() if x.strip()]
    return calls, events


def num_from_stem(stem: str) -> str:
    m = re.match(r"^(\d+)-", stem)
    return m.group(1) if m else ""


def pct_of(events: list[dict]) -> float:
    vs = [e for e in events if e.get("kind") == "verify" and e.get("total")]
    if not vs:
        return -1.0
    hit = sum(e.get("hit", 0) for e in vs)
    total = sum(e.get("total", 0) for e in vs)
    return round(hit * 100 / total, 1) if total else -1.0


def net_of(events: list[dict]) -> int:
    """净提升 = 命中数 - 配置前命中数。

    eNSP 实验包自带参考答案（`flash.efz` 里的 `vrpcfg.cfg`），设备开机即"已配好"。
    只按 pct 筛会把这类「命中率 100% 但净提升 0」的实验当成优质正样本，
    训练出来的模型只是在复述设备里本来就有的配置（见 data/lab_reports/issues.md P1）。
    """
    vs = [e for e in events if e.get("kind") == "verify" and e.get("total")]
    return sum(int(e.get("net", 0) or 0) for e in vs)


def commands_of(calls: list[dict], host_hint: str = "") -> list[dict]:
    """抽出模型实际下发的命令（带参数与回显摘要），按发生顺序。"""
    out = []
    for row in calls:
        if row.get("kind") != "tool_step":
            continue
        tool = row.get("tool", "")
        if tool not in CONFIG_TOOLS:
            continue
        args = row.get("args") or {}
        cmd = (args.get("command") or "").strip()
        if not cmd:
            continue
        out.append({
            "tool": tool,
            "host": args.get("host", host_hint),
            "port": args.get("port", ""),
            "command": cmd,
            "confirm": bool(args.get("confirm")),
            "output_head": (row.get("output") or "")[:600],
        })
    return out


def build(day: str, min_pct: float, min_net: int = 1) -> tuple[list[dict], list[dict]]:
    """min_net：净提升下限（默认 1，即强制排除「设备开机自带答案」的实验）。

    用 1 而不是 0：净提升 0 意味着模型下发的命令一条都没改变设备状态，
    这种样本拿去微调只会教会模型"复述设备里已有的配置"。
    """
    d = LOG_ROOT / day
    if not d.exists():
        raise SystemExit(f"没有 {day} 的运行日志（{d}）")

    good, low = [], []
    for fp in sorted(d.glob("*.jsonl")):
        if fp.name.endswith(".events.jsonl"):
            continue
        stem = fp.name[: -len(".jsonl")]
        calls, events = load_session(day, stem)
        cmds = commands_of(calls)
        pct = pct_of(events)
        net = net_of(events)
        if not cmds:
            continue
        num = num_from_stem(stem)
        try:
            doc = parse_doc(num) if num else None
        except SystemExit:
            doc = None
        # instruction 用与训练时一致的任务书（不含参考答案）
        instruction = (doc["requirement"] if doc else "").strip()
        sample = {
            "id": f"{day}/{stem}",
            "num": num,
            "instruction": instruction,
            "devices": [{"name": x["name"], "model": x["model"], "port": x["port"]}
                        for x in (doc["devices"] if doc else [])],
            "commands": cmds,
            "pct": pct,
            "net": net,
            "preset": net <= 0,  # 设备开机就自带答案 → 命中率是假阳性
            "answer": (calls[-1].get("answer", "") if calls else "")[:2000],
        }
        (good if (pct >= min_pct and net >= min_net) else low).append(sample)
    return good, low


def to_sft(samples: list[dict]) -> list[dict]:
    """转成一条条 SFT 记录：instruction / input / output。

    output 用「命令序列」而不是自然语言总结：命令是可验证的，
    而且训练目标正是「看到实验要求能直接产出可下发命令」。
    """
    rows = []
    for s in samples:
        dev_note = "；".join(
            f"{d['name']}({d['model']}, Telnet 端口 {d['port']})" for d in s["devices"])
        body = []
        for c in s["commands"]:
            head = f"# {c['host']}:{c['port']}" if c["host"] else "# 设备"
            flag = " [confirm]" if c["confirm"] else ""
            body.append(f"{head}{flag}\n{c['command']}")
        rows.append({
            "instruction": s["instruction"] or "按拓扑与要求完成设备配置",
            "input": f"设备：{dev_note}" if dev_note else "",
            "output": "\n".join(body),
            "meta": {"id": s["id"], "pct": s["pct"], "net": s.get("net", 0),
                     "preset": bool(s.get("preset"))},
        })
    return rows


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="从运行日志导出 SFT 数据集")
    ap.add_argument("--day", default=date.today().isoformat())
    ap.add_argument("--min-pct", type=float, default=60.0)
    ap.add_argument("--min-net", type=int, default=1,
                    help="净提升下限；默认 1=排除「设备开机自带答案」的假阳性实验，"
                         "设 0 可放行（仅当确定设备已清场）")
    ap.add_argument("--out", default="")
    args = ap.parse_args(argv[1:])

    good, low = build(args.day, args.min_pct, args.min_net)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_fp = Path(args.out) if args.out else OUT_DIR / f"sft_{args.day.replace('-', '')}.jsonl"
    low_fp = out_fp.with_name(out_fp.stem + "_low.jsonl")

    rows = to_sft(good)
    with out_fp.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    with low_fp.open("w", encoding="utf-8") as f:
        for s in low:
            f.write(json.dumps(s, ensure_ascii=False) + "\n")

    print(f"日期 {args.day}：合格实验 {len(good)} 个 -> {len(rows)} 条 SFT 样本")
    print(f"  正样本：{out_fp}")
    print(f"  待改进（命中率 < {args.min_pct}%）：{len(low)} 个 -> {low_fp}")
    min_pct = args.min_pct
    preset = [s for s in low if s.get("preset") and s["pct"] >= min_pct]
    if preset:
        print(f"  剔除 {len(preset)} 个「命中率达标但净提升 0」的假阳性实验"
              f"（设备开机自带答案，见 issues.md P1）：")
        for s in sorted(preset, key=lambda x: -x["pct"])[:10]:
            print(f"    {s['id']}  命中率 {s['pct']}%  净提升 {s['net']}")
    for s in sorted(good, key=lambda x: -x["net"])[:10]:
        print(f"    {s['id']}  命中率 {s['pct']}%  净提升 {s['net']:+d}  "
              f"命令 {len(s['commands'])} 条")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
