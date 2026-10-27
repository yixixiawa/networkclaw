# 实验 05：DHCP服务器配置

- 来源目录：`DHCP服务器配置`
- 拓扑文件：`DHCP服务器配置练习拓扑.topo`

## 一、题目要求

（题目为空）

## 二、设备清单

| 设备 | 型号 | Console(Telnet)端口 | 关键参数 |
|---|---|---|---|
| AR1 | AR2220 | 2001 | - |
| AR4 | AR2220 | 2006 | - |
| AR5 | AR2220 | 2004 | - |
| LSW1 | S5700 | 2000 | - |
| LSW2 | S5700 | 2002 | - |
| LSW3 | S5700 | 2003 | - |
| LSW4 | S5700 | 2005 | - |
| PC1 | PC | - | - |
| PC2 | PC | - | - |
| PC3 | PC | - | - |
| PC4 | PC | - | - |
| PC5 | PC | - | - |
| PC6 | PC | - | - |
| PC7 | PC | - | IP 192.168.1.254/24，网关 192.168.1.1 |

## 三、链路连接

- LSW1 `GigabitEthernet0/0/1` ↔ PC1 `Ethernet0/0/0`（Copper）
- LSW1 `GigabitEthernet0/0/2` ↔ PC2 `Ethernet0/0/0`（Copper）
- LSW2 `GigabitEthernet0/0/1` ↔ LSW1 `GigabitEthernet0/0/3`（Copper）
- LSW2 `GigabitEthernet0/0/2` ↔ LSW3 `GigabitEthernet0/0/1`（Copper）
- LSW3 `GigabitEthernet0/0/2` ↔ PC5 `Ethernet0/0/0`（Copper）
- LSW3 `GigabitEthernet0/0/3` ↔ PC6 `Ethernet0/0/0`（Copper）
- AR1 `GigabitEthernet0/0/0` ↔ PC3 `Ethernet0/0/0`（Copper）
- AR1 `GigabitEthernet0/0/1` ↔ PC4 `Ethernet0/0/0`（Copper）
- PC7 `Ethernet0/0/0` ↔ LSW4 `GigabitEthernet0/0/1`（Copper）
- LSW4 `GigabitEthernet0/0/3` ↔ AR4 `GigabitEthernet0/0/0`（Copper）
- AR4 `GigabitEthernet0/0/1` ↔ AR5 `GigabitEthernet0/0/0`（Copper）

## 四、拓扑图上的文字标注

- `192.168.10.1/24`（贴近 PC3）
- `192.168.20.1/24`（贴近 PC4）
- `VLAN 10`（贴近 LSW1）
- `VLAN 20`（贴近 PC2）
- `VLAN 10`（贴近 LSW3）
- `VLAN 20`（贴近 PC6）
- `TRUNK 10 20`（贴近 LSW1）
- `TRUNK 10 20`（贴近 LSW3）
- `DHCP服务器`（贴近 AR5）
- `192.168.10.1/24`（贴近 AR4）
- `192.168.20.1/24`（贴近 AR4）
- `192.168.20.2/24`（贴近 AR5）

## 五、参考答案（从 .model 自动提取，按设备分组）

> 说明：该列表由实验包的「参考答案」文件提取，仅含命令文本、不含缩进层级；
> 部分行是设备默认配置，需结合题目与拓扑判断哪些是本题真正要求下发的配置。

### AR5

```
sysname AR5
snmp-agent local-engineid 800007DB03000000000000
snmp-agent
clock timezone China-Standard-Time minus 08:00:00
portal local-server load portalpage.zip
drop illegal-mac alarm
set cpu-usage threshold 80 restore 75
dhcp enable
ip pool LAN1
aaa
firewall zone Local
interface GigabitEthernet0/0/0
interface GigabitEthernet0/0/1
interface GigabitEthernet0/0/2
interface NULL0
ip route-static 0.0.0.0 0.0.0.0 192.168.20.1
user-interface con 0
user-interface vty 0 4
user-interface vty 16 20
wlan ac
gateway-list 192.168.1.1
network 192.168.1.0 mask 255.255.255.0
dns-list 114.114.114.114
dns-list
Begin with
authentication-scheme default
authorization-scheme default
accounting-scheme default
domain default
domain default_admin
local-user admin service-type http
priority 15
ip address 192.168.20.2 255.255.255.0
dhcp select global
authentication-mode password
```

### LSW2

```
sysname LSW2
vlan batch 10 20
cluster enable
ntdp enable
ndp enable
drop illegal-mac alarm
dhcp enable
diffserv domain default
drop-profile default
ip pool vlan10
ip pool vlan20
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
gateway-list 192.168.10.254
network 192.168.10.0 mask 255.255.255.0
excluded-ip-address 192.168.10.200 192.168.10.253
lease day 0 hour 12 minute 0
dns-list 8.8.8.8
dns-list
Begin with
gateway-list 192.168.20.1
network 192.168.20.0 mask 255.255.255.0
lease day 1 hour 12 minute 0
authentication-scheme default
authorization-scheme default
accounting-scheme default
domain default
domain default_admin
local-user admin password simple admin
local-user admin service-type http
ip address 192.168.10.1 255.255.255.0
dhcp select global
ip address 192.168.20.1 255.255.255.0
port link-type trunk
port trunk allow-pass vlan 10 20
```

### AR4

```
sysname AR4
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
ip route-static 192.168.1.0 255.255.255.0 192.168.10.2
ip route-static
Begin with
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
port link-type access
port default vlan 10
port default vlan 20
port link-type trunk
port trunk allow-pass vlan 10 20
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
dhcp enable
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
dhcp select interface
dhcp server lease day 0 hour 12 minute 0
dhcp server dns-list 114.114.114.114 8.8.8.8
dhcp server dns
Begin with
ip address 192.168.20.1 255.255.255.0
dhcp server dns-list
authentication-mode password
```

### LSW4

```
sysname LSW4
vlan batch 10
cluster enable
ntdp enable
ndp enable
drop illegal-mac alarm
dhcp enable
diffserv domain default
drop-profile default
aaa
interface Vlanif1
interface Vlanif10
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
ip route-static 192.168.20.0 255.255.255.0 192.168.10.1
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
dhcp select relay
dhcp relay server-ip 192.168.20.2
dhcp relay
Begin with
ip address 192.168.10.2 255.255.255.0
port link-type access
port default vlan 10
```

### LSW3

```
sysname LSW3
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

## 六、验收要点

（待本地模型跑通后回填：需连通的 PC 对、需隔离的 PC 对、关键验证命令）
