# 双出口综合性企业办公网络（IPv4/IPv6 双栈）实验设计与实施记录

> 实验环境：eNSP（VMware 客户机 Windows Server 2019，`LAB_HOST=192.168.183.137`）
> 测量方式：LLDP 泛洪发现 + 逐台 `display current-configuration` 采集（`tools/lab_snapshot.py`）
> 配置下发：`tools/lab_apply.py`（每条命令过 `command_guard` 并写 `logs/command_audit.log`）
> 最近更新：2026-10-23

---

## 0. 实测环境（不是假设，是从设备上读回来的）

拓扑里共 **21 台可登录设备**（控制台端口 2000–2020），初始全部为**出厂默认配置**
（无 sysname、无 IP、无 VLAN、无路由、无 VPN），LLDP 默认关闭、sysname 默认全为 `Huawei`。

| 控制台端口 | 型号 | 本次分配 sysname | 实测角色 |
|---|---|---|---|
| 2000 | USG/SRG（VSP V500R003C07） | FW0 | 防火墙（仅 GE0/0/0 接线） |
| 2001 | S5700-28C-HI | HQ-CORE1 | **总部核心 1** |
| 2002 | S5700-28C-HI | HQ-CORE2 | **总部核心 2** |
| 2003–2007 | S3700-26C-HI ×5 | HQ-ACC1…ACC5 | **总部接入**（每台双上行到双核心） |
| 2008/2009/2013/2014 | AR2220 | R8/R9/R13/R14 | 分支（串接，2009-2013-2014 链式） |
| 2016/2017 | AR2220 | R16/R17 | 分支（2016 上联 2008，2017 挂在 2016 下） |
| 2010 | USG/SRG | FW10 | 防火墙（仅 GE0/0/0 接线） |
| 2011/2015/2019 | S3700-26C-HI | SW11/SW15/SW19 | 办事处接入 |
| 2012/2020 | AR201（Version 5.110 eNSP） | D12/D20 | 出口/边界（不支持 `lldp enable`） |
| 2018 | — | — | 采集超时，暂不可用（`##\x00` 未就绪） |

LLDP 实测链路（开 LLDP 后 16 条，全部为「确定」级）：

```
HQ-CORE1:GE0/0/4 ↔ HQ-ACC1:ETH0/0/1     HQ-CORE2:GE0/0/4 ↔ HQ-ACC1:ETH0/0/2
HQ-CORE1:GE0/0/5 ↔ HQ-ACC2:ETH0/0/1     HQ-CORE2:GE0/0/5 ↔ HQ-ACC2:ETH0/0/2
HQ-CORE1:GE0/0/3 ↔ HQ-ACC3:ETH0/0/1     HQ-CORE2:GE0/0/3 ↔ HQ-ACC3:ETH0/0/2
HQ-CORE1:GE0/0/7 ↔ HQ-ACC4:ETH0/0/1     HQ-CORE2:GE0/0/7 ↔ HQ-ACC4:ETH0/0/2
HQ-CORE1:GE0/0/1 ↔ HQ-ACC5:ETH0/0/3     HQ-CORE2:GE0/0/1 ↔ HQ-ACC5:ETH0/0/4
R8:GE0/0/1 ↔ R9:GE0/0/2                 R8:GE0/0/2 ↔ R16:GE0/0/0
R9:GE0/0/1 ↔ R13:GE0/0/1                R13:GE0/0/2 ↔ R14:GE0/0/0
R14:GE0/0/1 ↔ SW15:ETH0/0/1             R16:GE0/0/1 ↔ R17:GE0/0/0
```

> 两台防火墙只接了 GE0/0/0（管理口，默认 192.168.0.1/24 带 DHCP），**目前不在数据转发路径上**；
> 双核心之间也没有直连链路（`Eth-Trunk1` 建了但没有成员口），核心冗余靠「接入交换机双上行 + VLAN 双 SVI」实现。

---

## 1. 题目要求 → 落地映射

