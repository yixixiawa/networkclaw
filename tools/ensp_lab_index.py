"""把 eNSP 实验包（data/ensp_labs/src）解析成 RAG 知识库文档。

产物：knowledge/experiments/<NN>-<实验名>.md + 00-总览.md

数据来源（每个实验目录内）：
- instruction/instruction.txt  题目要求（GBK）
- paper/paper.topo             拓扑 XML（GBK）：设备/型号/console口/PC的IP/连线/图上文字标注
- <名>.model                   参考答案（UTF-16 流）：该实验各设备的参考配置命令序列

`.model` 说明：不是标准配置文本，而是「命令条目流」，条目以 \\x04+BOM 分隔，
每条目内含 1~2 段 ASCII 文本与一个比较标记（Equal/Different，表示相较默认配置是否变化）。
本脚本按设备分组提取其中的命令行，去噪后作为「参考配置」写进文档。

用法：
    python tools/ensp_lab_index.py                 # 生成全部实验文档
    python tools/ensp_lab_index.py --list          # 只列出识别到的实验
"""
from __future__ import annotations

import argparse
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
SRC_DIR = BASE_DIR / "data" / "ensp_labs" / "src"
OUT_DIR = BASE_DIR / "knowledge" / "experiments"

# ------------------------------------------------------------------ 工具

_UUID = re.compile(r"^[0-9A-F]{8}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{12}$", re.I)
_CMD_OK = re.compile(r"^[A-Za-z][A-Za-z0-9 _\-\./:@]{2,}$")
_NOISE = {"Equal", "Different", "None", "True", "False"}


def _read_text(p: Path) -> str:
    """按 GBK → UTF-8 → latin-1 顺序解码（eNSP 文本文件多为 GBK）。"""
    b = p.read_bytes()
    for enc in ("gbk", "utf-8-sig", "utf-8", "latin-1"):
        try:
            return b.decode(enc)
        except UnicodeDecodeError:
            continue
    return b.decode("gbk", "replace")


def _xml_root(p: Path) -> ET.Element | None:
    """解析 .topo。注意：paper.topo 在 </topo> 之后还挂着试卷元数据块
    （<paper>/<PaperID>/<LimitedTimes> 等），直接 parse 会报
    "junk after document element"，故先截取到 </topo> 为止。"""
    txt = _read_text(p)
    end = txt.find("</topo>")
    if end != -1:
        txt = txt[: end + len("</topo>")]
    txt = re.sub(r"<\?xml[^>]*\?>", "", txt, count=1)
    try:
        return ET.fromstring(txt.encode("utf-8"))
    except ET.ParseError:
        return None


# ------------------------------------------------------------------ 接口命名

def _iface_sequence(dev: ET.Element) -> list[tuple[str, str]]:
    """按槽位定义展开该设备的端口序列 [(内部类型, 接口名前缀), ...]。

    经全量核对（581 个设备实例、69 个 topo）：topo 里的 srcIndex/tarIndex 一律
    **0 基**（S5700 的 max_idx=23 对应 24 口；AR2220 的 max_idx=2/4 对应 3/5 口），
    接口名前缀取 `interfacename` 属性（'GE' → GigabitEthernet，'Ethernet' → Ethernet），
    不能用 `sztype`（S5700 的 sztype 也是 Ethernet，但实际是 GE 口）。
    """
    seq: list[tuple[str, str]] = []
    for iface in dev.iter("interface"):
        name = (iface.get("interfacename") or iface.get("sztype") or "Ethernet").strip()
        n = int(iface.get("count") or 0)
        seq.extend([(name, name)] * n)
    return seq


def _prefix(iface_kind: str) -> str:
    k = iface_kind.upper()
    if k.startswith("GE") or "GIGABIT" in k:
        return "GigabitEthernet0/0/"
    return "Ethernet0/0/"


def _is_router(model: str) -> bool:
    """路由器/防火墙的接口编号是 0 基（AR2220 首口 = GigabitEthernet0/0/0）。"""
    m = (model or "").upper()
    return m.startswith("AR") or m.startswith("USG") or "ROUTER" in m


