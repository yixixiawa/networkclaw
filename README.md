# Agent-Rag-MCP-startup

NetworkClaw 前身项目：本地 LLM（llama.cpp + Qwen）+ ChromaDB RAG 知识库 + MCP 工具链。

## 目录结构与职责

```
Agent-Rag-MCP-startup/
├── main.py                      # 统一启动入口：llama-server → 知识库索引 → 连接 MCP → 对话
│                                #   agent 模式（模型自主调用 MCP 工具）/ rag 模式可随时切换
│
├── core/                        # 核心业务层
│   ├── providers.py             # 模型提供方注册表：本地 / DeepSeek 统一抽象（能力画像 + 密钥 + 探测）
│   ├── parallel.py              # 多模态并行编排：本地识图 ∥ 多模型回答 → 融合成一份答案
│   ├── llama_start.py           # LLM 服务管理：单实例启动（已有实例自动复用）/健康检查/停止；
│   │                            #   --mmproj 多模态加载；`python -m core.llama_start kill` 清理残留
│   ├── llm_client.py            # LLM 客户端：按提供方组装请求、流式对话、思考过程拆分、
│   │                            #   工具调用（tools/tool_calls）解析、token 统计、并行调用
│   ├── ollama_interface.py      # Embedding 与向量库接口：Ollama embedding + ChromaDB
│   │                            #   集合名注册表 / 集合句柄工厂 / 索引指纹状态
│   ├── rag.py                   # RAG 流程：知识文档切分入库、检索、流式问答
│   ├── agent.py                 # Agent 流程：模型自主调用 MCP 工具的多轮循环（含安全红线提示词）
│   ├── session_skills.py        # 会话级设备技能：一个对话一套 skill（session/<sid>/skill/<设备>/）
│   ├── device_manual.py         # 设备手册骨架/小节读写/命令历史（路径按会话解析）
│   ├── data_report.py           # 工作流数据报告：汇总会话/设备/逐轮调用/命令/验收 → Markdown + JSON
│   ├── template_search.py       # 命令模板语义检索（阶段二）：意图匹配 + 厂商/设备类型过滤
│   ├── command_guard.py         # 命令安全网关：allow / confirm / block 三级裁决 + 审计日志
│   ├── device_conn.py           # 设备连接层：串口（pyserial）与 Telnet（自实现）会话、提示符识别
│   ├── vision.py                # 图像识别层：mmproj 探测、图片缩放编码、拓扑识读提示词
│   ├── paths.py                 # 路径与环境适配层：BASE_DIR/RESOURCE_DIR、标准流修复、
│   │                            #   llama-server 与模型探测（打包成 exe 后依然成立）
│   ├── local_service.py         # LocalService：本地 llama-server 生命周期封装（GUI/CLI 共用）
│   └── net.py                   # 本机回环代理劫持规避（NO_PROXY 注入）
│
├── gui/                         # PyQt6 桌面应用
│   ├── app.py                   # QApplication 组装：参数解析、主题、QSettings、异常兜底
│   ├── main_window.py           # 主窗口：侧边栏会话 + 对话/运行日志/命令控制台三页签
│   ├── widgets.py               # 消息气泡（流式渲染）、会话列表、附件栏、状态灯等控件
│   ├── worker.py                # AgentWorker（QThread）：后台跑 asyncio 事件循环 + 信号上屏
│   ├── dialogs.py               # 设置 / 工具箱 / 审计记录 对话框
│   ├── store.py                 # 会话持久化（data/sessions.json，导出 Markdown）
│   └── theme.py                 # 深色 / 浅色 QSS 主题
│
├── mcp_tools/                   # MCP 工具层
│   ├── template_server.py       # 注册中心（Network-Knowledge）：装配 2 个检索工具
│   ├── device_server.py         # 注册中心（Network-Device-Serial）：装配 4 个串口工具
│   ├── telnet_server.py         # 注册中心（Network-Device-Telnet）：装配 2 个 Telnet 工具
│   ├── vision_server.py         # 注册中心（Network-Vision）：装配 5 个识图工具
│   ├── manual_server.py         # 注册中心（Network-Device-Manual）：装配 6 个手册工具
│   ├── report_server.py         # 注册中心（Network-Data-Report）：装配 3 个报告工具
│   ├── topology_server.py       # 注册中心（Network-Topology-Flood）：装配 4 个拓扑工具
│   ├── tools/                   # 单工具模块：一个文件 = 一个 MCP 工具
│   │   ├── _bootstrap.py        #   公共：sys.path 引导 + 回显截断 + 相对路径
│   │   ├── _archive.py          #   公共：命令历史归档（telnet/serial 两通道）
│   │   ├── _manual_common.py    #   公共：会话位置说明 + 手册正文截断
│   │   ├── check_telnet.py      #   → check_telnet
│   │   ├── exec_telnet_command.py   #   → exec_telnet_command
│   │   ├── list_serial_ports.py     #   → list_serial_ports
│   │   ├── classify_command.py      #   → classify_command
│   │   ├── exec_command.py          #   → exec_command
│   │   ├── recent_audit.py          #   → recent_audit
│   │   ├── query_command_template.py    #   → query_command_template
│   │   ├── search_knowledge.py          #   → search_knowledge
│   │   ├── list_device_manuals.py       #   → list_device_manuals
│   │   ├── read_device_manual.py        #   → read_device_manual
│   │   ├── create_device_manual.py      #   → create_device_manual
│   │   ├── update_device_manual_section.py  #   → update_device_manual_section
│   │   ├── recent_device_history.py     #   → recent_device_history
│   │   ├── list_session_skills.py       #   → list_session_skills
│   │   ├── export_workflow_report.py    #   → export_workflow_report
│   │   ├── workflow_report_overview.py  #   → workflow_report_overview
│   │   ├── list_report_sessions.py      #   → list_report_sessions
│   │   ├── discover_topology.py         #   → discover_topology
│   │   ├── load_discovered_topology.py  #   → load_discovered_topology
│   │   ├── topology_summary.py          #   → topology_summary
│   │   ├── topology_mermaid.py          #   → topology_mermaid
│   │   ├── vision_ready.py              #   → vision_ready
│   │   ├── list_local_images.py         #   → list_local_images
│   │   ├── analyze_topology_image.py    #   → analyze_topology_image
│   │   ├── capture_topology.py          #   → capture_topology
│   │   └── get_topology_snapshot.py     #   → get_topology_snapshot
│   ├── internet.py              # MCP 服务端：封装 open-websearch 联网搜索工具
│   ├── client.py                # MCP 客户端层：stdio 拉起服务端、聚合工具、路由调用、重名检测
│   └── search_client.py         # MCP 客户端测试脚本（联网搜索服务单独试跑用）
│
├── models/                      # 模型源文件（llama.cpp GGUF）
│   ├── Qwen3.5-9B-Q4_K_M.gguf   # 主模型
│   └── mmproj-BF16.gguf         # 视觉投影文件（图像识别所需；缺失时自动降级为纯文本）
│
├── config/                      # 运行配置
│   ├── llm.json                 # 模型提供方配置（可选；含密钥，已加入 .gitignore）
│   └── llm.example.json         # 配置样例（可安全提交）
│
├── knowledge/                   # 知识库源文档（详见 docs/knowledge_base.md）
│   ├── huawei_devices_introduce.txt   # 华为设备知识文本（RAG 数据源）
│   ├── command_templates.csv    # 三厂商命令模板表（阶段一，手工维护，唯一数据源）
│   ├── compliance/              # 等保2.0 配置检查规则集（详见 docs/dengbao_rules.md）
│   │   ├── dengbao_rules/       #   56 条规则：一条一个 YAML + rules_index.json + 人读总表
│   │   └── dengbao_source_lines.json  # 测评表原文逐行存档（供测试核对命令出处）
│   ├── experiments/             # 58 个 eNSP 实验文档（题目/设备表/链路/标注/参考答案/验收要点）
│   │                            #   由 tools/ensp_lab_index.py 生成；是向量库的主要来源
│   ├── topology/                # 拓扑结构化数据集（57 实验 / 261 设备 / 426 链路 + index.json）
│   │                            #   由 tools/topo_extract.py 从 .topo 解析
│   └── review_queue.csv         # 阶段三人工审核队列（由脚手架生成）
│
├── tools/                       # 辅助工具
│   ├── manual_extractor.py      # 阶段三脚手架：从官方手册粗提取命令候选
│   ├── ensp_lab_index.py        # 实验包 → knowledge/experiments/*.md（进向量库）
│   ├── topo_extract.py          # .topo → knowledge/topology/*.json（结构化拓扑数据集）
│   ├── extract_answers.py       # 实验包参考答案 → data/lab_answers/
│   ├── kb_consistency.py        # 知识库一致性校验：experiments md ↔ topology json 互校
│   ├── build_dengbao_rules.py   # 等保2.0 测评项 → 配置检查规则 YAML（含命令出处三道自检）
│   ├── render_dengbao_overview.py  # 规则集人读总表生成
│   └── build_sft.py             # 运行日志 → SFT 微调数据集（含假阳性剔除）
│
├── training/                    # LoRA/QLoRA 微调（毕设核心，详见 training/README.md）
│   ├── train_sft.py             # 微调入口（unsloth + trl，产出 adapter / 合并模型 / GGUF）
│   ├── prepare_data.py          # SFT jsonl → chat 格式 + train/val 切分
│   ├── config_qwen35_9b_lora.yaml     # 复现参数快照
│   └── requirements.txt         # 训练依赖（与本体隔离，需 GPU）
│
├── tests/                       # pytest 测试（离线可跑）
│   ├── conftest.py              # 公共夹具：项目根路径 + 会话技能/运行日志目录隔离
│   ├── test_command_guard.py    # 命令分级 / 实验模式 / 多命令取最高级
│   ├── test_providers_and_net.py      # 提供方注册表 / 旧名兼容 / 回环代理豁免
│   ├── test_telnet_session.py   # 线程版"假设备"Telnet 端到端（无需真机）
│   ├── test_topo_extract.py     # .topo 解析与数据集完整性
│   ├── test_kb_consistency.py   # 两份拓扑数据交叉一致 + 历史 bug 回归
│   ├── test_rag.py              # 索引来源 / 分级前缀 / 日志摘要 / 检索状态机
│   ├── test_agent_loop.py       # 工具调用循环（async）：参数错误、轮次上限、回调
│   ├── test_mcp_servers.py      # 服务端工具清单 + 跨服务端重名检测 + 降级话术
│   ├── test_template_search.py  # 模板检索：元数据过滤收敛 / 无命中短路
│   ├── test_device_manual.py    # 设备手册建档 / 型号画像预填 / 小节读写
│   ├── test_audit_rotation.py   # 审计日志轮转与跨文件 tail
│   ├── test_run_log.py          # 运行日志：文件名安全 / 截断 / 会话枚举
│   ├── test_topology_flood.py   # 拓扑泛洪：LLDP/ARP/MAC 解析、层级推导、渲染、只读性
│   ├── test_session_skills.py   # 一个对话一套技能：隔离语义 / 指针文件 / 迁移 / 下游接线
│   └── test_data_report.py      # 工作流报告：采集完整 / 隔离语义 / 渲染质量 / 导出与 MCP 工具
│
├── session/                     # 会话级设备技能（运行期产物，已 gitignore）
│   ├── .current                 # 当前会话指针（一行 sid，主程序开对话时写入）
│   └── <会话标识>/skill/<设备名>/SKILL.md + history.jsonl
│
├── .github/workflows/ci.yml     # CI：py_compile + kb_consistency + pytest + 命令分级自检
│
├── docs/                        # 项目文档
│   ├── architecture.md          # 架构与数据流（mermaid）
│   ├── knowledge_base.md        # 知识库：来源 / 分级 / 检索状态 / 一致性校验 / 重建
│   ├── mcp_tools.md             # MCP 工具清单（名/参/用途 + 安全约定）
│   ├── sft_dataset.md           # SFT 数据集说明（来源 / 字段 / 复现）
│   ├── troubleshooting.md       # 踩坑手册（环境/代理/eNSP/vmrun/打包）
│   ├── packaging.md             # PyInstaller 打包
│   ├── startup_and_auto_topology.md   # 启动流程与拓扑自动巡检
│   └── phase3_extraction_plan.md      # 阶段三：官方手册自动提取方案
│
├── data/                        # 持久化数据
│   ├── Rag_data/                # ChromaDB 向量库（含 knowledge / command_templates 两个集合）
│   ├── index_state.json         # 各集合的索引指纹（判断是否需要重建）
│   ├── finetune/                # SFT 数据集（sft_*.jsonl + chat_*/，见 docs/sft_dataset.md）
│   ├── lab_answers/             # 实验参考答案（130 份路由器 .cfg + 58 份交换机 flash 备份）
│   ├── lab_reports/             # 批量实验报告 + issues.md 踩坑清单（会进知识库）
│   ├── topology_images/         # 拓扑识图样例（vision 工具输入）
│   ├── topology_snapshot.*      # 最近一次拓扑巡检结论快照
│   ├── ensp_labs/               # 58 个实验包原件（不入库，本地保留）
│   ├── device_history/          # 各设备命令历史（jsonl，运行时追加）
│   ├── device_inventory.json    # 设备与 console 端口映射
│   └── vm_bridge/               # 与实验虚拟机之间的文件桥（inbox/outbox）
│
├── logs/                        # 运行日志与会话记录（不入库）
│   ├── llama_server.log         # llama-server 运行日志
│   ├── command_audit.log        # 设备命令审计日志（每次裁决一条 JSON：通道/目标/命令/等级/是否执行）
│   ├── session_*.md             # 对话会话导出（启动时自动保存）
│   ├── gui_error.log            # GUI 运行期异常兜底日志
│   └── cli_output.log           # 打包后 --cli 模式的输出副本（窗口程序没有控制台）
│
├── LICENSE                      # MIT
├── CHANGELOG.md                 # 版本变更记录
├── CONTRIBUTING.md              # 协作与分层铁律
├── .env.example                 # 密钥/环境变量样例（复制为 .env）
├── .python-version              # 运行时版本（3.14）
├── pytest.ini                   # 测试配置（testpaths / timeout）
├── requirements.txt             # 运行依赖
└── requirements-dev.txt         # 开发/测试/打包依赖
```

