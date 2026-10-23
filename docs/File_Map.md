# NetworkClaw 项目总结与文件地图

> 生成日期：2026-10-21（随代码演进，具体数量以文中标注的来源为准，别把本文当唯一事实源）。
> 本文是**总览 + 文件地图**：逐目录说明"这个文件是干什么的"。
> 深入主题看专项文档：架构 `docs/architecture.md`、知识库 `docs/knowledge_base.md`、
> MCP 工具 `docs/mcp_tools.md`、等保规则 `docs/dengbao_rules.md`、
> SFT 数据 `docs/sft_dataset.md`、打包 `docs/packaging.md`、踩坑 `docs/troubleshooting.md`。

## 1. 一句话定位

**本地大模型 + RAG + MCP 工具，面向华为 eNSP 实验环境的网络设备配置代理与批量陪跑系统。**

端到端链路：本地/云端 LLM 通过 MCP 工具以 Telnet/串口登录设备下发命令，
命令先过安全网关裁决，全程留痕；批量实验结果导出为微调数据集，反哺模型。
本科毕业设计主线：本地 Qwen3.5-9B（llama.cpp GGUF）+ ChromaDB RAG + MCP 工具链。

## 2. 当前状态快照（2026-10-21）

| 维度 | 现状 |
|---|---|
| 入口 | `main.py`（CLI/agent 模式）+ `launcher.py`（PyQt6 桌面端 `--cli`） |
| 本地模型 | Qwen3.5-9B-Q4_K_M.gguf + mmproj-BF16.gguf（识图可选加载） |
| 云端模型 | DeepSeek Flash（多模态）/ Pro（深度推理），OpenAI 兼容协议 |
| MCP | 7 个服务端 / 26 个工具（"一个工具一个文件"拆分后不变，数量以 `tests/test_mcp_servers.py` 断言为准） |
| 知识库 | ChromaDB 两个集合：`huawei_devices`（知识）+ `command_templates`（命令模板） |
| 规则资产 | 58 个 eNSP 实验文档 + 57 份拓扑结构化数据集 + 56 条等保2.0 检查规则 |
| 实验闭环 | `lab_batch → lab_up → lab_run_agent → 验收比对 → lab_reports → build_sft → train_sft` |
| 测试 | `.venv/Scripts/python.exe -m pytest` 离线全量可跑（**不写死用例数**） |
| 打包 | PyInstaller onedir，产物 `dist/NetworkClaw/NetworkClaw.exe` |

## 3. 分层结构与调用关系

分层铁律（改代码前必读，详见 `CONTRIBUTING.md` 与项目 MEMORY 约定）：

- `llm_client` 是**唯一** LLM 调用出口，业务模块不得自行拼 HTTP；
- 端点/密钥/能力画像只在 `providers.py` 定义，`config/llm.json` 与 `.env` 只做覆盖；
- 所有设备通道（Telnet/串口）必须过 `command_guard`，密码不落盘；
- 向量库集合名只在 `ollama_interface.py` 注册，句柄现取现用，不模块级持有。

```
main.py
  ├── core/providers.py        提供方注册表（本地 llama-server / DeepSeek）
  ├── core/llama_start.py      按需启动/停止本地 llama-server（云端模式跳过）
  ├── core/rag.py              知识库索引（幂等）；ask() 检索 + 流式问答
  │     └── core/ollama_interface.py   Ollama embedding + ChromaDB 句柄工厂
  ├── core/agent.py            工具调用循环 → mcp_tools/client.py → MCP 服务端
  │     ├── core/llm_client.py 带 tools 的流式调用（本地需 --jinja 才有 tool_calls）
  │     └── core/vision.py     能看图直接送图；不能看图先本地识图再注入文字
  ├── core/parallel.py         多模态并行：识图 ∥ 多模型回答 → 融合
  ├── core/topology_flood.py   拓扑泛洪发现：LLDP/MAC/ARP → 层级 + Mermaid
  └── 设备操作链路（安全可控）
        mcp_tools/{telnet,device}_server.py
          → core/command_guard.py（allow/confirm/block 三级裁决 + 审计）
            → core/device_conn.py（串口 / Telnet 会话）
```

