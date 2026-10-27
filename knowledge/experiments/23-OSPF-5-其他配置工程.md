# 实验 23：OSPF-5-其他配置工程

- 来源目录：`OSPF-5-其他配置工程`
- 拓扑文件：`paper.topo`

## 一、题目要求

1、根据拓扑图配置各设备的IP地址及路由名称，路由名称为AR序号-学号后3位（如：AR1-101、AR2-101）
2、OSPF进程号为1，area1区域采用接口认证MD5 10，area0区域采用区域认证MD5 1
3、按拓扑图进行路由汇总
4、按拓扑图要求在AR3上静态路由路由，并引入在OSPF
5、按拓扑图设置静默接口
6、全面互通。
上交说明：上交文件名为学号-姓名.ans

## 二、设备清单

| 设备 | 型号 | Console(Telnet)端口 | 关键参数 |
|---|---|---|---|
| AR1 | AR2220 | 2000 | - |
| AR2 | AR2220 | 2001 | - |
| AR3 | AR2220 | 2002 | - |
| AR4 | AR2220 | 2003 | - |
| AR5 | AR2220 | 2004 | - |
| PC1 | PC | - | IP 192.168.4.10/24，网关 192.168.4.1 |

## 三、链路连接

- AR2 `GigabitEthernet0/0/0` ↔ AR1 `GigabitEthernet0/0/0`（Copper）
- AR1 `GigabitEthernet0/0/2` ↔ AR4 `GigabitEthernet0/0/0`（Copper）
- AR1 `GigabitEthernet0/0/1` ↔ AR3 `GigabitEthernet0/0/0`（Copper）
- PC1 `Ethernet0/0/0` ↔ AR4 `GigabitEthernet0/0/1`（Copper）
- AR3 `Ethernet0/0/0` ↔ AR5 `Ethernet0/0/0`（Serial）

## 四、拓扑图上的文字标注

- `10.10.12.0/24`（贴近 AR1）
- `2`（贴近 AR2）
- `1`（贴近 AR1）
- `OSPF 1 area 1`（贴近 AR2）
- `Area1接口认证MD5 10`（贴近 AR2）
- `执行区域间路由汇总`（贴近 AR1）
- `RID:1.1.1.1`（贴近 AR1）
- `10.10.14.0/24`（贴近 AR4）
- `1`（贴近 AR1）
- `4`（贴近 AR4）
- `10.10.13.0/24`（贴近 AR1）
- `1`（贴近 AR1）
- `3`（贴近 AR3）
- `area 0 区域认证MD5 1`（贴近 PC1）
- `设置为静默接口`（贴近 AR4）
- `执行区外部路由汇总`（贴近 AR3）
- `10.10.35.0/24`（贴近 AR3）
- `3`（贴近 AR3）
- `5`（贴近 AR5）
- `静态路由引入OSPF,引入的cost 10,type 1`（贴近 AR4）
- `OSPF1 area0`（贴近 AR4）
- `192.168.4.0/24`（贴近 PC1）
- `1`（贴近 AR4）
- `10`（贴近 PC1）
- `RID:4.4.4.4`（贴近 AR4）
- `RID:3.3.3.3`（贴近 AR4）

## 五、参考答案（从 .model 自动提取，按设备分组）

> 说明：该列表由实验包的「参考答案」文件提取，仅含命令文本、不含缩进层级；
> 部分行是设备默认配置，需结合题目与拓扑判断哪些是本题真正要求下发的配置。

### AR4

```
sysname AR4
Include
snmp-agent local-engineid 800007DB03000000000000
snmp-agent
clock timezone China-Standard-Time minus 08:00:00
portal local-server load portalpage.zip
drop illegal-mac alarm
undo info-center enable
set cpu-usage threshold 80 restore 75
aaa
firewall zone Local
interface GigabitEthernet0/0/0
interface GigabitEthernet0/0/1
interface GigabitEthernet0/0/2
interface NULL0
ospf 1 router-id 4.4.4.4
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
ip address 10.10.14.4 255.255.255.0
ip address 192.168.4.1 255.255.255.0
silent-interface GigabitEthernet0/0/1
area 0.0.0.0
authentication-mode password
authentication-mode md5 1
network 10.10.14.0 0.0.0.255
network 192.168.4.0 0.0.0.255
```