## 模块调用关系

```
main.py
  ├── core/providers.py              # 提供方注册表（本地 llama-server / DeepSeek …）与密钥、能力画像
  ├── core/llama_start.py            # 按需启动/停止本地 llama-server（云端模式下跳过，省内存）
  ├── core/rag.py                    # 知识库索引（幂等）；ask() 检索 + 流式问答
  │     ├── core/ollama_interface.py # Ollama embedding（nomic-embed-text，11434）+ ChromaDB
  │     └── core/llm_client.py       # 按提供方路由的流式调用
  ├── core/agent.py                  # 工具调用循环 → mcp_tools/client.py → MCP 服务端
  │     ├── core/llm_client.py       # 带 tools 的流式调用（本地实例需 --jinja 支持 tool_calls）
  │     └── core/vision.py           # 能看图则直接送图；不能看图则先本地识图再注入文字（桥接）
  ├── core/parallel.py               # 多模态并行：识图 ∥ 多模型回答 → 融合
  ├── core/topology_flood.py         # 拓扑泛洪发现：LLDP/MAC/ARP 解析 → 层级 + 上下级 + Mermaid 图
  ├── mcp_tools/client.py            # stdio 拉起 7 个服务端（知识 / 串口 / Telnet / 手册 / 报告 / 拓扑 / 视觉）
  │
  └── 设备操作链路（安全可控）
        mcp_tools/device_server.py ─┐
        mcp_tools/telnet_server.py ─┴→ core/command_guard.py（三级裁决 + 审计）
                                        └→ core/device_conn.py（串口 / Telnet 会话）
```

