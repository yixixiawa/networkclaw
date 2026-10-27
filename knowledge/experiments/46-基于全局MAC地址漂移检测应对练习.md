# 实验 46：基于全局MAC地址漂移检测应对练习

- 来源目录：`基于全局MAC地址漂移检测应对练习`
- 拓扑文件：`paper.topo`

## 一、题目要求

全局MAC地址漂移检测与应对配置练习
1）先使PC1与PC3、PC10与PC5进行通信，然后再让PC2与PC3、PC7与PC11持续通信（下面各步骤中，没有特别说明，保持各PC间持续互通）；
2) 观察SW1是否有MAC地址漂移告警信息，验证全局MAC地址漂移检测是否默认已经启动，默认应对为告警，查看漂移端口、漂移记录数；
3）配置SW1 MAC地址漂移检测白名单(VLAN 10)，看看SW1 G0/0/4与G0/0/1的MAC地址漂移信息是否还有报警，连续查看漂移记录，看看漂移
记录数增长情况；
4）配置SW1端口G0/0/1对发生漂移后的处理动作端口全部阻塞，观察一阵，是否有端口物理状态为“DOWN”；查看MAC地址漂移记录中，该端
口是否有"D"标记。
5）全局配置视图下，配置地址漂移引起的ERROR DOWN停止再停止漂移后30秒后自动恢复，恢复关闭的端口后，等端口再次发生关闭后，停止
MAC地址冲突的PC间的通信，过30秒后，看看关闭端口是否恢复正常；
6）取消SW1 G0/0/1的ERROR DOWN配置，修改端口的地址漂移应对为QUIT-VLAN；
7）当发现PC2与PC3不同互通后，查看MAC地址漂移记录中，该端口是否有"Q"标记,再看看PC10与PC5是否能够互通；
8）查看端口SW1 G0/0/1对VLAN通过的状态(diaplay port vlan active)，看看当前该端口允许哪些VLAN通过；
9）全局视图下，配置MAC地址漂移QUIT-VLAN模式，设置停止漂移后为1分钟自动恢复，停止PC2与PC3通信，1分钟后看看PC6与PC3是否恢复通信。
10) 保存配置提交ANS文件。

## 二、设备清单

| 设备 | 型号 | Console(Telnet)端口 | 关键参数 |
|---|---|---|---|
| HUB1 | HUB | - | - |
| HUB2 | HUB | - | - |
| HUB4 | HUB | - | - |
| HUB5 | HUB | - | - |
| LSW1 | S5700 | 2000 | - |
| LSW2 | S5700 | 2001 | - |
| PC1 | PC | - | IP 192.168.1.10/24 |
| PC10 | PC | - | IP 192.168.10.100/24 |
| PC11 | PC | - | IP 192.168.10.110/24 |
| PC2 | PC | - | IP 192.168.1.20/24 |
| PC3 | PC | - | IP 192.168.1.30/24 |
| PC4 | PC | - | IP 192.168.1.40/24 |
| PC5 | PC | - | IP 192.168.10.50/24 |
| PC6 | PC | - | IP 192.168.1.60/24 |
| PC7 | PC | - | IP 192.168.10.70/24 |

## 三、链路连接

- LSW1 `GigabitEthernet0/0/1` ↔ LSW2 `GigabitEthernet0/0/1`（Copper）
- PC3 `Ethernet0/0/0` ↔ LSW1 `GigabitEthernet0/0/3`（Copper）
- LSW1 `GigabitEthernet0/0/2` ↔ HUB1 `Ethernet0/0/0`（Copper）
- HUB1 `Ethernet0/0/1` ↔ PC4 `Ethernet0/0/0`（Copper）
- HUB1 `Ethernet0/0/2` ↔ PC1 `Ethernet0/0/0`（Copper）
- LSW2 `GigabitEthernet0/0/2` ↔ HUB2 `Ethernet0/0/0`（Copper）
- HUB2 `Ethernet0/0/1` ↔ PC6 `Ethernet0/0/0`（Copper）
- HUB2 `Ethernet0/0/2` ↔ PC2 `Ethernet0/0/0`（Copper）
- HUB4 `Ethernet0/0/0` ↔ LSW2 `GigabitEthernet0/0/3`（Copper）
- HUB4 `Ethernet0/0/1` ↔ PC5 `Ethernet0/0/0`（Copper）
- LSW1 `GigabitEthernet0/0/4` ↔ HUB5 `Ethernet0/0/0`（Copper）
- HUB5 `Ethernet0/0/1` ↔ PC7 `Ethernet0/0/0`（Copper）
- PC10 `Ethernet0/0/0` ↔ HUB5 `Ethernet0/0/2`（Copper）
- HUB4 `Ethernet0/0/2` ↔ PC11 `Ethernet0/0/0`（Copper）

