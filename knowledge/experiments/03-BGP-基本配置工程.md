# 实验 03：BGP-基本配置工程

- 来源目录：`BGP-基本配置工程`
- 拓扑文件：`paper.topo`

## 一、题目要求

1、基本配置
（1）配置各路由器的名称（AR序号-学号后三位，如AR1-101）及相关地址
（2）IGP使用OSPF协议（区域0）
2、配置BGP协议
（1）配置EBGP
（2）使用环路接口配置IBGP
（3）把172.16.20.0 通过import命令发布到BGP
（4）把192.168.10.0 通过network命令发布到BGP
（5）在AR3上引入OSPF协议 
（6）在AR2配置EBGP路由IBGP对等体为Next-Hop-local

## 二、设备清单

| 设备 | 型号 | Console(Telnet)端口 | 关键参数 |
|---|---|---|---|
| AR1 | AR2220 | 2000 | - |
| AR2 | AR2220 | 2001 | - |
| AR3 | AR2220 | 2002 | - |
| PC1 | PC | - | IP 192.168.10.10/24，网关 192.168.10.1 |
| PC2 | PC | - | IP 172.16.1.10/24，网关 172.16.1.1 |

## 三、链路连接

- AR1 `GigabitEthernet0/0/0` ↔ AR2 `GigabitEthernet0/0/0`（Copper）
- AR3 `GigabitEthernet0/0/1` ↔ AR2 `GigabitEthernet0/0/1`（Copper）
- PC1 `Ethernet0/0/0` ↔ AR1 `GigabitEthernet0/0/1`（Copper）
- AR3 `GigabitEthernet0/0/0` ↔ PC2 `Ethernet0/0/0`（Copper）

## 四、拓扑图上的文字标注

- `lo0：2.2.2.2/32`（贴近 AR2）
- `Lo0:3.3.3.3/32`（贴近 AR3）
- `10.10.23.0/24`（贴近 AR3）
- `2`（贴近 AR2）
- `3`（贴近 AR3）
- `10.10.12.0/24`（贴近 AR2）
- `1`（贴近 AR1）
- `2`（贴近 AR2）
- `lo0:1.1.1.1/32`（贴近 AR1）
- `AS 65009`（贴近 AR1）
- `AS 65008`（贴近 AR3）
- `IBGP`（贴近 AR3）
- `EBGP`（贴近 AR2）
- `192.168.10.0/24`（贴近 AR1）
- `1`（贴近 AR1）
- `10`（贴近 PC1）
- `172.16.1.0/24`（贴近 PC2）
- `1`（贴近 AR3）
- `10`（贴近 PC2）

## 五、参考答案（从 .model 自动提取，按设备分组）

> 说明：该列表由实验包的「参考答案」文件提取，仅含命令文本、不含缩进层级；
> 部分行是设备默认配置，需结合题目与拓扑判断哪些是本题真正要求下发的配置。

### AR1

```
sysname AR1
Include
snmp-agent local-engineid 800007DB03000000000000
snmp-agent
clock timezone China-Standard-Time minus 08:00:00
portal local-server load flash:/portalpage.zip
drop illegal-mac alarm
undo info-center enable
wlan ac-global carrier id other ac id 0
set cpu-usage threshold 80 restore 75
aaa
firewall zone Local
interface GigabitEthernet0/0/0
interface GigabitEthernet0/0/1
interface GigabitEthernet0/0/2
interface NULL0
interface LoopBack0
bgp 65009
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
ip address 10.10.12.1 255.255.255.0
ip address 192.168.10.1 255.255.255.0
ip address 1.1.1.1 255.255.255.255
router-id 1.1.1.1
peer 10.10.12.2 as-number 65008
ipv4-family unicast
authentication-mode password
undo synchronization
network 1.1.1.1 255.255.255.255
network 192.168.10.0
peer 10.10.12.2 enable
```

### AR3

```
sysname AR3
Include
snmp-agent local-engineid 800007DB03000000000000
snmp-agent
clock timezone China-Standard-Time minus 08:00:00
portal local-server load flash:/portalpage.zip
drop illegal-mac alarm
undo info-center enable
wlan ac-global carrier id other ac id 0
set cpu-usage threshold 80 restore 75
aaa
firewall zone Local
interface GigabitEthernet0/0/0
interface GigabitEthernet0/0/1
interface GigabitEthernet0/0/2
interface NULL0
interface LoopBack0
bgp 65008
ospf 1 router-id 3.3.3.3
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
ip address 10.10.23.3 255.255.255.0
ip address 3.3.3.3 255.255.255.255
router-id 3.3.3.3
peer 2.2.2.2 as-number 65008
peer 2.2.2.2 connect-interface LoopBack0
ipv4-family unicast
area 0.0.0.0
authentication-mode password
undo synchronization
import-route direct
import-route ospf 1
peer 2.2.2.2 enable
network 3.3.3.3 0.0.0.0
network 10.10.23.0 0.0.0.255
```

### AR2

```
sysname AR2
Include
snmp-agent local-engineid 800007DB03000000000000
snmp-agent
clock timezone China-Standard-Time minus 08:00:00
portal local-server load flash:/portalpage.zip
drop illegal-mac alarm
undo info-center enable
wlan ac-global carrier id other ac id 0
set cpu-usage threshold 80 restore 75
aaa
firewall zone Local
interface GigabitEthernet0/0/0
interface GigabitEthernet0/0/1
interface GigabitEthernet0/0/2
interface NULL0
interface LoopBack0
bgp 65008
ospf 1 router-id 2.2.2.2
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
ip address 10.10.12.2 255.255.255.0
ip address 10.10.23.2 255.255.255.0
ip address 2.2.2.2 255.255.255.255
router-id 2.2.2.2
peer 3.3.3.3 as-number 65008
peer 3.3.3.3 connect-interface LoopBack0
peer 10.10.12.1 as-number 65009
ipv4-family unicast
area 0.0.0.0
authentication-mode password
undo synchronization
peer 3.3.3.3 enable
peer 3.3.3.3 next-hop-local
peer 10.10.12.1 enable
network 2.2.2.2 0.0.0.0
network 10.10.23.0 0.0.0.255
```

## 六、验收要点

（待本地模型跑通后回填：需连通的 PC 对、需隔离的 PC 对、关键验证命令）
