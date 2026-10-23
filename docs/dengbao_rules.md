# 等保2.0 配置检查规则集

把 GB/T 22239 的测评项落成**可执行的配置检查规则**，供扫描器/Agent 判定设备是否符合等级保护要求。

规则不是手写的，是**从资料里抽出来的**：每条的 `source` 都指明取自哪份 xlsx 的哪一行，
每条 `remediation` 的命令都能在 `knowledge/command_templates.csv` 或测评表原文中找到出处。
由 `tools/build_dengbao_rules.py` 生成，测试 `tests/test_dengbao_rules.py`（18 项）守住契约。

## 目录

| 路径 | 内容 |
|---|---|
| `dengbao_rules/<规则ID>.yaml` | 单条规则正文，**一条规则一个文件** |
| `dengbao_rules/rules_index.json` | 机器可读索引：id / category / severity / check_type |
| `dengbao_rules/RULES_OVERVIEW.md` | 人读总表（覆盖分布 + 人工取证清单 + 不适用清单） |
| `dengbao_source_lines.json` | 资料原文逐行存档，供测试核对命令出处（免装 openpyxl） |
| `tools/build_dengbao_rules.py` | 生成器（唯一数据源），改规则改这里再重跑 |
| `tools/render_dengbao_overview.py` | 生成 `RULES_OVERVIEW.md` |
| `tools/_verify_remediation_source.py` | 命令出处核对器（白名单匹配算法） |
| `tests/test_dengbao_rules.py` | 契约 + 行为测试 |

## 取数范围

严格只用这三份资料，且每份只取指定部分：

| 资料 | 取用部分 |
|---|---|
| `等保2.0初级教材 测评操作.xlsx` | sheet「安全区域边界」访问控制/入侵防范；sheet「安全计算环境」全部（含路由器/交换机/防火墙三段） |
| `等保2.0差距评估与整改建议.xlsx` | sheet「安全计算环境-网络设备」「安全计算环境-安全设备」的**整改建议列** |
| `等保2.0一~三级测评项得分及权重-参考材料.xlsx` | sheet「安全通用要求权重表」的**第二级/第三级权重列** |

不包含物理环境、管理制度、人员管理、安全管理机构的相关条目。

## 规则字段

```yaml
id: DB-NET-ID-03            # DB-<范围>-<控制点>-<序号>
vendor: any                 # any / Huawei / H3C / Cisco
device_type: network_device  # network_device / firewall / ips / apt
category: 安全计算环境-网络设备
control_point: 身份鉴别
requirement: c)当进行远程管理时，应采取必要措施防止鉴别信息在网络传输过程中被窃听
weight_level: 3             # 2 或 3
severity: high              # 由权重推导，不可手填
source: A 表 sheet「安全计算环境」行4/行27；B 表行4；C 表行62（二/三级均=1）
check:
  type: config_regex
  target: VTY inbound 协议
  expect: VTY 只允许 SSH
  pattern: (?im)^\s*(?:protocol\s+inbound\s+ssh|transport\s+input\s+ssh|...)
remediation:                 # 命令，必须能在资料中找到出处
- stelnet server enable
- protocol inbound ssh
evidence_hint: 需同时确认没有 protocol inbound all 残留……
weight_detail:               # 附加：二级权重，便于二级系统复用
  level2: 1
  level3: 1
```

### `check.type` 只有五种

| 类型 | 语义 | 判定 |
|---|---|---|
| `config_contains` | 配置文本包含某字面量 | 命中即 pass |
| `config_absent` | 配置文本**不得**包含某模式 | 命中即 fail |
| `config_regex` | 正则匹配（主用） | 命中 pass |
| `config_value_compare` | 取值后与阈值比较 | 需外部阈值输入 |
| `manual_confirm` | 配置文本无法判定 | 输出 unknown，须人工取证 |

`config_absent` 有陷阱：设备**根本没配**时也会 pass。凡"应当存在的配置+其中不得出现某模式"的组合，
必须用 `config_regex` + 负向先行断言（参考 `DB-BND-AC-02`），否则「未配置」会被误判成「合规」。

### severity 推导

权重取自 C 表第三级权重列（`weight_level: 3`）：

| 权重 | severity | 含义 |
|---|---|---|
| 1 | high | 核心必测项，缺失直接判不符合 |
| 0.7 | medium | 一般项 |
| 0.4 | low | GB/T 22239 里带「可」字的增强项 |

`weight_level: 2` 时取第二级权重，推导规则相同。测试 `test_severity_derived_from_weight` 守住这条，
手改 severity 会直接失败。

## 覆盖面

