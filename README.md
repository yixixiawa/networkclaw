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
│   ├── template_server.py       # MCP 服务端：query_command_template + search_knowledge
│   ├── device_server.py         # MCP 服务端：串口设备操作（list_serial_ports/classify_command/exec_command/recent_audit）
│   ├── telnet_server.py         # MCP 服务端：Telnet 设备操作（check_telnet/exec_telnet_command）
│   ├── vision_server.py         # MCP 服务端：图像识别（vision_ready/list_local_images/analyze_topology_image）
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
├── knowledge/                   # 知识库源文档
│   ├── huawei_devices_introduce.txt   # 华为设备知识文本（RAG 数据源）
│   ├── command_templates.csv    # 三厂商命令模板表（阶段一，手工维护，唯一数据源）
│   └── review_queue.csv         # 阶段三人工审核队列（由脚手架生成）
│
├── tools/                       # 辅助工具
│   └── manual_extractor.py      # 阶段三脚手架：从官方手册粗提取命令候选
│
├── docs/                        # 项目文档
│   └── phase3_extraction_plan.md  # 阶段三：官方手册自动提取方案
│
├── data/                        # 持久化数据
│   ├── Rag_data/                # ChromaDB 向量库（含 knowledge / command_templates 两个集合）
│   ├── index_state.json         # 各集合的索引指纹（判断是否需要重建）
│   └── my_rag_db/               # 旧版向量库（疑似废弃，确认后可删除）
│
├── logs/                        # 运行日志与会话记录
│   ├── llama_server.log         # llama-server 运行日志
│   ├── command_audit.log        # 设备命令审计日志（每次裁决一条 JSON：通道/目标/命令/等级/是否执行）
│   ├── session_*.md             # 对话会话导出（启动时自动保存）
│   ├── gui_error.log            # GUI 运行期异常兜底日志
│   └── cli_output.log           # 打包后 --cli 模式的输出副本（窗口程序没有控制台）
│
└── requirements.txt             # Python 依赖清单
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
  ├── mcp_tools/client.py            # stdio 拉起 4 个服务端（知识 / 串口 / Telnet / 视觉）
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
| `deepseek` | 云端 | `deepseek-chat`（V3.2 非思考） | ✗ | ✓ | ✗ | `DEEPSEEK_API_KEY` |
| `deepseek-reasoner` | 云端 | `deepseek-reasoner`（V3.2 思考） | ✗ | ✓ | ✓ | 同上 |

> DeepSeek 走 OpenAI 兼容协议（`https://api.deepseek.com`），两者均已对应 V3.2、128K 上下文，
> **都支持 Tool Calls**；思考内容在 `reasoning_content` 字段。
> **注意：DeepSeek API 目前是纯文本，不接受图片输入** —— 这正是下面「多模态桥接 / 并行」存在的原因。

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
python main.py --provider deepseek     # 启动即用 DeepSeek
python main.py --provider local        # 用本地模型
# 对话中随时切换：
/model deepseek-reasoner               # 换成思考模式
```

云端模式下**不会启动本地 llama-server**（省下数 GB 内存）；切回 `/model local` 时会按需启动。

**2. 多模态桥接（自动）** —— 文本模型 + 本地视觉模型协作

开启图形后，如果当前提供方不看图而本轮带了图片，程序会先用本地多模态模型把图
**读成文字结论**，再连同你的问题一起交给 DeepSeek。拓扑图始终在本地解析、不外传，
文本推理则用云端模型。对话中会出现 `[多模态桥接]` 提示。

**3. 多模型并行（`/parallel`）** —— 同一问题并行跑多路，再融合

```bash
python main.py --parallel                                    # 每轮提问都并行
python main.py --parallel --parallel-providers local,deepseek
# 对话中：
/parallel                       # 开关
/parallel deepseek,deepseek-reasoner   # 指定组合
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
- **模型提供方**：本地 llama-server / DeepSeek / deepseek-reasoner，可在设置里换密钥并探测连通性；
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

## MCP 工具

默认接入 4 个服务端（stdio 传输），共 11 个工具：

| 服务端 | 工具 | 参数 | 功能 |
|--------|------|------|------|
| `template_server.py`<br>（`Network-Knowledge`） | `query_command_template` | `intent`（必填）、`vendor`、`device_type`、`top` | 命令模板语义检索（语义匹配 + 厂商/设备类型元数据过滤） |
| | `search_knowledge` | `query`、`top` | 通用知识库检索（设备介绍、配置说明；索引按指纹自动维护） |
| `device_server.py`<br>（`Network-Device-Serial`） | `list_serial_ports` | — | 列出本机可用串口 |
| | `classify_command` | `command` | 只做风险分级不执行（建议模型下发配置前先预检） |
| | `exec_command` | `command`、`port`、`baudrate`、`confirm`、`timeout` | 通过串口执行一条命令（过安全网关） |
| | `recent_audit` | `n` | 查看最近的命令审计记录 |
| `telnet_server.py`<br>（`Network-Device-Telnet`） | `check_telnet` | `host`、`port` | 探测 Telnet 端口连通性（只读，不下发命令） |
| | `exec_telnet_command` | `command`、`host`、`username`、`password`、`port`、`enable_password`、`confirm`、`timeout` | Telnet 登录并执行一条命令（过安全网关） |
| `vision_server.py`<br>（`Network-Vision`） | `vision_ready` | — | 检查识图能力（mmproj）是否就绪 |
| | `list_local_images` | `directory`、`limit` | 列出最近可用的图片，便于定位拓扑截图 |
| | `analyze_topology_image` | `image_path`、`question` | 识读拓扑图，输出设备/链路/IP/风险点结构化描述 |

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
python -m core.template_search "禁止telnet登录" --device-type router   # 模板语义检索
python -m core.template_search --rebuild                              # 强制重建模板索引
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
  `ask(query, provider="deepseek")` 可指定本轮使用的提供方。

## 命令模板库（三阶段）

| 阶段 | 内容 | 状态 |
|------|------|------|
| 一 | `knowledge/command_templates.csv`：华为/H3C/Cisco 共 174 条模板（`device_type` 列取 switch/router/both）。交换机部分：基础配置（系统管理、VLAN、接口IP、静态路由、SSH、NTP）；路由器部分：OSPF 单区域、BGP/ISIS 联动与静态/默认路由引入、AAA/RADIUS、ACL | ✅ 完成 |
| 二 | `core/template_search.py`：nomic-embed-text 向量化入 Chroma（集合 `command_templates`），意图语义匹配 + 厂商/设备类型元数据过滤 | ✅ 完成 |
| 三 | `docs/phase3_extraction_plan.md` + `tools/manual_extractor.py`：手册自动提取方案与脚手架（含 device_type 启发式推断） | 📋 方案就绪，待积累到几百条后启动 |

### 维护约定

`command_templates.csv` 是唯一数据源（utf-8-sig，可直接用 Excel 编辑）：

- `device_type` 取值仅限 `switch` / `router` / `both`（两类设备都适用的标 `both`），
  后续拆分交换机/路由器两张表时直接按该列筛选；
- 改完 CSV 后运行一次 `python -m core.template_search --rebuild` 同步向量库
  （只重建模板集合，不影响知识库集合）；
- `python tools/manual_extractor.py manual.txt --vendor Huawei` 会按命令关键词
  自动推断 `device_type`（推断不出则留空），候选先落到 `review_queue.csv`，
  人工复核后并入主表；`--device-type switch|router|both` 可强制指定。