## 4. 文件地图（目录 → 文件 → 职责）

### 4.1 根目录

| 文件 | 职责 |
|---|---|
| `main.py` | 唯一异步入口：llama-server → 索引 → MCP → 对话循环；agent / rag 模式可切换 |
| `launcher.py` | 桌面端启动器（GUI 默认；`--cli` 进命令行） |
| `NetworkClaw.spec` | PyInstaller 打包配置；**MCP 工具必须进 hiddenimports**，漏一个丢一个 |
| `build_exe.ps1` | 一键打包脚本 |
| `pytest.ini` / `requirements*.txt` | 测试配置 / 依赖清单 |
| `README.md` / `CHANGELOG.md` / `CONTRIBUTING.md` | 项目门面 / 变更记录 / 协作铁律 |
| `assets/` | 图标与启动图 |
| `_*.py`（根目录散脚本） | 一次性排查/验证脚本，非运行链路，可随时清理 |

### 4.2 `core/` 核心业务层（唯一出口原则）

| 文件 | 职责 |
|---|---|
| `paths.py` | 路径与环境适配：BASE_DIR、标准流修复、llama-server 与模型探测（打包后仍成立） |
| `net.py` | 本机回环代理劫持规避（NO_PROXY 注入，新增本机 HTTP 调用前确认已导入） |
| `providers.py` | 模型提供方注册表：本地 / DeepSeek 统一抽象（能力画像 + 密钥 + 探测）；新模型进这里或 `config/llm.json` |
| `llama_start.py` | LLM 服务生命周期：单实例启动/健康检查/停止；`--mmproj` 多模态；**必须 `--jinja`** 否则无 tool_calls |
| `llm_client.py` | 唯一 LLM 调用出口：按提供方组装请求、流式输出、思考拆分、tool_calls 解析、token 统计 |
| `ollama_interface.py` | 向量库唯一出口：集合名注册表、句柄工厂（现取现用）、索引指纹状态 |
| `rag.py` | RAG 流程：知识切分入库、检索、流式问答；`load_chunks()` 是索引来源的唯一事实源 |
| `template_search.py` | 命令模板语义检索（另一集合 `command_templates`，与知识库索引指纹互不干扰） |
| `agent.py` | Agent 流程：模型自主调用 MCP 工具的多轮循环（含安全红线提示词） |
| `command_guard.py` | 命令安全网关：allow / confirm / block 三级裁决 + 审计日志（密码不落盘） |
| `device_conn.py` | 设备连接层：串口（pyserial）与自实现 Telnet 会话、提示符识别 |
| `session_skills.py` | 会话级设备技能：一个对话一套 skill（`session/<sid>/skill/<设备>/`） |
| `device_manual.py` | 设备手册骨架 / 小节读写 / 命令历史；冷启动时用型号画像预填 |
| `device_registry.py` | 设备档案注册（型号、地址、通道） |
| `data_report.py` | 工作流数据报告：汇总会话/设备/逐轮调用/命令/验收 → Markdown + JSON |
| `topology_flood.py` | 拓扑泛洪发现：LLDP/CDP/MAC/ARP 解析 → 无向图生成树 → 层级 + Mermaid |
| `auto_topology.py` / `screen_capture.py` / `vision.py` | 自动巡检编排 / 截屏 / 图像识别（mmproj 探测、缩放编码、识读提示词） |
| `run_log.py` | 逐轮运行日志（calls + events 两份 JSONL），SFT 与报告的数据源 |
| `parallel.py` | 多模态并行编排：本地识图 ∥ 多模型回答 → 融合成一份答案 |
| `cmd_hints.py` / `local_service.py` | 命令提示 / 本地 llama-server 生命周期封装（GUI 与 CLI 共用） |

### 4.3 `mcp_tools/` MCP 工具层

**结构约定（2026-10-20 起）**：一个工具一个文件，`tools/<工具名>.py`，
**文件名 = 函数名 = 工具名**，工具函数不带 `@mcp.tool`（否则无法脱离 MCP 运行时被调用/测试）；
`*_server.py` 只做**注册中心**（`FastMCP` 实例 + `mcp.tool(fn)`），不含业务逻辑。

