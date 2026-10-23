"""把 rules_index.json 渲染成人读总表（Markdown），便于评审与交付。

不重复规则正文，只做「一眼看清覆盖面与可判定比例」的横切视图：
    · 按类别 × severity 的分布
    · 每条规则一行（id / 控制点 / severity / 判定方式 / 结论预期）
    · 明确列出 manual_confirm 条目及所需证据的关键词，避免交付时被误读成"没做"
"""
from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import yaml

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

RULE_DIR = Path(__file__).resolve().parent.parent / "knowledge" / "compliance" / "dengbao_rules"
OUT = RULE_DIR / "RULES_OVERVIEW.md"

SEV_CN = {"high": "高", "medium": "中", "low": "低"}
TYPE_CN = {
    "config_contains": "配置包含",
    "config_absent": "配置缺失",
    "config_regex": "配置正则",
    "config_value_compare": "配置值比较",
    "manual_confirm": "人工确认",
}


def main() -> int:
    idx = json.loads((RULE_DIR / "rules_index.json").read_text(encoding="utf-8"))
    rules = {}
    for f in RULE_DIR.glob("*.yaml"):
        r = yaml.safe_load(f.read_text(encoding="utf-8"))
        rules[r["id"]] = r

    lines: list[str] = []
    add = lines.append

    add("# 等保2.0 配置检查规则总表")
    add("")
    add("> 本文件由 `tools/build_dengbao_rules.py` 生成，**不要手工编辑**。")
    add("> 单条规则正文见同目录 `<规则ID>.yaml`；机器可读索引见 `rules_index.json`。")
    add("")
    add("## 覆盖范围")
    add("")
    add("| 类别 | 规则数 | 高 | 中 | 低 | 可自动判定 | 需人工确认 |")
    add("|---|---|---|---|---|---|---|")
    cats: dict[str, list[dict]] = {}
    for r in idx["rules"]:
        cats.setdefault(r["category"], []).append(r)
    for cat, rs in cats.items():
        hi = sum(1 for x in rs if x["severity"] == "high")
        me = sum(1 for x in rs if x["severity"] == "medium")
        lo = sum(1 for x in rs if x["severity"] == "low")
        auto = sum(1 for x in rs if x["check_type"] != "manual_confirm")
        man = len(rs) - auto
        add(f"| {cat} | {len(rs)} | {hi} | {me} | {lo} | {auto} | {man} |")
    add(f"| **合计** | **{idx['total']}** | "
        f"**{idx['by_severity'].get('high', 0)}** | "
        f"**{idx['by_severity'].get('medium', 0)}** | "
        f"**{idx['by_severity'].get('low', 0)}** | "
        f"**{sum(1 for r in idx['rules'] if r['check_type'] != 'manual_confirm')}** | "
        f"**{sum(1 for r in idx['rules'] if r['check_type'] == 'manual_confirm')}** |")
    add("")
    add(f"severity 推导规则：{idx['severity_rule']}")
    add("")
    add("## 规则清单")
    add("")

    for cat, rs in cats.items():
        add(f"### {cat}")
        add("")
        add("| 规则ID | 控制点 | severity | 判定方式 | 检查目标 |")
        add("|---|---|---|---|---|")
        for x in sorted(rs, key=lambda d: d["id"]):
            r = rules[x["id"]]
            add(f"| `{x['id']}` | {r['control_point']} | {SEV_CN[x['severity']]} | "
                f"{TYPE_CN.get(x['check_type'], x['check_type'])} | {r['check']['target']} |")
        add("")

    # ---- 人工确认条目单列（交付时最容易被质疑的部分）
    add("## 需人工取证的条目（manual_confirm）")
    add("")
    add("这些条目**不是没做**，而是资料本身没有给出可用配置文本判定的依据。"
        "每条都写明了缺什么证据，取证后即可给出结论。")
    add("")
    add("| 规则ID | severity | 需要什么证据 |")
    add("|---|---|---|")
    for x in sorted(idx["rules"], key=lambda d: d["id"]):
        if x["check_type"] != "manual_confirm":
            continue
        r = rules[x["id"]]
        hint = r["evidence_hint"].replace("\n", " ").replace("|", "\\|")
        if len(hint) > 150:
            hint = hint[:150] + "…"
        add(f"| `{x['id']}` | {SEV_CN[x['severity']]} | {hint} |")
    add("")

    # ---- 不适用的条目
    na = [x for x in idx["rules"] if "不适用" in rules[x["id"]]["evidence_hint"]
          or "not_applicable" in rules[x["id"]]["evidence_hint"]]
    if na:
        add("## 资料原文判定为「不适用」的条目")
        add("")
        add("以下条目在《测评操作》或《差距评估》里**原文写明不适用**"
            "（多为面向主机/数据库/应用层的条款），本规则集保留其编号与出处，"
            "但明确标注结论为 not_applicable，避免被误当成漏项：")
        add("")
        for x in sorted(na, key=lambda d: d["id"]):
            r = rules[x["id"]]
            add(f"- `{x['id']}` {r['control_point']}：{r['requirement'][:60]}…")
        add("")

    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"写出 {OUT}（{len(lines)} 行，{idx['total']} 条规则，"
          f"{len(na)} 条资料判不适用）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
