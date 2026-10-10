"""NetworkClaw 的 LoRA/QLoRA 微调入口（unsloth + trl）。

背景：主程序跑的是 llama-server + Qwen3.5 GGUF（models/Qwen3.5-9B-Q4_K_M.gguf）。
微调的目标是让模型学会「读任务书 -> 输出可下发的设备命令序列」，
导出的 LoRA adapter 合并后重新量化为 GGUF，放回 models/ 即可被 llama_start 加载。

数据：由 tools/build_sft.py 从批量实验日志导出（data/finetune/sft_*.jsonl），
再经 training/prepare_data.py 转成 chat 格式（messages 三角色）。

环境：需要 GPU（显存 >= 12GB 跑 9B QLoRA；更小显存先跑 4B）。
依赖不在 requirements.txt 里（体量大、与本体的 CPU 推理隔离）：
    pip install -r training/requirements.txt

用法（最小）：
    python training/train_sft.py --data data/finetune/chat_20261001 \
        --base Qwen/Qwen3.5-9B --epochs 3 --out artifacts/qwen35-9b-netcli-lora

从本地 GGUF 出发（unsloth 会转成 fp16 再挂 LoRA）：
    python training/train_sft.py --data ... --gguf models/Qwen3.5-9B-Q4_K_M.gguf ...

产出（--out 目录）：
    adapter/            LoRA adapter（safetensors）
    merged/             合并后的完整模型（--merge 时）
    merged-gguf/        重新量化的 GGUF（--gguf-out q4_k_m 时）
    train_report.json   超参 + 最终 loss（毕设要的可复现凭据）
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def load_rows(path: Path) -> list[dict]:
    rows = []
    for fp in sorted(path.glob("*.jsonl")):
        rows += [json.loads(l) for l in fp.read_text(encoding="utf-8").splitlines() if l.strip()]
    if not rows:
        raise SystemExit(f"{path} 下没有可用的 .jsonl")
    return rows


def row_to_text(row: dict, tokenizer) -> str:
    """套模型自带的 chat template；没有模板时退回 ChatML 手拼。"""
    msgs = row["messages"]
    try:
        return tokenizer.apply_chat_template(
            msgs, tokenize=False, add_generation_prompt=False)
    except Exception:  # noqa: BLE001
        parts = []
        for m in msgs:
            parts.append(f"<|im_start|>{m['role']}\n{m['content']}<|im_end|>")
        return "".join(parts)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--data", required=True, help="prepare_data.py 的输出目录（train/val.jsonl）")
    ap.add_argument("--base", default="Qwen/Qwen3.5-9B", help="HF 模型名（与 --gguf 二选一）")
    ap.add_argument("--gguf", default="", help="从本地 GGUF 出发（优先于 --base）")
    ap.add_argument("--out", default=f"artifacts/sft_{time.strftime('%Y%m%d')}")
    # LoRA
    ap.add_argument("--lora-r", type=int, default=16)
    ap.add_argument("--lora-alpha", type=int, default=32)
    ap.add_argument("--lora-dropout", type=float, default=0.05)
    # 训练
    ap.add_argument("--epochs", type=float, default=3.0)
    ap.add_argument("--lr", type=float, default=2e-4)
    ap.add_argument("--batch", type=int, default=2, help="per-device batch")
    ap.add_argument("--grad-accum", type=int, default=4)
    ap.add_argument("--max-seq", type=int, default=2048)
    ap.add_argument("--seed", type=int, default=42)
    # 产出
    ap.add_argument("--merge", action="store_true", help="训练后合并权重保存完整模型")
    ap.add_argument("--gguf-out", default="", choices=["", "q4_k_m", "q5_k_m", "q8_0"],
                    help="训练后重新量化导出 GGUF（q4_k_m 与主程序现状一致）")
    args = ap.parse_args()

    # ---- unsloth 延迟导入：让 --help 在无 GPU 机器上也能看
    from unsloth import FastLanguageModel
    from trl import SFTConfig, SFTTrainer

    data_dir = Path(args.data) if Path(args.data).is_absolute() else BASE_DIR / args.data
    out_dir = Path(args.out) if Path(args.out).is_absolute() else BASE_DIR / args.out
    out_dir.mkdir(parents=True, exist_ok=True)

    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name=args.gguf or args.base,
        max_seq_length=args.max_seq,
        load_in_4bit=True,
    )
    model = FastLanguageModel.get_peft_model(
        model,
        r=args.lora_r,
        lora_alpha=args.lora_alpha,
        lora_dropout=args.lora_dropout,
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj",
                        "gate_proj", "up_proj", "down_proj"],
        bias="none",
        use_gradient_checkpointing="unsloth",
        seed=args.seed,
    )

    rows = load_rows(data_dir)
    from datasets import Dataset  # noqa: PLC0415
    ds = Dataset.from_list([
        {"text": row_to_text(r, tokenizer)} for r in rows
    ])

    trainer = SFTTrainer(
        model=model,
        tokenizer=tokenizer,
        train_dataset=ds,
        dataset_text_field="text",
        args=SFTConfig(
            output_dir=str(out_dir / "checkpoints"),
            num_train_epochs=args.epochs,
            per_device_train_batch_size=args.batch,
            gradient_accumulation_steps=args.grad_accum,
            learning_rate=args.lr,
            lr_scheduler_type="cosine",
            warmup_ratio=0.03,
            logging_steps=5,
            save_strategy="epoch",
            bf16=True,
            seed=args.seed,
            report_to="none",
        ),
    )
    trainer.train()

    adapter_dir = out_dir / "adapter"
    model.save_pretrained(str(adapter_dir))
    tokenizer.save_pretrained(str(adapter_dir))

    report = {
        "base": args.gguf or args.base,
        "data": str(data_dir), "rows": len(rows),
        "lora": {"r": args.lora_r, "alpha": args.lora_alpha,
                 "dropout": args.lora_dropout},
        "epochs": args.epochs, "lr": args.lr,
        "batch": args.batch, "grad_accum": args.grad_accum,
        "max_seq": args.max_seq, "seed": args.seed,
        "final_loss": getattr(trainer.state, "log_history", [{}])[-1].get("train_loss"),
        "adapter": str(adapter_dir),
    }
    if args.merge or args.gguf_out:
        FastLanguageModel.for_inference(model)
        merged = model.merge_and_unload()
        if args.merge:
            merged_dir = out_dir / "merged"
            merged.save_pretrained(str(merged_dir))
            tokenizer.save_pretrained(str(merged_dir))
            report["merged"] = str(merged_dir)
        if args.gguf_out:
            gguf_dir = out_dir / "merged-gguf"
            model.save_pretrained_gguf(str(gguf_dir), tokenizer,
                                       quantization_method=args.gguf_out)
            report["gguf"] = str(gguf_dir)
    (out_dir / "train_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=1))
    print("完成。GGUF 产物请放回 models/ 并在 config/llm.json 里改 model 名。")


if __name__ == "__main__":
    main()
