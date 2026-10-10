# NetworkClaw 启动流程与自动拓扑巡检说明

> 适用版本：v1.0.1 开发版（含 OpenCV 自动识图功能）。
> 本文描述从双击启动到「模型看清拓扑」的完整过程，供自行测试与排查使用。

---

## 1. 功能总览

| 能力 | 说明 |
|---|---|
| 窗口截图 | OpenCV + Win32 自动找到 eNSP / VMware 窗口并抓图，窗口被遮挡也能抓 |
| 自动巡检 | 每次启动自动「看一眼」当前拓扑，识读结论注入后续所有对话 |
| 透明可控 | 执行前明确告知截哪个窗口、图存哪、怎么关；三处开关随时可停 |
| 数据安全 | 截图只落本机 `logs/captures/`（保留最近 20 张），识读由本地多模态模型完成，不上传 |

---

## 2. CLI 启动流程（python main.py / exe）

完整链路按顺序执行，任何一步失败都有对应的降级提示，不会直接崩溃：

```
双击 exe（launcher.py）或 python main.py
        │
        ▼
① 提供方准备
   · 加载项目根 .env（load_env_file）
   · 读取 config/llm.json，注册模型提供方（load_providers）
   · 按 --provider / 上次选择设定当前模型
        │
        ▼
② 本地服务准备
   · 需要识图（--mmproj）或本地模型时，拉起 llama-server
     端口 8080，参数含 --jinja（工具调用必需）与 --mmproj（识图必需）
   · 复用已有实例时检查 /props 是否加载了 mmproj
   · 纯云端模式（DeepSeek 且无 --mmproj/--image）跳过启动，省内存
        │
        ▼
③ 知识库索引（build_index）
   · 指纹比对（data/index_state.json），内容没变直接复用
   · 失败仅告警：本次可对话，检索类工具返回错误说明
        │
        ▼
④ MCP 服务端连接（McpHub，stdio 传输，共 13 个工具）
   · knowledge / device(串口) / telnet / vision 四个服务端
   · --with-search 额外接入联网搜索
        │
        ▼
⑤ 自动拓扑巡检（本次新增，默认开启）
   · 打印 notice() 告知文本 → 截图 → 本地模型识读 → 快照落盘
   · 失败/跳过均打印原因，不阻塞对话
        │
        ▼
⑥ 进入对话循环（agent 模式带工具调用；/rag、/parallel 等可切换）
```

### 2.1 与自动巡检相关的启动参数

| 参数 | 作用 |
|---|---|
| `--mmproj [路径]` | 启用图像识别（留空自动探测 `models/mmproj-BF16.gguf`）；**自动巡检的前提** |
| `--no-auto-vision` | 本次启动不执行自动巡检 |
| `--capture-keyword <词>` | 自定义目标窗口关键字（默认内置 eNSP/VMware/VirtualBox/GNS3/QEMU 等） |
| `--image <路径>` | 预载拓扑截图（与自动巡检二选一即可） |
| `--mode agent\|rag` | 对话模式 |
| `--provider <名>` | 指定模型提供方（local / deepseek-flash / deepseek-pro） |

### 2.2 对话内命令

| 命令 | 作用 |
|---|---|
| `/topology` | 立即手动执行一次巡检（强制重新截图+识读，绕过防抖） |
| `/autovision on\|off` | 开/关巡检（持久化到会话设置） |
| `/vision` | 查看识图能力状态（mmproj 是否加载） |
| `/image <路径>\|clear` | 手动附加图片让模型看 |

---

## 3. GUI 启动流程

```
launcher.exe --gui（或 python launcher.py）
        │
        ▼
gui/app.py：读设置（config/gui_settings.json）→ 建 QApplication → 主窗口
        │
        ▼
gui/main_window.py：界面初始化，submit("boot") 到后台 Worker（QThread + asyncio）
        │
        ▼
gui/worker.py::_boot：
   ① 连接 MCP 服务端
   ② 按设置拉起本地服务（mmproj 开 → 带 --mmproj 启动）
   ③ 发 sig_ready（工具/服务/提供方状态刷新到界面）
   ④ 若设置「自动拓扑巡检」开启（默认开）→ 自动投递 auto_vision 任务
        │
        ▼
Worker 执行 auto_topology.auto_inspect() → sig_log 播报过程 → sig_topology
   把识读结论作为一条消息气泡呈现，用户全程可见
```