def _iface_name(seq: list[tuple[str, str]], idx: int, model: str = "") -> str:
    """把 topo 里的 0 基端口序号映射为 eNSP 接口名。

    编号规则（2026-10-08 修正，已与真机 `display ip interface brief` 和
    lab_answers 参考答案逐台核对）：
        路由器/防火墙（AR/USG）：序号 i -> GigabitEthernet0/0/i   ← **0 基**
        交换机（S3700/S5700）  ：序号 i -> GigabitEthernet0/0/(i+1) ← 1 基
        HUB                    ：Ethernet0/0/{i}                 ← 0 基
    此前对路由器也按 1 基编号，导致实验文档里的链路接口名整体偏 1
    （BGP 实验编成 AR1 GE0/0/1 ↔ AR2，实际应为 GE0/0/0），
    而该文档正是知识库数据源 → 会教坏模型。回归校验见 tools/kb_consistency.py。
    """
    if not seq:
        return f"端口#{idx}"
    if len(seq) == 1:
        return "Ethernet0/0/0"
    idx = max(0, idx)
    if idx >= len(seq):
        idx = len(seq) - 1
    kind = seq[idx][0]
    if model.upper() == "HUB":
        # eNSP 的 HUB 端口是 0 基命名（Ethernet0/0/0 ~ 0/0/15）
        return _prefix(kind) + str(idx)
    if _is_router(model):
        # 路由器：按同类型端口重新计数，但**从 0 起**
        num = sum(1 for k in range(idx + 1) if seq[k][0] == kind) - 1
        return _prefix(kind) + str(num)
    # 交换机：序号 0 对应第 1 口；若前面还有别的类型端口，重新按类型计数
    num = 1
    seen = 0
    for k in range(idx + 1):
        if seq[k][0] == kind:
            seen += 1
        if k == idx:
            num = seen
    return _prefix(kind) + str(num)


# ------------------------------------------------------------------ 拓扑解析

def parse_topo(path: Path) -> dict:
    root = _xml_root(path)
    if root is None:
        return {"devices": [], "links": [], "tips": [], "error": "XML 解析失败"}

    devices = []
    dev_by_id: dict[str, dict] = {}
    for d in root.iter("dev"):
        name = d.get("name") or "?"
        model = d.get("model") or "?"
        settings = d.get("settings") or ""
        info = {
            "id": d.get("id") or "",
            "name": name,
            "model": model,
            "com_port": d.get("com_port") or "0",
            "cx": float(d.get("cx") or 0),
            "cy": float(d.get("cy") or 0),
            "ip": "",
            "mask": "",
            "gateway": "",
            "seq": _iface_sequence(d),
        }
        m = re.search(r"-simpc_ip\s+(\S+)", settings)
        if m and m.group(1) != "0.0.0.0":
            info["ip"] = m.group(1)
        m = re.search(r"-simpc_mask\s+(\S+)", settings)
        if m:
            info["mask"] = m.group(1)
        m = re.search(r"-simpc_gateway\s+(\S+)", settings)
        if m and m.group(1) != "0.0.0.0":
            info["gateway"] = m.group(1)
        devices.append(info)
        dev_by_id[info["id"]] = info

    links = []
    seen_link: set[tuple] = set()
    for line in root.iter("line"):
        s_id, d_id = line.get("srcDeviceID"), line.get("destDeviceID")
        sd, dd = dev_by_id.get(s_id or ""), dev_by_id.get(d_id or "")
        if not sd or not dd:
            continue
        # 一条 line 可能挂多个 interfacePair：这是**链路聚合（Eth-Trunk）**——
        # 成员口必须逐条列出，否则 STP/Eth-Trunk 类实验的拓扑在知识库里是残缺的
        # （2026-10-08 修正：此前只取 find() 的第一个 pair，MS TP 试卷少列 2 条成员链路）
        pairs = list(line.iter("interfacePair")) or [None]
        for pair in pairs:
            s_idx = int(pair.get("srcIndex") or 0) if pair is not None else 0
            t_idx = int(pair.get("tarIndex") or 0) if pair is not None else 0
            a_if = _iface_name(sd["seq"], s_idx, sd["model"])
            b_if = _iface_name(dd["seq"], t_idx, dd["model"])
            key = tuple(sorted([(sd["name"], a_if), (dd["name"], b_if)]))
            if key in seen_link:
                continue
            seen_link.add(key)
            links.append({
                "a": sd["name"], "a_if": a_if,
                "b": dd["name"], "b_if": b_if,
                "kind": (pair.get("lineName") if pair is not None else "Copper") or "Copper",
            })

    tips = []
    for t in root.iter("txttip"):
        content = (t.get("content") or "").strip()
        # 过滤掉被当成标注贴进来的整段题目（超长文本）
        if not content or len(content) > 120 or "\n" in content:
            continue
        try:
            cx = (float(t.get("left")) + float(t.get("right"))) / 2
            cy = (float(t.get("top")) + float(t.get("bottom"))) / 2
        except (TypeError, ValueError):
            cx = cy = 0.0
        tips.append({"content": content, "cx": cx, "cy": cy})

    # 标注就近归属设备
    for tip in tips:
        best, bestd = None, 1e18
        for d in devices:
            dist = (d["cx"] - tip["cx"]) ** 2 + (d["cy"] - tip["cy"]) ** 2
            if dist < bestd:
                best, bestd = d, dist
        tip["near"] = best["name"] if best and bestd < 260 ** 2 else ""

    return {"devices": devices, "links": links, "tips": tips}


