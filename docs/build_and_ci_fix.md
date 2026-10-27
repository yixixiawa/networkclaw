# 远程仓库无法构建：根因与修复

> 记录日期：2026-10-27　复现方式：`git clone --depth 1` 到干净目录，按
> `.github/workflows/ci.yml` 的步骤逐步执行（Python 3.13，**不装 PyQt6、不装 ollama**，
> 与 CI 的依赖清单完全一致）。

## 一、结论速览

CI 里 `python -m pytest` 这一步**在 collection 阶段就中断**（退出码 2），
所以「远程构建」必然是红的。中断背后是 **6 个互相独立的问题**，任何一个都足以单独让它失败。

| # | 根因 | 位置 | 现象 | 状态 |
|---|---|---|---|---|
| 1 | 用了 `Path` 注解但从未导入 | `core/command_guard.py:311,363` | Python 3.12/3.13 上 `import` 即 `NameError: name 'Path' is not defined` | ✅ 已修 |
| 2 | 正式依赖被当成临时脚本忽略 | `.gitignore:34` `tools/_*.py` 误伤 `tools/_verify_remediation_source.py` | clone 后模块不存在 → `tests/test_dengbao_rules.py` collection error | ✅ 已修 |
| 3 | 测试经由 GUI 模块间接依赖 PyQt6 | `tests/test_gui_stream_proxy.py:18` → `gui/main_window.py:25` | CI 不装 PyQt6 → `ModuleNotFoundError`，**整个 pytest 中断** | ✅ 已修 |
| 4 | 模块级实例化可选依赖 | `core/ollama_interface.py:63` | 缺 `ollama` 包时 `ValueError`，`core.rag` / `core.template_search` 无法 import | ✅ 已修 |
| 5 | 知识库数据被忽略 | `.gitignore:25` `knowledge/experiments/` | `tests/test_rag.py` 报「实验文档数据源为空」；`kb_consistency` 无数据可校验 | ✅ 已修 |
| 6 | 依赖版本号不存在 | `requirements.txt:24` `opencv-python-headless==5.0.0` | `pip install -r requirements.txt` 直接失败（PyPI 只有 `5.0.0.93`） | ✅ 已修 |

另有 4 项仓库卫生问题不影响 CI 通过，但会让 clone/构建体验很差，见第五节。

## 二、为什么本地一直是绿的

本地 `.venv` 是 **Python 3.14.3**，CI 是 **3.12 / 3.13**。两者差异掩盖了根因 1：

- Python 3.14 起（PEP 649/749）函数注解默认**惰性求值**，`def f(p: Path)` 在 3.14 上
  即使 `Path` 未定义也不会报错；3.12/3.13 会在**定义函数时立即求值**，直接 `NameError`。
- `core/command_guard.py` 既没有 `from pathlib import Path`，也没有
  `from __future__ import annotations`，所以只在 3.12/3.13 崩。

根因 2/3/5 则是因为**本地工作区有、仓库里没有**：被 gitignore 的文件在本地照常存在，
测试能跑；clone 到别处就消失。这类问题本地永远复现不出来，只能靠「干净克隆」验证。

## 三、逐个根因的修复

### 1. `core/command_guard.py` 缺少 `Path` 导入

```python
import re
from pathlib import Path        # ← 新增
from core.paths import BASE_DIR
```

`_rotate_if_needed(path: Path)` 与 `_tail_lines(path: Path, n)` 两处注解需要它。

### 2. `tools/_verify_remediation_source.py` 被误忽略

`.gitignore` 原本用 `tools/_*.py` 收纳临时诊断脚本，但这个文件是
`tools/build_dengbao_rules.py` 与 `tests/test_dengbao_rules.py` 都 import 的**正式依赖**
（源命令出处校验）。加例外：

```gitignore
tools/_*.py
!tools/_verify_remediation_source.py
```

### 3. StreamProxy 迁出 GUI（解除 PyQt6 硬依赖）

`StreamProxy` 只用到 `io`，与 Qt 毫无关系，却因为住在 `gui/main_window.py` 里，
让 `tests/test_gui_stream_proxy.py` 必须 `import PyQt6`。CI 为了控制体积故意不装 PyQt6。

- 新增 `core/stream_proxy.py`（类定义 + 原始注释完整搬迁）
- `gui/main_window.py` 改为 `from core.stream_proxy import StreamProxy`
- 测试改 `from core.stream_proxy import StreamProxy`

这样 GUI 行为不变，测试却能脱离 Qt 运行。**不采用** `pytest.importorskip("PyQt6")`——
那会让这个测试在 CI 上静默跳过，等于废掉对两个历史 bug 的保护。

### 4. `ollama_interface` 惰性化 embedding 函数

```python
_embedding_fn = None

def get_embedding_function():
    global _embedding_fn
    if _embedding_fn is None:
        _embedding_fn = BatchedOllamaEmbeddingFunction(url=OLLAMA_URL, model_name=EMBED_MODEL)
    return _embedding_fn
```

`get_collection()` / `check_embedder()` 改为调用它。`ollama` 是「检索时才需要」的外部
服务客户端，不该在模块 import 期就把离线单测拖死。

### 5. `knowledge/experiments/` 恢复入库

它是 `core/rag.py:load_chunks()` 的 rule 类来源、`tools/kb_consistency.py` 的校验对象、
`tests/test_rag.py` 断言「非空」的必备数据。**仅 477KB / 59 个 md**，原始二进制实验包
（`data/ensp_labs/`）仍然不进库。

