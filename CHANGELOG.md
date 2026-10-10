# Changelog

所有对外可见的变更记录在此文件。
格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
版本号遵循 [SemVer](https://semver.org/lang/zh-CN/)。

## [Unreleased]

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