# ------------------------------------------------------------------ 参考答案解析

def parse_model(path: Path, known_names: set[str] | None = None) -> dict[str, list[str]]:
    """从 .model 提取 {设备名: [命令, ...]}（按出现顺序、去重）。

    .model 是「命令条目流」：条目以 \\x04+BOM 分隔，条目内可能含
    「改动前」「改动后」两段文本与 Equal/Different 比较标记。
    设备分段格外必须用拓扑里的**已知设备名**匹配——只按「短标识符」猜会把
    `aaa`、`undo` 之类的配置行误判成设备名。
    """
    text = path.read_bytes().decode("utf-16", "replace")
    parts = text.split("\x04\ufeff")
    known = {n.upper() for n in (known_names or set())}

    result: dict[str, list[str]] = {}
    cur: str | None = None

    for seg in parts:
        runs = [r.strip() for r in re.findall(r"[ -~]{2,}", seg)]
        runs = [r for r in runs if _CMD_OK.match(r) and r not in _NOISE and not _UUID.match(r)]
        if not runs:
            continue
        if known and runs[0].upper() in known:
            cur = runs[0]
            result.setdefault(cur, [])
            continue
        if cur is None:
            continue
        for r in runs:
            if r.upper() == cur.upper():
                continue
            if r not in result[cur]:
                result[cur].append(r)
    return result


# ------------------------------------------------------------------ 文档生成

def _safe(name: str) -> str:
    return re.sub(r'[\\/:*?"<>|]', "_", name).strip()[:80]


def find_lab_files(lab_dir: Path) -> dict:
    files: dict = {"instruction": None, "topos": [], "models": [], "papers": []}
    for p in sorted(lab_dir.rglob("*")):
        if not p.is_file():
            continue
        n = p.name.lower()
        if n == "instruction.txt" and files["instruction"] is None:
            files["instruction"] = p
        elif p.suffix.lower() == ".topo":
            files["topos"].append(p)
        elif p.suffix.lower() == ".model":
            files["models"].append(p)
        elif p.suffix.lower() == ".paper":
            files["papers"].append(p)
    return files