## 四、拓扑图上的文字标注

- `192.168.1.40/24`（贴近 PC4）
- `192.168.1.30/24`（贴近 PC3）
- `192.168.10.50/24`（贴近 PC5）
- `192.168.10.70/24`（贴近 PC10）
- `VLAN 10`（贴近 LSW1）
- `VLAN 10`（贴近 HUB2）
- `TRUNK 1 10`（贴近 LSW2）
- `192.168.1.60/24`（贴近 PC6）
- `VLAN 1`（贴近 LSW1）
- `VLAN 1`（贴近 LSW1）
- `VLAN 1`（贴近 HUB2）

## 五、参考答案（从 .model 自动提取，按设备分组）

> 说明：该列表由实验包的「参考答案」文件提取，仅含命令文本、不含缩进层级；
> 部分行是设备默认配置，需结合题目与拓扑判断哪些是本题真正要求下发的配置。

### LSW1

```
sysname SW1
vlan batch 10
cluster enable
ntdp enable
ndp enable
drop illegal-mac alarm
mac-address flapping detection exclude vlan 10
mac-address flapping quit-vlan recover-time 1
diffserv domain default
drop-profile default
aaa
interface Vlanif1
interface MEth0/0/1
interface GigabitEthernet0/0/1
interface GigabitEthernet0/0/2
interface GigabitEthernet0/0/3
interface GigabitEthernet0/0/4
interface GigabitEthernet0/0/5
interface GigabitEthernet0/0/6
interface GigabitEthernet0/0/7
interface GigabitEthernet0/0/8
interface GigabitEthernet0/0/9
interface GigabitEthernet0/0/10
interface GigabitEthernet0/0/11
interface GigabitEthernet0/0/12
interface GigabitEthernet0/0/13
interface GigabitEthernet0/0/14
interface GigabitEthernet0/0/15
interface GigabitEthernet0/0/16
interface GigabitEthernet0/0/17
interface GigabitEthernet0/0/18
interface GigabitEthernet0/0/19
interface GigabitEthernet0/0/20
interface GigabitEthernet0/0/21
interface GigabitEthernet0/0/22
interface GigabitEthernet0/0/23
interface GigabitEthernet0/0/24
interface NULL0
user-interface con 0
user-interface vty 0 4
authentication-scheme default
authorization-scheme default
accounting-scheme default
domain default
domain default_admin
local-user admin password simple admin
local-user admin service-type http
port link-type trunk
port trunk allow-pass vlan 10
mac-address flapping trigger quit-vlan
port link-type access
port default vlan 10
```

### LSW2

```
sysname SW2
vlan batch 10
cluster enable
ntdp enable
ndp enable
drop illegal-mac alarm
diffserv domain default
drop-profile default
aaa
interface Vlanif1
interface MEth0/0/1
interface GigabitEthernet0/0/1
interface GigabitEthernet0/0/2
interface GigabitEthernet0/0/3
interface GigabitEthernet0/0/4
interface GigabitEthernet0/0/5
interface GigabitEthernet0/0/6
interface GigabitEthernet0/0/7
interface GigabitEthernet0/0/8
interface GigabitEthernet0/0/9
interface GigabitEthernet0/0/10
interface GigabitEthernet0/0/11
interface GigabitEthernet0/0/12
interface GigabitEthernet0/0/13
interface GigabitEthernet0/0/14
interface GigabitEthernet0/0/15
interface GigabitEthernet0/0/16
interface GigabitEthernet0/0/17
interface GigabitEthernet0/0/18
interface GigabitEthernet0/0/19
interface GigabitEthernet0/0/20
interface GigabitEthernet0/0/21
interface GigabitEthernet0/0/22
interface GigabitEthernet0/0/23
interface GigabitEthernet0/0/24
interface NULL0
user-interface con 0
user-interface vty 0 4
authentication-scheme default
authorization-scheme default
accounting-scheme default
domain default
domain default_admin
local-user admin password simple admin
local-user admin service-type http
port link-type trunk
port trunk allow-pass vlan 10
port trunk allow-pass vlan
Begin with
port link-type access
port default vlan 10
```

## 六、验收要点

（待本地模型跑通后回填：需连通的 PC 对、需隔离的 PC 对、关键验证命令）
