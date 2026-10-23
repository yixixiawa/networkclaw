# MCP 工具清单（26 个）

由 `mcp_tools/` 各服务端经 `@mcp.tool` 暴露，客户端 `mcp_tools/client.py`（McpHub）
负责装配与按名路由（**两个服务端不得定义同名工具**）。工具签名从源码 AST 提取，
更新方式：改完工具后重跑本文件末尾的生成命令。

**工具名冲突怎么发现**：

- 运行期：装配时 `McpHub._load_tools()` 逐个服务端拉工具清单，一旦发现跨服务端同名，
  会打印 `[MCP] 警告：工具名冲突 <工具名>（<原属主> 与 <新属主>），调用将路由到 <后注册者>`
  —— 即**后注册者覆盖前者**，同名工具会被路由到错误的服务端。
- 静态防线：`tests/test_mcp_servers.py` 里
  `test_no_duplicate_tool_names_across_servers` 断言跨服务端无重名，
  `test_mcp_client_detects_duplicate_names` 断言 client 源码里确有重名检测逻辑。

## 目录结构：一个工具一个文件

| 层 | 位置 | 职责 |
|---|---|---|
| 服务端入口 | `mcp_tools/<名字>_server.py` | **只做注册中心**：`mcp = FastMCP(...)` + `mcp.tool(fn)` 装配。被 client 以 stdio 拉起。 |
| 工具实现 | `mcp_tools/tools/<工具名>.py` | 一个文件一个工具，文件名 = 函数名 = 工具名。带 docstring（就是给模型看的描述）。 |
| 公共支撑 | `mcp_tools/tools/_*.py` | 下划线开头，不是工具：`_bootstrap`（路径引导/截断）、`_archive`（命令历史归档）、`_manual_common`（会话位置/手册截断）。 |

**为什么工具文件不带 `@mcp.tool`**：装饰器绑定在 mcp 实例上，会让工具无法脱离
MCP 运行时被调用。现在由注册中心 `mcp.tool(fn)` 装配，工具函数就是普通函数，
单元测试可直接 `from mcp_tools.tools.exec_command import exec_command` 调用。

**新增一个工具的完整步骤**：
1. 新建 `mcp_tools/tools/<工具名>.py`，定义同名函数（首行 `from mcp_tools.tools import _bootstrap`）；
2. 在对应 `mcp_tools/<服务端>_server.py` 里 import 并 `mcp.tool(fn)`；
3. `NetworkClaw.spec` 的 hiddenimports 加 `mcp_tools.tools.<工具名>`（否则打包后该工具丢失）；
4. 更新本文档与本文件末尾的生成命令输出；跑 `pytest tests/test_mcp_servers.py`（会校验文件/函数名/装配一致性）。

## telnet_server（Telnet 通道）

| 工具 | 签名 | 用途 |
|---|---|---|
| `check_telnet` | `(host, port=23)` | 探测设备 Telnet 端口可达性（只读） |
| `exec_telnet_command` | `(command, host, username='', password='', port=23, enable_password='', confirm=False, timeout=20, disable_paging=True)` | Telnet 登录并执行一条命令 |

## device_server（串口通道）

| 工具 | 签名 | 用途 |
|---|---|---|
| `list_serial_ports` | `()` | 列出本机可用串口（执行前先确认端口号） |
| `classify_command` | `(command)` | 判断命令风险等级，**不执行** |
| `exec_command` | `(command, port, baudrate=9600, confirm=False, timeout=20, disable_paging=True)` | 串口（Console）执行一条命令 |
| `recent_audit` | `(n=10)` | 查看最近命令审计记录 |

## template_server（知识 + 命令模板）

| 工具 | 签名 | 用途 |
|---|---|---|
| `query_command_template` | `(intent, vendor='', device_type='', top=5)` | 按厂商/设备类型/意图检索命令模板（数据源 `knowledge/command_templates.csv`） |
| `search_knowledge` | `(query, top=3)` | 通用知识库检索（向量库 `huawei_devices` 集合） |

## manual_server（设备手册，运行期自建）

**一个对话一套技能**：手册与命令历史按会话隔离存放，布局由用户指定——

```
session/<会话标识>/skill/<设备名>/SKILL.md          手册
session/<会话标识>/skill/<设备名>/history.jsonl     命令历史
session/.current                                   当前会话指针
```

「当前会话」由主程序开对话时写入 `session/.current`（GUI 切换会话也会更新），
本服务端每次调用前读取，因此**切换会话无需重连**。其他对话的设备记忆不会
出现在这些工具里——这是刻意隔离。用户明确问「上次那个会话」时，才用
`list_session_skills` 拿会话标识，再以 `session=` 参数显式跨会话只读。

| 工具 | 签名 | 用途 |
|---|---|---|
| `list_device_manuals` | `()` | 列出**当前对话**的设备建档情况（手册是否存在/更新时间/历史条数） |
| `read_device_manual` | `(device, session='')` | 读某台设备的操作手册；`session` 非空时显式读**其他对话**的手册 |
| `create_device_manual` | `(device, vendor='', model='', address='', role='', login='', note='', transport='', host='', port=0, serial_port='')` | 首次建档（生成手册骨架；命中型号画像时预填「注意事项」基线） |
| `update_device_manual_section` | `(device, section, text, mode='append', title='')` | 写入**当前对话**手册的指定小节 |
| `recent_device_history` | `(device, n=10, session='')` | 某设备最近命令历史（自动记录）；`session` 非空时跨对话只读 |
| `list_session_skills` | `()` | 所有对话各自的设备技能分布（只读总览，回答「上次那个会话里」用） |

