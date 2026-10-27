# 实验 44：全局的MAC地址漂移检测与应对

- 来源目录：`全局的MAC地址漂移检测与应对`
- 拓扑文件：`paper.topo`

## 一、题目要求

（题目为空）

## 二、设备清单

| 设备 | 型号 | Console(Telnet)端口 | 关键参数 |
|---|---|---|---|
| HUB1 | HUB | - | - |
| HUB2 | HUB | - | - |
| LSW1 | S5700 | 2000 | - |
| LSW2 | S5700 | 2001 | - |
| PC1 | PC | - | IP 192.168.1.10/24 |
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
- LSW2 `GigabitEthernet0/0/3` ↔ PC5 `Ethernet0/0/0`（Copper）
- PC7 `Ethernet0/0/0` ↔ LSW1 `GigabitEthernet0/0/4`（Copper）
- LSW2 `GigabitEthernet0/0/2` ↔ HUB2 `Ethernet0/0/0`（Copper）
- HUB2 `Ethernet0/0/1` ↔ PC6 `Ethernet0/0/0`（Copper）
- HUB2 `Ethernet0/0/2` ↔ PC2 `Ethernet0/0/0`（Copper）

## 四、拓扑图上的文字标注

- `192.168.1.40/24`（贴近 PC4）
- `192.168.1.30/24`（贴近 PC3）
- `192.168.10.50/24`（贴近 PC5）
- `192.168.10.70/24`（贴近 PC7）
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
sysname LSW1
vlan batch 10
cluster enable
ntdp enable
ndp enable
drop illegal-mac alarm
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
sysname Huawei
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
port link-type access
port default vlan 10
```

## 六、验收要点

（待本地模型跑通后回填：需连通的 PC 对、需隔离的 PC 对、关键验证命令）
