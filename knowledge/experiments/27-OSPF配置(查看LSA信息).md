# 实验 27：OSPF配置(查看LSA信息)

- 来源目录：`OSPF配置(查看LSA信息)`
- 拓扑文件：`paper.topo`

## 一、题目要求

要求：
请按照拓扑图信息完成各设备接口及路由配置，使得拓扑图中所有网络都能互通。

提交信息：
1、提交ANS文档；
2、观察网络10.10.24.0/24，指出哪个路由器是DR并截图；
3、在R2中查看LSDB指出哪台路由器产生了ASBR-SUMMARY-LSA，哪台是ASBR；
4、观察A6是否有全网的路由，提交AR6 OSPF路由表截图。

## 二、设备清单

| 设备 | 型号 | Console(Telnet)端口 | 关键参数 |
|---|---|---|---|
| AR10 | AR1220 | 2006 | - |
| AR4 | AR2220 | 2003 | - |
| AR5 5.5.5.5 | AR2220 | 2005 | - |
| AR6  6.6.6.6 | AR2220 | 2007 | - |
| AR9 | AR2220 | 2004 | - |
| HUB1 | HUB | - | - |
| PC1 | PC | - | IP 192.168.1.1/24，网关 182.168.1.0 |
| PC2 | PC | - | - |
| R1  1.1.1.1 | AR2220 | 2000 | - |
| R2  2.2.2.2 | AR2220 | 2001 | - |
| R3  3.3.3.3 | AR2220 | 2002 | - |

## 三、链路连接

- R2  2.2.2.2 `GigabitEthernet0/0/0` ↔ R1  1.1.1.1 `GigabitEthernet0/0/0`（Copper）
- R2  2.2.2.2 `GigabitEthernet0/0/1` ↔ R3  3.3.3.3 `GigabitEthernet0/0/0`（Copper）
- R2  2.2.2.2 `GigabitEthernet0/0/2` ↔ HUB1 `Ethernet0/0/0`（Copper）
- HUB1 `Ethernet0/0/1` ↔ AR5 5.5.5.5 `GigabitEthernet0/0/0`（Copper）
- HUB1 `Ethernet0/0/2` ↔ AR4 `GigabitEthernet0/0/0`（Copper）
- HUB1 `Ethernet0/0/3` ↔ AR6  6.6.6.6 `GigabitEthernet0/0/0`（Copper）
- R1  1.1.1.1 `GigabitEthernet0/0/1` ↔ PC1 `Ethernet0/0/0`（Copper）
- R1  1.1.1.1 `Ethernet0/0/0` ↔ AR5 5.5.5.5 `Ethernet0/0/0`（Serial）
- R3  3.3.3.3 `GigabitEthernet0/0/1` ↔ AR9 `GigabitEthernet0/0/0`（Copper）
- AR10 `GigabitEthernet0/0/0` ↔ R1  1.1.1.1 `GigabitEthernet0/0/2`（Copper）
- AR4 `GigabitEthernet0/0/1` ↔ PC2 `Ethernet0/0/0`（Copper）

## 四、拓扑图上的文字标注

- `OSPF 1 AREA 0`（贴近 R2  2.2.2.2）
- `OSPF 1 AREA 1`（贴近 R3  3.3.3.3）
- `10.10.12.0/24`（贴近 R2  2.2.2.2）
- `.1`（贴近 R1  1.1.1.1）
- `.2`（贴近 R2  2.2.2.2）
- `10.10.23.0/24`（贴近 HUB1）
- `.2`（贴近 R2  2.2.2.2）
- `.3`（贴近 R3  3.3.3.3）
- `10.10.24.0/24`（贴近 HUB1）
- `.2`（贴近 R2  2.2.2.2）
- `.4`（贴近 AR4）
- `5`（贴近 AR5 5.5.5.5）
- `6`（贴近 AR6  6.6.6.6）
- `192.168.1.0/24`（贴近 PC1）
- `1`（贴近 R1  1.1.1.1）
- `10.10.15.0/24`（贴近 AR5 5.5.5.5）
- `1`（贴近 R1  1.1.1.1）
- `5`（贴近 AR5 5.5.5.5）
- `10.10.39.0/24`（贴近 AR9）
- `3`（贴近 R3  3.3.3.3）
- `9`（贴近 AR9）
- `引入静态路由到OSPF`（贴近 R3  3.3.3.3）
- `外网`（贴近 AR10）
- `引入默认路由到OSPF`（贴近 R1  1.1.1.1）
- `10.10.110.1/24`（贴近 R1  1.1.1.1）
- `10.10.110.10/24`（贴近 AR10）
- `192.168.4.1/24`（贴近 PC2）
- `DR`（贴近 HUB1）
- `引入直连网络路由`（贴近 AR4）

## 五、参考答案（从 .model 自动提取，按设备分组）

> 说明：该列表由实验包的「参考答案」文件提取，仅含命令文本、不含缩进层级；
> 部分行是设备默认配置，需结合题目与拓扑判断哪些是本题真正要求下发的配置。

### R3  3.3.3.3

