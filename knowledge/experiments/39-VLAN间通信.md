# 实验 39：VLAN间通信

- 来源目录：`VLAN间通信`
- 拓扑文件：`VLAN间通信.topo`

## 一、题目要求

要求：按照拓扑图提示信息配置，实现VLAN间互通

## 二、设备清单

| 设备 | 型号 | Console(Telnet)端口 | 关键参数 |
|---|---|---|---|
| AR1 | AR2220 | 2002 | - |
| AR2 | AR2220 | 2001 | - |
| LSW1 | S5700 | 2003 | - |
| LSW2 | S5700 | 2000 | - |
| LSW3 | S5700 | 2004 | - |
| PC1 | PC | - | IP 192.168.10.10/24，网关 192.168.10.1 |
| PC2 | PC | - | IP 192.168.20.10/24，网关 192.168.20.1 |
| PC3 | PC | - | IP 192.168.10.10/24，网关 192.168.10.1 |
| PC4 | PC | - | IP 192.168.20.10/24，网关 192.168.20.1 |
| PC5 | PC | - | IP 192.168.10.10/24，网关 192.168.10.1 |
| PC6 | PC | - | IP 192.168.20.10/24，网关 192.168.20.1 |

## 三、链路连接

- AR2 `GigabitEthernet0/0/0` ↔ LSW2 `GigabitEthernet0/0/1`（Copper）
- LSW2 `GigabitEthernet0/0/2` ↔ PC1 `Ethernet0/0/0`（Copper）
- LSW2 `GigabitEthernet0/0/3` ↔ PC2 `Ethernet0/0/0`（Copper）
- AR1 `GigabitEthernet0/0/0` ↔ LSW1 `GigabitEthernet0/0/1`（Copper）
- AR1 `GigabitEthernet0/0/1` ↔ LSW1 `GigabitEthernet0/0/2`（Copper）
- LSW1 `GigabitEthernet0/0/3` ↔ PC3 `Ethernet0/0/0`（Copper）
- LSW1 `GigabitEthernet0/0/4` ↔ PC4 `Ethernet0/0/0`（Copper）
- LSW3 `GigabitEthernet0/0/1` ↔ PC5 `Ethernet0/0/0`（Copper）
- LSW3 `GigabitEthernet0/0/2` ↔ PC6 `Ethernet0/0/0`（Copper）

## 四、拓扑图上的文字标注

- `192.168.10.10/24`（贴近 PC1）
- `192.168.20.10/24`（贴近 PC2）
- `VLAN 10`（贴近 PC1）
- `VLAN 20`（贴近 PC2）
- `TRUNK 10 20`（贴近 LSW2）
- `单臂路由模式`（贴近 AR2）
- `接口路由模式`（贴近 AR1）
- `192.168.10.10/24`（贴近 PC3）
- `192.168.20.10/24`（贴近 PC4）
- `192.168.10.1/24`（贴近 LSW1）
- `192.168.20.1/24`（贴近 LSW1）
- `VLAN 10`（贴近 PC3）
- `VLAN 10`（贴近 LSW1）
- `VLAN 20`（贴近 PC4）
- `VLAN 20`（贴近 LSW1）
- `三层交换机虚接口模式`（贴近 LSW3）
- `VLAN 10`（贴近 PC5）
- `VLAN 20`（贴近 PC6）
- `192.168.10.10/24`（贴近 PC5）
- `192.168.20.10/24`（贴近 PC6）
- `要求：按照拓扑图提示信息配置，实现VLAN间互通`（贴近 AR1）

## 五、参考答案（从 .model 自动提取，按设备分组）

> 说明：该列表由实验包的「参考答案」文件提取，仅含命令文本、不含缩进层级；
> 部分行是设备默认配置，需结合题目与拓扑判断哪些是本题真正要求下发的配置。

### AR2

```
sysname AR2
snmp-agent local-engineid 800007DB03000000000000
snmp-agent
clock timezone China-Standard-Time minus 08:00:00
portal local-server load portalpage.zip
drop illegal-mac alarm
set cpu-usage threshold 80 restore 75
aaa
firewall zone Local
interface GigabitEthernet0/0/0
interface GigabitEthernet0/0/0.1
interface GigabitEthernet0/0/0.2
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
dot1q termination vid 10
ip address 192.168.10.1 255.255.255.0
arp broadcast enable
dot1q termination vid 20
ip address 192.168.20.1 255.255.255.0
authentication-mode password
```

### LSW1

```
sysname LSW1
undo info-center enable
vlan batch 10 20
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
port link-type access
port default vlan 10
port default vlan 20
```

### LSW2

```
sysname LWS2
undo info-center enable
vlan batch 10 20
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
port trunk allow-pass vlan 10 20
port link-type access
port default vlan 10
port default vlan 20
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
ip address 192.168.10.1 255.255.255.0
ip address 192.168.20.1 255.255.255.0
authentication-mode password
```

### LSW3

```
sysname LWS3
undo info-center enable
vlan batch 10 20
cluster enable
ntdp enable
ndp enable
drop illegal-mac alarm
diffserv domain default
drop-profile default
aaa
interface Vlanif1
interface Vlanif10
interface Vlanif20
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
ip address 192.168.10.1 255.255.255.0
ip address 192.168.20.1 255.255.255.0
port link-type access
port default vlan 10
port default vlan 20
```

## 六、验收要点

（待本地模型跑通后回填：需连通的 PC 对、需隔离的 PC 对、关键验证命令）