GUI 开关位置：**设置 → 运行环境 → 「启动时自动查看当前拓扑」**；另有「目标窗口关键字」输入框。
注意：mmproj 开关的变更在**下次启动**生效。

---

## 4. 自动拓扑巡检的完整过程（`core/auto_topology.py` + `core/screen_capture.py`）

### 4.1 第一步：告知（notice）

巡检开始前打印/播报：

```
[自动拓扑巡检] 已开启，即将自动执行一次：
  · 目标窗口：「Windows Server 2019 - VMware Workstation」
  · 截图只保存在本机 logs/captures/，不上传；识读由本地多模态模型完成
  · 识读结论会存到 data/topology_snapshot.md，供后续对话引用
  · 若窗口被遮挡，可能需要短暂把它切到前台（不影响窗口内容）
  · 关闭方式：启动时加 --no-auto-vision，或对话中 /autovision off（GUI 在设置里）
```

### 4.2 第二步：找窗口并截图（screen_capture）

1. **枚举可见窗口**，按关键字表匹配标题/类名（eNSP、VMware、VirtualBox、GNS3、QEMU、Packet Tracer、拓扑……），可用 `--capture-keyword` 追加；
2. **首选 PrintWindow**（`PW_RENDERFULLCONTENT`，经 ctypes 调 user32）：窗口被遮挡也能抓，不打扰操作；
3. **质量判定**：用 OpenCV 统计暗像素比例，若画面区大面积全黑（DirectX 渲染区抓不到，或屏幕刚从休眠唤醒尚未重绘），自动**降级**——`AttachThreadInput` 强制把窗口切到前台，再 `ImageGrab` 抓屏幕对应矩形；
4. **择优**：对两种结果做 Canny 边缘密度评分，取信息量更大的一张；
5. **预处理**：按客户区裁掉标题栏/边框 → `trim_uniform_border` 去黑边 → 长边限制内等比缩放；
6. **落盘**：`logs/captures/topology_YYYYMMDD_HHMMSS.png`，自动清理只留最近 20 张。

> 已内置 DPI 感知修正（`SetProcessDpiAwareness`），高缩放屏幕下抓屏区域不会错位。

### 4.3 第三步：防抖判断

与上次截图做高斯模糊+差分：
- 画面变化 < 0.2% 且快照仍在新鲜期（**12 小时**内）→ **跳过识图**，直接复用上次结论（省 10~40 秒推理）；
- `/topology` 命令带 `force=True`，跳过防抖强制重看。

### 4.4 第四步：本地模型识读

- 调 `core/vision.py`：图片编码为 JPEG data URI → 发给带 mmproj 的本地模型；
- 输出结构固定：**拓扑概览 / 设备清单 / 连接关系 / IP 与网段 / 风险点**；
- 未标注的信息必须写「图中未标注」，模型不得编造。

### 4.5 第五步：快照落盘与注入

| 产物 | 路径 |
|---|---|
| 结构化快照 | `data/topology_snapshot.json`（含时间戳、窗口名、识读结论） |
| 可读版 | `data/topology_snapshot.md`（自己打开就能看） |

此后每次对话（agent / rag 两条链路），`context_for_model()` 都会把快照结论（截断到 1500 字，仅 12 小时内的新鲜快照）注入系统提示词——**模型开局就知道当前拓扑，无需再描述**。

### 4.6 模型侧 MCP 工具（vision_server，共 13 个工具）

| 工具 | 用途 |
|---|---|
| `capture_topology` | 模型自己要求「再看一眼」当前拓扑（重新截图+识读） |
| `get_topology_snapshot` | 读上次巡检快照 |
| `vision_ready` / `list_local_images` / `analyze_topology_image` | 原有识图工具不变 |

---

## 5. 自行测试步骤（建议按序）

### 前置条件

1. eNSP 拓扑已在虚拟机里打开且**画面可见**（如截图所示 AR1-AR3、LSW1-LSW3 那种布局）；
2. Ollama 在跑（11434）且已 `ollama pull nomic-embed-text`；
3. `models/Qwen3.5-9B-Q4_K_M.gguf` 与 `models/mmproj-BF16.gguf` 就位（`python -m core.llama_start mmproj` 查状态）。

### 测试一：CLI 全链路

```powershell
.venv\Scripts\python.exe main.py --mmproj --mode agent
```

