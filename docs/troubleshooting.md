# Troubleshooting —— 踩坑手册

所有条目都是实际踩过并验证过解法的坑（2026-09 ~ 2026-10）。
按类别组织；每条给出「症状 → 原因 → 解法」。

## 1. Python 环境

### 1.1 `ModuleNotFoundError: telnetlib`
- **症状**：3.14 的 venv 里 import telnetlib 直接失败。
- **原因**：PEP 594——`telnetlib` 自 Python 3.13 起从标准库移除。
- **解法**：项目用 socket 自实现了最小 Telnet 客户端（`core/device_conn.py` 的
  `TelnetSession`，含 IAC 协商拒绝逻辑），不依赖 telnetlib。venv 当前为
  **Python 3.14**（见 `.python-version`）。

### 1.2 Windows 上 `setsockopt` 报 WinError 10022
- **原因**：用了裸数字常量（如 `setsockopt(0xFFFF, ...)`）。
- **解法**：必须用 `socket.SOL_SOCKET` / `socket.SO_REUSEADDR` 等常量。

## 2. 网络与代理

### 2.1 本机 HTTP 请求 127.0.0.1 返回 502
- **症状**：requests/httpx 访问 localhost 的 llama-server/Ollama 得到 502/连接被拒。
- **原因**：本机代理（HTTP_PROXY 环境变量）**会劫持回环请求**。
- **解法**：`core/net.py` 的 `ensure_localhost_bypass()` 在 llama_start /
  ollama_interface 导入时把 `127.0.0.1, localhost, ::1` 写进 NO_PROXY。
  **新增任何本机 HTTP 调用前，确认该模块已被导入**。

### 2.2 真实端点连通性验证
- **技巧**：没有真密钥也能验证——用假密钥打真实端点，收到 **401 而非 404**
  即证明地址与鉴权链路正确。

## 3. llama-server / Ollama

### 3.1 工具调用静默失效
- **症状**：模型从不返回 tool_calls，日志无报错。
- **原因**：llama-server 启动没带 `--jinja`；或复用了别处启动的**旧实例**
  （旧实例没带 jinja/mmproj）。
- **解法**：`core/llama_start.py` 统一拉起（单实例复用 + 健康检查 + `kill` 清理）；
  复用外部实例时用 `server_vision_state()` 查 `/props` 确认 mmproj 状态。

### 3.2 Ollama 模型列表被清空 / 索引丢失
- **事实**：本机出现过两次 Ollama 模型列表被清空。
- **铁律**：**任何重建索引前必须先 `check_embedder()`**——Ollama 挂掉时
  严禁执行「先删后建」，否则旧索引白丢。索引指纹在 `data/index_state.json`。

### 3.3 向量库集合句柄失效
- **原因**：模块级持有 collection 句柄，集合重建后句柄失效。
- **解法**：一律 `get_collection(名字)` 现取现用；集合名只在
  `ollama_interface.py` 注册。

## 4. 命令行 / PowerShell / git

### 4.1 含中文的 .ps1 直接语法报错
- **原因**：PowerShell 5.1 对无 BOM 文件按 ANSI 解析。
- **解法**：含中文的 .ps1 **必须带 UTF-8 BOM**。

### 4.2 本机 bash shim 的 PATH 损坏
- **症状**：`ls`/`tail`/`grep` 找不到。
- **解法**：shell 操作优先用 PowerShell 或直接跑 python 脚本；验证脚本
  **写文件后用 Read 读**（stdout 也经常被吞）。

### 4.3 Edit 报告成功但内容没落盘
- **解法**：编辑后 grep 确认内容真的写入（本机出现过多次）。

### 4.4 git：`git add -f` 把该忽略的东西提交了
- **解法**：提交用**显式路径白名单**，且 `git add` 不加 `-f`
  （-f 会把 `dist/NetworkClaw/logs`、`data/sessions.json` 一起提交）。
- 相关：`.githooks/* eol=lf`（否则 sh 报 bad interpreter）；`dist/** -text -diff`。

### 4.5 沙箱删除保护卡住打包
- **症状**：PyInstaller COLLECT 阶段 `Removing dir ...` 后中断。
- **原因**：本机沙箱对成规模删除 fail-closed（回收站操作被中止）。
- **解法**：**重新打包前先删旧 `dist\NetworkClaw`**；并看日志的 EXIT 变量
  而不是外层退出码。

## 5. VMware / vmrun（来宾操作）

两条铁律（都实测踩过）：