| 文件 | 职责 |
|---|---|
| `client.py` | McpHub：stdio 拉起服务端、聚合工具清单、按名路由调用；**跨服务端重名检测**（见 §7） |
| `tools/_bootstrap.py` | 公共支撑：sys.path 引导 + 回显截断 + 相对路径 |
| `tools/_archive.py` | 公共支撑：命令历史归档（telnet/serial 两通道共用） |
| `tools/_manual_common.py` | 公共支撑：会话位置说明 + 手册正文截断 |
| `tools/<26 个工具>.py` | 按域分四组：Telnet 通道（check_telnet / exec_telnet_command）、串口通道（list_serial_ports / classify_command / exec_command / recent_audit）、知识与模板（query_command_template / search_knowledge）、设备手册（list_device_manuals / read_device_manual / create_device_manual / update_device_manual_section / recent_device_history / list_session_skills）、工作流报告（export_workflow_report / workflow_report_overview / list_report_sessions）、拓扑（discover_topology / load_discovered_topology / topology_summary / topology_mermaid）、视觉（vision_ready / list_local_images / analyze_topology_image / capture_topology / get_topology_snapshot） |
| `telnet_server.py` / `device_server.py` / `template_server.py` / `manual_server.py` / `report_server.py` / `topology_server.py` / `vision_server.py` | 七个注册中心，装配对应工具 |
| `internet.py` / `search_client.py` | 联网搜索服务端 / 其单独试跑脚本 |

> 新增工具四步：① 建 `tools/<名>.py` ② 注册中心 import + `mcp.tool(fn)`
> ③ **spec hiddenimports 加 `mcp_tools.tools.<名>`**（漏加则打包丢工具）
> ④ 更新 `docs/mcp_tools.md` + 跑 `tests/test_mcp_servers.py`。

### 4.4 `gui/` PyQt6 桌面端

| 文件 | 职责 |
|---|---|
| `app.py` | QApplication 组装：参数解析、主题、QSettings、异常兜底 |
| `main_window.py` | 主窗口：侧边栏会话 + 对话/运行日志/命令控制台三页签 |
| `widgets.py` | 消息气泡（流式渲染）、会话列表、附件栏、状态灯 |
| `worker.py` | AgentWorker（QThread）：后台跑 asyncio 事件循环 + 信号上屏 |
| `dialogs.py` / `store.py` / `theme.py` | 设置/工具箱/审计对话框；会话持久化（导出 Markdown）；深浅色 QSS |

### 4.5 `knowledge/` 知识资产

| 路径 | 职责 |
|---|---|
| `huawei_devices_introduce.txt` | 华为设备知识文本，RAG 数据源 ①（instance 级） |
| `experiments/NN-*.md` | eNSP 实验文档：题目/设备清单（含 console 端口）/链路/画布标注/参考答案/验收要点，由 `tools/ensp_lab_index.py` 生成，RAG 数据源 ②（rule 级，向量库主要来源） |
| `command_templates.csv` | 三厂商命令模板表，**唯一数据源**，手工维护；另一集合 `command_templates` |
| `topology/*.json` | 拓扑结构化数据集，由 `tools/topo_extract.py` 从 `.topo` 解析；`core/rag.py` 有 `TOPOLOGY_DIR` 常量但**未纳入索引**，改用 `tools/kb_consistency.py` 与 experiments 互校防漂移 |
| `compliance/dengbao_rules/<ID>.yaml` | 等保2.0 配置检查规则，**一条一文件**；改规则只改 `tools/build_dengbao_rules.py` 再重跑，勿手改 YAML（会被覆盖） |
| `compliance/dengbao_source_lines.json` | 测评表原文逐行存档，供测试核对"命令必须有出处"（venv 无 openpyxl，直接读 xlsx 会被 skip） |
| `device_profiles.py` | 型号基线画像，用于**设备建档预填**（写入手册「注意事项」），**不是 RAG 来源**；最长键优先匹配 |