def build_lab_doc(idx: int, lab_dir: Path) -> tuple[str, dict]:
    files = find_lab_files(lab_dir)
    name = lab_dir.name
    stats = {"name": name, "n_dev": 0, "n_link": 0, "ref_dev": 0, "ref_cmd": 0}

    out: list[str] = []
    out.append(f"# 实验 {idx:02d}：{name}\n")
    out.append(f"- 来源目录：`{lab_dir.name}`")
    if files["topos"]:
        out.append(f"- 拓扑文件：`{files['topos'][0].name}`")
    out.append("")

    # 题目
    out.append("## 一、题目要求\n")
    if files["instruction"]:
        text = _read_text(files["instruction"]).strip()
        out.append(text if text else "（题目为空）")
    else:
        out.append("（未找到 instruction.txt）")
    out.append("")

    # 拓扑
    topo_doc = None
    for tp in files["topos"]:
        info = parse_topo(tp)
        if info["devices"]:
            topo_doc = (tp, info)
            break
    if topo_doc:
        tp, info = topo_doc
        devs, links, tips = info["devices"], info["links"], info["tips"]
        stats["n_dev"], stats["n_link"] = len(devs), len(links)

        out.append("## 二、设备清单\n")
        out.append("| 设备 | 型号 | Console(Telnet)端口 | 关键参数 |")
        out.append("|---|---|---|---|")
        for d in sorted(devs, key=lambda x: x["name"]):
            params = []
            if d["ip"]:
                params.append(f"IP {d['ip']}/{_masklen(d['mask'])}")
            if d["gateway"]:
                params.append(f"网关 {d['gateway']}")
            cp = d["com_port"] if d["com_port"] != "0" else "-"
            out.append(f"| {d['name']} | {d['model']} | {cp} | {'，'.join(params) or '-'} |")
        out.append("")

        if links:
            out.append("## 三、链路连接\n")
            for l in links:
                out.append(f"- {l['a']} `{l['a_if']}` ↔ {l['b']} `{l['b_if']}`（{l['kind']}）")
            out.append("")

        if tips:
            out.append("## 四、拓扑图上的文字标注\n")
            for t in tips:
                near = f"（贴近 {t['near']}）" if t["near"] else ""
                out.append(f"- `{t['content']}`{near}")
            out.append("")

    # 参考答案
    if files["models"]:
        known = {d["name"] for d in (topo_doc[1]["devices"] if topo_doc else [])}
        ref = parse_model(files["models"][0], known)
        if ref:
            out.append("## 五、参考答案（从 .model 自动提取，按设备分组）\n")
            out.append("> 说明：该列表由实验包的「参考答案」文件提取，仅含命令文本、不含缩进层级；")
            out.append("> 部分行是设备默认配置，需结合题目与拓扑判断哪些是本题真正要求下发的配置。\n")
            for dev, cmds in ref.items():
                if not cmds:
                    continue
                stats["ref_dev"] += 1
                stats["ref_cmd"] += len(cmds)
                out.append(f"### {dev}\n")
                out.append("```")
                out.extend(cmds)
                out.append("```")
                out.append("")

    out.append("## 六、验收要点\n")
    out.append("（待本地模型跑通后回填：需连通的 PC 对、需隔离的 PC 对、关键验证命令）")
    out.append("")
    return "\n".join(out), stats


def _masklen(mask: str) -> str:
    if not mask:
        return "?"
    try:
        parts = [int(x) for x in mask.split(".")]
    except ValueError:
        return mask
    bits = sum(bin(p).count("1") for p in parts)
    return str(bits)


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true")
    args = ap.parse_args(argv[1:])

    if not SRC_DIR.is_dir():
        print(f"未找到实验源目录：{SRC_DIR}")
        return 1

    labs = sorted([d for d in SRC_DIR.iterdir() if d.is_dir()])
    if args.list:
        for i, d in enumerate(labs, 1):
            print(f"{i:02d} {d.name}")
        return 0

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    overview = ["# eNSP 实验集总览\n", f"共 {len(labs)} 个实验，来源：虚拟机桌面 `unzip`。\n"]
    overview.append("| # | 实验 | 设备数 | 链路数 | 参考答案设备数 |")
    overview.append("|---|---|---|---|---|")

    for i, lab in enumerate(labs, 1):
        try:
            doc, stats = build_lab_doc(i, lab)
        except Exception as e:  # 单个实验失败不阻断
            print(f"[{i:02d}] {lab.name} 解析失败：{type(e).__name__}: {e}")
            continue
        fn = OUT_DIR / f"{i:02d}-{_safe(lab.name)}.md"
        fn.write_text(doc, encoding="utf-8")
        overview.append(
            f"| {i:02d} | {lab.name} | {stats['n_dev']} | {stats['n_link']} | {stats['ref_dev']} |"
        )
        print(f"[{i:02d}] {lab.name} -> {fn.name} "
              f"(设备 {stats['n_dev']} / 链路 {stats['n_link']} / 参考 {stats['ref_dev']}台 {stats['ref_cmd']}条)")

    (OUT_DIR / "00-总览.md").write_text("\n".join(overview) + "\n", encoding="utf-8")
    print(f"\n总览已写入 {OUT_DIR / '00-总览.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