| 类别 | 规则数 | 高 | 中 | 低 | 可自动判定 | 需人工确认 |
|---|---|---|---|---|---|---|
| 安全区域边界-访问控制 | 5 | 2 | 3 | 0 | 3 | 2 |
| 安全区域边界-入侵防范 | 5 | 5 | 0 | 0 | 0 | 5 |
| 安全计算环境-安全设备 | 23 | 15 | 7 | 1 | 2 | 21 |
| 安全计算环境-网络设备 | 23 | 15 | 7 | 1 | 10 | 13 |
| **合计** | **56** | **37** | **17** | **2** | **15** | **41** |

`manual_confirm` 占比高（41/56）不是偷懒，是资料的客观限制：

* **防火墙段（A 表行48~70）** 的测评方法全部走 WEB 界面（"左侧导航树选择系统管理>>配置"），
  **一条 CLI 命令都没给**。例如行48 的测评路径是浏览器登录 + 用户列表页，
  唯一可量化的判据是预期结果里的「口令长度8位以上…每季度至少更改一次」。
  配置文本读不到这些，只能人工取证。
* **边界入侵防范（A 表行11~15）** 要求「部署了 IPS/IDS」「规则库更新到最近」，
  这是**设备存在性 + 运维记录**，不是配置项。
* **资料原文判「不适用」的 17 条**（e/f/g 这类面向主机数据库的条款）也归在 `manual_confirm`，
  但 `evidence_hint` 会引用原文出处并写明结论应为 `not_applicable`。

反过来，能自动判定的 15 条都做了真检查：网络设备段的 SSH 强制、VTY 超时、ACL 源地址限制、
日志外发、空闲端口 shutdown 等，全部有对应的配置正则，且经行为测试验证
（规范配置 pass、裸奔配置 fail、`permit ip any any` 必须被识别）。

## 命令出处白名单

`tools/_verify_remediation_source.py#SourceIndex.check()` 按四级匹配，任一命中即通过：

| 方式 | 含义 | 例 |
|---|---|---|
| `csv-exact` | 与 `command_templates.csv` 命令列逐字一致 | `interface GigabitEthernet0/0/1` |
| `kb-line` | 与测评表原文某一**行**逐字一致 | `no cdp run` |
| `kb-substr` | 是测评表原文的连续子串 | `info-center loghost 192.10.12.1 facility local 1` |
| `csv-shape` | 与 csv 模板同构（只差可变值） | `rule 10 permit source 10.1.100.0 0.0.0.255` |
| `csv-sample` | 差异位落在「样例值白名单」 | `local-user netadmin ...`（模板是 admin） |

「同构」的做法是把命令拆成**只保留命令关键字**的骨架（IP、接口号、口令、密文全部折叠为占位符），
再比骨架是否相同。这样 `local-user X password Y Z` 与 `local-user X password Y Z` 天然匹配，
而 `totally-made-up-command xyz` 因为 `made-up` 不是任何模板里的关键字而无法蒙混。

**注意**：资料本身有 OCR 错字（`exec-timcout`、`Iocal6`、`p http shutdown`、掩码粘连 `172.16.4.0.0.0.0.255`）。
规则里**照原文收录**，并在 `evidence_hint` 注明真机写法。不做"顺手修正"——修正后的写法在资料中
找不到出处，就违反了「命令必须有出处」这条硬约束。

## 使用

```bash
# 重新生成（改完 tools/build_dengbao_rules.py 后跑）
D:/python/python.exe tools/build_dengbao_rules.py       # 需要 openpyxl
D:/python/python.exe tools/render_dengbao_overview.py   # 刷新人读总表

# 验证：契约 + 行为 + 命令出处
.venv/Scripts/python.exe -m pytest tests/test_dengbao_rules.py -q

# 引擎自测（规范配置全 pass / 裸奔配置全 fail / 全通策略必须被抓）
D:/python/python.exe tools/_selftest_dengbao_rules.py
```

生成器内置三道自检，任一不过即**拒绝产出**：

1. `check.type` 必须在五种之内
2. `manual_confirm` 的 `evidence_hint` 不得少于 40 字（必须说清缺什么证据）
3. 每条 `remediation` 命令必须通过出处核对

## 已知缺口

* **A 表行24/行47/行70（可信验证）** 只写「参见2.3和3.6可信验证」，没有测评方法，
  属资料缺口。规则保留为 `manual_confirm` 并在 `evidence_hint` 里点明。
* **A 表「安全计算环境」行13 与行45**：第 12 行「b)」和第 13 行「c)」的安全要求文本完全重复
  （原表笔误）。规则按原表保留两条独立编号（`DB-BND-IPS-02` / `DB-BND-IPS-03`），
  否则会与资料行号失去对应关系。
* **A 表「安全计算环境」第 33/34/35 行** 的条目编号写成了 `d)e)f)`，而 C 表是 `e)f)g)`。
  规则以 C 表编号为准（`DB-NET-AC-05/06/07`）。
