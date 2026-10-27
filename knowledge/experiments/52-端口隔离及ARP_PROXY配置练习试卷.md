# 实验 52：端口隔离及ARP_PROXY配置练习试卷

- 来源目录：`端口隔离及ARP_PROXY配置练习试卷`
- 拓扑文件：`paper.topo`

## 一、题目要求

（题目为空）

## 二、设备清单

| 设备 | 型号 | Console(Telnet)端口 | 关键参数 |
|---|---|---|---|
| AR1 | AR2220 | 2002 | - |
| LSW1 | S5700 | 2000 | - |
| LSW2 | S5700 | 2001 | - |
| LSW3 | S5700 | 2003 | - |
| PC1 | PC | - | IP 192.168.10.10/24 |
| PC2 | PC | - | IP 192.168.10.130/24 |
| PC3 | PC | - | - |
| PC4 | PC | - | - |
| PC5 | PC | - | - |
| PC6 | PC | - | - |

## 三、链路连接

- AR1 `GigabitEthernet0/0/0` ↔ PC1 `Ethernet0/0/0`（Copper）
- AR1 `GigabitEthernet0/0/1` ↔ PC2 `Ethernet0/0/0`（Copper）
- LSW1 `GigabitEthernet0/0/1` ↔ LSW2 `GigabitEthernet0/0/1`（Copper）
- LSW2 `GigabitEthernet0/0/2` ↔ PC3 `Ethernet0/0/0`（Copper）
- LSW2 `GigabitEthernet0/0/3` ↔ PC4 `Ethernet0/0/0`（Copper）
- LSW1 `GigabitEthernet0/0/2` ↔ LSW3 `GigabitEthernet0/0/1`（Copper）
- LSW3 `GigabitEthernet0/0/2` ↔ PC5 `Ethernet0/0/0`（Copper）
- LSW3 `GigabitEthernet0/0/3` ↔ PC6 `Ethernet0/0/0`（Copper）

## 四、拓扑图上的文字标注

- `192.168.10.10/24`（贴近 PC1）
- `192.168.10.130/24`（贴近 PC2）
- `192.168.10.1/25`（贴近 AR1）
- `192.168.10.129/25`（贴近 PC2）
- `VLAN 10`（贴近 PC4）
- `VLANIF 100: 192.168.10.1/24`（贴近 LSW2）
- `VLAN 20`（贴近 PC6）
- `192.168.10.30/24`（贴近 PC3）
- `192.168.10.40/24`（贴近 PC4）
- `192.168.10.50/24`（贴近 PC5）
- `192.168.10.60/24`（贴近 PC6）
- `TRUNK 10`（贴近 LSW2）
- `TRUNK 20`（贴近 LSW3）

## 五、参考答案（从 .model 自动提取，按设备分组）

> 说明：该列表由实验包的「参考答案」文件提取，仅含命令文本、不含缩进层级；
> 部分行是设备默认配置，需结合题目与拓扑判断哪些是本题真正要求下发的配置。

### LSW3

```
sysname LSW3
undo info-center enable
vlan batch 20
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
port trunk allow-pass vlan 20
port link-type access
port default vlan 20
port-isolate enable group 20
```

### LSW1

```
sysname LSW1
undo info-center enable
vlan batch 10 20 100
cluster enable
ntdp enable
ndp enable
drop illegal-mac alarm
diffserv domain default
drop-profile default
vlan 100
aaa
interface Vlanif1
interface Vlanif100
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
aggregate-vlan
access-vlan 10 20
authentication-scheme default
authorization-scheme default
accounting-scheme default
domain default
domain default_admin
local-user admin password simple admin
local-user admin service-type http
ip address 192.168.10.1 255.255.255.0
arp-proxy inter-sub-vlan-proxy enable
arp-proxy inner-sub-vlan-proxy enable
port link-type trunk
port trunk allow-pass vlan 10
port trunk allow-pass vlan 20
```

### LSW2

```
sysname LSW2
undo info-center enable
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
port-isolate enable group 10
```

### AR1

```
sysname AR1
snmp-agent local-engineid 800007DB03000000000000
snmp-agent
clock timezone China-Standard-Time minus 08:00:00
portal local-server load portalpage.zip
drop illegal-mac alarm
set cpu-usage threshold 80 restore 75
aaa
firewall zone Local
interface GigabitEthernet0/0/0
interface GigabitEthernet0/0/1
interface GigabitEthernet0/0/2
interface NULL0
user-interface con 0
user-interface vty 0 4
user-interface vty 16 20
wlan ac
authentication-scheme default
authorization-scheme default
accounting-scheme default
domain default
domain default_admin
local-user admin service-type http
priority 15
ip address 192.168.10.1 255.255.255.128
arp-proxy enable
ip address 192.168.10.129 255.255.255.128
authentication-mode password
```

## 六、验收要点

（待本地模型跑通后回填：需连通的 PC 对、需隔离的 PC 对、关键验证命令）