观察点：
- [ ] 启动时打印 notice 告知文本，目标窗口名正确；
- [ ] `logs/captures/` 出现新 png，打开看是不是你的拓扑画面；
- [ ] 巡检结束后 `data/topology_snapshot.md` 有结构化结论；
- [ ] 随后问一句「当前拓扑有哪些设备」——模型应直接答出，不再反问。

### 测试二：防抖

紧接着再启动一次（不改拓扑）：
- [ ] 应看到「画面未变化，复用上次结论」类日志，秒级完成而非重新识读。

### 测试三：强制重看

对话中输入 `/topology`：
- [ ] 应强制重新截图+识读（绕过防抖）。

### 测试四：开关

- [ ] `--no-auto-vision` 启动 → 不执行巡检；
- [ ] `/autovision off` → 本会话后续启动不巡检；
- [ ] GUI 设置页关闭开关 → 下次 GUI 启动不巡检。

### 测试五：GUI

```powershell
.venv\Scripts\python.exe launcher.py --gui
```

- [ ] 就绪后日志区播报巡检过程，对话区出现拓扑识读气泡；
- [ ] 设置 → 运行环境里能看到并修改「自动拓扑巡检」开关与关键字。

### 测试六：无窗口场景（优雅降级）

关掉 VMware / eNSP 再启动：
- [ ] 应打印「未找到目标窗口，跳过」之类提示，程序正常可用。

---

## 6. 常见问题排查

| 现象 | 原因与处理 |
|---|---|
| 抓到的图画面区全黑 | ① 屏幕刚从休眠唤醒、画面未重绘——动一下鼠标再 `/topology` 重试（正常使用不会出现）；② 虚拟机本身没显示桌面/锁屏——进虚拟机把 eNSP 摆出来。程序会在黑屏时自动降级为「置前+抓屏」，若仍黑说明是场景② |
| 「未找到目标窗口」 | eNSP/VMware 窗口没开，或标题不含关键字 → 用 `--capture-keyword` 加自定义词（GUI 在设置页填） |
| 巡检报「识图不可用」 | llama-server 没带 mmproj。`python -m core.llama_start kill` 后用 `--mmproj` 重启；或 `/vision` 查状态 |
| 模型不调用工具 | 复用了别处启动的旧 llama-server（缺 `--jinja`）→ kill 后让程序自己拉起 |
| 抓屏抓到了无关窗口 | 置前被系统拒绝时的保护逻辑是「宁可不抓」；若仍发生，把目标窗口手动放前台再 `/topology` |
| 本机 HTTP 请求 502 | 本地代理劫持回环——`core/net.py` 已把 127.0.0.1 加入 NO_PROXY，确认新代码没有绕过它 |
| 识读很慢 | 首次识读 10~40 秒属正常（9B 模型看图）；之后靠防抖复用，不再重复推理 |

---

## 7. 相关文件索引

| 文件 | 职责 |
|---|---|
| `core/screen_capture.py` | 窗口枚举、PrintWindow/抓屏、DPI 修正、预处理、落盘 |
| `core/auto_topology.py` | 告知、巡检编排、防抖、快照读写、上下文注入 |
| `core/device_registry.py` | 设备登记（种子清单 ∪ 访问记录）与并发在线探测 |
| `main.py` | CLI 入口：`--no-auto-vision` / `--capture-keyword`、`/topology`、`/autovision` |
| `gui/worker.py` | GUI 后台线程：`_boot` 完成后自动投递 auto_vision 任务；`device_probe` 探测任务 |
| `gui/main_window.py` | `sig_topology` 呈现识读结论气泡；设置页开关；「设备」页签 |
| `gui/dialogs.py` | 设置对话框：自动巡检开关、窗口关键字 |
| `mcp_tools/vision_server.py` | `capture_topology` / `get_topology_snapshot` 等 5 个视觉工具 |
| `data/topology_snapshot.{json,md}` | 巡检快照产物 |
| `data/device_inventory.json` | 人工维护的设备端口映射清单（种子） |
| `data/device_access.json` | 智能体访问过的设备登记（运行期自动生成） |
| `logs/captures/` | 截图产物（保留 20 张） |

---

## 8. 设备管理页签（SecureCRT 风格状态灯）

**位置**：主界面「设备」页签（对话页右侧）。

