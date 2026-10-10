"""把 SFT 数据转换成训练用的 chat 格式（并切分训练/验证集）。

输入：data/finetune/sft_*.jsonl —— tools/build_sft.py 导出的 Alpaca 风格样本：
    正样本 {"instruction", "input", "output"}   命中率达标，参与训练
    负样本 low.jsonl {"id","num","instruction","devices","commands",...}  不参与训练

输出：--out 指定的目录
    train.jsonl / val.jsonl   每行 {"messages":[{role,content},...]}
    stats.json                条数、来源、切分比例

角色约定（与 NetworkClaw 的 agent 场景一致）：
    system  设备操作安全提示（只允许模型在 confirm 流程内执行配置类命令）
    user    instruction + input（任务书 + 设备清单）
    assistant  output（可直接下发的命令序列）

用法：
    python training/prepare_data.py \
        --src data/finetune/sft_20261001.jsonl \
        --val-ratio 0.2 --out data/finetune/chat_20261001
"""
from __future__ import annotations

import argparse
import json
import random
from datetime import date
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

SYSTEM_PROMPT = (
    "你是网络设备配置助手 NetworkClaw。根据任务书给出可直接下发的华为 VRP 命令序列。"
    "命令用分号或换行分隔；只读命令（display/show/ping）可直接执行，"
    "配置类命令必须先向用户说明影响并获得确认（confirm=true），"
    "破坏性命令（undo/shutdown/reset 等）一律不得执行。"
)


def to_messages(rec: dict) -> dict:
    """Alpaca 三字段 -> messages。input 为空时不拼进 user。"""
    user = rec["instruction"]
    if rec.get("input", "").strip():
        user += "\n\n" + rec["input"].strip()
    return {"messages": [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user},
        {"role": "assistant", "content": rec["output"]},
    ]}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--src", action="append", required=True,
                    help="SFT jsonl（可多次出现），例如 data/finetune/sft_20261001.jsonl")
    ap.add_argument("--val-ratio", type=float, default=0.2)
    ap.add_argument("--out", default=f"data/finetune/chat_{date.today().strftime('%Y%m%d')}")
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    recs: list[dict] = []
    for src in args.src:
        p = BASE_DIR / src if not Path(src).is_absolute() else Path(src)
        lines = p.read_text(encoding="utf-8").splitlines()
        recs += [to_messages(json.loads(l)) for l in lines if l.strip()]
        print(f"  {p.name}: {len(lines)} 条")

    random.Random(args.seed).shuffle(recs)
    n_val = max(1, round(len(recs) * args.val_ratio)) if len(recs) > 1 else 0
    val, train = recs[:n_val], recs[n_val:]

    out = Path(args.out) if Path(args.out).is_absolute() else BASE_DIR / args.out
    out.mkdir(parents=True, exist_ok=True)
    (out / "train.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in train) + "\n", encoding="utf-8")
    (out / "val.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in val) + "\n", encoding="utf-8")
    (out / "stats.json").write_text(json.dumps({
        "sources": args.src, "total": len(recs),
        "train": len(train), "val": len(val), "seed": args.seed,
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"训练 {len(train)} / 验证 {len(val)} -> {out}")


if __name__ == "__main__":
    main()
