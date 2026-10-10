"""从实验包里提取每台设备的参考答案配置 -> data/lab_answers/<实验名>/。

背景：
    实验包 data/ensp_labs/src/<实验名>/paper/<设备UUID>/ 下，
    路由器存 vrpcfg.zip（内含 vrpcfg.cfg，即保存过的完整配置 = 参考答案），
    交换机存 flash.efz（eNSP 私有二进制 flash 归档，魔数 'eNSP'，暂无法解包，
    只做原样备份）；*.orig 是初始（未配置）版本。
    设备名/UUID 对应关系从 paper.topo 解析（tools/topo_extract.parse_topo）。

输出布局：
    data/lab_answers/<实验名>/AR1.cfg          # 路由器参考答案（解压自 vrpcfg.zip）
    data/lab_answers/<实验名>/LSW1.flash.efz   # 交换机 flash 归档（原样，未解包）
    data/lab_answers/<实验名>/<x>.orig.*       # 初始版本（.orig）
    data/lab_answers/index.json                # 提取清单

用法：
    python tools/extract_answers.py            # 全量提取
    python tools/extract_answers.py --lab BGP
"""
from __future__ import annotations

import argparse
import json
import sys
import zipfile
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from tools.topo_extract import find_topo, parse_topo  # noqa: E402

SRC_ROOT = BASE_DIR / "data" / "ensp_labs" / "src"
OUT_ROOT = BASE_DIR / "data" / "lab_answers"


def extract_lab(lab_dir: Path) -> dict | None:
    topo_path = find_topo(lab_dir)
    if topo_path is None:
        return None
    topo = parse_topo(topo_path, lab_dir.name)
    uuid2name = {d["id"]: d["name"] for d in topo["devices"]}
    paper_dir = lab_dir / "paper"
    if not paper_dir.is_dir():
        return None

    out_dir = OUT_ROOT / lab_dir.name
    out_dir.mkdir(parents=True, exist_ok=True)
    got: list[dict] = []

    for dev_dir in sorted(p for p in paper_dir.iterdir() if p.is_dir()):
        name = uuid2name.get(dev_dir.name, dev_dir.name[:8])
        for f in sorted(dev_dir.iterdir()):
            if f.suffix == ".zip" and f.stem == "vrpcfg":
                try:
                    with zipfile.ZipFile(f) as z:
                        inner = z.namelist()[0]
                        cfg = z.read(inner).decode("utf-8", "replace")
                    dst = out_dir / f"{name}.cfg"
                    dst.write_text(cfg, encoding="utf-8")
                    got.append({"device": name, "file": dst.name, "kind": "answer"})
                except Exception as e:  # noqa: BLE001
                    got.append({"device": name, "file": f.name, "kind": "error", "err": str(e)})
            elif f.name.endswith(".orig") or ".orig." in f.name:
                dst = out_dir / f"{name}.{f.name}"
                dst.write_bytes(f.read_bytes())
                got.append({"device": name, "file": dst.name, "kind": "orig"})
            elif f.suffix == ".efz":
                dst = out_dir / f"{name}.{f.name}"     # eNSP 私有格式，原样备份
                dst.write_bytes(f.read_bytes())
                got.append({"device": name, "file": dst.name, "kind": "flash(binary)"})
            elif f.suffix == ".zip":
                dst = out_dir / f"{name}.{f.name}"
                dst.write_bytes(f.read_bytes())
                got.append({"device": name, "file": dst.name, "kind": "archive"})
    return {"experiment": lab_dir.name, "devices": got}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--lab", default="", help="只提取名字含该关键字的实验")
    args = ap.parse_args()

    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    index, errors = [], 0
    for lab_dir in sorted(p for p in SRC_ROOT.iterdir() if p.is_dir()):
        if args.lab and args.lab.lower() not in lab_dir.name.lower():
            continue
        try:
            r = extract_lab(lab_dir)
        except Exception as e:  # noqa: BLE001
            print(f"  !! {lab_dir.name}: {e}")
            errors += 1
            continue
        if not r or not r["devices"]:
            continue
        answers = sum(1 for d in r["devices"] if d["kind"] == "answer")
        index.append(r)
        print(f"  {r['experiment']}: 答案 {answers} 台 / 文件 {len(r['devices'])} 个")

    (OUT_ROOT / "index.json").write_text(
        json.dumps({"total_labs": len(index), "labs": index}, ensure_ascii=False, indent=1),
        encoding="utf-8")
    print(f"完成 {len(index)} 个实验（失败 {errors}）-> {OUT_ROOT.relative_to(BASE_DIR)}")


if __name__ == "__main__":
    main()
