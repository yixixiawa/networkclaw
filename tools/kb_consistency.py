"""知识库一致性校验：knowledge/experiments/*.md 与 knowledge/topology/*.json 互校。

背景（为什么需要）：
    这两份数据是**从同一批 .topo 独立推导**出来的，都在知识库/数据集里供模型使用：
        knowledge/experiments/NN-*.md   由 tools/ensp_lab_index.py 生成（进向量库）
        knowledge/topology/<实验>.json  由 tools/topo_extract.py 生成（结构化数据集）
    一旦两者漂移（历史上真发生过：路由器接口编号按 1 基算，把 AR1 的
    GE0/0/0 写成 GE0/0/1），模型会从知识库里学到错的接口名，而且**很难发现**。
    本工具把「难发现」变成「一条命令发现」，并可作为回归测试。

校验项：
    1. 设备集合与 console 端口
    2. 链路条数与每条的「设备A 接口 ↔ 设备B 接口」（无序比较）
    3. 画布文字标注条数

用法：
    python tools/kb_consistency.py            # 全量校验，人读输出
    python tools/kb_consistency.py --json     # 机器可读（CI/测试用）
    python tools/kb_consistency.py --lab BGP  # 只查名字含 BGP 的实验

退出码：0 = 全部一致；1 = 存在不一致；2 = 数据缺失（先跑生成脚本）。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from tools.topo_extract import _REAL_MODELS as REAL_MODELS  # noqa: PLC2701

EXP_DIR = BASE_DIR / "knowledge" / "experiments"
TOPO_DIR = BASE_DIR / "knowledge" / "topology"

# | AR1 | AR2220 | 2000 | - |        （第二列是型号，第三列是 console 端口或 -）
_DEV_ROW = re.compile(r"^\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*([^|]*?)\s*\|")
_SEPARATOR = re.compile(r"^[-:\s]+$")
# - AR1 `GigabitEthernet0/0/0` ↔ AR2 `GigabitEthernet0/0/0`（Copper）
#   设备名可能带空格（如 "Web server"），所以不能用 \w+ 限定
_LINK = re.compile(r"^-\s*(.+?)\s*`([^`]+)`\s*↔\s*(.+?)\s*`([^`]+)`")
# - `lo0：2.2.2.2/32`（贴近 AR2）
_ANNOT = re.compile(r"^-\s*`([^`]+)`")


def parse_md(path: Path) -> dict:
    """从实验文档抽取设备表 / 链路 / 标注内容。"""
    devices: dict[str, dict] = {}
    links: set[tuple[str, str, str, str]] = set()
    annots: set[str] = set()
    section = ""
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if line.startswith("## "):
            section = line[3:].strip()
            continue
        if section.startswith("二、设备清单"):
            m = _DEV_ROW.match(line)
            if m and not _SEPARATOR.match(m.group(1)) and m.group(1) != "设备":
                port = m.group(3).strip()
                devices[m.group(1)] = {
                    "model": m.group(2).strip(),
                    "console_port": int(port) if port.isdigit() else 0,
                }
        elif section.startswith("三、链路连接"):
            m = _LINK.match(line)
            if m:
                a, a_if, b, b_if = (x.strip() for x in m.groups())
                links.add(_norm_link(a, a_if, b, b_if))
        elif section.startswith("四、"):
            m = _ANNOT.match(line)
            if m:
                annots.add(m.group(1).strip())
    return {"devices": devices, "links": links, "annots": annots}


def _norm_link(a: str, a_if: str, b: str, b_if: str) -> tuple[str, str, str, str]:
    """链路两端无序化，便于与 JSON 双向比对。"""
    one, two = (a, a_if), (b, b_if)
    return (*one, *two) if one <= two else (*two, *one)


def links_from_json(data: dict) -> set[tuple[str, str, str, str]]:
    out = set()
    for link in data.get("links", []):
        for pair in link.get("interfaces", []):
            s_if, d_if = pair.get("src_if"), pair.get("dst_if")
            if not s_if or not d_if:
                continue
            out.add(_norm_link(link["src"], s_if, link["dst"], d_if))
    return out


def find_md(experiment: str) -> Path | None:
    """实验文档文件名带编号前缀（03-BGP-基本配置工程.md），按后缀精确匹配。

    不用 glob 拼模式：实验名里含 `(`、`、` 等字符，且 `[]` 会被 glob 当通配符。
    """
    direct = EXP_DIR / f"{experiment}.md"
    if direct.exists():
        return direct
    for p in EXP_DIR.glob("*.md"):
        if "-" in p.stem and p.stem.split("-", 1)[1] == experiment:
            return p
    return None


def check_lab(experiment: str) -> dict | None:
    """比对单个实验；返回 None 表示数据缺失。"""
    md = find_md(experiment)
    js = TOPO_DIR / f"{experiment}.json"
    if md is None or not js.exists():
        return None
    m, data = parse_md(md), json.loads(js.read_text(encoding="utf-8"))

    # 只比较真设备（JSON 的 devices 字段就是真设备；PC/HUB 记在 pc_count / pc_settings）
    md_real = {k: v for k, v in m["devices"].items() if REAL_MODELS.match(v["model"])}
    md_pc = len(m["devices"]) - len(md_real)
    jd = {d["name"]: {"model": d.get("model", ""), "console_port": d.get("console_port", 0)}
          for d in data.get("devices", [])}
    problems: list[str] = []
    if md_pc != data.get("pc_count", 0):
        problems.append(f"PC/终端数量不一致：md={md_pc} json={data.get('pc_count')}")

    only_md = sorted(set(md_real) - set(jd))
    only_js = sorted(set(jd) - set(md_real))
    if only_md:
        problems.append(f"设备仅见于 md：{only_md}")
    if only_js:
        problems.append(f"设备仅见于 json：{only_js}")
    for name in sorted(set(md_real) & set(jd)):
        a, b = md_real[name]["console_port"], jd[name]["console_port"]
        if a != b:
            problems.append(f"{name} console 端口不一致：md={a} json={b}")
        if md_real[name]["model"].upper() != str(jd[name]["model"]).upper():
            problems.append(
                f"{name} 型号不一致：md={md_real[name]['model']} json={jd[name]['model']}")

    jl = links_from_json(data)
    if m["links"] != jl:
        missing = sorted(m["links"] - jl)
        extra = sorted(jl - m["links"])
        if missing:
            problems.append(f"链路仅见于 md：{missing[:3]}{' …' if len(missing) > 3 else ''}")
        if extra:
            problems.append(f"链路仅见于 json：{extra[:3]}{' …' if len(extra) > 3 else ''}")

    # 标注：md 会去重、可能省略重复文案，所以只要求「md ⊆ json」（内容级校验）
    j_annots = {(a or "").strip() for a in data.get("annotations", [])}
    missing_annots = sorted(m["annots"] - j_annots)
    if missing_annots:
        problems.append(f"md 标注在 json 中找不到：{missing_annots[:3]}"
                        f"{' …' if len(missing_annots) > 3 else ''}")

    return {
        "experiment": experiment,
        "md_devices": len(md_real),
        "json_devices": len(jd),
        "md_links": len(m["links"]),
        "json_links": len(jl),
        "md_annots": len(m["annots"]),
        "json_annots": len(j_annots),
        "multi_topo": _extra_topos(experiment),
        "problems": problems,
    }


def _extra_topos(experiment: str) -> list[str]:
    """该实验目录下「没被索引」的额外 topo（多子工程实验室）——信息提示，不算不一致。"""
    from tools.topo_extract import SRC_ROOT, find_all_topos

    lab = SRC_ROOT / experiment
    if not lab.is_dir():
        return []
    topos = find_all_topos(lab)
    return [p.name for p in topos[1:]]


def check_all(only: str = "") -> dict:
    if not TOPO_DIR.is_dir() or not EXP_DIR.is_dir():
        return {"error": "数据目录缺失，请先运行 tools/ensp_lab_index.py 与 tools/topo_extract.py",
                "labs": []}
    labs, skipped = [], []
    for js in sorted(TOPO_DIR.glob("*.json")):
        if js.name == "index.json":
            continue
        if only and only.lower() not in js.stem.lower():
            continue
        r = check_lab(js.stem)
        if r is None:
            skipped.append(js.stem)
        else:
            labs.append(r)
    bad = [r for r in labs if r["problems"]]
    return {"total": len(labs), "skipped": skipped, "mismatched": len(bad), "labs": labs}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--lab", default="")
    ap.add_argument("--json", action="store_true", help="输出 JSON（CI/测试用）")
    args = ap.parse_args()

    r = check_all(args.lab)
    if args.json:
        print(json.dumps(r, ensure_ascii=False, indent=1))
    else:
        if r.get("error"):
            print(r["error"])
            sys.exit(2)
        print(f"校验 {r['total']} 个实验（跳过 {len(r['skipped'])} 个缺数据）")
        for lab in r["labs"]:
            if lab["problems"]:
                print(f"  ✗ {lab['experiment']}")
                for p in lab["problems"]:
                    print(f"      - {p}")
        multi = [lab for lab in r["labs"] if lab.get("multi_topo")]
        for lab in multi:
            print(f"  ℹ {lab['experiment']}：目录内还有未索引的子拓扑 {lab['multi_topo']}")
        print(f"结论：{r['mismatched']} 个实验不一致 / 共 {r['total']} 个"
              f"（{len(multi)} 个含多个子拓扑）")
    sys.exit(1 if r.get("mismatched") else 0)


if __name__ == "__main__":
    main()