| 题目要求 | 本实验的落地方式 | 状态 |
|---|---|---|
| 企业总部 | 双核心 S5700（2001/2002）+ 5 台接入 S3700（2003–2007）+ 2 台防火墙 | ✅ 核心与接入已配 |
| 3 个分支机构 | 分支 A=R8/R9，分支 B=R13/R14，分支 C=R16/R17（AR2220） | ⏳ 待配 |
| 6~10 个办事处 | SW11 / SW15 / SW19 做办事处接入；后续可用 AR201（2012/2020）做办事处出口 | ⏳ 待配 |
| 双核心双出口 | 双核心已做 VRRP + OSPFv2 双邻居；双出口由两台 AR2220（R8/R16）+ 两台 AR201 承担 | 🟡 核心完成，出口待配 |
| 路由冗余/备份 | 核心：OSPF 两条等价路径；出口：两条默认路由不同 preference（主 60 / 备 80） | 🟡 核心完成 |
| 防火墙安全规划 | FW0/FW10 划 trust/untrust/dmz，域间策略 + NAT（源 NAT + NAT Server） | ⏳ 待配 |
| 综合业务 | DHCP（IPv4/IPv6）、NAT、ACL、STP、链路聚合 | 🟡 部分完成 |
| 总部分部 VPN | IPsec（分支固定 IP 场景）或 DSVPN（分支地址不固定场景） | ⏳ 待配 |
| IPv4/IPv6 双栈 | 每个 SVI 同时配 IPv4 + ULA IPv6，IGP 用 OSPFv2 + OSPFv3 双进程 | 🟡 IPv4 通，IPv6 待收敛 |

---

## 2. 地址规划

内网 IPv6 统一用 ULA `fd00::/8`（不依赖运营商前缀，实验环境最稳），互联链路用 /30 与 /126 对齐。

| 区域 | 设备/接口 | IPv4 | IPv6 |
|---|---|---|---|
| 核心互联（VLAN 99） | HQ-CORE1 Vlanif99 | 10.10.99.1/24 | fd00:99::1/64 |
| | HQ-CORE2 Vlanif99 | 10.10.99.2/24 | fd00:99::2/64 |
| 办公 VLAN 10 | HQ-CORE1 Vlanif10 | 10.10.10.252/24 | fd00:10::252/64 |
| | HQ-CORE2 Vlanif10 | 10.10.10.253/24 | fd00:10::253/64 |
| | **VRRP 虚拟网关** | **10.10.10.254**（CORE1 主，prio 120） | 由 OSPFv3 通告 |
| 业务 VLAN 20 | HQ-CORE1 Vlanif20 | 10.10.20.252/24 | fd00:20::252/64 |
| | HQ-CORE2 Vlanif20 | 10.10.20.253/24 | fd00:20::253/64 |
| | **VRRP 虚拟网关** | **10.10.20.254**（CORE2 主，prio 120） | 由 OSPFv3 通告 |
| 分支 A | R8/R9 互联 | 10.20.0.0/30 | fd00:20a::/126 |
| 分支 B | R13/R14 互联 | 10.30.0.0/30 | fd00:30a::/126 |
| 分支 C | R16/R17 互联 | 10.40.0.0/30 | fd00:40a::/126 |
| 出口 | FW0/FW10 外联 | 10.99.0.0/30 | 2001:db8:99::/126（模拟运营商） |

VLAN 规划：10=办公、20=业务/服务器、99=核心互联与管理。

---

## 3. 协议与冗余设计（已落地的部分）

**双核心（已实测生效）**
- 两台 S5700 各配 VLAN 10/20/99，5 台接入交换机**每台双上行**（ETH0/0/1→CORE1、ETH0/0/2→CORE2），trunk 放通 10/20/99。
- 三层网关用 Vlanif + VRRP 做**负载分担+冗余**：VLAN10 由 CORE1 主、VLAN20 由 CORE2 主，单台核心挂掉各留一半网关。
- 生成树：两台核心分别 `stp root primary` / `stp root secondary`（默认 MSTP 模式；`stp mode rstp` 会弹 `[Y/N]` 确认，本环境已跳过）。
- 验证命令与实测结果：
  - `display vrrp brief` → CORE1：vrid10 **Master**、vrid20 Backup；CORE2：vrid10 Backup、vrid20 **Master** ✅
  - `display ospf peer brief` → 两台互相在 Vlanif10 / Vlanif20 上 **Full**（双邻居 = 双核心间两条三层路径）✅
  - `ping 10.10.20.252`（CORE2 → CORE1）→ **Reply，ttl=255** ✅

