# Agent-Rag-MCP-startup

NetworkClaw 前身项目：本地 LLM（llama.cpp + Qwen）+ ChromaDB RAG 知识库 + MCP 工具链。

## 目录结构与职责

```
Agent-Rag-MCP-startup/
├── main.py                      # 统一启动入口：llama-server → 知识库索引 → 连接 MCP → 对话
│                                #   agent 模式（模型自主调用 MCP 工具）/ rag 模式可随时切换
│
├── core/                        # 核心业务层
│   ├── llama_start.py           # LLM 服务管理：单实例启动（已有实例自动复用）/健康检查/停止；
│   │                            #   `python -m core.llama_start kill` 可一键清理残留进程
│   ├── llm_client.py            # LLM 客户端：统一端点与模型名、流式对话、思考过程拆分、
│   │                            #   工具调用（tools/tool_calls）解析与 token 统计
│   ├── ollama_interface.py      # Embedding 与向量库接口：Ollama embedding + ChromaDB
│   │                            #   集合名注册表 / 集合句柄工厂 / 索引指纹状态
│   ├── rag.py                   # RAG 流程：知识文档切分入库、检索、流式问答
│   ├── agent.py                 # Agent 流程：模型自主调用 MCP 工具的多轮循环
│   └── template_search.py       # 命令模板语义检索（阶段二）：意图匹配 + 厂商/设备类型过滤
│
├── mcp_tools/                   # MCP 工具层
│   ├── template_server.py       # MCP 服务端：query_command_template + search_knowledge
│   ├── internet.py              # MCP 服务端：封装 open-websearch 联网搜索工具
│   ├── client.py                # MCP 客户端层：stdio 拉起服务端、聚合工具、路由调用
│   └── search_client.py         # MCP 客户端测试脚本（联网搜索服务单独试跑用）
│
├── models/                      # 模型源文件（llama.cpp GGUF）
│   └── Qwen3.5-9B-Q4_K_M.gguf
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
│   └── session_*.md             # 对话会话导出（启动时自动保存）
│
└── requirements.txt             # Python 依赖清单
```

## 模块调用关系

```
main.py
  ├── core/llama_start.py            # 启动/停止 llama-server（Qwen3.5-9B，端口 8080）
  ├── core/rag.py                    # 知识库索引（幂等）；ask() 检索 + 流式问答
  │     ├── core/ollama_interface.py # Ollama embedding（nomic-embed-text，11434）+ ChromaDB
  │     └── core/llm_client.py       # 流式调用 llama-server
  ├── core/agent.py                  # 工具调用循环 → mcp_tools/client.py → MCP 服务端
  │     └── core/llm_client.py       # 带 tools 的流式调用（--jinja 支持 tool_calls）
  └── mcp_tools/client.py            # stdio 拉起 mcp_tools/template_server.py 等
```

## 运行前提

1. `llama-server.exe` 路径已在 `core/llama_start.py` 中配置；模型文件默认取
   `models/Qwen3.5-9B-Q4_K_M.gguf`（相对项目根，换模型只需替换文件或改 `MODEL_PATH`）
2. Ollama 服务已启动，并已拉取 `nomic-embed-text` 模型（`ollama pull nomic-embed-text`）
3. 依赖已安装：`pip install -r requirements.txt`

## 对话入口（main.py）

```bash
python main.py                  # 默认 agent 模式：模型自主调用 MCP 工具
python main.py --mode rag       # 直接进入 RAG 问答
python main.py --with-search    # 额外接入联网搜索 MCP（需 npx + open-websearch）
python main.py --no-thinking    # 不打印模型思考过程
```

对话中可用命令：

| 命令 | 说明 |
|------|------|
| `/help` | 显示帮助 |
| `/tools` | 列出已接入的 MCP 工具 |
| `/call 工具名 {json}` | 直接调用某个 MCP 工具，不经模型 |
| `/agent` `/rag` | 切换 agent / rag 模式 |
| `/thinking` | 开关思考过程显示 |
| `/stream` | 开关流式打印（关闭后由主程序打印 `ask()` 的返回值） |
| `/last` | 重新显示最近一次回答 |
| `/save [路径]` | 导出本次会话为 Markdown（退出时也会自动保存） |

两种模式的分工：

- **agent 模式**：把 MCP 工具定义交给本地模型，由模型自己决定调用
  `query_command_template` / `search_knowledge`（可扩展 `/search`），
  最多 `--max-rounds`（默认 3）轮工具调用后收口出答案；每次工具调用与结果都会打印。
- **rag 模式**：固定「知识库检索 + 流式生成」的单轮问答，行为与原版一致。

> 工具调用依赖 llama-server 的 `--jinja` 参数（已写入启动命令）。若复用的是别处启动的
> 旧实例（不带 `--jinja`），模型可能无法发起工具调用，此时可用
> `python -m core.llama_start kill` 清掉再重新启动。

## MCP 工具

`mcp_tools/template_server.py` 把两类检索能力封装成两个独立 MCP 工具（stdio 传输，服务名 `Network-Knowledge`）：

| 工具 | 参数 | 功能 |
|------|------|------|
| `query_command_template` | `intent`（必填）、`vendor`、`device_type`、`top` | 命令模板语义检索（语义匹配 + 厂商/设备类型元数据过滤） |
| `search_knowledge` | `query`、`top` | 通用知识库检索（设备介绍、配置说明；索引按指纹自动维护） |

`mcp_tools/client.py` 是客户端层：用当前解释器（.venv）以 stdio 拉起服务端、聚合工具清单、
按工具名路由调用，并可转成 OpenAI 风格工具定义交给模型。

自检：

```bash
python -m mcp_tools.client           # 列出工具并实际调用两个检索工具
python -m mcp_tools.search_client    # 单独测试联网搜索服务
```

注册到外部 MCP 客户端（如 WorkBuddy 的 `~/.workbuddy/mcp.json`）：

```json
{
  "mcpServers": {
    "network-knowledge": {
      "command": "D:\\anyworkspace\\python\\Agent-Rag-MCP-startup\\.venv\\Scripts\\python.exe",
      "args": ["D:\\anyworkspace\\python\\Agent-Rag-MCP-startup\\mcp_tools\\template_server.py"]
    }
  }
}
```

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
python main.py                      # 一键启动：LLM 服务（单实例）+ 知识库 + MCP 工具
python -m core.rag                  # 仅 RAG 问答（需 llama-server 已在运行）
python -m core.rag --rebuild        # 强制重建知识库索引
python -m core.template_search "禁止telnet登录" --device-type router   # 模板语义检索
python -m core.template_search --rebuild                              # 强制重建模板索引
python -m core.llama_start          # 单独管理 llama-server
python -m core.llama_start kill     # 强制清理所有残留的 llama-server.exe
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

`core/llm_client.stream_chat()` 统一负责流式调用（RAG 与 Agent 共用）：

- **实时思考过程**：优先读取 `delta.reasoning_content` 字段；若思考内容以
  `<think>...</think>` 内嵌在正文中（Qwen 系列常见），也能实时拆分显示
  （兼容标签被拆散在多个 chunk 的情况）；
- **实时回答**：回答正文逐 token 打印（`show_answer=False` 时只收集不打印）；
- **token 统计**：优先使用服务端 `usage.completion_tokens`，否则按输出块数近似，
  每次回答结束打印 `[输出 token 数：N ｜ 思考 x ＋ 回答 y]`；
- `ask(query, show_thinking=False)` 可关闭思考过程显示；
  `ask(query, stream=False)` 不在函数内打印回答，由调用方渲染返回值。

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