### 4.6 `tools/` 实验与运维脚本

| 脚本 | 职责 |
|---|---|
| `lab_batch.py` | 批量实验调度（**必须走 `tools/spawn.py` + `CREATE_BREAKAWAY_FROM_JOB`**，否则 2 分钟后台任务超时被杀） |
| `lab_up.py` / `lab_probe_devices.py` / `lab_run_agent.py` | 起实验：开 topo + 起设备 → 等 console 就绪 → 任务书交给模型跑配置 |
| `ensp_open_lab.py` / `ensp_start_devices.py` / `ensp_ui.py` / `vm_*` | eNSP/VMware 界面自动化（键鼠注入走 `guest_run_elevated()`，UIPI 会静默丢弃 Medium→High 的注入） |
| `extract_answers.py` / `ensp_lab_index.py` / `topo_extract.py` | 实验包 → 参考答案 / 实验文档 / 拓扑数据集 |
| `kb_consistency.py` | 两份拓扑数据（experiments ↔ topology）交叉一致 + 历史 bug 回归 |
| `build_dengbao_rules.py` / `render_dengbao_overview.py` / `_verify_remediation_source.py` | 等保规则生成器（三道自检）/ 人读总表 / 命令出处白名单 |
| `build_sft.py` | 运行日志 → SFT 数据集（`--min-pct` / `--min-net` 过滤假阳性） |
| `spawn.py` | 脱离进程启动长任务（breakaway job） |
| `gui_smoke_test.py` / `exe_verify.py` | GUI 离屏冒烟 / 出包自检 |

### 4.7 `training/` 微调（毕设核心）

| 文件 | 职责 |
|---|---|
| `train_sft.py` | 微调入口（unsloth + trl，QLoRA），产出 adapter / 合并模型 / GGUF |
| `prepare_data.py` | SFT jsonl → chat 格式 + train/val 切分 |
| `config_qwen35_9b_lora.yaml` | 复现参数快照 |
| `training/README.md` | 微调专题说明 |

### 4.8 `data/` `logs/` `session/` `models/` `config/`

| 路径 | 职责 |
|---|---|
| `data/Rag_data/` | ChromaDB 向量库持久化（已 gitignore） |
| `data/index_state.json` | 各集合索引指纹（内容 md5 + 块数），判断是否需要重建 |
| `data/finetune/` | SFT 数据集（正/负样本） |
| `data/lab_answers/` | 实验参考答案（验收基准） |
| `data/lab_reports/` | 批量实验报告 + `issues.md` 踩坑清单（**进知识库**，history 级） |
| `data/run_logs/` | 逐轮运行日志（摘要只取当前会话进索引） |
| `data/ensp_labs/` | 58 个实验包原件（不入库，本地保留） |
| `logs/command_audit.log` | 命令裁决审计（**密码不落盘**） |
| `session/<sid>/skill/<设备>/` | 会话级设备技能：`SKILL.md` + `history.jsonl`；`session/.current` 为指针文件（原子写） |
| `models/` | GGUF 模型源文件（不入库） |
| `config/llm.json` | 模型配置覆盖（含密钥，已 gitignore；样例见 `llm.example.json`） |

## 5. 三条核心数据流

1. **对话主链路**：用户 → `main.py` → `llm_client`（本地/云端）→ `agent.py` 循环
   → `McpHub` 路由到 MCP 工具 → `command_guard` 裁决 → 设备执行 → 回显进 prompt。
   知识检索走 `search_knowledge` / `query_command_template`；识图走 vision 工具或多模态桥接。
2. **批量实验产数据（毕设主线）**：`lab_batch` 调度 → `lab_up` 起设备 → `lab_run_agent`
   让模型自己配 → 与 `lab_answers` 比对验收（`net` 指标剔除"开机自带答案"假阳性）
   → 报告落 `lab_reports` → `build_sft` 导出 → `train_sft.py` QLoRA 微调 → 新 GGUF 回流。
3. **安全与留痕**：所有设备命令过三级裁决（`allow`/`confirm`/`block`），
   裁决写 `logs/command_audit.log`；`confirm` 需带 `confirm=true` 重调；多命令按最高风险裁决。

