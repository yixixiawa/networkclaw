# 实验 04：dhcp_snooping配置

- 来源目录：`dhcp_snooping配置`
- 拓扑文件：`DHCP SNOOPING配置拓扑.topo`

## 一、题目要求

（题目为空）

## 二、设备清单

| 设备 | 型号 | Console(Telnet)端口 | 关键参数 |
|---|---|---|---|
| AR1 | AR2220 | 2001 | - |
| AR2 | AR2220 | 2002 | - |
| CORE | S5700 | 2003 | - |
| LSW1 | S5700 | 2000 | - |
| PC1 | PC | - | IP 192.168.1.253/24，网关 192.168.1.1 |
| PC2 | PC | - | IP 192.168.10.253/24，网关 192.168.10.1 |
| PC3 | PC | - | IP 192.168.1.254/24，网关 192.168.1.1 |

## 三、链路连接

- LSW1 `GigabitEthernet0/0/2` ↔ PC1 `Ethernet0/0/0`（Copper）
- LSW1 `GigabitEthernet0/0/3` ↔ PC2 `Ethernet0/0/0`（Copper）
- PC3 `Ethernet0/0/0` ↔ LSW1 `GigabitEthernet0/0/4`（Copper）
- LSW1 `GigabitEthernet0/0/1` ↔ CORE `GigabitEthernet0/0/1`（Copper）
- LSW1 `GigabitEthernet0/0/5` ↔ AR1 `GigabitEthernet0/0/0`（Copper）
- LSW1 `GigabitEthernet0/0/6` ↔ AR2 `GigabitEthernet0/0/0`（Copper）

## 四、拓扑图上的文字标注

- `vlan 10`（贴近 PC2）
- `TRUNK 1 10`（贴近 LSW1）
- `VLAN 1`（贴近 PC1）
- `VLAN 1`（贴近 LSW1）
- `VLAN 1`（贴近 AR1）
- `172.16.1.1/24`（贴近 AR1）
- `vlan 10`（贴近 AR2）
- `172.16.10.1/24`（贴近 AR2）

## 五、参考答案（从 .model 自动提取，按设备分组）

> 说明：该列表由实验包的「参考答案」文件提取，仅含命令文本、不含缩进层级；
> 部分行是设备默认配置，需结合题目与拓扑判断哪些是本题真正要求下发的配置。

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
ip address 172.16.1.1 255.255.255.0
dhcp select interface
authentication-mode password
```

### LSW1

```
sysname LSW1
undo info-center enable
vlan batch 10
stp disable
cluster enable
ntdp enable
ndp enable
drop illegal-mac alarm
dhcp enable
dhcp snooping enable
user-bind static ip-address 192.168.1.10 interface GigabitEthernet0/0/4
diffserv domain default
drop-profile default
vlan 1
vlan 10
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
dhcp snooping check dhcp-chaddr enable
dhcp snooping trusted interface GigabitEthernet0/0/1
ip source check user-bind enable
authentication-scheme default
authorization-scheme default
accounting-scheme default
domain default
domain default_admin
local-user admin password simple admin
local-user admin service-type http
port link-type trunk
port trunk allow-pass vlan 10
dhcp snooping trusted
port link-type access
port default vlan 10
```

### CORE

```
sysname CORE
undo info-center enable
vlan batch 10
stp disable
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
dhcp select interface
ip address 192.168.10.1 255.255.255.0
port link-type trunk
port trunk allow-pass vlan 10
port link-type access
port default vlan 10
```

### AR2

```
sysname AR2
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
ip address 172.16.10.1 255.255.255.0
dhcp select interface
authentication-mode password
```

## 六、验收要点

（待本地模型跑通后回填：需连通的 PC 对、需隔离的 PC 对、关键验证命令）