## 运行前提

1. `llama-server.exe` 路径已在 `core/llama_start.py` 中配置；模型文件默认取
   `models/Qwen3.5-9B-Q4_K_M.gguf`（相对项目根，换模型只需替换文件或改 `MODEL_PATH`）
   —— 只走云端模型时可跳过本地服务，见下文「模型提供方」
2. Ollama 服务已启动，并已拉取 `nomic-embed-text` 模型（`ollama pull nomic-embed-text`）
   （仅 RAG / 命令模板检索需要；不启动则检索类工具会返回错误说明）
3. 依赖已安装：`pip install -r requirements.txt`
4. **图像识别**（可选）：`models/mmproj-BF16.gguf` 存在即可，用 `--mmproj` 启用；
   串口功能需要 `pyserial`（已在 requirements 中）
5. **DeepSeek**（可选）：申请 API Key 后写入项目根 `.env`：`DEEPSEEK_API_KEY=sk-xxx`

## 模型提供方：本地 + DeepSeek（多模型 / 多模态并行）

`core/providers.py` 把「模型端点」抽象成统一的 **Provider**，其他模块只按名字取用，
不再硬编码 base_url 与模型名。内置三个（可在 `config/llm.json` 增删）：

| 名称 | 类型 | 模型 | 图片 | 工具 | 思考 | 密钥 |
|------|------|------|:----:|:----:|:----:|------|
| `local` | 本地 | Qwen3.5-9B（llama-server） | ✓ | ✓ | ✓ | 不需要 |
| `deepseek-flash` | 云端 | `deepseek-flash`（V4.1 Flash 多模态） | ✓ | ✓ | ✓ | `DEEPSEEK_API_KEY` |
| `deepseek-pro` | 云端 | `deepseek-v4-pro`（V4 Pro 深度推理） | ✗ | ✓ | ✓ | 同上 |

> DeepSeek 走 OpenAI 兼容协议（`https://api.deepseek.com`），2026-09 起模型线换代：
> **`deepseek-flash`（V4.1 Flash）原生多模态，可直接接收图片输入**，1M 上下文 / 384K 输出；
> `deepseek-v4-pro` 为纯文本深度推理（内置默认已开启 `thinking`）。两者都支持 Tool Calls，
> 思考内容在 `reasoning_content` 字段。旧的 `deepseek-chat` / `deepseek-reasoner` 名称已退役，
> 但 `/model deepseek`、`/model deepseek-reasoner` 会被自动映射到 flash / pro，无需改习惯。
> `deepseek-pro` 不看图——发给它的图片会先由本地视觉模型识读成文字再注入（多模态桥接）。

### 配置与密钥

优先级：内置默认 → `config/llm.json` → 环境变量 / `.env`（最高）。

```bash
# 最省事：项目根 .env（已加入 .gitignore）
DEEPSEEK_API_KEY=sk-xxxxxxxx

# 或临时指定（不落盘）
python main.py --deepseek-key sk-xxx
```

`config/llm.json` 可改模型名、超时、能力开关，也能新增其它 OpenAI 兼容提供方
（`base_url` + `model` 即可，例如把 Ollama、通义、智谱接进来）。样例见 `config/llm.example.json`。

### 三种协作方式

**1. 切换使用（`/model`）** —— 单模型回答，能力最完整（含 MCP 工具）

```bash
python main.py --provider deepseek-flash   # 启动即用 DeepSeek Flash（多模态）
python main.py --provider deepseek-pro     # 用 DeepSeek Pro（深度推理）
python main.py --provider local            # 用本地模型
# 对话中随时切换：
/model deepseek-pro                        # 换成深度推理
/model deepseek-flash                      # 换回多模态 Flash
```

云端模式下**不会启动本地 llama-server**（省下数 GB 内存）；切回 `/model local` 时会按需启动。

**2. 多模态桥接（自动）** —— 文本模型 + 本地视觉模型协作

开启图形后，如果当前提供方不看图而本轮带了图片（比如 `deepseek-pro` 或未加载 mmproj 的本地模型），
程序会先用本地多模态模型把图**读成文字结论**，再连同你的问题一起交给它。拓扑图始终在本地解析、
不外传，文本推理则用云端模型。对话中会出现 `[多模态桥接]` 提示。当然，也可以直接
`/model deepseek-flash` 让云端模型原生看图（图片会上传，注意隐私场景）。

**3. 多模型并行（`/parallel`）** —— 同一问题并行跑多路，再融合

```bash
python main.py --parallel                                    # 每轮提问都并行
python main.py --parallel --parallel-providers local,deepseek-flash
# 对话中：
/parallel                       # 开关
/parallel deepseek-flash,deepseek-pro   # 指定组合
/parallel off
```

流程：**视觉识读（本地）∥ 各文本模型回答** 同时开跑 → 最后一路（默认云端）把
「识图结论 + 各路回答」**融合成一份最终答案**（冲突处以实际拓扑为准，并保留可粘贴的命令）。
总耗时可近似视为最慢那一路，而不是各路之和。也可单独使用：

```bash
python -m core.parallel "这个拓扑有什么风险" --image topo.png --providers local,deepseek
python -m core.parallel "对比两家的 ACL 写法" --strategy cascade --no-synth
```

### 健壮性设计

- **能力裁剪**：不支持的参数不下发（思考模式不发 `temperature`；不支持的模型不塞 `tools` 并显式提示）
- **自动降级**：服务端 400 拒绝 `stream_options` / `temperature` 时，去掉该参数重试并记住
- **端点回退**：`/chat/completions` 与 `/v1/chat/completions` 自动择一（命中后缓存）
- **单路隔离**：并行时某一路失败（密钥错、欠费、限流）只影响该路，其余照常返回
- **可读报错**：401 鉴权 / 402 余额 / 429 限流 / 404 端点 / 连接失败，都会给出中文原因与修复建议
- **不吞密钥**：密钥只从环境变量或配置文件读取，不写入日志与审计记录

自检命令：

```bash
python -m core.providers                 # 列出提供方与配置状态（不联网）
python -m core.providers --check         # 探测可用性（本地探端口、云端验证密钥）
python -m core.llm_client --provider deepseek --ask "你好"   # 单模型连通性自检
python -m core.llm_client --all --ask "1+1=?"                # 所有已配置提供方各问一次
```

## 桌面应用（PyQt6 GUI）

命令行版的所有能力都有界面版（`python launcher.py` 或 `python -m gui.app`）：

- **三种模式**：agent / rag / parallel（多模态并行，本地识图 ∥ DeepSeek 融合）随时切换；
- **模型提供方**：本地 llama-server / DeepSeek Flash（多模态）/ DeepSeek Pro（深度推理），
  可在设置里换密钥并探测连通性；