### 6. `requirements.txt` 版本号

`opencv-python-headless==5.0.0` → `5.0.0.93`（与本地 `pip show` 一致）。
修完这条之后 `pip install --dry-run -r requirements.txt` 在 3.13 上返回 0。

### 附带：`tools/kb_consistency.py` 的假绿灯

`--json` 分支在数据缺失时直接落到 `sys.exit(1 if mismatched else 0)`，而 error 结果里
没有 `mismatched` 键 → 退出码 **0**，CI 的 `if [ $rc -eq 2 ]` 永远不触发。
现已改为「有 error 就 `sys.exit(2)`」，`--json` 模式也遵守，实测：

```
$ mv knowledge/topology{,.bak}; python tools/kb_consistency.py --json; echo $?
2
```

## 四、验证结果

| 检查项 | 修复前 | 修复后 |
|---|---|---|
| `py_compile`（全部模块，3.13） | rc=0 | rc=0 |
| `pytest`（3.13，无 PyQt6 / 无 ollama） | **collection error，rc=2，6 个 ERROR** | **rc=0，全部通过（7 skipped）** |
| `kb_consistency --json`（有数据） | 57 实验 / 0 不一致，rc=0 | 同左 |
| `kb_consistency --json`（无数据） | rc=0（假绿灯） | rc=2（CI 正确降级为 warning） |
| `pip install --dry-run -r requirements.txt`（3.13） | 失败（opencv 版本不存在） | rc=0 |
| `python -m core.command_guard` | — | rc=0 |

## 五、仍需你决定（未改动，涉及已提交历史）

### 1. `dist/` 被提交（270MB / 1236 文件）

仓库工作区 467MB，其中 `dist/NetworkClaw` 占 270MB；`.git` 已有 140MB。
后果不只是 clone 慢：`build_exe.ps1` 用 `--distpath dist --noconfirm`，
PyInstaller 会先 `rmtree` 掉 `dist/NetworkClaw`，于是**每次构建完 git status 都会出现
上千个 `deleted`**，很容易误提交。

建议（二选一）：

```bash
# A. 构建产物不入库，exe 走 GitHub Releases
git rm -r --cached dist
printf '\n# 打包产物：由 build_exe.ps1 生成，发布走 Releases\ndist/\n' >> .gitignore
```

```bash
# B. 只保留最终 exe（仍不推荐，二进制进 git 会持续膨胀历史）
git rm -r --cached dist/NetworkClaw/_internal
```
注意：`git rm --cached` 只改索引，历史里的 270MB 仍在。要真正瘦身需 `git filter-repo`
重写历史并强推，属破坏性操作，务必先备份。

### 2. 运行时产物入库

| 路径 | 体积 | 性质 |
|---|---|---|
| `data/Rag_data/`（含 `chroma.sqlite3` 15.5MB） | 50MB | 向量库，`python -m core.rag --rebuild` 可重建 |
| `data/index_state.json` | 小 | 索引状态，重建即生成 |
| `data/_backup_device_history_20261014.zip` | 30KB | 一次性备份 |
| `data/lab_answers/*.{efz,orig,model}` | — | 实验包二进制（62 个） |

建议加进 `.gitignore`（与既有约定一致：`data/Rag_data/**` 本来就在待补清单里）：

```gitignore
data/Rag_data/
data/index_state.json
```

### 3. `requirements.txt` 是 Windows-only 的全量 freeze

- 含 `pywin32==312`、`PyQt6==6.11.0`，**在 ubuntu 上装不了**，所以 CI 才手工列了子集；
- 也含 spec 明确 `excludes` 的 `llama-index` 全家、`kubernetes`、`onnxruntime`，安装体积虚高。

建议拆两个文件：`requirements.txt`（运行必需 + 平台标记）与 `requirements-dev.txt`
（测试/打包），至少给 CI 的注释补一句「本文件不适用于 Linux CI」。

### 4. `build_exe.ps1` 在 clone 后必然失败

第 13-14 行：

```powershell
$py = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { Write-Error "未找到虚拟环境解释器：$py（先运行 pip install pyinstaller）" }
```

`.venv` 不入库，所以新 clone 必须先建虚拟环境。这不是 bug，但 README/CI 里应明确
「构建前置：Python 3.14（打包产物为 cp314）+ `pip install -r requirements.txt`」，
否则会被当成「构建失败」。另外 CI 目前**只跑测试，没有 build job**，
exe 构建从未被自动化验证过。

## 六、本次改动文件清单

| 文件 | 改动 |
|---|---|
| `core/command_guard.py` | 补 `from pathlib import Path` |
| `core/stream_proxy.py` | **新增**，StreamProxy 迁入 |
| `gui/main_window.py` | 改为从 `core.stream_proxy` 导入，删除本地类定义与冗余 `import io` |
| `core/ollama_interface.py` | embedding 函数改惰性构造 `get_embedding_function()` |
| `tools/kb_consistency.py` | 数据缺失时（含 `--json`）统一 `exit(2)` |
| `tests/test_gui_stream_proxy.py` | 导入路径改为 `core.stream_proxy`，补迁移说明 |
| `.gitignore` | 加 `!tools/_verify_remediation_source.py`；放开 `knowledge/experiments/` |
| `requirements.txt` | `opencv-python-headless==5.0.0.93` |