**IGP 双栈**
- OSPFv2：`ospf 1 router-id 10.0.0.1/.2`，`area 0`，`network 10.10.0.0 0.0.255.255`。
- OSPFv3：`ospfv3 1` + `router-id`，接口下 `ospfv3 1 area 0`（注意：**必须先创建进程并设 router-id**，
  否则接口命令直接报 `Error: Process does not exist`，这条是实测踩到的）。
- IPv6 转发需在系统视图执行 `ipv6` 全局使能，只配 `ipv6 address` 不会转发。

**双出口（待实施，方案已定）**
- 主出口：`ip route-static 0.0.0.0 0.0.0.0 <FW0> preference 60`
- 备出口：`ip route-static 0.0.0.0 0.0.0.0 <FW10> preference 80`（路由备份而非等价，避免回程不对称）
- 把静态默认路由 `import-route static` 进 OSPF，核心侧只需一条默认路由即可自动切换。

---

## 4. 安全与 VPN（设计，待实施）

**防火墙（FW0 / FW10）**
- 安全域：`trust`（内网 VLAN10/20）、`untrust`（外网）、`dmz`（对外服务器）、`local`（设备自身）。
- 域间策略要点：trust→untrust 只放行办公业务端口；untrust→dmz 只放行 80/443 到 Server；
  untrust→trust 一律拒绝；local 域限制管理源（只允许 10.10.99.0/24 管理）。
- 源 NAT（内网上网）：`nat-policy` + `source-nat easy-ip`（或 `nat outbound <acl>`）。
- NAT Server（对外发布）：`nat server global 10.99.0.10 inside 10.10.20.10`（把 DMZ 的 Web 映射出去）。

**总部-分部 VPN**
- 选型：分支出口 IP 固定 → **IPsec 静态隧道（IKEv1 主模式 + ESP）**；分支地址不固定 → **DSVPN（mGRE + NHRP）**。
  本实验分支都是固定互联地址，先用 IPsec，后续可加 DSVPN 演示动态分支。
- 关键参数：IKE proposal（aes-256 + sha2-256 + dh group14）、IPsec proposal（esp aes-256 + sha2-256）、
  预共享密钥、ACL 定义感兴趣流（总部 10.10.0.0/16 ↔ 分支 10.20.0.0/16）、`ipsec policy` 绑到出口接口。

---

## 5. 实施阶段与进度

| 阶段 | 内容 | 设备 | 验证命令 | 状态 |
|---|---|---|---|---|
| 0 | 基线采集（型号/接线/配置） | 21 台 | `display interface brief` / `display current-configuration` | ✅ 完成 |
| 0 | 唯一 sysname + 开 LLDP | 21 台 | `display lldp neighbor brief` | ✅ 完成 |
| 1 | 总部核心 + 5 接入（VLAN/Eth-Trunk/SVI/VRRP/OSPFv2） | 2001–2007 | `display vrrp brief`、`display ospf peer brief`、`ping` | ✅ 完成 |
| 1.5 | OSPFv3 收敛（IPv6 双栈打通） | 2001/2002 | `display ospfv3 peer`、`ping ipv6` | 🟡 进程已建，邻居待收敛 |
| 2 | 双出口 + 默认路由备份 + NAT | R8/R16/FW0/FW10/AR201 | `display ip routing-table`、`tracert`、`display nat session` | ⏳ 未开始 |
| 3 | 分支三层 + 办事处接入 + DHCP/DHCPv6 | R9/R13/R14/R17/SW11/SW15/SW19 | `display ip routing-table`、`display dhcp server ip-in-use` | ⏳ 未开始 |
| 4 | 防火墙安全域/策略/NAT Server | FW0/FW10 | `display security-policy rule all`、`display firewall session table` | ⏳ 未开始 |
| 5 | IPsec VPN 总部-分支 | 出口 + 分支 | `display ike sa`、`display ipsec sa` | ⏳ 未开始 |

---

## 6. 这个环境里实测踩到的坑（按影响排序）

1. **eNSP 控制台是单会话**：上一次连接被强杀后会「占着」控制台，新连接能建但一个字节都不回，
   表现为整台设备 60 条命令全部超时。处理：`tools/lab_apply.py` 已加预检（敲回车 → Ctrl+C/Ctrl+Z 复位 → 仍无响应则跳过该设备）。
2. **部分命令会追问 `[Y/N]`**（如 `stp mode rstp`、覆盖已有配置）：不回答会让后续所有命令等不到提示符。
   处理：下发器已自动识别 `[Y/N]`/`Continue?` 并回 `y`。
