# Changelog

所有对外可见的变更记录在此文件。
格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
版本号遵循 [SemVer](https://semver.org/lang/zh-CN/)。

## [Unreleased]

### Added
- **等保2.0 合规规则集**（`knowledge/compliance/`）。把 GB/T 22239 测评项落成可执行的
  配置检查规则，并把「命令不许编造」做成生成期硬约束。
  - 56 条规则，覆盖四个指定范围：安全区域边界-访问控制（5）、安全区域边界-入侵防范（5）、
    安全计算环境-网络设备（23）、安全计算环境-安全设备（23）。**一条规则一个 YAML**，
    外加 `rules_index.json`（机器可读）与 `RULES_OVERVIEW.md`（人读总表）。
  - 字段固定：`id / vendor / device_type / category / control_point / requirement /
    weight_level / severity / source / check{type,target,expect,pattern} / remediation /
    evidence_hint`（另附 `weight_detail` 便于二级系统复用）。
  - `check.type` 只用五种：`config_contains / config_absent / config_regex /
    config_value_compare / manual_confirm`。实测分布：`config_regex` 15、`manual_confirm` 41。
  - `severity` **由权重表推导**（1→high、0.7→medium、0.4→low），不允许手填；
    测试 `test_severity_derived_from_weight` 守住。
  - `tools/build_dengbao_rules.py` 内置三道自检，任一不过即**拒绝产出**：
    ① `check.type` 越界 ② `manual_confirm` 的 `evidence_hint` 说不清缺什么证据
    ③ `remediation` 命令在资料中找不到出处。
  - `tools/_verify_remediation_source.py` 实现出处白名单：`csv-exact`（与
    `command_templates.csv` 逐字一致）/ `kb-line`（与测评表原文某行一致）/ `kb-substr` /
    `csv-shape`（骨架同构）/ `csv-sample`（差异位落在显式声明的样例值白名单）。
    做法是把命令折叠成「只保留关键字」的骨架再比对，因此 `local-user X password Y Z`
    能与模板同构，而 `totally-made-up-command xyz` 无法蒙混。
  - `manual_confirm` 占 41/56 是资料客观限制，不是保守：防火墙段（测评操作行48~70）
    的测评方法**全部走 WEB 界面**，一条 CLI 都没给；边界入侵防范要求「部署了 IPS、
    规则库为近期版本」属设备存在性 + 运维记录；另有 17 条资料原文即写「此项不适用」。
  - 资料本身的 OCR 错字（`exec-timcout`、`Iocal6`、`p http shutdown`、
    掩码粘连 `172.16.4.0.0.0.0.255`）**照原文收录**并在 `evidence_hint` 注明真机写法——
    修正后的写法在资料中找不到出处，会违反「命令必须有出处」。
  - 生成器同时导出 `dengbao_source_lines.json`（测评表原文逐行存档，641 行）。
    为什么要存档：项目 venv 无 `openpyxl`，测试直接读 xlsx 会 ImportError → 被 skip，
    而「命令不许编造」恰恰是最不能跳过的一条约束；存档是纯 JSON，任何环境可读。
  - `tests/test_dengbao_rules.py` 18 项：契约字段 / 五种 type / severity 推导 / source 带行号 /
    manual_confirm 可执行性 / 无模糊表述 / **命令出处逐条核对** / 规则可跑性（规范配置
    全 pass、裸奔配置全 fail、`permit ip any any` 必须被抓）/ 索引与文件一致性。
  - 修掉两个真实缺陷（由自测发现，非事后补写）：
    ① `DB-BND-AC-02` 原用 `config_absent` 判「无全通策略」，设备**根本没配 ACL** 时也会
       pass ——「未配置」被误判成「合规」。改为 `config_regex` + 负向先行断言，
       要求既有 ACL 定义、又不得含 any→any。
    ② 该负向断言最初写成 `(?im)^...(?![\\s\\S]*?^...)`，`^` 在 MULTILINE 下只匹配行首，
       跨行断言失效 → 含 `permit ip any any` 仍判 pass。改用 `(?is)(?=...)` 窗口式写法。
  - 测试 241 → 259 项。
- `docs/dengbao_rules.md`：规则集说明（字段契约、severity 推导、出处白名单算法、
  已知资料缺口与三处原表笔误的处理方式）。

### Changed
- **MCP 工具改为「一个工具一个文件」**。用户需求：「以单个作用点分离一个文件，
  文件命名以该工具的名称或者作用命名」。
  - 新增 `mcp_tools/tools/` 包：26 个 MCP 工具各自独立成文件，**文件名 = 函数名 = 工具名**
    （如 `tools/exec_telnet_command.py` 里的 `exec_telnet_command`）。
  - 7 个服务端文件（`template_server.py` / `device_server.py` / `telnet_server.py` /
    `manual_server.py` / `report_server.py` / `topology_server.py` / `vision_server.py`）
    **退化为纯注册中心**：只建 `FastMCP` 实例并 `mcp.tool(fn)` 装配，不再含业务逻辑。
    服务端标识、工具总数（26）、`mcp_tools/__init__.py#SERVERS` 映射全部不变。
  - 工具函数**不带 `@mcp.tool` 装饰器**。原因：装饰器绑定 mcp 实例会让工具无法脱离
    MCP 运行时被调用。现在由注册中心装配，工具就是普通函数，测试可直接 import 调用。
  - 新增 3 个下划线公共支撑（不是工具）：`tools/_bootstrap.py`（sys.path 引导、
    `truncate()` 回显截断、`relpath()`）、`tools/_archive.py`（命令历史归档，
    telnet/serial 两通道共用解析链）、`tools/_manual_common.py`（会话位置说明、手册截断）。
  - `NetworkClaw.spec` hiddenimports 补齐 26 个 `mcp_tools.tools.*` + 3 个公共支撑——
    **漏加会让打包后的 exe 丢失对应工具**（服务端是 runpy 拉起的，静态分析不可靠）。
  - 测试 `tests/test_mcp_servers.py` 重写（12 项结构断言）：工具文件与工具清单一一对应、
    文件名=函数名、docstring 非空、工具文件不自带装饰器、各服务端装配清单与文档一致、
    总数 26、跨服务端无重名、服务端文件不含实现细节（只扫代码，剥掉 docstring）。
    原 3 个失败项（断言 `def xxx(` 在服务端源码里 / `template_server.build_knowledge_index`）
    是测试依赖了旧的文件布局，改为从 `mcp_tools.tools.<工具名>` 导入。
  - 测试 229 → 241 项。

### Added
- **工作流数据报告（跑完就导出）**。用户需求：「多添加一个报告导出的环节，让本地模型
  跑完后输出整个工作流的内容，MCP 工具名为 data_report」。
  - `core/data_report.py`（新模块）：把一轮工作流（会话 → 设备 → 逐轮调用 → 命令 → 验收）
    汇总成一份自包含报告。数据来自三处只读源：会话技能目录（`session/<sid>/skill/<设备>/`
    的 `SKILL.md` + `history.jsonl`）、运行日志（`data/run_logs/<日期>/<sid>.jsonl` +
    `.events.jsonl`）、实验报告（`data/lab_reports/<NN-实验名>.md`）。
    出口 `collect()` / `render_markdown()` / `export()` / `summary_text()`，CLI 入口
    `python -m core.data_report [--session --days --format --list]`。
  - 落盘 `data/data_reports/<时间戳>-<会话>.md` 与 `.json`（JSON 只存结构化数据 + 实验报告
    路径，不重复塞全文）。Markdown 渲染经 `_join_blocks()` 规范化空行——直接把块列表
    `"\n".join` 会让标题/表格/代码块粘连，渲染会错乱。
  - **默认只导当前对话**（与「一个对话一套技能」一致的隔离语义）：其他对话只在「附：其他
    对话」小节报数量、不搬内容；复盘别的对话时显式传 `session=`（只读，不改当前指针）。
    设备目录采集跳过 `_` 开头的备份目录（如 `_misnamed_backup`），避免污染设备清单。
  - `mcp_tools/report_server.py`（新服务端 `Network-Data-Report`，3 个工具）：
    `export_workflow_report(session, format, days)`、`workflow_report_overview(session)`、
    `list_report_sessions()`；非法 `format` / 非法会话标识返回可读报错而非抛异常。
  - `core/agent.py` 系统提示词新增「数据报告类」工具说明与「数据报告工作流（跑完就导出）」
    一条：跑完后先 `workflow_report_overview` 再 `export_workflow_report`，把路径告诉用户；
    默认只覆盖当前对话，别中途或反复导出。
  - `tools/lab_run_agent.py`：每个实验收尾**确定性自动导出**一份（`data_report.export`），
    导出失败不影响实验；`data-report` 服务端**不挂给模型**，由 runner 触发，保证批量
    无人值守时一定有产物。`make_sid()` 清洗实验名（顿号/括号等非法字符 → `-`），避免
    `SessionError`（顿号不在 `safe_name` 白名单，但不放宽安全边界）。
  - 三处注册同步：`mcp_tools/__init__.py#SERVERS`、`client.DEFAULT_SERVERS`、
    `NetworkClaw.spec` hiddenimports（含 `core.data_report`）。
  - 测试新增 `tests/test_data_report.py`（23 项：采集完整 / 隔离语义 / 渲染质量与超长裁剪 /
    导出落盘 / CLI / MCP 三工具）。工具总数 23 → 26，服务端 6 → 7；测试 206 → 229。
- **一个对话一套技能（设备记忆按会话隔离）**。用户需求：「一个对话一个 skill，
  不将所有对话的设备记忆统一」，存放格式 `session/<每个独立会话>/skill/<每个设备技能>/`。
  - `core/session_skills.py`（新模块）：会话标识的生成/校验/解析，以及
    `session/<sid>/skill/<设备名>/SKILL.md` + `history.jsonl` 的路径工厂。
  - **「当前会话」如何跨进程一致**：主程序开对话时调 `use_session(sid)`，把 sid 写进
    `session/.current` 并同步 `core.run_log` 的会话标识（技能与运行日志同会话、同命运）。
    MCP 服务端是独立子进程，每次工具调用前读该指针（按 mtime 缓存），因此 **GUI 切换
    会话无需重连**。解析优先级：本进程钉住的 sid > `.current` > 环境变量
    `NETWORKCLAW_SESSION` > `default`。
  - `core/device_manual.py` 全部路径改为会话作用域；新增 `context_for_model()`
    （当前会话技能摘要，供提示词直注）、`sessions_overview()`、`migrate_legacy()`
    （旧版全局目录一次性迁移，含「只有历史没有手册」的设备）。
  - **隔离是读/写/检索三层一起做的**：手册**移出向量库索引**（塞进全局单份索引会在
    切换会话后串味，且每次重建都是「先删后建」、期间检索落空），改为当前会话摘要
    直注系统提示词 + 按需 `read_device_manual` 读全文；`_run_log_digests()` 同步改为
    **只取当前会话**（`data/run_logs/<当前会话>/*.jsonl`）。
  - MCP 工具：新增 `list_session_skills`（所有对话的技能分布总览）；
    `read_device_manual` / `recent_device_history` 增加 `session` 参数支持**显式跨会话
    只读**（用户明确问「上次那个会话」时才用）。
  - 入口接线：`main.py` 每次启动现开一个 `cli-<时间戳>-<随机>` 会话并新增 `/sessions`
    命令；`gui/main_window.py` 新建/切换会话时切作用域（且在 worker 启动前就钉住，
    避免索引构建读到默认会话）；`tools/lab_run_agent.py` 每个实验一个独立会话
    （跑批量实验时尤其重要——实验 A 踩的坑不会渗进实验 B）。
  - `.gitignore` 增补 `session/`；`skills/` 与 `data/device_history/` 停止读取、仅用于迁移。
    本项目历史内容（6 份手册 + 6 台设备 346 条命令历史）已迁移到 `session/legacy-global/`。
  - 测试新增 `tests/test_session_skills.py`（49 项：布局、命名安全含 Windows 保留名与
    路径穿越、隔离语义、指针文件与 env 兜底、迁移、下游接线）。
- `tests/conftest.py` 增加 autouse 夹具：把「会话技能根目录」与「运行日志根目录」隔离到
  临时目录——否则任何碰到手册的测试都会读写真实 `session/`、甚至覆盖真实 `.current` 指针。

### Changed
- **设备手册不再进向量库索引**：`core/rag.py` 移除 `_manual_texts()` 与 `SKILLS_DIR`，
  索引来源从五项回落为四项（设备介绍 / 实验文档 / 实验报告 / 当前会话运行日志摘要），
  知识库块数 2307 → 2128；`knowledge_sources()` 的描述同步更新。
- `core/agent.py` 系统提示词新增「设备技能的隔离规则」小节（明确「不要假设某台设备
  以前配过」「用户问别的会话时才显式跨会话读」），并注入 `_session_skill_context()`。
- `mcp_tools/client.py#_child_env()` 透传 `NETWORKCLAW_SESSION`（父进程派生时的兜底）。
- 测试从 157 项扩到 **206 项**。
- 旧版全局目录 `skills/` 与 `data/device_history/` 不再被读取（仅 `--migrate-legacy` 用）；
  本项目旧目录已清理（内容迁移到 `session/legacy-global/`，删除前有 zip 备份），
  `migrate_legacy()` 在源目录不存在时自动跳过。

### Fixed
- `mcp_tools/manual_server.py#recent_device_history` 跨会话读取时，位置说明写死成
  「当前会话」（`_where()` 漏传 `session`），用户会误以为读的是本对话的历史。已修，
  并有回归测试。
- `core/device_manual.py` 的 `append_history` / `tail_history` 只捕获 `ManualError`，
  而 `session_skills` 抛的是 `SessionError`——非法设备名会让异常逃逸到 MCP 框架，
  工具调用直接报错而不是返回可读文案。已在 `manual_path`/`history_path` 边界统一转换。
- `core/session_skills.py#safe_name` 未拒 Windows 保留设备名（`con`/`com1`/`lpt1`…），
  拿它当目录名会让 `mkdir` 失败且报错信息与「权限不足」极像。已在建目录前拒掉。
- `.workbuddy/skills/device-config-recorder`（项目自带技能文档）同步到新布局，
  其离线脚本 `append_history.py` 改为经 `core.device_manual` 写入，并支持
  `--session <会话>`；显式指定会话时**不**改全局 `.current` 指针。
- `mcp_tools/device_server.py` 与 `mcp_tools/telnet_server.py` 的 `_record()` 把命令
  历史的归档落点写死成 `data/device_history/<设备>.jsonl`——实际写入早已改走
  `session/<会话>/skill/<设备>/history.jsonl`，回显里「（已记入 …）」指引的是不存在的
  路径。已改为使用 `append_history()` 的真实返回值并转成项目内相对路径。

### Added
- **拓扑泛洪发现（新功能）**：`core/topology_flood.py` + `mcp_tools/topology_server.py`。
  逐台登录设备「泛洪」只读命令（`display lldp neighbor brief` / `display mac-address` /
  `display arp` / `display ip interface brief`，思科走 `show cdp neighbors detail`），
  解析邻居表与地址表，**自动推导链路与上下级关系**，输出文字报告 + Mermaid 图 + DOT + JSON。
  - 三级证据：LLDP（最硬，直接给「本端口→邻居设备+端口」）> CDP（思科）> MAC 表（兜底，标「推测」）；
    ARP 只用于标注三层邻居与网段，不产生连线。
  - **层级算法**：链路按无向图 BFS 生成生成树定层级；父节点优先取 LLDP 方向信息
    （「A 看到 B、B 没看到 A」⇒ A 是 B 的下行端）、已定级的根、度数大者。
    生成树之外的边记为**冗余链路**（双上行/Eth-Trunk 双链路），记录但不参与层级，也不会死循环。
    *（写这一版时踩过坑：LLDP 是双向的，若只按有向关系建有向图，两点会互相指向，
    从任一点 BFS 都会发现对方"已有层级"，于是永远建不出父子关系——必须用无向图做生成树。）*
  - 接口名归一化覆盖华为/思科各种写法（`GigabitEthernet0/0/1`/`GE0/0/1`/`Gi0/1` → `GE0/0/1`，
    `Eth-Trunk1`/`Bridge-Aggregation1`/`Port-channel1` → `ETH-TRUNK1`）。
    *（踩过坑：`Eth-Trunk` 会被 `Ethernet(Eth)` 规则先吃掉，匹配表顺序必须把聚合口排前面。）*
  - 设备名别名解析：LLDP 报的 `<sw2>` / 大小写差异能归回清单里的 `SW2`。
  - 结果可落盘 `data/topology_discovered.json`（已 gitignore），`--from-snapshot` 秒读复用。
  - **安全性**：只下发 `display`/`show` 开头的只读命令，全部命中 `command_guard` 的 `allow` 级，
    不改任何配置；有回归测试 `test_all_flood_commands_are_readonly` 守住这条。
  - CLI：`python -m core.topology_flood [--save] [--roots R1] [--from-snapshot]
    [--mermaid-only] [--format text|mermaid|dot|json] [--device SW1,SW2]`。
  - MCP 工具 4 个：`discover_topology` / `load_discovered_topology` /
    `topology_summary` / `topology_mermaid`。
- **实测拓扑注入 prompt**：`core/agent.py` 新增 `_flooded_topology_context()`，
  把泛洪发现的结果注入系统提示词，并明确标注「可信度高于图片识读，冲突时以本段为准」；
  提示词工作流第 3 条改为按可信度分级取用（实测 > 图片识读 > 用户口述）。
- 测试从 113 项扩到 **157 项**：新增 `tests/test_topology_flood.py`（44 项，
  覆盖三家格式的解析、层级推导、双链路、孤立设备、显式根、失败设备兜底、渲染、落盘、
  以及泛洪命令的只读性）。

### Changed
- MCP 服务端从 5 个增到 **6 个**、工具从 18 个增到 **22 个**；
  `mcp_tools/__init__.py` 的 `SERVERS` 与 `client.DEFAULT_SERVERS` 同步注册 `topology`，
  `NetworkClaw.spec` 的 hiddenimports 补 `mcp_tools.topology_server` 与 `core.topology_flood`。
- `.gitignore` 增补 `data/topology_discovered.json`（运行时重新探测即可复现，不入库）。

### Added
- **知识库第五个索引来源：逐轮运行日志**。`core/rag.py` 新增 `_run_log_digests()`，
  从 `data/run_logs/**/*.jsonl` 取**最近 3 天**的会话压成摘要（去重后的配置类命令 +
  最多 5 行报错回显；`display`/`show`/`ping`/`tracert`/`dir`/`more` 等只读命令刻意排除，
  免得挤占检索名额；纯只读会话注明「没有下发配置类命令」）。会话枚举复用
  `core.run_log.list_sessions()` / `read_session()`，不自行猜文件名。
  知识库块数 2115 → 2307（含 19 场会话摘要）。
- **知识块可信度分级**。每个块入索引前加前缀，把「现行规则」与「上次踩的坑」分开：
  `【现行规则｜可据此直接作答】`（实验文档、设备手册）、
  `【历史记录｜仅供参考，与规则冲突时以规则为准】`（运行报告、逐轮日志）、
  `【实例数据｜事实描述，不含操作建议】`（设备介绍）。
- **检索状态机 `RetrievalResult`**（`core/rag.py`）。`retrieve_ex()` 返回
  `(chunks, status, reason)`，用 `ok` / `empty` / `no_match` / `unavailable` /
  `embed_failed` 区分「知识库里确实没有」和「检索链路故障」。降级时把告警**写进 prompt 正文**
  （「本轮没有可用的知识片段……不要声称查过知识库」），`ask()` 另在终端打 `[降级]`；
  `mcp_tools/template_server.py#search_knowledge` 返回「⚠ 知识库检索不可用……
  **这不是「知识库中没有相关内容」，而是检索链路故障**」并附修复命令。
  `retrieve()` 保留为兼容包装，旧调用点不受影响。
- **设备型号画像**（`knowledge/device_profiles.py`）。10 个型号的通用基线
  （AR2220/AR2200/AR1200/S5700/S3700/S6700/S7700/S12700/NE40E/USG），
  最长键优先匹配；`core/device_manual.skeleton()` 建档时预填「注意事项」
  （如 S5700 的 1 基端口、`undo port link-type` 前置、LI/EI 差异、Trunk 放行 VLAN），
  未匹配型号退回通用提示而不写占位文字。画像不可用不会阻断建档（try/except 兜底）。
- **命令审计日志轮转**（`core/command_guard.py`）。超阈值自动
  `command_audit.log` → `.log.1` → …；阈值/份数可用
  `NETWORKCLAW_AUDIT_MAX_BYTES`（默认 5 MiB）/ `NETWORKCLAW_AUDIT_BACKUPS`（默认 5，
  设 0 为直接截断）覆盖；`audit_tail(n)` 改为 8 KB 反向块扫描并跨备份回读，不再整读文件。
- **CI**（`.github/workflows/ci.yml`）：push / PR / 手动触发，Python 3.12 与 3.13 矩阵，
  `py_compile` 全量 → `kb_consistency.py --json`（数据缺失降级为跳过）→ `pytest` →
  `core.command_guard` 自检；故意只装测试所需轻量依赖而非完整 `requirements.txt`。
- **`.env`**（进 `.gitignore`）：DeepSeek 密钥位 + VMware/eNSP 环境变量 +
  `NETWORKCLAW_RUNLOG` / `NETWORKCLAW_AUDIT_*` 开关说明，新用户可直接体验云端模型与多模态。
- **测试从 41 项扩到 113 项**：新增 `test_rag.py`(17)、`test_agent_loop.py`(8)、
  `test_mcp_servers.py`(6)、`test_template_search.py`(8)、`test_device_manual.py`(15)、
  `test_audit_rotation.py`(7)、`test_run_log.py`(9)。
  `pytest.ini` 加 `asyncio_mode = auto`（工具循环测试是 async），
  `requirements-dev.txt` 加 `pytest-asyncio`。

### Changed
- `knowledge/huawei_devices_introduce.txt` 从 26 行扩到 148 行：补端口编号规则
  （路由器 0 基 / 交换机 1 基）、视图与模式、access/trunk/hybrid 与 Eth-Trunk、
  常用诊断命令、**7 条易错点**、华为/H3C/Cisco 三厂商对照表。
- `docs/knowledge_base.md`：补「五个来源与可信度分级」「逐轮日志为何只取摘要」
  「检索状态机」「不索引清单」「一致性校验」「重建排查」，章节重编号。

### Fixed
- **知识库链路接口名错误**：`tools/ensp_lab_index.py` 对路由器也按 1 基编号，
  AR1 接 AR2 的口被写成 `GE0/0/1`（实际 `GE0/0/0`）。该文档是向量库主要来源，
  等于教模型用错接口。已按真机 `display ip interface brief` 与参考答案双向核实修正。
- **实验文档丢失链路聚合成员口**：一条 `<line>` 挂多个 `interfacePair` 时只取第一个，
  MSTP 试卷少列 2 条 Eth-Trunk 成员链路。已修。
- **多子工程实验包选错拓扑**：`is-is路由基本配置` 外层是 4 台设备的残缺副本，
  完整那份（8 台）在嵌套目录里；两个工具现统一为「排序后第一个可解析的」。
- **检索降级时模型无感知**：Ollama 挂掉时 `retrieve()` 只打一行 warning 就返回 `[]`，
  上层照旧拼空上下文，模型分不清「没有」与「坏了」，最坏会凭记忆编命令并声称查过知识库。
  见上方 `RetrievalResult`。

### Added（前次）
- `tools/kb_consistency.py`：`knowledge/experiments/*.md` ↔ `knowledge/topology/*.json`
  交叉一致性校验（设备/型号/console 端口/链路含接口名/画布标注），退出码可用于 CI；
  上述三个 bug 全部由它查出，回归测试见 `tests/test_kb_consistency.py`。
- **实验报告反哺知识库**：`core/rag.py` 新增第四个索引来源 `data/lab_reports/*.md`
  （含 `issues.md` 踩坑清单），运行报告统一注入「历史运行记录（可能已过时）」抬头；
  知识库块数 1681 → 2115。
- `docs/knowledge_base.md`：知识库体系说明（来源/集合/索引机制/一致性校验/明确不索引
  的数据及原因/重建命令）。

### Added
- `training/`：LoRA/QLoRA 微调链路（`train_sft.py` + `prepare_data.py` + 配置快照），
  替代早期 `modal_sft.py` 入口，全流程可复现。
- `tools/topo_extract.py`：解析 eNSP `.topo`（GBK 双 XML）为结构化拓扑数据集，
  导出 `knowledge/topology/`（57 实验 / 261 设备 / 426 链路）。
- `tools/extract_answers.py`：从实验包提取每台设备参考答案到 `data/lab_answers/`
  （43 实验 / 130 份路由器配置）。
- `tests/`：正式 pytest 测试 36 项（命令安全分级、提供方注册表、localhost 代理豁免、
  topo 解析、Telnet 假设备端到端），离线可跑。
- `docs/`：architecture（mermaid 架构/数据流）、mcp_tools（18 工具清单）、
  sft_dataset（数据集说明）、troubleshooting（踩坑手册）。
- 工程规范：LICENSE(MIT)、CHANGELOG、.env.example、requirements-dev.txt、
  .python-version、CONTRIBUTING。

### Changed
- `.gitignore`：`docs/`、`knowledge/` 不再整体忽略（毕设交付物需入库）；
  改为精确忽略 `knowledge/experiments/`（解析产物）与 `data/ensp_labs/`（实验包原件）。
- 旧向量库 `data/my_rag_db/`（无代码引用）归档到 `.workbuddy/archive/my_rag_db_20261008/`。
- README 目录树补全 `training/`、`tests/`、`knowledge/topology/`、`data/{finetune,lab_answers,
  lab_reports,topology_images}/` 与全部 docs；补上缺失的 `manual_server.py`。

## [1.1] - 2026-09

### Added
- 一键发布 `tools/git_release.ps1`（清理→构建→提交→打标签→可选推送），
  `.githooks/pre-push` 校验产物入库。
- 多模型提供方体系（`core/providers.py`）：本地 + DeepSeek V4
  （`deepseek-flash` 多模态 / `deepseek-pro` 深度推理），旧名 ALIASES 兼容；
  `config/llm.json` + `.env` 覆盖。
- 云端模式启动不拉起本地 llama-server；并行模式 `/parallel`（识图 ∥ 多模型融合）。

### Changed
- 打包默认 onedir（MCP 服务端经 `exe --serve-mcp` 复用自身拉起）；
  MCP 服务端模块进 spec hiddenimports；新增 `tools/exe_verify.py` 出包自检。

## [1.0] - 2026-08

### Added
- 项目骨架：llama-server 生命周期管理（`core/llama_start.py`）、唯一 LLM 出口
  （`core/llm_client.py`，流式/工具调用/思考分离）、RAG 知识库
  （ChromaDB + nomic-embed-text，`huawei_devices` / `command_templates` 双集合）。
- MCP 服务端五件套（Telnet / 串口 / 知识模板 / 设备手册 / 视觉）+ McpHub 客户端。
- 命令安全网关 `core/command_guard.py`：allow / confirm / block 三级裁决 +
  审计日志，设备通道统一过闸。
- PyQt6 桌面端（历史侧边栏 / 本地与云端模型切换 / CLI 模式）与 PyInstaller 打包。
- eNSP 批量陪跑链路（`tools/lab_batch.py` 等）：打开拓扑 → 起设备 → 模型配置 →
  验收 → 报告，SFT 导出（`tools/build_sft.py`，含假阳性剔除）。
