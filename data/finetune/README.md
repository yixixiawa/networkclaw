# data/finetune/ —— 微调（SFT）数据

字段说明、构造规则与复现命令见 **docs/sft_dataset.md**（唯一权威说明）。

## 本目录文件

| 文件 | 说明 |
|---|---|
| `sft_20261001.jsonl` | 正样本 3 条（命中率 ≥60% 且净提升 ≥1），Alpaca 三字段 + meta |
| `sft_20261001_low.jsonl` | 待改进 15 条（命中率不足或"设备自带答案"假阳性），含完整命令轨迹 |
| `chat_YYYYMMDD/` | `training/prepare_data.py` 的输出（train/val.jsonl + stats.json），训练直接消费 |

## 快速复现

```bash
python tools/build_sft.py --day 2026-10-01 --min-pct 60   # 重新导出
python training/prepare_data.py --src data/finetune/sft_20261001.jsonl
```

注意：`--min-net 1`（默认）会剔除"设备开机就自带参考答案"的假阳性满分样本；
`low.jsonl` 不参与训练，用于人工复核。
