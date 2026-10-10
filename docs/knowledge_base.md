# 知识库（RAG）说明

模型不是靠记性答对的：设备知识、实验题面、参考答案、**历次运行踩过的坑**都进向量库，
由 `search_knowledge` / `query_command_template` 两个工具按需检索。

## 1. 集合注册表（唯一注册点在 `core/ollama_interface.py`）

| 集合 | 用途 | 写入方 | 当前块数 |
|---|---|---|---|
| `huawei_devices` | 知识库：设备知识 + 实验文档 + 设备手册 + 运行报告 + 逐轮运行日志 | `core/rag.py` | 2307（2026-10-08） |
| `command_templates` | 命令模板（`knowledge/command_templates.csv`） | `core/template_search.py` | 174 |

物理上同库（`data/Rag_data`，ChromaDB 持久化），逻辑分集。
**集合名不得在业务模块里硬编码**，一律 `get_collection(名字)` 现取现用。

## 2. 知识库的五个来源与可信度分级（`core/rag.py`）

| # | 来源 | 内容 | 生成方式 | 分级 |
|---|---|---|---|---|
| ① | `knowledge/huawei_devices_introduce.txt` | 华为设备产品线与基础命令说明 | 人工维护 | `instance` |
| ② | `knowledge/experiments/NN-*.md` | **每个实验**：题目要求 / 设备清单（含 console 端口）/ 链路连接 / 画布标注 / 参考答案 / 验收要点 | `tools/ensp_lab_index.py` | `rule` |
| ③ | `skills/<设备名>/SKILL.md` | 运行期自建的设备手册 | 模型运行时自建 | `rule` |
| ④ | `data/lab_reports/*.md` | 实验运行报告 + `issues.md` 踩坑清单 | `tools/lab_run_agent.py` | `history` |
| ⑤ | `data/run_logs/**/*.jsonl` | **逐轮工具调用与设备回显**的会话摘要 | `core/run_log.py`（模型运行时写） | `history` |

### 2.1 分级前缀：让模型知道该信几分

四类内容混在一个集合里时，模型分不清"现行规则"和"上次踩过的坑"，
会把过时经验当命令照抄。所以每个块入索引前都加一个前缀（`_decorate()`）：

| 分级 | 前缀 | 含义 |
|---|---|---|
| `TIER_RULE` | `【现行规则｜可据此直接作答】` | 实验文档与设备手册——权威，可直接依据 |
| `TIER_HISTORY` | `【历史记录｜仅供参考，与规则冲突时以规则为准】` | 运行报告、逐轮日志——可能过时 |
| `TIER_INSTANCE` | `【实例数据｜事实描述，不含操作建议】` | 设备介绍等事实性文本 |

④⑤ 是「经验反哺」：模型每跑同类实验都会重踩同样的坑（视图丢失、undo 被拦、
命令报错要换写法…）。运行报告注入时统一加 `history` 前缀，
`issues.md` 例外——它是维护中的现行问题清单。

### 2.2 ⑤ 逐轮运行日志：摘要而非原文

`data/run_logs/<日期>/<会话名>.jsonl` 是**每轮 LLM 调用与工具步骤**的原始记录，
体量大且充满重复。`_run_log_digests()` 只取**最近 3 天**的会话，
每场压成一节摘要：

- 抬头：日期 / 会话名 / 用的模型 / LLM 调用数 / 工具步数
- **去重后的配置类命令**（`display`/`show`/`ping`/`tracert`/`dir`/`more` 等只读命令被刻意排除——
  它们对"怎么配"没有信息量，只会占检索名额）
- 最多 5 行报错回显（匹配 `Error` / `Unrecognized` / `Wrong parameter` / `失败` / `不可达`）
- 纯只读会话写「本次会话只做只读查看，没有下发配置类命令。」

当前贡献 19 场摘要。会话枚举复用 `core.run_log.py` 的 `list_sessions()` / `read_session()`
（而不是自己猜文件名），避免和它的安全文件名规则漂移。

## 3. 索引机制（为什么可以放心改文档）

- **指纹幂等**：`build_index()` 用「内容 md5 + 块数」判断是否需要重建，
  每次启动可放心调用；改完知识文档**不用手动清库**，指纹变化会自动触发重建。
- **重建是「先删后建」**：因此**必须先 `check_embedder()`**——
  Ollama 没起来时宁可不重建，也不能把旧索引删了建不回来。
- **切分**：`RecursiveCharacterTextSplitter(chunk_size=300, overlap=50)`；
  Embedding 用 Ollama `nomic-embed-text`，**批大小 64**（Chroma 会把整批文档
  一次性交出去，实测 512 条会把 Ollama runner 打崩，128 以内稳定）。
- 索引指纹落在 `data/index_state.json`，按集合名分区，两个集合互不影响。

## 5. 检索状态：区分「没有」和「坏了」（`RetrievalResult`）

