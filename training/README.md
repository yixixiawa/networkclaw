# training/ —— LoRA/QLoRA 微调

毕设核心环节「模型是微调过的」的可复现代码。训练目标：让 Qwen3.5 学会
**读实验任务书 → 输出可直接下发的华为 VRP 命令序列**。

> 历史说明：早期版本的入口叫 `modal_sft.py`（跑在云 GPU 上）；现在统一为本目录的
> `train_sft.py`，可在本机 GPU 或任意云 GPU 上复现，参数完全一致。

## 全流程（三步）

```
1. 数据导出      python tools/build_sft.py --day 2026-10-01 --min-pct 60
                 # 从批量实验运行日志导出 SFT 样本（详见 docs/sft_dataset.md）

2. 格式转换      python training/prepare_data.py \
                     --src data/finetune/sft_20261001.jsonl \
                     --val-ratio 0.2 --out data/finetune/chat_20261001

3. 训练          python training/train_sft.py \
                     --data data/finetune/chat_20261001 \
                     --base Qwen/Qwen3.5-9B --epochs 3 \
                     --merge --gguf-out q4_k_m --out artifacts/qwen35-9b-netcli
```

环境：独立装 `pip install -r training/requirements.txt`（需要 GPU；不要装进主项目 venv，
本体是 CPU 推理 + llama-server，两者依赖互不污染）。复现参数快照见
`config_qwen35_9b_lora.yaml`。

## 产出

| 路径 | 内容 |
|---|---|
| `artifacts/<run>/adapter/` | LoRA adapter（safetensors） |
| `artifacts/<run>/merged/` | 合并后的完整模型（`--merge`） |
| `artifacts/<run>/merged-gguf/` | 重新量化的 GGUF（`--gguf-out q4_k_m`） |
| `artifacts/<run>/train_report.json` | 超参 + 最终 loss（论文可引用） |

GGUF 产物放回 `models/`，在 `config/llm.json` 里把 model 名指向它，
`main.py` 启动即为微调后模型。`artifacts/` 建议加入 .gitignore（大文件）。

## 数据现状（2026-10-04）

正样本 3 条 / 待改进 15 条（`data/finetune/sft_20261001*.jsonl`）。
正式训练前需要把 71 个实验全部跑完，把正样本扩到百级；
当前数据量下训练仅用于打通全流程验证。