```
sysname R3
snmp-agent local-engineid 800007DB03000000000000
snmp-agent
clock timezone China-Standard-Time minus 08:00:00
portal local-server load flash:/portalpage.zip
drop illegal-mac alarm
wlan ac-global carrier id other ac id 0
set cpu-usage threshold 80 restore 75
aaa
firewall zone Local
interface GigabitEthernet0/0/0
interface GigabitEthernet0/0/1
interface GigabitEthernet0/0/2
interface NULL0
ospf 1 router-id 3.3.3.3
router-id 3.3.3.3
End with
ip route-static 172.16.1.0 255.255.255.0 10.10.39.9
ip route-static 192.168.10.0 255.255.255.0 10.10.39.9
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
ip address 10.10.23.3 255.255.255.0
ip address 10.10.39.3 255.255.255.0
import-route static
area 0.0.0.1
authentication-mode password
network 10.10.23.0 0.0.0.255
network
Begin with
```

### R2  2.2.2.2

```
sysname R2
snmp-agent local-engineid 800007DB03000000000000
snmp-agent
clock timezone China-Standard-Time minus 08:00:00
portal local-server load flash:/portalpage.zip
drop illegal-mac alarm
wlan ac-global carrier id other ac id 0
set cpu-usage threshold 80 restore 75
aaa
firewall zone Local
interface GigabitEthernet0/0/0
interface GigabitEthernet0/0/1
interface GigabitEthernet0/0/2
interface NULL0
ospf 1 router-id 2.2.2.2
router-id 2.2.2.2
End with
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
ip address 10.10.24.2 255.255.255.0
ospf dr-priority 100
ospf dr-priority
Begin with
area 0.0.0.0
area 0.0.0.1
authentication-mode password
network 10.10.12.0 0.0.0.255
network
network 10.10.23.0 0.0.0.255
network 10.10.24.2 0.0.0.0
```

### R1  1.1.1.1

```
sysname R1
board add 0/1 2SA
snmp-agent local-engineid 800007DB03000000000000
snmp-agent
clock timezone China-Standard-Time minus 08:00:00
portal local-server load flash:/portalpage.zip
drop illegal-mac alarm
wlan ac-global carrier id other ac id 0
set cpu-usage threshold 80 restore 75
aaa
firewall zone Local
interface Serial1/0/0
interface Serial1/0/1
interface GigabitEthernet0/0/0
interface GigabitEthernet0/0/1
interface GigabitEthernet0/0/2
interface NULL0
ospf 1 router-id 1.1.1.1
router-id 1.1.1.1
End with
ip route-static 0.0.0.0 0.0.0.0 10.10.110.10
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
link-protocol ppp
ip address 10.10.15.1 255.255.255.0
ip address 10.10.12.1 255.255.255.0
ip address 192.168.1.1 255.255.255.0
ip address 10.10.110.1 255.255.255.0
default-route-advertise
area 0.0.0.0
authentication-mode password
network 10.10.12.1 0.0.0.0
network
Begin with
network 10.10.15.0 0.0.0.255
network 192.168.1.0 0.0.0.255
```

### AR6  6.6.6.6

```
sysname AR6
snmp-agent local-engineid 800007DB03000000000000
snmp-agent
clock timezone China-Standard-Time minus 08:00:00
portal local-server load flash:/portalpage.zip
drop illegal-mac alarm
wlan ac-global carrier id other ac id 0
set cpu-usage threshold 80 restore 75
aaa
firewall zone Local
interface GigabitEthernet0/0/0
interface GigabitEthernet0/0/1
interface GigabitEthernet0/0/2
interface NULL0
ospf 1 router-id 6.6.6.6
router-id 6.6.6.6
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
ip address 10.10.24.6 255.255.255.0
area 0.0.0.1
authentication-mode password
network 10.10.24.0 0.0.0.255
network
```

### AR4

```
sysname AR4
snmp-agent local-engineid 800007DB03000000000000
snmp-agent
clock timezone China-Standard-Time minus 08:00:00
portal local-server load flash:/portalpage.zip
drop illegal-mac alarm
wlan ac-global carrier id other ac id 0
set cpu-usage threshold 80 restore 75
aaa
firewall zone Local
interface GigabitEthernet0/0/0
interface GigabitEthernet0/0/1
interface GigabitEthernet0/0/2
interface NULL0
ospf 1 router-id 4.4.4.4
router-id 4.4.4.4
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
ip address 10.10.24.4 255.255.255.0
ip address 192.168.4.1 255.255.255.0
import-route direct
area 0.0.0.1
authentication-mode password
network 10.10.24.4 0.0.0.0
network
```

### AR5 5.5.5.5

```
sysname R5
board add 0/1 2SA
snmp-agent local-engineid 800007DB03000000000000
snmp-agent
clock timezone China-Standard-Time minus 08:00:00
portal local-server load flash:/portalpage.zip
drop illegal-mac alarm
wlan ac-global carrier id other ac id 0
set cpu-usage threshold 80 restore 75
aaa
firewall zone Local
interface Serial1/0/0
interface Serial1/0/1
interface GigabitEthernet0/0/0
interface GigabitEthernet0/0/1
interface GigabitEthernet0/0/2
interface NULL0
ospf 1 router-id 5.5.5.5
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
link-protocol ppp
ip address 10.10.15.5 255.255.255.0
ip address 10.10.24.5 255.255.255.0
ospf enable 1 area 0.0.0.1
area 0.0.0.0
area 0.0.0.1
authentication-mode password
network 10.10.15.5 0.0.0.0
network
Begin with
```

## 六、验收要点

（待本地模型跑通后回填：需连通的 PC 对、需隔离的 PC 对、关键验证命令）