早期 `retrieve()` 在 Ollama 挂掉时只是打印一行 warning 然后返回 `[]`，
上层 `ask()` 照旧拼一个空上下文——模型于是无法分辨
「知识库里确实没有相关内容」和「检索链路故障」，
最糟的结果是**凭记忆编命令并声称查过知识库**。

现在 `retrieve_ex()` 返回 `RetrievalResult(chunks, status, reason)`：

| status | 含义 | 是否降级 | 处置 |
|---|---|---|---|
| `ok` | 正常命中 | 否 | 直接作答 |
| `empty` | 集合为空（还没建索引） | 否 | 提示"知识库为空，需先重建" |
| `no_match` | 检索通了但没有相关内容 | 否 | 如实说"没有找到"，可以凭通用知识回答但要标注 |
| `unavailable` | Ollama / 集合拿不到 | **是** | 注入降级告警 |
| `embed_failed` | query 向量化失败 | **是** | 注入降级告警 |

降级时 `notice()` 生成的告警会**插进 prompt 正文**，明确告诉模型
「本轮没有可用的知识片段……不要声称查过知识库」；
`ask()` 另在终端打 `[降级]` 标签；Agent 模式下的 `search_knowledge`
工具则返回「⚠ 知识库检索不可用……**这不是「知识库中没有相关内容」，而是检索链路故障**……
请明确告知用户检索失败，不要凭记忆编造命令或结论。（修复：启动 Ollama 并执行
`ollama pull nomic-embed-text`）」。

`retrieve()` 保留为兼容包装（`return retrieve_ex(...).chunks`），旧调用点不受影响。
回归测试：`tests/test_rag.py`。

## 6. 明确**不**入向量库的东西（以及原因）

| 数据 | 原因 |
|---|---|
| `knowledge/topology/*.json` | 内容已被 ② 的实验文档以表格形式完整重建（设备/端口/链路/标注）。重复入库会产生大量近重复块，检索时互相挤占名额。改为用**一致性校验**防漂移（见下）。 |
| `data/lab_answers/*.cfg` | 路由器参考答案的**文本**已在 ② 的「五、参考答案」小节里（`ensp_lab_index` 从 `.model` 提取）。再单独入库既重复，又会进一步提高"照抄答案"的风险——验收的 `net`（净提升）指标本就为此承压。 |
| `data/lab_answers/*.flash.efz` | eNSP 私有二进制（魔数 `eNSP`），不可向量化；交换机参考答案需从「清场后重配」的运行日志侧补齐。 |

## 7. 一致性校验（把"难发现"变成"一条命令"）

```bash
python tools/kb_consistency.py          # 人读输出；不一致时退出码 1
python tools/kb_consistency.py --json   # CI / pytest 用
```

比对 `knowledge/experiments/*.md` 与 `knowledge/topology/*.json`：
设备集合、型号、console 端口、链路（含接口名）、画布标注（内容级子集）。

两份数据是**从同一批 `.topo` 独立推导**的（一个给向量库、一个给结构化数据集），
独立实现才有交叉验证价值。历史战果（都是本工具查出来的）：

1. **路由器接口编号错 1 位**：`ensp_lab_index` 对路由器也按 1 基编号，
   AR1 接 AR2 的口被写成 `GE0/0/1`，实际是 `GE0/0/0`
   （真机 `display ip interface brief` 与 `lab_answers` 参考答案双向核实）。
   该文档正是知识库来源 → 会教坏模型。已修。
2. **Eth-Trunk 成员链路丢失**：一条 `<line>` 挂多个 `interfacePair` 时，
   生成器只取第一个，MSTP 试卷少列 2 条成员链路。已修。
3. **多子工程实验包选错 topo**：`is-is路由基本配置` 外层是 4 台设备的残缺副本，
   完整那份（8 台）在嵌套目录里。两个工具现统一为「排序后第一个可解析的」。

当前状态：**57 个实验 / 0 不一致**；10 个实验目录内含多个子拓扑
（工具会以 `ℹ` 提示未索引的那几个，例如 `综合练习` 下有 `OSPF配置` 与 `综合配置` 两份）。

回归测试：`tests/test_kb_consistency.py`（数据缺失时自动跳过）。

## 8. 重建 / 排查

```bash
ollama serve                          # 前提：Ollama 必须在跑（11434）且已 pull nomic-embed-text
python -m core.rag --rebuild          # 强制重建知识库集合
python -m core.template_search --rebuild   # 重建命令模板集合（只动这一个集合）
python tools/kb_consistency.py        # 校验两份数据一致
python tools/ensp_lab_index.py        # 重生成实验文档（改动拓扑解析逻辑后）
python tools/topo_extract.py          # 重生成拓扑结构化数据集
```

已知坑：本机代理会劫持回环请求（curl/requests 访问 127.0.0.1 报
`upstream connect failed`）——`core/net.py` 的 `ensure_localhost_bypass()`
已在导入时写入 NO_PROXY，用裸 curl 排查时记得加 `--noproxy '*'`。