- **图片附件**：拖拽或选择拓扑截图，不看图的云端模型自动走「本地识图桥接」；
- **流式上屏**：思考过程与正文分栏实时渲染，带 token 统计（QThread + 信号，不卡界面）；
- **斜杠命令控制台**：`/tools`（看工具）、`/call 工具名 {json}`（手动调用）、`/audit`（看命令审计）、
  `/vision`、`/rebuild`（重建索引）、`/providers`、`/services` 等，与命令行习惯一致；
- **会话侧边栏**：新建/重命名/删除/导出 Markdown，自动保存（`data/sessions.json`）；
- **主题**：深色 / 浅色，QSettings 记住偏好。

异常兜底：任何槽函数异常不再静默杀进程，全栈写 `logs/gui_error.log` 并显示到运行日志页签。

## 打包为 exe（PyInstaller）

```powershell
.\build_exe.ps1          # 产物：dist\NetworkClaw\NetworkClaw.exe（目录形态，推荐）
```

- exe 具有三种身份：双击 = GUI；`--cli` = 命令行；`--serve-mcp <标识>` = MCP 服务端子进程
  （打包后没有 Python 解释器，exe 复用自身拉起 4 个服务端）；
- 模型（`models/*.gguf`）与密钥（`.env`/`config/llm.json`）**不在包内**，放到 exe 同目录即可；
  首次运行会把内置的 `knowledge/`、`config/llm.example.json`、`docs/` 释放到 exe 旁边供编辑；
- 为什么默认目录形态而不是单文件：MCP 子进程要多次拉起 exe，单文件每次都要重新解压
  ~300MB，启动会慢到不可用。详见 `docs/packaging.md` 与 `NetworkClaw.spec` 头部注释。

发布（git 自动打包）：`.\tools\git_release.ps1 -Tag v1.0` —— 清理临时产物 → 构建 →
把源码与 `dist\NetworkClaw` 一起提交 → 打注释标签（配了远端加 `-Push` 即连推送）。
配套 `.githooks/pre-push` 会在推送标签时校验产物已入库，防止发出没有 exe 的版本。
exe 已入库（267MB），clone 即可运行；取舍与 LFS 建议见 `docs/packaging.md` 第七节。

## 对话入口（main.py）

```bash
python main.py                  # 默认 agent 模式：模型自主调用 MCP 工具
python main.py --mode rag       # 直接进入 RAG 问答
python main.py --provider deepseek   # 用 DeepSeek（云端，不启动本地服务）
python main.py --deepseek-key sk-xxx # 临时提供密钥（推荐写入 .env）
python main.py --parallel       # 每轮提问走多模型并行 + 融合
python main.py --mmproj         # 启用图像识别（自动探测 models/*mmproj*.gguf）
python main.py --mmproj D:\x\mmproj-BF16.gguf   # 显式指定视觉投影文件
python main.py --image topo.png # 启动时就带上一张拓扑图（可多次指定）
python main.py --with-search    # 额外接入联网搜索 MCP（需 npx + open-websearch）
python main.py --no-thinking    # 不打印模型思考过程
python main.py --max-rounds 6   # 放宽工具调用轮次上限（设备操作建议 4~6）
```

对话中可用命令：

| 命令 | 说明 |
|------|------|
| `/help` | 显示帮助 |
| `/model [名称]` | 查看/切换模型提供方（`local` / `deepseek` / `deepseek-reasoner`…） |
| `/key sk-xxx` | 临时设置 DeepSeek API Key（推荐写入 `.env`） |
| `/parallel [列表]` | 开关多模型并行；`/parallel local,deepseek` 指定组合；`/parallel off` 关闭 |
| `/tools` | 列出已接入的 MCP 工具 |
| `/call 工具名 {json}` | 直接调用某个 MCP 工具，不经模型 |
| `/image [路径]` | 附加一张拓扑图到后续提问；`/image clear` 取消 |
| `/vision` | 查看图像识别能力状态（是否已加载 mmproj、当前模型是否支持图片） |
| `/audit [n]` | 查看最近的设备命令审计记录 |
| `/agent` `/rag` | 切换 agent / rag 模式 |
| `/thinking` | 开关思考过程显示 |
| `/stream` | 开关流式打印（关闭后由主程序打印 `ask()` 的返回值） |
| `/last` | 重新显示最近一次回答 |
| `/save [路径]` | 导出本次会话为 Markdown（退出时也会自动保存） |

三种模式的分工：

- **agent 模式**：把 MCP 工具定义交给当前模型，由模型自己决定调用
  （命令模板检索 / 知识检索 / 串口 / Telnet / 图像识别，可扩展 `/search`），
  最多 `--max-rounds`（默认 4）轮工具调用后收口出答案；每次工具调用与结果都会打印。
- **rag 模式**：固定「知识库检索 + 流式生成」的单轮问答，行为与原版一致。
- **parallel 模式**：多模型并行 + 融合，不挂 MCP 工具（避免多路并发共享同一条 MCP 连接），
  需要工具时用 `/agent` 切回单模型。

## 设备操作与命令安全（核心）

智能体可以通过**串口**或 **Telnet** 连接设备执行命令，但所有命令都要先过
`core/command_guard.py` 的三级网关——模型理解偏差时，破坏性命令不会被真正下发：

| 等级 | 覆盖命令 | 行为 |
|------|----------|------|
| **允许** `allow` | `display` / `show` / `ping` / `tracert`（含 `dir` / `more` 等只读命令） | 直接执行 |
| **需确认** `confirm` | `sysname` / `vlan` / `interface` / `ip` / `ospf` / `acl` / `aaa` 等一切配置类命令；**未匹配任何规则的命令默认按此处理** | 工具拒执行，只返回风险说明；模型必须先把影响讲给用户，用户同意后带 `confirm=true` 重新调用 |
| **拦截** `block` | `undo` / `no` / `shutdown` / `delete` / `reset` / `reboot` / `reload` / `erase` / `save` / `write` 等 | 任何参数都拒绝执行，并提示"请人工在设备上操作" |

补充机制：

- **多命令整体裁决**：`display version ; reboot` 这类串联命令逐条判定，取最高风险等级后再统一裁决；
- **否定前缀识别**：Huawei `undo x` 与 Cisco `no x` 一律按高危处理；
- **审计留痕**：每次裁决写入 `logs/command_audit.log`（通道 / 目标 / 命令 / 等级 / 是否执行 / 原因），
  对话里用 `/audit` 或 `recent_audit` 工具查看；
- **连接参数必须由用户提供**：COM 口、IP、用户名、密码由用户给出，提示词明确禁止模型臆造；
  密码不写入审计日志；
- **自动关分页**：会话建立时自动下发 `screen-length 0 temporary` / `terminal length 0`
  等只读会话命令（下发前会用同一套网关自查，必须判定为 allow），避免长回显被 `---- More ----` 截断。

### 串口通道

```bash
# 对话中
可用串口有哪些？                       # 模型会调 list_serial_ports
用 COM3 看一下设备版本                 # 模型会调 exec_command(display version, port=COM3)
把 COM3 上这台设备改名为 SW-Core-01     # 配置命令：模型会先说明影响，你同意后再执行
```

### Telnet 通道

```bash
# 对话中（连接信息由你提供）
帮我 telnet 到 192.168.183.200，用户名 admin，密码 xxx，看看接口 IP 配置
```

或不经模型直接调用：

```bash
/call check_telnet {"host":"192.168.183.200"}
/call exec_telnet_command {"command":"display ip interface brief","host":"192.168.183.200","username":"admin","password":"xxx"}
```

## 图像识别（拓扑识读）

`--mmproj` 让 llama-server 额外加载视觉投影文件，模型即可读图。三种用法：