1. `vmrun -interactive` 时 `-gu` **必须等于当前交互登录用户**；
2. **不带** `-gu/-gp` 直接报 "requires valid user name and password"。

其余要点：

- `runProgramInGuest ... cmd.exe` 一律返回 1 → 必须用 powershell.exe；
- vmrun 不回传来宾 stdout → 脚本写文件再 `copyFileFromGuestToHost`；
- 含空格/引号的 `-Command` 会被截断 → 用 `-EncodedCommand`；**但**经
  `cmd.exe` 中转的（SYSTEM 计划任务）**不能用** EncodedCommand（ASCII/OEM
  按 16 位 base64 拆开变乱码），要用 `-Command` + here-string；
- 稍长的 EncodedCommand 会报 `bora/lib/string/str.c:443 Buffer too small`
  → 拆批或改走文件；
- 拉起 GUI 程序必须 `-interactive`（否则进程在会话 0，窗口不可见）；
- 特权操作走「Administrator 凭据 + 不带 -interactive + SYSTEM 计划任务」
  （`tools/vm_sys.py`）；UAC 已关（ConsentPromptBehaviorAdmin=0）时 Medium
  进程 `Start-Process -Verb RunAs` 静默放行，但**别以为来宾进程就是 High IL**；
- `Start-Process` 在本会话报「已添加项:Path」→ 会话里同时有 Path/PATH 两键，
  用 `tools/spawn.py`（DETACHED_PROCESS + **CREATE_BREAKAWAY_FROM_JOB**，
  否则调度器 kill job 时批量任务被静默回收）。

## 6. eNSP 实验自动化

- **AR 端口开放 ≠ 设备可用**：eNSP 一启动就开 console 端口，AR2220 的 VRP
  还要几分钟；登录回显只有 `'##\x00'` = 未就绪，重试即可（整场 0 分不一定是
  模型的锅，先看日志里「超时：期望 N 个端口，实际 M 个」）。
- **`undo` 被拦**：实验模式（`set_experiment_mode(True)`）把 undo/no 降级为
  「需确认」——否则设备回 `Please renew the default configuration` 没法配。
- **`.topo` 是 GBK 双 XML 拼接**：`<topo>…</topo><paper>…</paper>`，直接
  ET.parse 报 junk after document element；解析见 `tools/topo_extract.py`。
- **`flash.efz` 是 eNSP 私有二进制**（魔数 `eNSP`），非 zip，暂无法解包。
- **换实验不用点 GUI**：`eNSP_Client.exe "<x>.topo"` 命令行直接打开拓扑。
- **VirtualBox 版本注册表**必须等于真实安装版本（5.1.24），被 HCL 改成 6.0.14
  就弹「VirtualBox version is not supported」；`[pathVBox]` 指向 VBox 安装目录，
  该 ini 是 ASCII、不要留 BOM。
- **eNSP 起设备前提**：来宾 `VirtualBox Host-Only Network` 存在且启用
  （192.168.56.1/24）；禁掉它所有设备都起不来。
- 「eNSP 帮助」窗口会盖住画布 → 关掉 hh.exe / ServerManager / notepad 再操作。
- **鼠标注入被冻结时一切 GUI 自动化作废**：判定方法 = 记事本对照实验
  （键盘能进、`Cursor.Position` 恒等屏幕中心即冻结）。详见技能
  `ensp-vm-gui-automation` 第 9 节。

## 7. HCL 共存问题

- HCL 会改 VBox 版本注册表（见 6）；两者同机时先恢复注册表再跑 eNSP。
- HCL 的 `SimwareWrapper` 默认占 TCP 16600 与 `lock.ini` 文件锁，
  新起实例报 LockFileEx 错误属预期（协议见 `tools/hcl_wrapper.py`）。
- 带空格路径传给 SimwareWrapper 协议会失败 → 用 8.3 短路径（`c:\progra~2\hcl`）。

## 8. 打包（PyInstaller）

- MCP 服务端模块必须写进 spec 的 **hiddenimports**（runpy 动态导入静态分析
  看不见）；excludes 改动前先用 `sys.modules[name]=None` 模拟 ImportError 验证。
- **默认 onedir**：onefile 下 MCP 服务端靠 `exe --serve-mcp <标识>` 复用自身
  拉起，单文件每次解压 ~300MB，不可接受。
- 验证：`python tools/exe_verify.py`（--serve-mcp 真实调用 + GUI 离屏存活 +
  种子释放检查）。
- 改文档不必重建 exe：直接覆盖 `_internal/README.md`、`_internal/docs/` 种子。
