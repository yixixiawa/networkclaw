# NetworkClaw 打包指南（PyInstaller → exe）

> 一句话：`powershell -ExecutionPolicy Bypass -File .\build_exe.ps1`，
> 产物在 `dist\NetworkClaw\NetworkClaw.exe`，双击即用。

## 一、快速开始

```powershell
# 前置：虚拟环境里装好依赖（PyQt6 与 pyinstaller 已在 requirements.txt）
.venv\Scripts\python.exe -m pip install -r requirements.txt

# 打包（目录形态，推荐）
.\build_exe.ps1

# 打包（单文件形态，见下文「两种形态」）
.\build_exe.ps1 -OneFile
```

构建脚本会依次做四件事：

1. 重新生成图标（`tools/make_icon.py` → `assets/networkclaw.ico/.png`，改完图标源码重跑即可）；
2. 对 `launcher.py / main.py / core / mcp_tools / gui` 全量 `py_compile` 语法自检；
3. 调 PyInstaller 按 `NetworkClaw.spec` 构建；
4. 打印产物路径与体积。

## 二、两种形态怎么选

| | onedir（默认） | onefile（`-OneFile`） |
|---|---|---|
| 产物 | `dist\NetworkClaw\` 目录（内含 `NetworkClaw.exe`） | 单个 `dist\NetworkClaw.exe` |
| 首屏启动 | 秒开 | 每次启动解压 ~300MB，明显偏慢 |
| MCP 子进程 | 秒级拉起 | **每个子进程都要重新解压一遍**（4~5 个子进程，基本不可用） |
| 适合 | 日常使用 / 分发整个文件夹 | 极少数只需要“一个文件”的场景 |

**本项目默认且强烈建议 onedir。** 原因在 `NetworkClaw.spec` 头部注释里有详细说明：
主程序会把自身拉起 4~5 次来充当 MCP 服务端子进程，onefile 模式下这一开销会被放大。

## 三、打包后的程序结构（三种身份）

入口是 `launcher.py`，同一份 exe 按参数切换身份：

```
NetworkClaw.exe                        # 双击 → 桌面应用（GUI）
NetworkClaw.exe --cli [参数…]           # 等价 python main.py（输出同时写 logs\cli_output.log）
NetworkClaw.exe --serve-mcp <标识>      # 内部使用：GUI 主进程用它拉起 MCP 服务端子进程
```

`--serve-mcp` 的存在理由：打包后没有可用的 Python 解释器，无法再
`python mcp_tools/xxx.py` 拉起服务端；于是让 exe 复用自身。标识 → 模块的
映射只在 `mcp_tools/__init__.py` 注册一份，客户端与 launcher 都从这里取。

## 四、文件都去哪了（BASE_DIR vs RESOURCE_DIR）

| 位置 | 源码运行 | 打包运行 | 用途 |
|---|---|---|---|
| `BASE_DIR` | 项目根 | **exe 所在目录** | `models/`、`data/`、`logs/`、`config/llm.json`、`.env` |
| `RESOURCE_DIR` | 项目根 | 解包目录 `_internal/` | 内置的 `knowledge/`、`docs/`、`config/llm.example.json`、`README.md`、`assets/` |

首次运行时 `core/paths.ensure_user_data()` 会把内置种子资源**按需**释放到 exe
旁边（已存在的文件绝不覆盖，用户改动不会被升级抹掉）。因此拿到 exe 后目录里
会逐渐出现可直接编辑的 `knowledge/command_templates.csv` 等。

**不打包的内容（有意为之）：**

- `models/*.gguf`（模型 5.6GB + 0.9GB）——放在 exe 同目录的 `models/` 下即可；
- `config/llm.json` / `.env`（密钥）——只内置 `llm.example.json` 作模板；
- `data/`（向量索引、会话记录）——运行时生成。

## 五、spec 里的关键取舍（NetworkClaw.spec）

- **hiddenimports 必须列全 MCP 服务端模块**：`launcher.serve_mcp()` 用
  `runpy.run_module(动态字符串)` 拉起，PyInstaller 静态分析看不见，漏了就会出现
  “exe 能开界面但知识检索/串口/图像识别全部失效”。
- **排除清单都验证过**：chromadb 对 kubernetes/onnxruntime/nltk/tokenizers 等
  全是 try/except 惰性导入（开发环境用 `sys.modules[name]=None` 模拟 ImportError
  逐一验证过），本项目用 Ollama 嵌入、用不到默认嵌入函数，排除 onnxruntime 省 44MB。
- **`console=False`**：窗口程序；`--cli` 输出会落 `logs/cli_output.log`，
  MCP 子进程的 stdio 走父进程给的管道，`core/paths.ensure_standard_streams()`
  已兜底修复标准流为 None 的情况。
- **UPX 关闭**：收益有限且容易触发杀软误报。

## 六、打包后验证

```powershell
# 1) 离屏跑 GUI 冒烟（走打包产物，覆盖：窗口构建/MCP 连接/命令链路/流式生成）
$env:QT_QPA_PLATFORM = "offscreen"
dist\NetworkClaw\NetworkClaw.exe --gui   # 正常应能出现窗口；headless 下看 logs\gui_error.log

# 2) 验证 --serve-mcp 派发（应有 JSON-RPC 响应、退出码 0）
#    见 tools\mcp_probe.py 的源码模式等价逻辑

# 3) CLI 身份
dist\NetworkClaw\NetworkClaw.exe --cli --help
```

## 七、常见问题

- **双击闪退**：看 `logs\launcher_error.log`（launcher 启动期兜底会写全栈）或
  `logs\gui_error.log`（运行期异常兜底）。
- **杀软报毒/误删**：关闭 UPX（spec 已默认关）、给 exe 签名，或把整个目录加白名单。
- **PowerShell 脚本报「字符串缺少终止符」**：`.ps1` 必须带 UTF-8 BOM（PowerShell 5.1
  对无 BOM 文件按 ANSI 解析，中文注释会把语法搞坏）。`build_exe.ps1` 已带 BOM，
  若自行改动后重蹈，用编辑器「UTF-8 with BOM」保存。
- **找不到模型/llama-server**：把 `Qwen3.5-9B-Q4_K_M.gguf`、`mmproj-BF16.gguf` 放到
  exe 同目录 `models/`，`llama-server.exe` 放 exe 同目录或 `bin/`，或设环境变量
  `NETWORKCLAW_LLAMA_SERVER` 指路。
- **知识检索不可用**：本机需要 Ollama（127.0.0.1:11434）并已 `ollama pull nomic-embed-text`；
  检索不可用时问答会自动降级，不影响纯对话。
