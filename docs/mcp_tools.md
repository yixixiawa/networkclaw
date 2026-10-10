# MCP 工具清单（22 个）

由 `mcp_tools/` 各服务端经 `@mcp.tool` 暴露，客户端 `mcp_tools/client.py`（McpHub）
负责装配与按名路由（**两个服务端不得定义同名工具**）。工具签名从源码 AST 提取，
更新方式：改完服务端后重跑本文件末尾的生成命令。

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

| 工具 | 签名 | 用途 |
|---|---|---|
| `list_device_manuals` | `()` | 列出设备建档情况（手册是否存在/更新时间） |
| `read_device_manual` | `(device)` | 读某台设备的操作手册 |
| `create_device_manual` | `(device, vendor='', model='', address='', role='', login='', note='', transport='', host='', port=0, serial_port='')` | 首次建档（生成手册骨架） |
| `update_device_manual_section` | `(device, section, text, mode='append', title='')` | 写入手册指定小节 |
| `recent_device_history` | `(device, n=10)` | 某设备最近命令历史（自动记录） |

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

```bash
python - <<'PY'
import ast, pathlib
for f in sorted(pathlib.Path('mcp_tools').glob('*.py')):
    if f.name in ('__init__.py','client.py','search_client.py'): continue
    for n in ast.walk(ast.parse(f.read_text(encoding='utf-8'))):
        if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and any(
                ast.unparse(d).startswith('mcp.tool') for d in n.decorator_list):
            print(f"{f.stem}|{n.name}|({ast.unparse(n.args)})|{(ast.get_docstring(n) or '').strip().splitlines()[0]}")
PY
```
