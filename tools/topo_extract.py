"""把 eNSP 实验包的 .topo 解析为结构化拓扑数据集。

数据源：data/ensp_labs/src/<实验名>/ 下的 *.topo（优先取 paper/paper.topo）。
输出：  knowledge/topology/<实验名>.json（每个实验一份）
        knowledge/topology/index.json（全部实验的设备/链路统计索引）

.topo 文件格式（2026-10 对 58 个实验包实测）：
    - GBK 编码
    - 一个文件里拼接了**两份** XML：<topo>…</topo> + <paper>…</paper>
      （直接 ET.parse 会报 junk after document element，必须先按 </topo> 切开）
    - <topo> 下的有效节点：
        devices/dev   @id @name @model @com_port(console Telnet 端口)
                      @settings(仅 PC/Server 类设备: -simpc_ip 等 仿真参数)
        lines/line    @srcDeviceID @destDeviceID
                      + 若干 interfacePair(@lineName 线缆类型, @srcIndex/@tarIndex 接口号)
        txttips/*     @content = 画布文字标注（IP/环回口/VLAN 等题面信息）
        shapes/*      纯装饰框（忽略）
    - <paper> 下是试卷元数据（PaperID/LimitedTimes 等，忽略）

接口名映射约定（2026-10-08 修正并逐台核对真机 `display ip interface brief`
与 data/lab_answers 参考答案；与 tools/ensp_lab_index.py 是**两份独立实现**，
由 tools/kb_consistency.py 互校漂移）：
    dev/interface 子节点给出槽位（interfacename + count：AR2220 是「GE×1 + GE×2」
    共 3 口、S5700 是「GE×24」），按 count 展开为端口序列后：
        AR/USG 路由器：序号 i -> GigabitEthernet0/0/i        （0 基）
        交换机 S 系列：序号 i -> GigabitEthernet0/0/(i+1)    （1 基）
        HUB          ：Ethernet0/0/{i}                       （0 基）
    非 GE 类的前缀为 Ethernet0/0/。

用法：
    python tools/topo_extract.py                 # 解析全部实验包
    python tools/topo_extract.py --lab BGP       # 只解析名字含 BGP 的实验
    python tools/topo_extract.py --one "<topo>"  # 解析单个文件并打印
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

SRC_ROOT = BASE_DIR / "data" / "ensp_labs" / "src"
OUT_DIR = BASE_DIR / "knowledge" / "topology"

# com_port 只有路由器/交换机等真设备才有；PC/Hub 为 0 或空
_REAL_MODELS = re.compile(r"^(AR|S\d{4}|USG|Router|Switch)", re.I)


# ---------------------------------------------------------------- 解析
def read_topo_xml(path: Path) -> ET.Element:
    """读 .topo 并返回 <topo> 根节点（自动处理 GBK 与双 XML 拼接）。"""
    text = path.read_bytes().decode("gbk", "replace")
    head = text.split("</topo>", 1)[0] + "</topo>"
    return ET.fromstring(head)


def _parse_pc_settings(settings: str) -> dict:
    """dev@settings 是 '-simpc_ip x.x.x.x -simpc_mask ...' 形式的参数串。"""
    out: dict[str, str] = {}
    for m in re.finditer(r"-(\w+)\s+([^\s-]+)", settings or ""):
        key, val = m.group(1), m.group(2)
        if key.startswith("simpc_"):
            out[key[len("simpc_"):]] = val
    return out


def _is_router(model: str) -> bool:
    m = str(model).upper()
    return m.startswith("AR") or m.startswith("USG") or "ROUTER" in m


def _prefix(kind: str) -> str:
    k = str(kind).upper()
    if k.startswith("GE") or "GIGABIT" in k:
        return "GigabitEthernet0/0/"
    return "Ethernet0/0/"


def _iface_sequence(dev: ET.Element) -> list[str]:
    """按槽位定义展开端口序列（interfacename + count）。"""
    seq: list[str] = []
    for iface in dev.iter("interface"):
        kind = (iface.get("interfacename") or iface.get("sztype") or "Ethernet").strip()
        try:
            n = int(iface.get("count") or 0)
        except ValueError:
            n = 0
        seq.extend([kind] * n)
    return seq


def _if_name(model: str, index: int, seq: list[str] | None = None) -> str | None:
    """把 topo 的 0 基端口序号映射为接口名（与 ensp_lab_index._iface_name 同规则）。"""
    m = str(model).upper()
    seq = seq or []
    if not seq:
        return None
    if len(seq) == 1:
        return "Ethernet0/0/0"
    idx = max(0, min(index, len(seq) - 1))
    kind = seq[idx]
    if m == "HUB":
        return _prefix(kind) + str(idx)
    if _is_router(model):
        # 0 基：AR2220 首口是 GigabitEthernet0/0/0
        num = sum(1 for k in range(idx + 1) if seq[k] == kind) - 1
        return _prefix(kind) + str(num)
    # 交换机：序号 0 对应第 1 口
    num = sum(1 for k in range(idx + 1) if seq[k] == kind)
    return _prefix(kind) + str(num)


def parse_topo(path: Path, experiment: str = "") -> dict:
    root = read_topo_xml(path)
    devices: dict[str, dict] = {}
    seq_by_id: dict[str, list[str]] = {}
    for dev in root.iter("dev"):
        did = dev.get("id", "")
        model = dev.get("model", "")
        try:
            com_port = int(dev.get("com_port") or 0)
        except ValueError:
            com_port = 0
        item: dict = {
            "id": did,
            "name": dev.get("name", ""),
            "model": model,
        }
        if com_port:
            item["console_port"] = com_port
        if _REAL_MODELS.match(model) is None:
            pc = _parse_pc_settings(dev.get("settings", ""))
            if pc:
                item["pc_settings"] = pc
        devices[did] = item
        seq_by_id[did] = _iface_sequence(dev)

    links: list[dict] = []
    for line in root.iter("line"):
        src_id, dst_id = line.get("srcDeviceID", ""), line.get("destDeviceID", "")
        src, dst = devices.get(src_id), devices.get(dst_id)
        if not src or not dst:
            continue
        pairs = []
        for pair in line.iter("interfacePair"):
            s_i, t_i = int(pair.get("srcIndex", -1)), int(pair.get("tarIndex", -1))
            pairs.append({
                "cable": pair.get("lineName", ""),
                "src_index": s_i,
                "src_if": _if_name(src["model"], s_i, seq_by_id.get(src_id)),
                "dst_index": t_i,
                "dst_if": _if_name(dst["model"], t_i, seq_by_id.get(dst_id)),
            })
        links.append({"src": src["name"], "dst": dst["name"], "interfaces": pairs})


    annotations = [
        (tip.get("content") or "").strip()
        for tip in root.iter("txttip")
        if (tip.get("content") or "").strip()
    ]

    real = [d for d in devices.values() if _REAL_MODELS.match(d["model"])]
    try:
        source = str(path.resolve().relative_to(BASE_DIR))
    except ValueError:
        source = str(path)
    return {
        "experiment": experiment or path.stem,
        "source": source,
        "device_count": len(real),
        "devices": sorted(real, key=lambda d: d.get("console_port") or 0),
        "pc_count": len(devices) - len(real),
        "link_count": len(links),
        "links": links,
        "annotations": annotations,
    }


# ---------------------------------------------------------------- 导出
def find_all_topos(lab_dir: Path) -> list[Path]:
    """实验包内所有「能解析出设备」的 topo，按路径排序。

    一个实验目录可能装多个子工程（实测 `综合练习` 下有 `OSPF配置`(5 台)
    与 `综合配置`(6 台) 两个 topo）——此时只索引排序最前的一个，
    其余通过 `--all` 提示，避免把两个不同题目的设备混成一份数据。
    """
    out: list[Path] = []
    for p in sorted(lab_dir.rglob("*.topo")):
        try:
            if parse_topo(p, lab_dir.name)["device_count"]:
                out.append(p)
        except Exception:  # noqa: BLE001  坏文件不阻断整体导出
            continue
    return out


def find_topo(lab_dir: Path) -> Path | None:
    """实验包内选 topo：**排序后第一个可解析的**（与 tools/ensp_lab_index.py
    的选法完全一致，两边由此对齐；回归校验见 tools/kb_consistency.py）。

    为什么不是「取设备最多的」：`综合练习` 这种含多个子工程的目录里，
    设备多的那份只是另一个题目，不是「更完整」。选法一旦不一致，
    知识库文档与结构化数据集就会描述不同的拓扑——历史上真踩过
    `is-is路由基本配置` 外层残缺副本被选中的坑（外层 4 台 vs 嵌套 8 台）。
    """
    topos = find_all_topos(lab_dir)
    if topos:
        return topos[0]
    cands = sorted(lab_dir.rglob("*.topo"))
    return cands[0] if cands else None


def extract_all(only: str = "") -> tuple[list[Path], list[str]]:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    made, errors = [], []
    index: list[dict] = []
    for lab_dir in sorted(p for p in SRC_ROOT.iterdir() if p.is_dir()):
        if only and only.lower() not in lab_dir.name.lower():
            continue
        topo_path = find_topo(lab_dir)
        if topo_path is None:
            errors.append(f"{lab_dir.name}: 没有找到 .topo")
            continue
        try:
            data = parse_topo(topo_path, lab_dir.name)
        except Exception as e:  # noqa: BLE001
            errors.append(f"{lab_dir.name}: 解析失败 {e}")
            continue
        out = OUT_DIR / f"{lab_dir.name}.json"
        out.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        made.append(out)
        index.append({
            "experiment": lab_dir.name,
            "devices": data["device_count"],
            "pcs": data["pc_count"],
            "links": data["link_count"],
            "has_answer_dir": (BASE_DIR / "data" / "lab_answers" / lab_dir.name).exists(),
        })
    (OUT_DIR / "index.json").write_text(
        json.dumps({"total": len(index), "labs": index}, ensure_ascii=False, indent=1),
        encoding="utf-8")
    return made, errors


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--lab", default="", help="只解析名字含该关键字的实验")
    ap.add_argument("--one", default="", help="解析单个 .topo 文件并打印")
    args = ap.parse_args()

    if args.one:
        data = parse_topo(Path(args.one))
        print(json.dumps(data, ensure_ascii=False, indent=1))
        return
    made, errors = extract_all(args.lab)
    print(f"导出 {len(made)} 份 -> {OUT_DIR.relative_to(BASE_DIR)}")
    for e in errors:
        print("  !!", e)


if __name__ == "__main__":
    main()