1. **启动时预载**：`python main.py --mmproj --image topo.png`
2. **对话中附加**：`/image D:\pics\topo.png`，之后每个问题都会带上这张图
3. **交给模型自主识图**：直接说"这是我当前的拓扑（图片路径：D:\pics\topo.png），帮我看看"，
   模型会调用 `analyze_topology_image` 工具

识图结果按固定结构输出：**拓扑概览 → 设备清单（名称/型号/角色/IP）→ 连接关系（接口对接口）
→ IP 与网段/VLAN → 风险点（单点故障、环路、IP 冲突）**，并要求模型对图中未标注的信息写
"图中未标注"而不是编造，便于后续据此生成配置。

- 图片会等比缩放到长边 1280px 再编码（`core/vision.py`），避免 base64 过长挤爆上下文；
- `/vision` 或 `vision_ready` 工具可自查能力是否就绪；
- 未找到 mmproj 时不会崩，只是识图工具返回带下载地址的提示
  （模型来源：`https://www.modelscope.cn/models/unsloth/Qwen3.5-9B-GGUF`）；

> 工具调用依赖 llama-server 的 `--jinja` 参数（已写入启动命令）。若复用的是别处启动的
> 旧实例（不带 `--jinja`），模型可能无法发起工具调用，此时可用
> `python -m core.llama_start kill` 清掉再重新启动。

### 自动拓扑巡检（启动时自动"看一眼"当前拓扑）

程序**默认在每次启动时**自动执行一次拓扑巡检（`core/screen_capture.py` +
`core/auto_topology.py`）：

1. 按内置关键字表（eNSP / VMware / VirtualBox / GNS3…）找到拓扑所在的窗口；
2. 用 Win32 `PrintWindow` 截取窗口画面（窗口被遮挡也能抓）——若大片区域是黑的
   （DirectX 渲染的虚拟机画面抓不到），自动降级为「窗口置前 + 屏幕抓取」并择优；
3. OpenCV 预处理：按客户区裁掉标题栏、去黑边、等比缩放，与上次截图做差分；
4. 交给本地多模态模型识读，结论落盘 `data/topology_snapshot.md`（JSON 同步一份），
   之后 agent / rag 的系统提示词会自动注入该快照——模型开局就知道当前拓扑；
5. 画面与上次一致时直接复用结论，不重复推理。

**知情与可控**：巡检执行前会在日志里明确播报（截哪个窗口、图存哪、怎么关）；
截图只存本机 `logs/captures/`（保留最近 20 张），识读全程在本地、不上传；
找不到目标窗口时跳过并列出可见窗口。关闭方式：`--no-auto-vision`（CLI/GUI 启动参数）、
GUI 设置页「启动时自动巡检拓扑」、对话中 `/autovision off`。手动触发：`/topology [关键字]`。
模型侧也可自主调用 `capture_topology`（实时重看）与 `get_topology_snapshot`（读快照）两个 MCP 工具。

## MCP 工具

默认接入 7 个服务端（stdio 传输），共 26 个工具：

> **一个工具一个文件**：工具实现在 `mcp_tools/tools/<工具名>.py`（文件名 = 函数名 = 工具名），
> `mcp_tools/*_server.py` 只做注册中心（建 `FastMCP` 实例 + `mcp.tool(fn)` 装配）。
> 好处：改一个工具只动一个文件；新增工具 = 新文件 + 注册中心加一行；
> 工具函数不带装饰器，可脱离 MCP 运行时被直接调用（测试/脚本）。
> `tools/_bootstrap.py`、`_archive.py`、`_manual_common.py` 是下划线开头的公共支撑，不是工具。

| 服务端 | 工具 | 参数 | 功能 |
|--------|------|------|------|
| `template_server.py`<br>（`Network-Knowledge`） | `query_command_template` | `intent`（必填）、`vendor`、`device_type`、`top` | 命令模板语义检索（语义匹配 + 厂商/设备类型元数据过滤） |
| | `search_knowledge` | `query`、`top` | 通用知识库检索（设备介绍、配置说明、实验文档；索引按指纹自动维护） |
| `device_server.py`<br>（`Network-Device-Serial`） | `list_serial_ports` | — | 列出本机可用串口 |
| | `classify_command` | `command` | 只做风险分级不执行（建议模型下发配置前先预检） |
| | `exec_command` | `command`、`port`、`baudrate`、`confirm`、`timeout` | 通过串口执行一条命令（过安全网关；**执行后自动归档命令历史**） |
| | `recent_audit` | `n` | 查看最近的命令审计记录 |
| `telnet_server.py`<br>（`Network-Device-Telnet`） | `check_telnet` | `host`、`port` | 探测 Telnet 端口连通性（只读，不下发命令） |
| | `exec_telnet_command` | `command`、`host`、`username`、`password`、`port`、`enable_password`、`confirm`、`timeout` | Telnet 登录并执行一条命令（过安全网关；**执行后自动归档命令历史**） |
| `manual_server.py`<br>（`Network-Device-Manual`） | `list_device_manuals` | — | 查看**当前对话**里哪些设备已建档、哪些还没有 |
| | `read_device_manual` | `device`、`session` | 读设备手册（常用配置 / 注意事项）；`session` 可显式跨对话只读 |
| | `create_device_manual` | `device`、`vendor`、`model`、`address`、`role`、`login`、`note`、`transport`、`host`、`port`、`serial_port` | 首次接触设备时建档（骨架自动生成；可顺带把设备名绑定到地址） |
| | `update_device_manual_section` | `device`、`section`、`text`、`mode`、`title` | 把有效命令序列 / 踩过的坑写回**当前对话**的手册 |
| | `recent_device_history` | `device`、`n`、`session` | 查看设备最近的命令历史（自动记录）；`session` 可跨对话只读 |
| | `list_session_skills` | — | 查看**所有对话**各自的设备技能分布（回答「上次那个会话」用） |
| `report_server.py`<br>（`Network-Data-Report`） | `export_workflow_report` | `session`、`format`、`days` | **导出整轮工作流报告**：汇总设备技能、逐条命令历史、逐步工具调用与回显、验收结论（md/json/both）；留空 session = 当前对话 |
| | `workflow_report_overview` | `session` | 只看统计摘要（不落盘）：设备数、手册数、命令/模型/工具调用次数 |
| | `list_report_sessions` | — | 列出可导出报告的会话（当前对话 + 其他对话） |
| `topology_server.py`<br>（`Network-Topology-Flood`） | `discover_topology` | `workers`、`timeout`、`roots`、`save`、`devices` | **泛洪发现拓扑**：逐台登录下发只读命令，解析 LLDP/MAC/ARP 推导连线与上下级，出 Mermaid 图 |
| | `load_discovered_topology` | — | 读取上次发现结果（不重新探测，秒回） |
| | `topology_summary` | — | 只要紧凑摘要（层级 + 链路 + 上下级），适合直接放进上下文 |
| | `topology_mermaid` | `direction` | 只要 Mermaid 图源码（贴文档即可渲染） |
| `vision_server.py`<br>（`Network-Vision`） | `vision_ready` | — | 检查识图能力（mmproj）是否就绪 |
| | `list_local_images` | `directory`、`limit` | 列出最近可用的图片，便于定位拓扑截图 |
| | `analyze_topology_image` | `image_path`、`question` | 识读拓扑图，输出设备/链路/IP/风险点结构化描述 |
| | `capture_topology` | `keyword`、`force` | 实时看拓扑：自动截取 eNSP/虚拟机窗口并识读（画面未变时复用结论） |
| | `get_topology_snapshot` | — | 读取最近一次自动巡检的拓扑结论（瞬时返回，不推理） |

