# 实验 17：MPLS_VPN配置练习

- 来源目录：`MPLS_VPN配置练习`
- 拓扑文件：`paper.topo`

## 一、题目要求

配置要求：
按照拓扑图中信息完成MPLS VPN 配置，使得A公司与其办事处、B公司与其办事处分别实现互通。

提交资料：
1、在CE1中查看路由表，观察是否有A公司办事处网络路由，截图提交；
2、在PE2查看BGP VPNV4 全部路由，指出哪些路由是B公司网络路由；
3、提交 ans文档。

## 二、设备清单

| 设备 | 型号 | Console(Telnet)端口 | 关键参数 |
|---|---|---|---|
| CE1 | AR2220 | 2004 | - |
| CE2 | AR2220 | 2005 | - |
| CE3 | AR2220 | 2006 | - |
| CE4 | AR2220 | 2007 | - |
| P1 | AR2220 | 2001 | - |
| P2 | AR2220 | 2002 | - |
| PC3 | PC | - | IP 192.168.1.10/24，网关 192.168.1.1 |
| PC4 | PC | - | IP 192.168.100.10/24，网关 192.168.10.1 |
| PC5 | PC | - | IP 192.168.1.10/24，网关 192.168.1.1 |
| PC6 | PC | - | IP 192.168.200.10/24，网关 192.168.10.1 |
| PE1 | AR2220 | 2000 | - |
| PE2 | AR2220 | 2003 | - |

## 三、链路连接

- P1 `GigabitEthernet0/0/1` ↔ P2 `GigabitEthernet0/0/0`（Copper）
- P2 `GigabitEthernet0/0/1` ↔ PE2 `GigabitEthernet0/0/0`（Copper）
- PE1 `GigabitEthernet0/0/0` ↔ P1 `GigabitEthernet0/0/0`（Copper）
- PE1 `GigabitEthernet0/0/1` ↔ CE1 `GigabitEthernet0/0/0`（Copper）
- PE1 `GigabitEthernet0/0/2` ↔ CE2 `GigabitEthernet0/0/0`（Copper）
- PE2 `GigabitEthernet0/0/1` ↔ CE3 `GigabitEthernet0/0/0`（Copper）
- PE2 `GigabitEthernet0/0/2` ↔ CE4 `GigabitEthernet0/0/0`（Copper）
- CE1 `GigabitEthernet0/0/1` ↔ PC3 `Ethernet0/0/0`（Copper）
- CE3 `GigabitEthernet0/0/1` ↔ PC4 `Ethernet0/0/0`（Copper）
- CE2 `GigabitEthernet0/0/1` ↔ PC5 `Ethernet0/0/0`（Copper）
- CE4 `GigabitEthernet0/0/1` ↔ PC6 `Ethernet0/0/0`（Copper）

## 四、拓扑图上的文字标注

- `1.16.2.2/30`（贴近 CE2）
- `1.16.2.1/30`（贴近 PE1）
- `1.17.2.2/30`（贴近 CE4）
- `192.168.100.10/24`（贴近 PC4）
- `lo0:1.1.1.1/32`（贴近 PE1）
- `lo0:2.2.2.2/32`（贴近 P1）
- `lo0:3.3.3.3/32`（贴近 P2）
- `lo0:4.4.4.4/32`（贴近 PE2）
- `1.10.12.1/24`（贴近 P1）
- `1.10.12.2/24`（贴近 P1）
- `1.10.23.1/24`（贴近 P2）
- `1.10.23.2/24`（贴近 P2）
- `1.10.34.1/24`（贴近 P2）
- `1.10.34.2/24`（贴近 PE2）
- `MPLS骨干网 AS100`（贴近 P2）
- `B公司总部`（贴近 CE2）
- `A公司办事处`（贴近 CE3）
- `A公司总部`（贴近 CE1）
- `B公司办事处`（贴近 CE4）
- `1.17.1.1/30`（贴近 PE2）
- `1.17.2.1/30`（贴近 CE4）
- `1.16.1.2/30`（贴近 CE1）
- `1.16.1.1/30`（贴近 PE1）
- `1.17.1.2/30`（贴近 CE3）
- `192.168.1.10/24`（贴近 PC3）
- `192.168.1.10/24`（贴近 PC5）
- `192.168.200.10/24`（贴近 PC6）
- `BGP`（贴近 PE1）
- `OSPF`（贴近 PE2）
- `AS65540`（贴近 CE1）
- `OSPF`（贴近 CE2）
- `静态路由`（贴近 CE4）
- `IS-IS`（贴近 P2）
- `0000.0000.0002.00`（贴近 P1）
- `0000.0000.0003.00`（贴近 P2）
- `48.0001`（贴近 P2）
- `48.0002`（贴近 P1）
- `48.0003`（贴近 PE2）
- `0000.0000.0001.00`（贴近 PE1）
- `0000.0000.0004.00`（贴近 PE2）

## 五、参考答案（从 .model 自动提取，按设备分组）

> 说明：该列表由实验包的「参考答案」文件提取，仅含命令文本、不含缩进层级；
> 部分行是设备默认配置，需结合题目与拓扑判断哪些是本题真正要求下发的配置。

### CE2

```
sysname CE2
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
ospf
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
ip address 1.16.2.2 255.255.255.252
ip address 192.168.1.1 255.255.255.0
area 0.0.0.0
authentication-mode password
network 0.0.0.0 255.255.255.255
network
```

### PE1