### AR3

```
sysname AR3
Include
board add 0/1 2SA
snmp-agent local-engineid 800007DB03000000000000
snmp-agent
clock timezone China-Standard-Time minus 08:00:00
portal local-server load portalpage.zip
drop illegal-mac alarm
undo info-center enable
set cpu-usage threshold 80 restore 75
aaa
firewall zone Local
interface Serial1/0/0
interface Serial1/0/1
interface GigabitEthernet0/0/0
interface GigabitEthernet0/0/1
interface GigabitEthernet0/0/2
interface NULL0
ospf 1 router-id 3.3.3.3
ip route-static 1.1.1.0 255.255.255.0 10.10.35.5
ip route-static 1.1.2.0 255.255.255.0 10.10.35.5
ip route-static 1.1.3.0 255.255.255.0 10.10.35.5
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
ip address 10.10.35.3 255.255.255.0
ip address 10.10.13.3 255.255.255.0
asbr-summary 1.1.0.0 255.255.252.0
import-route static cost 10 type 1
area 0.0.0.0
authentication-mode password
authentication-mode md5 1
network 10.10.13.0 0.0.0.255
```

### AR1

```
sysname AR1
Include
snmp-agent local-engineid 800007DB03000000000000
snmp-agent
clock timezone China-Standard-Time minus 08:00:00
portal local-server load portalpage.zip
drop illegal-mac alarm
undo info-center enable
set cpu-usage threshold 80 restore 75
aaa
firewall zone Local
interface GigabitEthernet0/0/0
interface GigabitEthernet0/0/1
interface GigabitEthernet0/0/2
interface NULL0
ospf 1 router-id 1.1.1.1
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
ospf authentication-mode md5 10
ip address 10.10.13.1 255.255.255.0
ip address 10.10.14.1 255.255.255.0
area 0.0.0.0
area 0.0.0.1
authentication-mode password
authentication-mode md5 1
network 10.10.13.0 0.0.0.255
network 10.10.14.0 0.0.0.255
abr-summary 172.16.0.0 255.255.248.0
network 10.10.12.0 0.0.0.255
```

### AR5

```
sysname AR5
Include
board add 0/1 2SA
snmp-agent local-engineid 800007DB03000000000000
snmp-agent
clock timezone China-Standard-Time minus 08:00:00
portal local-server load portalpage.zip
drop illegal-mac alarm
undo info-center enable
set cpu-usage threshold 80 restore 75
aaa
firewall zone Local
interface Serial1/0/0
interface Serial1/0/1
interface GigabitEthernet0/0/0
interface GigabitEthernet0/0/1
interface GigabitEthernet0/0/2
interface NULL0
interface LoopBack0
interface LoopBack1
interface LoopBack2
ip route-static 0.0.0.0 0.0.0.0 10.10.35.3
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
ip address 10.10.35.5 255.255.255.0
ip address 1.1.1.1 255.255.255.0
ip address 1.1.2.1 255.255.255.0
ip address 1.1.3.1 255.255.255.0
authentication-mode password
```

### AR2

```
sysname AR2
Include
snmp-agent local-engineid 800007DB03000000000000
snmp-agent
clock timezone China-Standard-Time minus 08:00:00
portal local-server load portalpage.zip
drop illegal-mac alarm
undo info-center enable
set cpu-usage threshold 80 restore 75
aaa
firewall zone Local
interface GigabitEthernet0/0/0
interface GigabitEthernet0/0/1
interface GigabitEthernet0/0/2
interface NULL0
interface LoopBack0
interface LoopBack1
interface LoopBack2
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
ospf authentication-mode md5 10
ip address 172.16.3.1 255.255.255.0
ip address 172.16.4.1 255.255.255.0
ip address 172.16.5.1 255.255.255.0
area 0.0.0.1
authentication-mode password
network 10.10.12.0 0.0.0.255
network 172.16.3.0 0.0.0.255
network 172.16.4.0 0.0.0.255
network 172.16.5.0 0.0.0.255
```

## 六、验收要点

（待本地模型跑通后回填：需连通的 PC 对、需隔离的 PC 对、关键验证命令）