3. **默认 sysname 全为 `Huawei`**：LLDP 邻居全是 `Huawei`，拓扑推导会把对端认错（上午第一次泛洪就因此产出了假的 `ERROR:↔Global:LLDP` 边，
   已顺带修掉解析器把报错行当表格的 bug）。必须先设唯一 sysname。
4. **LLDP 默认关闭**：不开 LLDP 只能看到「全部孤立」；`lldp enable` 是 confirm 级命令，需走审批。
5. **S3700 的上联口是 `ETH0/0/x`（百兆），S5700 是 `GE0/0/x`**：接口名拼错（写成 `GigabitEthernetGE0/0/2`）不会报错但配置不生效。
6. **`save` 被命令护栏拦住**（block 级）：设备重启后配置会丢，实验期间别重启设备；需要持久化要单独授权。
7. **`stp mode rstp`、`undo` 类命令**：`undo` 在非实验模式下是 block 级，回退配置需显式开启实验模式。

---

## 7. 相关工具

| 文件 | 作用 |
|---|---|
| `tools/lab_snapshot.py` | 并发采集全部设备配置 → `data/lab_reports/current_<ts>/{*.cfg,digest.json,digest.txt}` |
| `tools/lab_apply.py` | 批量下发配置（plan JSON → 逐条过护栏 + 审计 + `[Y/N]` 自动确认 + 控制台预检） |
| `data/lab_reports/plans/hq_phase1.json` | 总部双核心+接入的配置计划（可 diff、可重放） |
| `data/lab_reports/plans/sysname_plan.json` | 全设备 sysname 命名计划 |

---

## 5.1 实测确认的出口链路（2026-10-23 晚，ARP/ping 配对法）

LLDP 对 USG/AR201 无效（不支持 lldp enable），改用「配置探测地址 → display arp /
mac-address 交叉定位 → /30 互 ping 验证」测绘，以下链路均有 MAC 级证据：

| 链路 | 证据 | 状态 |
|---|---|---|
| CORE1:GE0/0/2 ↔ FW0:GE0/0/2 | FW0 MAC 0000-0067-b802 学在 CORE1 VLAN100/GE0/0/2；ARP 双向解析；**ping 通** | ✅ 已配 10.99.0.0/30 |
| CORE2:GE0/0/2 ↔ FW0:GE0/0/3 | ARP 学到 0000-0067-b803 | ✅ 已配 10.99.0.4/30 |
| FW10:GE0/0/1 ↔ R16:GE0/0/2 | FW10 ARP 学到 00e0-fc81-29f0（R16） | 地址待配 |
| R8:GE0/0/0 / R9:GE0/0/0 / FW0:GE0/0/1 / FW0:GE0/0/5 / D12×3 / D20×2 | 与上述所有端点 17 对互 ping 全部不通；唯一共同指向 **2018** | ⏳ 对端=2018（ISP），控制台未就绪 |

**结论：2018 就是全网唯一的 ISP/出口汇聚设备**，FW0 双上行（GE0/0/1/5）、
分支 A/B（R8/R9）各一条上行、D12/D20（AR201，疑似分支 C 与办事处的出口）都接它。
2018 控制台持续返回 `## `（未就绪），需在 eNSP GUI 里重启该设备才能继续阶段 2~5。

VRRPv6 落地（阶段 1.5 完成）：
- `vrrp6 vrid N virtual-ip FE80::N link-local` → `vrrp6 vrid N virtual-ip FD00:x::254`
  （老 VRP 语法：第一个虚拟地址必须是 link-local，`link-local` 关键字在地址**之后**）
- 实测：CORE1 vrid10 Master(120)/vrid20 Backup(100)，CORE2 反之，与 IPv4 VRRP 角色一致
- CORE2 之前 OSPFv3 不收敛的根因：缺全局 `ipv6`（只有接口级 `ipv6 enable` 不转发，
  `display ipv6 statistics` 收发全 0），补上后 Vlanif10/20 邻居 Full、`ping ipv6` 通

探测残留：10.97.x / 10.98.x / 10.199.x 临时地址散布在 FW0/FW10/D12/D20/R8/R9，
正式配置落地时统一清理。CORE1/CORE2 的 GE0/0/2 已从遗留的空挂 Eth-Trunk1 解绑。
