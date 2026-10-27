# 实验 42：VRRP基本配置_-_交换机

- 来源目录：`VRRP基本配置_-_交换机`
- 拓扑文件：`paper.topo`

## 一、题目要求

（题目为空）

## 二、设备清单

| 设备 | 型号 | Console(Telnet)端口 | 关键参数 |
|---|---|---|---|
| AR1 | AR2220 | 2003 | - |
| LSW1 | S5700 | 2001 | - |
| LSW2 | S5700 | 2000 | - |
| LSW3 | S5700 | 2002 | - |
| PC1 | PC | - | IP 192.168.1.10/24，网关 192.168.1.254 |
| PC2 | PC | - | IP 172.16.1.10/24，网关 172.16.1.254 |
| PC3 | PC | - | IP 192.168.3.10/24，网关 192.168.3.1 |

## 三、链路连接

- LSW1 `GigabitEthernet0/0/3` ↔ PC1 `Ethernet0/0/0`（Copper）
- LSW1 `GigabitEthernet0/0/4` ↔ PC2 `Ethernet0/0/0`（Copper）
- PC3 `Ethernet0/0/0` ↔ AR1 `GigabitEthernet0/0/2`（Copper）
- LSW2 `GigabitEthernet0/0/1` ↔ LSW1 `GigabitEthernet0/0/1`（Copper）
- LSW3 `GigabitEthernet0/0/1` ↔ LSW1 `GigabitEthernet0/0/2`（Copper）
- LSW3 `GigabitEthernet0/0/24` ↔ AR1 `GigabitEthernet0/0/1`（Copper）
- LSW2 `GigabitEthernet0/0/24` ↔ AR1 `GigabitEthernet0/0/0`（Copper）

## 四、拓扑图上的文字标注

- `OSPF`（贴近 AR1）
- `vlan 100`（贴近 LSW2）
- `vlan 200`（贴近 LSW3）
- `10.10.13.3/24`（贴近 AR1）
- `10.10.23.3/24`（贴近 LSW3）
- `192.168.1.10/24`（贴近 PC1）
- `172.16.1.10/24`（贴近 PC2）
- `192.168.3.10/24`（贴近 PC3）
- `192.168.3.1/24`（贴近 AR1）
- `VLAN 10`（贴近 PC1）
- `VLAN 20`（贴近 PC2）
- `TRUNK ALL`（贴近 LSW1）
- `TRUNK ALL`（贴近 LSW3）

## 五、参考答案（从 .model 自动提取，按设备分组）

> 说明：该列表由实验包的「参考答案」文件提取，仅含命令文本、不含缩进层级；
> 部分行是设备默认配置，需结合题目与拓扑判断哪些是本题真正要求下发的配置。

### LSW2

```
sysname LSW2
vlan batch 10 20 100
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
ospf 1
user-interface con 0
user-interface vty 0 4
authentication-scheme default
authorization-scheme default
accounting-scheme default
domain default
domain default_admin
local-user admin password simple admin
local-user admin service-type http
ip address 192.168.1.1 255.255.255.0
vrrp vrid 10 virtual-ip 192.168.1.254
vrrp vrid 10 priority 120
vrrp vrid 10 preempt-mode timer delay 20
ip address 172.16.1.1 255.255.255.0
vrrp vrid 20 virtual-ip 172.16.1.254
vrrp vrid 20 priority 120
vrrp vrid 20 preempt-mode disable
ip address 10.10.13.1 255.255.255.0
port link-type trunk
port trunk allow-pass vlan 2 to 4094
port link-type access
port default vlan 100
area 0.0.0.0
network 0.0.0.0 255.255.255.255
```

### LSW3

```
sysname LSW3
vlan batch 10 20 200
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
interface Vlanif200
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
ospf 1
user-interface con 0
user-interface vty 0 4
authentication-scheme default
authorization-scheme default
accounting-scheme default
domain default
domain default_admin
local-user admin password simple admin
local-user admin service-type http
ip address 192.168.1.2 255.255.255.0
vrrp vrid 10 virtual-ip 192.168.1.254
ip address 172.16.1.2 255.255.255.0
vrrp vrid 20 virtual-ip 172.16.1.254
ip address 10.10.23.2 255.255.255.0
port link-type trunk
port trunk allow-pass vlan 2 to 4094
port link-type access
port default vlan 200
area 0.0.0.0
network 0.0.0.0 255.255.255.255
network
Begin with
```

### LSW1

```
sysname LSW1
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
port trunk allow-pass vlan 2 to 4094
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
ospf 1
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
ip address 10.10.13.3 255.255.255.0
ip address 10.10.23.3 255.255.255.0
ip address 192.168.3.1 255.255.255.0
area 0.0.0.0
authentication-mode password
network 0.0.0.0 255.255.255.255
network
Begin with
```

## 六、验收要点

（待本地模型跑通后回填：需连通的 PC 对、需隔离的 PC 对、关键验证命令）