> **设备手册是运行期资产，不在仓库里，且按对话隔离**：手册由本地模型在首次接触
> 设备时自建（`session/<会话标识>/skill/<设备名>/SKILL.md`），配置验证有效后由模型
> 自己沉淀回手册；命令历史由工具层确定性追加到同目录的 `history.jsonl`。
> 一个对话一套技能——对话之间互不共享，详见上文「一个对话一套技能」。
> `session/`、`data/device_access.json` 均已进 `.gitignore`。

## 工作流数据报告（跑完就导出）

**要解决的问题**：一轮实验/一次对话产生的信息散落在三处——会话技能目录（手册 + 命令历史）、
运行日志（逐轮 LLM 调用与工具调用）、实验报告（验收比对）。人工拼接既慢又容易漏，
复盘和造微调语料时尤其麻烦。

`report_server.py` 提供三个工具把这轮工作流汇总成**一份自包含报告**，本地模型跑完后
自己调用即可（提示词里已写明「跑完先 overview 再 export」）：

| 动作 | 产出 |
|---|---|
| `workflow_report_overview()` | 统计摘要（不落盘）：设备 / 手册 / 命令 / 模型调用 / 工具调用次数 |
| `export_workflow_report()` | 完整报告：总览 + 每台设备手册与命令序列 + 逐步工具调用（含设备回显，超长裁剪）+ 过程事件 + 实验报告全文 |
| `list_report_sessions()` | 可导出报告的会话清单（当前对话 + 其他对话） |

**默认只导当前对话**（与「一个对话一套技能」一致的隔离语义）；其他对话只报数量、不搬内容，
需要复盘别的对话时显式传 `session=`（只读，不会污染当前会话）。

```bash
python -m core.data_report                    # 导出当前会话（md）
python -m core.data_report --format both      # 同时出 Markdown + JSON
python -m core.data_report --session 01-xxx   # 导出指定会话
python -m core.data_report --list             # 列出所有会话
```

落盘：`data/data_reports/<时间戳>-<会话>.md` 与 `.json`（JSON 只存结构化数据与实验报告路径）。
批量实验（`tools/lab_run_agent.py`）在每个实验收尾时**确定性自动导出**一份，导出失败不影响实验。

## 拓扑泛洪发现（自动求出上下级关系与拓扑图）

**要解决的问题**：`data/device_inventory.json` 里的 `topology_notes` 是手写的，
设备一多、链路一改就过期，而且写错了没人发现。但设备自己其实"知道"邻居是谁——
LLDP 邻居表、MAC 地址表、ARP 表都是现成证据，只要逐台读出来就能把
「谁连着谁、谁是上级」从人工记录变成**实测事实**。

```bash
python -m core.topology_flood                    # 泛洪全部 Telnet 设备，打印报告 + Mermaid 图
python -m core.topology_flood --save             # 顺带落盘 data/topology_discovered.json
python -m core.topology_flood --roots R1         # 指定出口/核心当根
python -m core.topology_flood --from-snapshot    # 不重新探测，读上次结果
python -m core.topology_flood --mermaid-only     # 只出 Mermaid 源码
python -m core.topology_flood --format dot       # Graphviz DOT
python -m core.topology_flood --device SW1,SW2   # 只探这两台（调试）
```

**三级证据**（越靠前越可信）：

| 证据 | 命令 | 说明 |
|---|---|---|
| LLDP 邻居表 | `display lldp neighbor brief` | 最硬：直接给出「本端口 → 邻居设备名 + 邻居口」。需对端也开 LLDP 且已设 sysname |
| CDP（思科） | `show cdp neighbors detail` | 思科设备走这条；命令集按 `vendor` 自动切换 |
| MAC 地址表 | `display mac-address` | 兜底：两端共享同一 MAC 时推断直连，标为「推测」 |
| ARP 表 | `display arp` | 只用于标注三层邻居与网段，不产生连线 |

**上下级（层级）怎么定**：链路是无向的（谁连谁），但 LLDP 的**发现方向**有额外信息——
「A 看到 B、B 没看到 A」说明 A 是 B 的下行端。算法用无向图 BFS 生成**生成树**定层级，
父节点优先取「被指向方 / 已定级的根 / 度数大者」；生成树之外的边记为**冗余链路**
（真实的双上行、Eth-Trunk 双链路），记录下来但不参与层级计算，也不会死循环。
没有 LLDP 的孤立设备标为「孤立」，并给出「请确认已 `lldp enable`」的提示。

**安全性**：本功能只下发 `display` / `show` 开头的**只读**命令，全部命中
command_guard 的 `allow` 级，**不会修改任何设备配置**，因此模型可以自行调用而无需用户确认
（有回归测试 `test_all_flood_commands_are_readonly` 守住这条）。

**与图片识读的关系**：`get_topology_snapshot` / `capture_topology` 是"看图猜的"，
泛洪发现是"设备自己报的"。两者都会注入 prompt，提示词里明确要求
**冲突时以实测为准**，并说明差异。

`mcp_tools/client.py` 是客户端层：用当前解释器（.venv）以 stdio 拉起服务端、聚合工具清单、
按工具名路由调用，并可转成 OpenAI 风格工具定义交给模型；若多个服务端出现同名工具会显式告警
（避免调用被路由到错误的服务端）。

自检：

```bash
python -m mcp_tools.client           # 连接全部服务端，列出工具并实际调用检索工具
python -m mcp_tools.search_client    # 单独测试联网搜索服务
```

注册到外部 MCP 客户端（如 WorkBuddy 的 `~/.workbuddy/mcp.json`）：

```json
{
  "mcpServers": {
    "network-knowledge": {
      "command": "D:\\anyworkspace\\python\\Agent-Rag-MCP-startup\\.venv\\Scripts\\python.exe",
      "args": ["D:\\anyworkspace\\python\\Agent-Rag-MCP-startup\\mcp_tools\\template_server.py"]
    },
    "network-device-serial": {
      "command": "D:\\anyworkspace\\python\\Agent-Rag-MCP-startup\\.venv\\Scripts\\python.exe",
      "args": ["D:\\anyworkspace\\python\\Agent-Rag-MCP-startup\\mcp_tools\\device_server.py"]
    },
    "network-device-telnet": {
      "command": "D:\\anyworkspace\\python\\Agent-Rag-MCP-startup\\.venv\\Scripts\\python.exe",
      "args": ["D:\\anyworkspace\\python\\Agent-Rag-MCP-startup\\mcp_tools\\telnet_server.py"]
    },
    "network-vision": {
      "command": "D:\\anyworkspace\\python\\Agent-Rag-MCP-startup\\.venv\\Scripts\\python.exe",
      "args": ["D:\\anyworkspace\\python\\Agent-Rag-MCP-startup\\mcp_tools\\vision_server.py"]
    }
  }
}
```

> 串口 / Telnet / 视觉这三个服务端是独立进程，也可以被别的 Agent 直接复用；
> 但视觉服务端依赖主程序先把 llama-server 以 `--mmproj` 拉起。

## 向量库：集合隔离与索引维护

- **集合名集中注册**在 `core/ollama_interface.py`：`KNOWLEDGE_COLLECTION = "huawei_devices"`（知识库）、
  `TEMPLATE_COLLECTION = "command_templates"`（命令模板）。其他模块不再自行硬编码集合名。
- **不持有长生命周期集合句柄**：各模块通过 `get_collection(名字)` 现取现用，避免某模块重建集合
  后，另一个模块手里的旧句柄指向已删除对象。
- **索引指纹独立**：`data/index_state.json` 按集合名分别记录「内容指纹 + 条数 + 构建时间」，
  两个集合互不影响。数据源一变（改 CSV、改知识文档）指纹即变化，下次启动自动重建；
  一致则跳过，可放心在每次启动时调用。