**手册为什么不进向量库**：按会话隔离后，塞进全局索引会出现两个问题——切换会话后
旧会话的手册仍会被检索出来（正好破坏隔离）；每次切换都重建索引又是「先删后建」，
期间检索会拿到空库。因此手册改为「当前会话摘要直注系统提示词 + 按需读全文」，
运行日志摘要同样只取当前会话。详见 `docs/knowledge_base.md`。

## report_server（工作流数据报告，跑完就导出）

把**一轮工作流**（会话 → 设备 → 逐轮调用 → 命令 → 验收）汇总成一份自包含报告。
数据来自三处只读源：会话技能目录（手册 + 命令历史）、运行日志（LLM/工具调用 + 事件）、
实验报告（`data/lab_reports/`）。默认只导**当前对话**，其他对话只报数量、不搬内容；
复盘别的对话时显式传 `session=`（只读，不改指针）。

| 工具 | 签名 | 用途 |
|---|---|---|
| `export_workflow_report` | `(session='', format='md', days=3)` | 导出完整报告：总览 + 每台设备手册与命令序列 + 逐步工具调用（含回显，超长裁剪）+ 过程事件 + 实验报告全文；`format` = md/json/both |
| `workflow_report_overview` | `(session='')` | 只出统计摘要（不落盘）：设备/手册/命令/模型调用/工具调用次数 |
| `list_report_sessions` | `()` | 列出可导出报告的会话（当前对话 + 其他对话） |

落盘：`data/data_reports/<时间戳>-<会话>.md` 与 `.json`（JSON 只存结构化数据 + 实验报告路径）。
CLI：`python -m core.data_report [--session ... --format ... --days ... --list]`。
批量实验（`tools/lab_run_agent.py`）每实验收尾**确定性自动导出**一次，失败不影响实验。

## topology_server（拓扑泛洪发现）

| 工具 | 签名 | 用途 |
|---|---|---|
| `discover_topology` | `(workers=4, timeout=25.0, roots='', save=True, devices='')` | 泛洪探测各设备（LLDP/CDP/MAC/ARP），推导连线与上下级并出 Mermaid 图 |
| `load_discovered_topology` | `()` | 读取上次发现结果（不重新探测） |
| `topology_summary` | `()` | 紧凑摘要（层级 + 链路 + 上下级），适合直接进上下文 |
| `topology_mermaid` | `(direction='TD')` | 只返回 Mermaid 图源码 |

**为什么是「泛洪」**：维护手写的 `topology_notes` 会过期，而设备自己知道邻居是谁。
逐台把 LLDP 邻居表 / MAC 地址表 / ARP 表读出来，就能把「谁连着谁、谁是上级」
从人工记录变成实测事实。

**只读保证**：这些工具只下发 `display` / `show` 开头的命令，全部命中
`command_guard` 的 `allow` 级，**不修改任何配置**，因此模型可自行调用无需用户确认
（回归测试 `tests/test_topology_flood.py::test_all_flood_commands_are_readonly` 守住）。

**与视觉识读的区别**：`vision_server` 的 `capture_topology` / `get_topology_snapshot`
是"看图猜的"；本服务端是"设备自己报的"。两者都会注入 prompt，
`core/agent.py` 明确要求**冲突时以实测为准**。

## vision_server（视觉）

| 工具 | 签名 | 用途 |
|---|---|---|
| `vision_ready` | `()` | 检查 llama-server 是否已加载 mmproj |
| `list_local_images` | `(directory='', limit=20)` | 列出可用图片 |
| `analyze_topology_image` | `(image_path, question='')` | 识读拓扑图：设备/连接/IP/风险点 |
| `capture_topology` | `(keyword='', force=False)` | 自动截取 eNSP/VMware 窗口并识读 |
| `get_topology_snapshot` | `()` | 读取最近一次巡检快照（瞬时返回） |

## internet（联网搜索）

| 工具 | 签名 | 用途 |
|---|---|---|
| `search` | `(query, limit=5)` | open-websearch 网络搜索 |

## 安全约定（与工具强相关，必读）

- 所有执行类工具走 `core/command_guard` 三级裁决：
  `allow`（display/show/ping 等只读）/ `confirm`（配置类，**未匹配即归此类**；
  须用户同意后带 `confirm=true` 重调）/ `block`（undo/no/shutdown/reset/save 等，硬拦）；
- 多命令（`;`/换行）按最高风险等级统一裁决；每次裁决写 `logs/command_audit.log`；
- 连接参数（IP/端口/账号密码）必须由用户提供，提示词禁止模型臆造；密码不落盘。

## 重新生成

工具实现在 `mcp_tools/tools/*.py`（不是服务端文件），所以从 tools/ 目录扫：

```bash
python - <<'PY'
import ast, pathlib
for f in sorted(pathlib.Path('mcp_tools/tools').glob('*.py')):
    if f.name.startswith('_'): continue          # 公共支撑，不是工具
    for n in ast.walk(ast.parse(f.read_text(encoding='utf-8'))):
        if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name == f.stem:
            print(f"{f.stem}|({ast.unparse(n.args)})|{(ast.get_docstring(n) or '').strip().splitlines()[0]}")
PY
```
