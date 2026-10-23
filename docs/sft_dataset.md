# SFT 数据集说明

回答四个问题：数据从哪来、怎么构造、字段什么含义、怎么复现。
生成代码：`tools/build_sft.py`；训练消费代码：`training/prepare_data.py`。

## 1. 数据来源（两个独立来源，可互相校验）

| 来源 | 内容 | 提取方式 |
|---|---|---|
| **运行日志**（主来源） | 批量实验中模型真实下发的命令序列 + 设备回显 + 验收命中率。落地在 `data/run_logs/<日期>/<实验>.jsonl`（`core/run_log.py` 写入） | `tools/build_sft.py` |
| **实验包参考答案**（校验/扩充来源） | 58 个实验包自带的标准答案：`data/ensp_labs/src/<实验>/paper/<UUID>/vrpcfg.zip`（路由器）与 `flash.efz`（交换机） | `tools/extract_answers.py` → `data/lab_answers/`；拓扑结构 `tools/topo_extract.py` → `knowledge/topology/` |

任务书（instruction）来自实验包 `instruction/instruction.txt`；
设备清单（input 里的 "LSW1(S5700, Telnet 端口 2000)…"）来自实验文档
`knowledge/experiments/NN-*.md` 的设备表。

## 2. 构造规则（build_sft.py）

- **正样本**：单次实验的「任务书 → 模型实际下发的配置命令序列」。
  命令序列而非自然语言总结，因为它是可执行、可验证的。
- **过滤参数**（与导出一一对应）：
  - `--min-pct`（默认 60）：验收命中率下限；
  - `--min-net`（默认 1）：**净提升下限**。命中率 100% 但 net=0 的实验说明
    设备开机就自带参考答案（假阳性），其"满分"与模型能力无关，强制剔除。
- **display 类只读命令不入训练输出**，但保留成 output 里的 `# ...` 注释——
  「先查看再配置」是希望保留的行为习惯。
- 命中率不足或假阳性的实验落 `low.jsonl`，不参与训练。

## 3. 字段含义

### 正样本 `data/finetune/sft_YYYYMMDD.jsonl`（Alpaca 风格）

| 字段 | 含义 |
|---|---|
| `instruction` | 任务书原文（实验要求，含提交物说明） |
| `input` | 设备清单：`设备：LSW1(S5700, Telnet 端口 2000)；…` |
| `output` | 模型实际下发的命令序列；`# <host>:<port>` 注释行标示目标设备（host 取自运行日志，即 `LAB_HOST` 指定的实验主机） |
| `meta` | 溯源信息：`id`（日期/实验号）、`pct`（命中率%）、`net`（净提升条数）、`preset`（是否设备自带答案） |

### 负样本 `data/finetune/sft_YYYYMMDD_low.jsonl`

| 字段 | 含义 |
|---|---|
| `id` / `num` | 实验全名 / 实验编号 |
| `pct` / `net` / `preset` | 同上；`pct=-1` 表示验收未执行（设备没起来） |
| `devices` | `[{name, model, port}]` 设备清单 |
| `commands` | 模型每次工具调用的完整记录（tool/host/port/command/confirm/output_head） |
| `answer` | 模型的自然语言总结（含失败原因，供人工复核与提示词改进） |

## 4. 复现命令

```bash
# 从运行日志导出（当天的所有实验）
python tools/build_sft.py --day 2026-10-01 --min-pct 60 --min-net 1

# 转 chat 格式 + 切分训练/验证集
python training/prepare_data.py --src data/finetune/sft_20261001.jsonl --val-ratio 0.2

# 重新生成参考答案与拓扑数据（需要本地保留 data/ensp_labs/，不入库）
python tools/extract_answers.py
python tools/topo_extract.py
```

## 5. 现状与扩充计划（2026-10-04）

| 数据集 | 条数 | 用途 |
|---|---|---|
| `sft_20261001.jsonl` | 3 | 训练正样本（命中率 ≥60 且净提升 ≥1） |
| `sft_20261001_low.jsonl` | 15 | 人工复核 / 提示词改进后重跑 |
| `data/lab_answers/` | 43 实验 / 130 份路由器答案 | 验收基准；也可构造「任务书→标准答案」合成样本 |
| `knowledge/topology/` | 57 实验 / 261 设备 / 426 链路 | 拓扑结构化数据（vision/图能力） |

正样本达到百级（71 个实验全部跑通后）再启动正式训练；
在那之前训练只用于打通全流程。交换机类答案为 eNSP 私有 `flash.efz` 格式
（魔数 `eNSP`，未解包），后续可从「清场后重配」的运行日志侧补齐交换机答案。