- **重建前预检 Embedding 服务**：重建是「先删后建」，若 Ollama 不可用会导致旧索引被清空，
  因此 `check_embedder()` 会在删除前先探测，失败时抛出带处理建议的错误而不破坏现有索引。
- 手动重建：`python -m core.template_search --rebuild`、`python -m core.rag --rebuild`。

## 知识库的可信度与可用性（不让模型"假装查过"）

模型最大的失败模式不是不会，而是**不知道自己的依据不可靠**。为此知识库链路做了两件事：

**一、分级前缀。** 四个索引来源（设备介绍 / 实验文档 / 运行报告 / 逐轮运行日志，
清单以 `core/rag.py:load_chunks()` 为准）在入索引前各加一个前缀，
把"现行规则"和"上次踩的坑"分开：

| 分级 | 前缀 |
|---|---|
| 规则 | `【现行规则｜可据此直接作答】` |
| 历史 | `【历史记录｜仅供参考，与规则冲突时以规则为准】` |
| 实例 | `【实例数据｜事实描述，不含操作建议】` |

**二、检索状态。** `retrieve_ex()` 返回 `RetrievalResult(chunks, status, reason)`，
明确区分「确实没有」和「链路坏了」：

| status | 含义 | 降级 | 模型行为 |
|---|---|---|---|
| `ok` | 正常命中 | 否 | 直接依据作答 |
| `empty` | 集合为空（未建索引） | 否 | 提示需先重建 |
| `no_match` | 检索通了但无相关内容 | 否 | 如实说没找到，可凭通用知识回答但需标注 |
| `unavailable` | Ollama / 集合不可用 | **是** | prompt 内注入降级告警 |
| `embed_failed` | query 向量化失败 | **是** | prompt 内注入降级告警 |

降级时不仅终端打 `[降级]`，更关键的是**把告警写进 prompt 正文**：
「本轮没有可用的知识片段……不要声称查过知识库」。Agent 模式下 `search_knowledge`
工具也返回「⚠ 知识库检索不可用……**这不是「知识库中没有相关内容」，而是检索链路故障**」，
并附带修复命令。**逐轮运行日志**（第四个来源）只取最近 3 天的会话摘要——
去重后的配置类命令 + 报错回显，刻意剔除 `display`/`ping` 这类只读命令，
避免它们挤占检索名额。

**不是索引来源的两样东西**：`knowledge/topology/*.json`（有 `TOPOLOGY_DIR` 常量但
**未纳入索引**，改用 `tools/kb_consistency.py` 与实验文档互校防漂移）、
`knowledge/device_profiles.py`（型号基线画像，用于**设备建档预填**，不进向量库）。

## 设备手册的冷启动（型号画像）

`session/<会话>/skill/<设备名>/SKILL.md` 是模型运行期自建的，但新设备第一次建档时是空白的。
`knowledge/device_profiles.py` 提供 10 个型号的通用基线（AR2220 / AR2200 / AR1200 /
S5700 / S3700 / S6700 / S7700 / S12700 / NE40E / USG），`device_manual.skeleton()`
在建档时把它预填进「注意事项」。例如 S5700 会自动写入：

- 端口 **1 基编号**：`GE0/0/1` 起（与路由器的 0 基相反）
- 改接口类型前若已有 trunk/hybrid 配置，需先 `undo port link-type`
- S5700-LI 不支持 `ip routing`，要三层功能必须 EI 版本
- Trunk 口记得 `port trunk allow-pass vlan`

画像匹配用**最长键优先**（`S5700-28C-HI` 会命中 `S5700` 而不是 `S37`），
未匹配到型号时**不写占位文字**而是退回通用提示。注意：画像是通用事实，
**具体以真机回显为准**——预填文本里也这样标注。

## 一个对话一套技能（设备记忆按会话隔离）

**需求**：一个对话一个 skill，不把所有对话的设备记忆统一在一起。
存放格式由用户指定：`session/<每个独立会话>/skill/<每个设备技能>/`。

```
session/
├── .current                          # 当前会话指针（一行 sid）
├── cli-20261014-152000-ab12/         # 一次 CLI 对话（每次启动现开一个）
│   └── skill/
│       ├── SW1/SKILL.md              # 该对话里 SW1 的手册
│       ├── SW1/history.jsonl         # 该对话里 SW1 的命令流水
│       └── R1/SKILL.md
├── <GUI 会话 uuid>/skill/...         # 桌面端每个会话一套
└── legacy-global/                    # 旧版全局 skills/ 的一次性迁移落点
```

### 为什么这么改

最早的版本把所有对话的手册统一放在 `skills/<设备名>/SKILL.md`。结果是对话 A 里
给 SW1 踩的坑、写下的命令序列，会在对话 B 检索知识库时被原样捞出来——模型把
**另一段对话里的结论**当成本对话的经验，改错了还查不出原因。

### 三个关键设计

1. **「当前会话」跨进程一致**。主程序（CLI / GUI / 批量实验）开出一个对话时调
   `session_skills.use_session(sid)`：把 sid 写进 `session/.current`，并同步
   `core.run_log` 的会话标识（运行日志与技能同会话、同命运）。MCP 服务端是
   **独立子进程**，每次工具调用前读这个指针文件（按 mtime 缓存），所以 GUI 里
   切换会话后无需重连，工具立刻跟随新会话。解析优先级：
   本进程钉过的 sid > `session/.current` > 环境变量 `NETWORKCLAW_SESSION` > `default`。
2. **手册不进向量库，改为直注提示词**。手册已按会话隔离，而索引是全局单份——
   塞进去会出现两个问题：切换会话后旧会话的手册仍会被检索出来（正好破坏隔离）；
   每次切换都重建索引又是「先删后建」，期间检索会拿到空库。因此当前会话的技能
   摘要（设备/型号/角色/最新踩的坑）由 `core/agent.py` 直注系统提示词，
   全文按需走 `read_device_manual`。运行日志摘要同理只取当前会话。
3. **隔离是读、写、检索三层一起做的**，不是只换个目录。测试
   `tests/test_session_skills.py` 逐项断言：A 对话的技能 B 看不到、切回来还在、
   B 里给同名设备建档不污染 A、RAG 不索引手册、日志摘要不跨会话。

### 用法

```bash
python -m core.device_manual --current          # 当前会话与技能目录
python -m core.device_manual --sessions         # 所有对话各自的设备技能
python -m core.device_manual --migrate-legacy   # 旧版 skills/ 搬进一个会话（一次性）
# 对话里：
/sessions                                        # CLI 内置命令，查看各对话技能分布
```

模型侧新增工具 `list_session_skills`（所有对话的技能分布总览）；
`read_device_manual(device, session="<sid>")` 与 `recent_device_history(..., session=...)`
支持**显式跨会话只读**——用户明确问「上次那个会话里」时才用，日常只看当前对话。

> 旧版全局目录 `skills/` 与 `data/device_history/` 已停止读取；本项目已完成迁移并清理旧目录
> （历史内容在 `session/legacy-global/`：6 份手册 + 6 台设备共 346 条命令历史，删除前另有 zip 备份）。
> `--migrate-legacy` 保留给仍持有旧副本的场景，源目录不存在时自动跳过。

## 命令审计日志的轮转

`logs/command_audit.log` 原来只追加、无上限，长期运行会无限增长；
`audit_tail()` 也要读完整文件再取末尾 n 行。现在：

- 超过阈值自动轮转：`command_audit.log` → `.log.1` → `.log.2` …
- 阈值与保留份数可用环境变量覆盖：`NETWORKCLAW_AUDIT_MAX_BYTES`（默认 5 MiB）、
  `NETWORKCLAW_AUDIT_BACKUPS`（默认 5；设为 0 表示直接截断不留备份）