## 6. 知识库索引来源（以 `core/rag.py:load_chunks()` 为准，共四类）

| # | 来源 | 分级 |
|---|---|---|
| ① | `knowledge/huawei_devices_introduce.txt` | instance |
| ② | `knowledge/experiments/*.md` | rule |
| ③ | `data/lab_reports/*.md`（含 `issues.md`） | history |
| ④ | `data/run_logs/<当前会话>/*.jsonl`（摘要） | history |

**设备手册不进索引**（会话隔离，直注系统提示词）；`topology/` 有常量但未纳入索引；
`device_profiles.py` 是建档预填不是来源。分级前缀让模型区分"现行规则"与"上次踩的坑"。

## 7. 测试与验证

- 唯一离线全量命令：`.venv/Scripts/python.exe -m pytest`（conftest autouse 夹具把
  `session/` 与日志根隔离到临时目录）。
- **工具名冲突防线**：`McpHub._load_tools()` 检测到跨服务端同名会打印
  `[MCP] 警告：工具名冲突 <名>（<原属主> 与 <新属主>），调用将路由到 <后注册者>`；
  `tests/test_mcp_servers.py` 里 `test_no_duplicate_tool_names_across_servers` 断言无重名，
  `test_mcp_client_detects_duplicate_names` 断言 client 确有检测逻辑。
- **测试数据读 JSON 不读 xlsx**：等保原文存 `knowledge/compliance/dengbao_source_lines.json`。
- 其他自检：`python -m core.command_guard`（命令分级）、`python -m mcp_tools.client`（MCP 装配）、
  `tools/kb_consistency.py --json`（拓扑数据一致）。

## 8. 运行前提与易变项（别在文档里写死）

| 项 | 说明 |
|---|---|
| 实验主机 | **以 `LAB_HOST` 环境变量为准**（`tools/lab_up.py` / `lab_run_agent.py` / `lab_probe_devices.py` 读取，默认值见源码） |
| Telnet 端口 | 2000-2002=R1-R3、2003-2005=SW1-SW3；无 Telnet 凭据，sysname 已设 |
| Ollama | 必跑（:11434 + `nomic-embed-text`），否则检索类工具降级告警 |
| llama-server | :8080，**必须 `--jinja`**；识图需 `models/mmproj-BF16.gguf` |
| VirtualBox | 起设备前提：来宾 Host-Only Network 存在且启用（192.168.56.1/24） |
| 依赖 | `pip install -r requirements.txt`；串口需 `pyserial`；DeepSeek 密钥走 `.env` 或 `config/llm.json` |

## 9. 新人阅读路径

1. `README.md`（总览）→ 本文（文件地图）→ `docs/architecture.md`（架构与数据流）
2. 跑起来：`python main.py`，试 `/model` 切换、`/parallel` 并行、`/topology` 巡检
3. 读代码从 `main.py` → `core/agent.py` → `core/llm_client.py` → `mcp_tools/client.py`
4. 设备安全看 `core/command_guard.py`；知识库看 `core/rag.py` + `docs/knowledge_base.md`
5. 跑实验看 `tools/lab_batch.py` 与 `docs/sft_dataset.md`

## 10. 与其它文档的分工

| 想知道 | 看 |
|---|---|
| 整体架构 / 数据流 / 外部依赖 | `docs/architecture.md` |
| 知识库来源 / 分级 / 检索状态 / 一致性校验 | `docs/knowledge_base.md` |
| MCP 工具清单与安全约定 | `docs/mcp_tools.md` |
| 等保规则字段契约与出处算法 | `docs/dengbao_rules.md` |
| SFT 数据集与微调复现 | `docs/sft_dataset.md` |
| 启动流程 / 拓扑自动巡检 | `docs/startup_and_auto_topology.md` |
| 环境踩坑（代理/eNSP/vmrun/打包） | `docs/troubleshooting.md` |
| 打包与发布 | `docs/packaging.md` |
| 逐次工作明细 | `.workbuddy/memory/YYYY-MM-DD.md` |