- **清单来源**：`data/device_inventory.json` 的 6 台种子设备 + 智能体实际访问过的设备
  ——Telnet（`check_telnet` / `exec_telnet_command`）或串口（`exec_command`）工具
  **连接成功即自动登记**到 `data/device_access.json`，临时给过 IP 的新设备也会出现；
- **状态灯**：绿点 ● = 在线（TCP 可达 / 串口在枚举列表），灰点 ● = 离线；
  表格列：状态 / 设备 / 型号 / 地址 / 通道 / 最后访问 / 说明（失败原因）；
- **刷新**：就绪后自动探测一轮，此后默认 30 秒一轮（可切 10/30/60 秒或关闭，或点「刷新状态」）；
  探测为**只读**（TCP connect + 串口枚举），绝不下发命令，整轮并发执行；
- **自测要点**：开着 eNSP 虚拟机时 R1-SW3 应亮绿灯；关掉虚拟机后半分钟内变灰；
  在对话里让模型 `check_telnet` 一台清单外设备，该设备会自动出现在表格里。

---

## 9. 设备手册：由本地模型在运行期自建（不进仓库）

**设计原则**：设备手册不是代码仓库里的固定资产，而是模型「遇到哪台设备、就为它建一份档」
的本机资产。所有内容都来自本地模型经工具链采集/沉淀，仓库里只保留生成它的能力。

| 产物 | 位置 | 谁写 |
|---|---|---|
| 设备手册 | `skills/<设备名>/SKILL.md` | **本地模型**（通过 `create_device_manual` / `update_device_manual_section`） |
| 命令历史 | `data/device_history/<设备名>.jsonl` | **工具层自动**（每次 `exec_telnet_command` / `exec_command` 后追加，确定性） |
| 设备访问登记 | `data/device_access.json` | 工具层自动（连接成功即登记，含名字绑定） |

**模型侧工具（`manual_server.py`，`Network-Device-Manual`）**：
`list_device_manuals` / `read_device_manual` / `create_device_manual` /
`update_device_manual_section` / `recent_device_history`

**系统提示词里的作业规范（`core/agent.py`）**：先读手册 → 后动手 → 再沉淀：
① 先 `list_device_manuals` 看有没有该设备手册，没有就 `create_device_manual` 建档
（设备名按型号命名：交换机型 `SW<n>`、AR 系列 `R<n>`，并传 transport/host/port 绑定地址）；
② 动手前 `read_device_manual` 读「常用配置」「注意事项」；
③ 验证有效后用 `update_device_manual_section` 把命令序列与坑写回手册；
④ 命令历史由工具自动写，模型不得手工造。

**手册会自动进知识库**：`core/rag.py` 的 `load_chunks()` 除 `knowledge/` 外，
还会把所有 `skills/*/SKILL.md` 切块索引（按指纹自动触发重建），
因此 RAG 模式检索时模型也能「熟悉」自己积累的设备知识。

**不进 git**：`skills/`、`data/device_history/`、`data/device_access.json` 已加入 `.gitignore`；
发布脚本 `tools/git_release.ps1` 的白名单里也不含这些路径。

> **2026-09-28 起手册从零开始**：先前由 agent 预写的 6 份设备手册已清空（备份在
> `logs/manual_backup_20260928/`），此后手册完全由模型在对话中自建。
> 已实测验证：对话里给出设备信息 → 模型调用 `create_device_manual` 生成
> `skills/<设备名>/SKILL.md` → 另一轮对话模型 `read_device_manual` 读回并准确识别该设备。
>
> **上下文长度**：agent 模式（系统提示词 + 18 个工具 schema 约 4.6K tokens + 多轮工具回显）
> 需要 16K 上下文，llama-server 启动参数已从 `-c 4096` 提到 `-c 16384`
> （KV cache 仍为 q4_0 量化，显存增量有限；显存紧张可用 `NETWORKCLAW_CTX=8192` 调低）。

**自测要点**：
- 首次对某台新设备说「给这台设备配 XXX」→ 观察日志里模型是否先调 `list_device_manuals`、
  再 `create_device_manual`（`skills/` 下应出现新目录）；
- 命令执行成功后，模型是否用 `update_device_manual_section` 沉淀；
- `data/device_history/<设备名>.jsonl` 应随每条命令自动增长（含被拦截的命令，`executed=false`）；
- 重启程序后问「SW1 之前配过什么」→ 模型应先 `read_device_manual` 再回答。