```
sysname PE1
snmp-agent local-engineid 800007DB03000000000000
snmp-agent
clock timezone China-Standard-Time minus 08:00:00
portal local-server load portalpage.zip
drop illegal-mac alarm
set cpu-usage threshold 80 restore 75
ip vpn-instance A
ip vpn-instance
Begin with
ip vpn-instance B
mpls lsr-id 1.1.1.1
mpls
mpls ldp
aaa
isis 1
isis
firewall zone Local
interface GigabitEthernet0/0/0
interface GigabitEthernet0/0/1
interface GigabitEthernet0/0/2
interface NULL0
interface LoopBack0
bgp 100
ospf 1 vpn-instance B
vpn-instance B
End with
user-interface con 0
user-interface vty 0 4
user-interface vty 16 20
wlan ac
ipv4-family
authentication-scheme default
authorization-scheme default
accounting-scheme default
domain default
domain default_admin
local-user admin service-type http
network-entity 48.0002.0000.0000.0001.00
priority 15
ip address 1.10.12.1 255.255.255.0
isis enable 1
isis enable
isis circuit-level level-2
ip binding vpn-instance A
ip binding vpn-instance
ip address 1.16.1.1 255.255.255.252
ip binding vpn-instance B
ip address 1.16.2.1 255.255.255.252
ip address 1.1.1.1 255.255.255.255
router-id 1.1.1.1
undo default ipv4-unicast
peer 4.4.4.4 as-number 100
peer 4.4.4.4 connect-interface LoopBack0
ipv4-family unicast
ipv4-family vpnv4
ipv4-family vpn-instance A
ipv4-family vpn-instance B
import-route bgp
area 0.0.0.0
authentication-mode password
route-distinguisher 100:100
vpn-target 300:100 export-extcommunity
vpn-target 100:100 import-extcommunity
route-distinguisher 100:200
vpn-target 400:100 export-extcommunity
vpn-target 200:100 import-extcommunity
undo synchronization
undo peer 4.4.4.4 enable
policy vpn-target
peer 4.4.4.4 enable
router-id 1.16.1.1
peer 1.16.1.2 as-number 65540
import-route ospf 1
import-route ospf
network 1.16.2.1 0.0.0.0
sysname P2
mpls lsr-id 3.3.3.3
is-level level-2
network-entity 48.0001.0000.0000.0003.00
ip address 1.10.23.2 255.255.255.0
ip address 1.10.34.1 255.255.255.0
ip address 3.3.3.3 255.255.255.255
```

### CE1

```
sysname CE1
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
bgp 65540
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
ip address 1.16.1.2 255.255.255.252
ip address 192.168.1.1 255.255.255.0
router-id 1.16.1.2
peer 1.16.1.1 as-number 100
ipv4-family unicast
authentication-mode password
undo synchronization
network 192.168.1.0
peer 1.16.1.1 enable
```

### PE2

```
sysname PE2
snmp-agent local-engineid 800007DB03000000000000
snmp-agent
clock timezone China-Standard-Time minus 08:00:00
portal local-server load portalpage.zip
drop illegal-mac alarm
set cpu-usage threshold 80 restore 75
ip vpn-instance A
ip vpn-instance
Begin with
ip vpn-instance B
mpls lsr-id 4.4.4.4
mpls
mpls ldp
aaa
isis 1
isis
firewall zone Local
interface GigabitEthernet0/0/0
interface GigabitEthernet0/0/1
interface GigabitEthernet0/0/2
interface NULL0
interface LoopBack0
bgp 100
ospf 1 vpn-instance A
vpn-instance
Include
ip route-static vpn-instance B 192.168.200.0 255.255.255.0 1.17.2.2
ip route-static vpn-instance
user-interface con 0
user-interface vty 0 4
user-interface vty 16 20
wlan ac
ipv4-family
authentication-scheme default
authorization-scheme default
accounting-scheme default
domain default
domain default_admin
local-user admin service-type http
network-entity 48.0003.0000.0000.0004.00
priority 15
ip address 1.10.34.2 255.255.255.0
isis enable 1
isis enable
isis circuit-level level-2
ip binding vpn-instance A
ip binding vpn-instance
ip address 1.17.1.1 255.255.255.252
ip binding vpn-instance B
ip address 1.17.2.1 255.255.255.252
ip address 4.4.4.4 255.255.255.255
router-id 4.4.4.4
undo default ipv4-unicast
peer 1.1.1.1 as-number 100
peer 1.1.1.1 connect-interface LoopBack0
ipv4-family unicast
ipv4-family vpnv4
ipv4-family vpn-instance A
ipv4-family vpn-instance B
import-route bgp
area 0.0.0.0
authentication-mode password
route-distinguisher 100:300
vpn-target 100:100 export-extcommunity
vpn-target 300:100 import-extcommunity
route-distinguisher 100:400
vpn-target 200:100 export-extcommunity
vpn-target 400:100 import-extcommunity
undo synchronization
undo peer 1.1.1.1 enable
policy vpn-target
peer 1.1.1.1 enable
import-route ospf 1
import-route ospf
import-route static
network 1.17.1.1 0.0.0.0
network
sysname P1
mpls lsr-id 2.2.2.2
is-level level-2
network-entity 48.0001.0000.0000.0002.00
ip address 1.10.12.2 255.255.255.0
ip address 1.10.23.1 255.255.255.0
ip address 2.2.2.2 255.255.255.255
```

### CE4

```
sysname CE4
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
ip route-static 192.168.1.0 255.255.255.0 1.17.2.1
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
ip address 1.17.2.2 255.255.255.252
ip address 192.168.10.1 255.255.255.0
authentication-mode password
```

### CE3

```
sysname CE3
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
ospf
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
ip address 1.17.1.2 255.255.255.252
ip address 192.168.100.1 255.255.255.0
area 0.0.0.0
authentication-mode password
network 0.0.0.0 255.255.255.255
network
```

## 六、验收要点

（待本地模型跑通后回填：需连通的 PC 对、需隔离的 PC 对、关键验证命令）
