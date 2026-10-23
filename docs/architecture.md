# NetworkClaw 架构

一句话：**本地大模型 + RAG + MCP 工具，面向网络设备（华为 eNSP 实验环境）的
配置代理与批量陪跑系统**。端到端链路：本地/云端 LLM 通过 MCP 工具 Telnet/串口
登录设备下发命令，命令过安全网关，全程留痕，实验结果导出为微调数据。

## 1. 总体结构

```mermaid
flowchart TB
    subgraph 入口
        MAIN[main.py 唯一入口/异步]
        GUI[gui/ PyQt6 桌面端]
        CLI[launcher.py --cli]
    end

    subgraph core 核心层
        LS[llama_start<br/>llama-server 生命周期]
        LC[llm_client<br/>唯一 LLM 调用出口]
        PR[providers<br/>模型提供方注册表]
        AG[agent<br/>工具调用循环]
        RAG[rag / template_search<br/>知识检索]
        OI[ollama_interface<br/>向量库唯一出口]
        VIS[vision / parallel / screen_capture<br/>识图与多模态编排]
        DG[command_guard<br/>命令安全网关]
        DC[device_conn<br/>串口/Telnet 唯一连接出口]
    end

    subgraph mcp_tools["mcp_tools/（MCP 服务端 + 客户端）"]
        HUB[client.py McpHub]
        TS[telnet_server]
        DS[device_server 串口]
        TPL[template_server 知识+模板]
        MAN[manual_server 设备手册]
        RPT[report_server 工作流报告]
        VS[vision_server]
    end

    subgraph 外部
        DEV[eNSP 设备<br/>AR2220 / S5700 ...]
        VM[VMware 实验机<br/>192.168.1.179]
        OLL[Ollama :11434<br/>nomic-embed-text]
        LLS[llama-server :8080<br/>Qwen3.5 GGUF + mmproj]
        DS2[DeepSeek API<br/>deepseek-flash / deepseek-pro]
    end

    MAIN --> LS & OI & HUB
    GUI & CLI --> MAIN
    PR --> LC
    LC --> LLS & DS2
    AG --> LC & HUB & RAG & VIS
    RAG --> OI --> OLL
    HUB --> TS & DS & TPL & MAN & RPT & VS
    TS & DS --> DG --> DC --> DEV
    VS --> VM
```

分层铁律（改动前先看 `docs/` 与 MEMORY 约定）：

- `llm_client` 是**唯一** LLM 调用出口，业务模块不得自行拼 HTTP；
- 端点/密钥/能力画像只在 `providers.py` 定义，`config/llm.json` 与 `.env` 只做覆盖；
- 所有设备通道（Telnet/串口）必须过 `command_guard`，密码不落盘；
- 向量库集合只在 `ollama_interface.py` 注册，句柄现取现用。

## 2. 批量实验数据流（毕设主线的"跑实验→产数据"闭环）

```mermaid
flowchart LR
    subgraph 起实验
        A[lab_batch 调度] --> B[lab_up<br/>打开 topo + 开启设备]
        B --> C[lab_probe_devices<br/>等 console 就绪]
    end
    subgraph 模型配置
        C --> D[lab_run_agent<br/>任务书 -> 模型]
        D --> E[MCP 工具循环<br/>telnet/知识检索/识图]
        E --> F[command_guard 裁决<br/>allow/confirm/block]
        F --> G[设备执行 + 回显]
    end
    subgraph 留痕与导出
        G --> H[run_log<br/>calls + events 两份日志]
        H --> I[lab_verify 验收<br/>与 lab_answers 比对]
        I --> J[lab_reports + issues]
        H --> K[build_sft 导出<br/>min-pct/min-net 过滤]
        K --> L[(data/finetune)]
        L --> M[train_sft.py QLoRA]
        M --> N[(models/ 新 GGUF)]
        N --> D
    end
```

要点：

- **验收基准**来自实验包自带参考答案（`data/lab_answers/`），
  「设备开机自带答案」的假阳性用 `net`（净提升）指标剔除；
- 调度器只给后台任务 2 分钟超时，长任务必须经 `tools/spawn.py` 脱离进程启动；
- 实验中每条命令的裁决与执行都写 `logs/command_audit.log`（密码不落盘）。

## 3. 关键外部依赖

| 依赖 | 版本/端口 | 说明 |
|---|---|---|
| llama-server | :8080 | 必须 `--jinja` 才返回 tool_calls；视觉要加载 mmproj |
| Ollama | :11434 | Embedding 用 `nomic-embed-text`；挂了不许清索引（先 `check_embedder`） |
| VirtualBox | 5.1.24 | eNSP 路由器 = VBox VM 克隆；路径写死在 eNSP `cfg/config_sys.ini` |
| eNSP | 1.2.00.510 | 58 个实验包，`.topo` 为 GBK 双 XML 拼接（解析见 `tools/topo_extract.py`） |
| DeepSeek | api.deepseek.com | `deepseek-flash`(多模态) / `deepseek-pro`(深度推理)；旧名走 ALIASES |

## 4. 目录速览

```
main.py           唯一入口
core/             23 个核心模块（见第 1 节）
mcp_tools/        7 个 MCP 服务端 + McpHub 客户端（26 个工具，清单见 docs/mcp_tools.md）
tools/            62 个运维/实验脚本（vm_*、lab_*、build_sft、topo_extract…）
training/         LoRA/QLoRA 微调（train_sft.py，见 training/README.md）
gui/              PyQt6 桌面端
knowledge/        命令模板 CSV、实验文档、拓扑数据集 topology/
data/             运行数据（finetune/、lab_answers/、topology_images/…）
session/          会话级设备技能：session/<会话>/skill/<设备名>/SKILL.md + history.jsonl
docs/             本文档 + packaging + sft_dataset + troubleshooting
tests/            pytest（离线可跑）
```