- `audit_tail(n)` 跨当前文件与备份回读，用 8 KB 反向块扫描，不再整读

## 持续集成

`.github/workflows/ci.yml` 在 push / PR 时跑（Python 3.12 与 3.13 矩阵）：
`py_compile` 全量语法检查 → `kb_consistency.py --json`（数据缺失时降级为跳过）→
`pytest` 全量 → `core.command_guard` 分级自检。
CI 故意只装**测试所需**的轻量依赖，不装完整 `requirements.txt`。

## 常用命令

```bash
python main.py                      # 一键启动：LLM 服务（单实例）+ 知识库 + 4 个 MCP 服务端
python launcher.py                  # 打开桌面应用（GUI）；--cli 进命令行，--serve-mcp 内部用
python -m tools.gui_smoke_test      # GUI 离屏冒烟测试
.\build_exe.ps1                     # 打包为 exe（产物 dist\NetworkClaw\NetworkClaw.exe）
.\tools\git_release.ps1 -Tag v1.1   # 打包 + 提交产物 + 打标签（git 自动打包）
python main.py --provider deepseek  # 用云端模型（跳过本地 llama-server）
python main.py --parallel           # 多模型并行 + 融合
python main.py --mmproj             # 额外启用图像识别（自动探测 mmproj）
python -m core.providers            # 列出模型提供方与配置状态（--check 探测可用性）
python -m core.llm_client --all --ask "1+1=?"   # 各提供方连通性自检（验证密钥）
python -m core.parallel "问题" --image topo.png --providers local,deepseek   # 多模态并行编排
python -m core.rag                  # 仅 RAG 问答（需 llama-server 已在运行）
python -m core.rag --rebuild        # 强制重建知识库索引
python tools/kb_consistency.py      # 校验实验文档与拓扑数据集是否一致（退出码 1 = 漂移）
python -m pytest                    # 全量离线测试（含知识库一致性回归）
python -m pytest tests/test_rag.py  # 只跑知识库链路（来源/分级/检索状态）
python -m pytest tests/test_session_skills.py   # 只跑「一个对话一套技能」隔离语义
python -m core.device_manual --sessions         # 所有对话各自的设备技能分布
python -m core.template_search "禁止telnet登录" --device-type router   # 模板语义检索
python -m core.template_search --rebuild                              # 强制重建模板索引
python -m core.topology_flood       # 泛洪发现拓扑：自动推导上下级关系并出 Mermaid 图
python -m core.topology_flood --save # 同上，并把结果落盘（下次 --from-snapshot 秒读）
python -m core.llama_start          # 单独管理 llama-server
python -m core.llama_start mmproj   # 查看 mmproj 探测结果与当前实例的视觉状态
python -m core.llama_start kill     # 强制清理所有残留的 llama-server.exe
python -m core.command_guard        # 自检：打印各类命令的分级结果
python -m mcp_tools.client          # MCP 客户端自检
python tools/manual_extractor.py manual.txt --vendor Huawei           # 阶段三：手册粗提取
```

## 多实例问题的修复说明

此前每次运行 `main.py` 都会无条件拉起一个新的 llama-server，且健康检查失败时
子进程可能不被回收，导致多个 llama-server.exe 同时占用数 GB 内存/显存。现在：

1. **启动前端口探测**：8080 端口已有健康实例时直接复用，不再重复启动；
2. **失败必回收**：健康检查改为最长 120 秒的重试循环，期间任何异常都会终止
   并清理刚拉起的子进程；
3. **退出只关自己的**：复用的外部实例不会被误杀；
4. **一键清理**：`python -m core.llama_start kill` 可清掉历史残留进程。

## 流式输出与 token 统计

`core/llm_client.stream_chat()` 统一负责流式调用（RAG 与 Agent 共用，支持任意提供方）：

- **实时思考过程**：优先读取 `delta.reasoning_content` 字段（DeepSeek 思考模式 / llama.cpp `--jinja`
  均走这里）；若思考内容以 `<think>...</think>` 内嵌在正文中（Qwen 系列常见），也能实时拆分显示
  （兼容标签被拆散在多个 chunk 的情况）；
- **实时回答**：回答正文逐 token 打印（`show_answer=False` 时只收集不打印）；
- **token 统计**：优先使用服务端 `usage.completion_tokens`，否则按输出块数近似，
  每次回答结束打印 `[提供方/模型 ｜ 输出 token 数：N ｜ 思考 x ＋ 回答 y]`；
- **中文不乱码**：流式响应头常为 `text/event-stream` 且不带 charset，requests 会按
  ISO-8859-1 解码导致中文全乱码，因此改为按字节读取后显式 UTF-8 解码；
- `ask(query, show_thinking=False)` 可关闭思考过程显示；
  `ask(query, stream=False)` 不在函数内打印回答，由调用方渲染返回值；
  `ask(query, provider="deepseek-flash")` 可指定本轮使用的提供方。

## 命令模板库（三阶段）

| 阶段 | 内容 | 状态 |
|------|------|------|
| 一 | `knowledge/command_templates.csv`：华为/H3C/Cisco 共 174 条模板（`device_type` 列取 switch/router/both）。交换机部分：基础配置（系统管理、VLAN、接口IP、静态路由、SSH、NTP）；路由器部分：OSPF 单区域、BGP/ISIS 联动与静态/默认路由引入、AAA/RADIUS、ACL | ✅ 完成 |
| 二 | `core/template_search.py`：nomic-embed-text 向量化入 Chroma（集合 `command_templates`），意图语义匹配 + 厂商/设备类型元数据过滤 | ✅ 完成 |
| 三 | `docs/phase3_extraction_plan.md` + `tools/manual_extractor.py`：手册自动提取方案与脚手架（含 device_type 启发式推断） | 📋 方案就绪，待积累到几百条后启动 |

### 等保2.0 合规规则集

`knowledge/compliance/dengbao_rules/` 把等级保护测评项落成可执行的配置检查规则（56 条，详见
[docs/dengbao_rules.md](docs/dengbao_rules.md)）：

- **一条规则一个 YAML**，`check.type` 只有五种（`config_contains` / `config_absent` /
  `config_regex` / `config_value_compare` / `manual_confirm`）
- `severity` 由权重表推导（1→high、0.7→medium、0.4→low），不允许手填
- **每条 remediation 命令必须能在 `command_templates.csv` 或测评表原文找到出处** ——
  生成器内置出处核对，编造命令直接拒绝产出
- 配置文本判不了的条目写 `manual_confirm` 并注明缺什么证据，不用「建议加强」这类空话

```bash
D:/python/python.exe tools/build_dengbao_rules.py      # 重新生成（需 openpyxl）
python -m pytest tests/test_dengbao_rules.py           # 契约/行为测试（原文读 JSON，不读 xlsx）
```

### 维护约定

`command_templates.csv` 是唯一数据源（utf-8-sig，可直接用 Excel 编辑）：

- `device_type` 取值仅限 `switch` / `router` / `both`（两类设备都适用的标 `both`），
  后续拆分交换机/路由器两张表时直接按该列筛选；
- 改完 CSV 后运行一次 `python -m core.template_search --rebuild` 同步向量库
  （只重建模板集合，不影响知识库集合）；
- `python tools/manual_extractor.py manual.txt --vendor Huawei` 会按命令关键词
  自动推断 `device_type`（推断不出则留空），候选先落到 `review_queue.csv`，
  人工复核后并入主表；`--device-type switch|router|both` 可强制指定。
