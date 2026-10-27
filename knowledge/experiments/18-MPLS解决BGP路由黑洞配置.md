# 实验 18：MPLS解决BGP路由黑洞配置

- 来源目录：`MPLS解决BGP路由黑洞配置`
- 拓扑文件：`paper.topo`

## 一、题目要求

（题目为空）

## 二、设备清单

| 设备 | 型号 | Console(Telnet)端口 | 关键参数 |
|---|---|---|---|
| AR1 | AR2220 | 2000 | - |
| AR2 | AR2220 | 2001 | - |
| AR3 | AR2220 | 2002 | - |
| AR4 | AR2220 | 2003 | - |
| AR5 | AR2220 | 2004 | - |
| PC1 | PC | - | IP 200.200.10.10/24，网关 200.200.10.1 |
| PC2 | PC | - | IP 200.200.50.10/24，网关 200.200.50.1 |

## 三、链路连接

- AR4 `GigabitEthernet0/0/1` ↔ AR5 `GigabitEthernet0/0/0`（Copper）
- AR5 `GigabitEthernet0/0/1` ↔ PC2 `Ethernet0/0/0`（Copper）
- AR4 `GigabitEthernet0/0/0` ↔ AR3 `GigabitEthernet0/0/1`（Copper）
- AR1 `GigabitEthernet0/0/1` ↔ PC1 `Ethernet0/0/0`（Copper）
- AR1 `GigabitEthernet0/0/0` ↔ AR2 `GigabitEthernet0/0/0`（Copper）
- AR2 `GigabitEthernet0/0/1` ↔ AR3 `GigabitEthernet0/0/0`（Copper）

## 四、拓扑图上的文字标注

- `200.200.12.0/24`（贴近 AR2）
- `1`（贴近 AR1）
- `2`（贴近 AR2）
- `EBGP`（贴近 AR2）
- `100.100.23.0/24`（贴近 AR3）
- `2`（贴近 AR2）
- `4`（贴近 AR4）
- `2`（贴近 AR2）
- `3`（贴近 AR3）
- `3`（贴近 AR3）
- `4`（贴近 AR4）
- `AS100`（贴近 AR1）
- `AS200`（贴近 AR4）
- `AS300`（贴近 AR5）
- `100.100.34.0/24`（贴近 AR4）
- `200.200.45.0/24`（贴近 AR5）
- `4`（贴近 AR4）
- `5`（贴近 AR5）
- `200.200.10.0/24`（贴近 PC1）
- `1`（贴近 AR1）
- `10`（贴近 PC1）
- `1`（贴近 AR5）
- `10`（贴近 PC2）
- `200.200.50.0/24`（贴近 PC2）
- `ROUTER-ID 1.1.1.1`（贴近 AR1）
- `ROUTER-ID 5.5.5.5`（贴近 AR5）
- `按照下面拓扑要求配置设备，是PC与PC2互通`（贴近 AR2）

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
aaa
firewall zone Local
interface GigabitEthernet0/0/0
interface GigabitEthernet0/0/1
interface GigabitEthernet0/0/2
interface NULL0
bgp 100
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
ip address 200.200.12.1 255.255.255.0
ip address 200.200.10.1 255.255.255.0
router-id 1.1.1.1
peer 200.200.12.2 as-number 200
ipv4-family unicast
authentication-mode password
undo synchronization
network 200.200.10.0
peer 200.200.12.2 enable
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
mpls lsr-id 4.4.4.4
mpls
mpls ldp
aaa
firewall zone Local
interface GigabitEthernet0/0/0
interface GigabitEthernet0/0/1
interface GigabitEthernet0/0/2
interface NULL0
interface LoopBack0
bgp 200
ospf 1
ip ip-prefix test index 10 permit 200.200.10.0 24
permit 200.200.10.0 24
End with
route recursive-lookup tunnel ip-prefix test
route recursive-lookup tunnel ip-prefix
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
ip address 100.100.34.4 255.255.255.0
ip address 200.200.45.4 255.255.255.0
ip address 4.4.4.4 255.255.255.255
router-id 4.4.4.4
peer 2.2.2.2 as-number 200
peer 2.2.2.2 connect-interface LoopBack0
peer 200.200.45.5 as-number 300
ipv4-family unicast
area 0.0.0.0
authentication-mode password
undo synchronization
peer 2.2.2.2 enable
peer 2.2.2.2 next-hop-local
peer 200.200.45.5 enable
network 4.4.4.4 0.0.0.0
network 100.100.34.0 0.0.0.255
```

### AR3

```
sysname AR3
snmp-agent local-engineid 800007DB03000000000000
snmp-agent
clock timezone China-Standard-Time minus 08:00:00
portal local-server load portalpage.zip
drop illegal-mac alarm
set cpu-usage threshold 80 restore 75
mpls lsr-id 3.3.3.3
mpls
mpls ldp
aaa
firewall zone Local
interface GigabitEthernet0/0/0
interface GigabitEthernet0/0/1
interface GigabitEthernet0/0/2
interface NULL0
interface LoopBack0
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
ip address 100.100.23.3 255.255.255.0
ip address 100.100.34.3 255.255.255.0
ip address 3.3.3.3 255.255.255.255
area 0.0.0.0
authentication-mode password
network 0.0.0.0 255.255.255.255
```

### AR5

```
sysname AR5
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
bgp 300
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
ip address 200.200.45.5 255.255.255.0
ip address 200.200.50.1 255.255.255.0
router-id 5.5.5.5
peer 200.200.45.4 as-number 200
ipv4-family unicast
authentication-mode password
undo synchronization
network 200.200.50.0
peer 200.200.45.4 enable
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
mpls lsr-id 2.2.2.2
mpls
mpls ldp
aaa
firewall zone Local
interface GigabitEthernet0/0/0
interface GigabitEthernet0/0/1
interface GigabitEthernet0/0/2
interface NULL0
interface LoopBack0
bgp 200
ospf 1
ip ip-prefix test index 10 permit 200.200.50.0 24
permit 200.200.50.0 24
End with
route recursive-lookup tunnel ip-prefix test
route recursive-lookup tunnel ip-prefix
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
ip address 200.200.12.2 255.255.255.0
ip address 100.100.23.2 255.255.255.0
ip address 2.2.2.2 255.255.255.255
router-id 2.2.2.2
peer 4.4.4.4 as-number 200
peer 4.4.4.4 connect-interface LoopBack0
peer 200.200.12.1 as-number 100
ipv4-family unicast
area 0.0.0.0
authentication-mode password
undo synchronization
peer 4.4.4.4 enable
peer 4.4.4.4 next-hop-local
peer 200.200.12.1 enable
network 2.2.2.2 0.0.0.0
network 100.100.23.0 0.0.0.255
```

## 六、验收要点

（待本地模型跑通后回填：需连通的 PC 对、需隔离的 PC 对、关键验证命令）
