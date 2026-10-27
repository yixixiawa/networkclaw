# 实验 41：Vlink及特殊区域配置练习

- 来源目录：`Vlink及特殊区域配置练习`
- 拓扑文件：`paper.topo`

## 一、题目要求

下面拓扑图中，各个路由器接口已经配置。
实验步骤：
1、按照拓扑图中信息配置各个路由器接口IP地址；
2、按照图中提示配置OSPF网络及静态路由；
3、按照图中所示，从AR3及AR5中引入静态路由到OSPF中；
4、查看VLINK状态截图；
5、把AREA3配置为stub区域，在AR5中查询LSDB并截图，看看AR1是否产生默认的第3类LSA,是否存在OSPF外部引入路由；
6、把AREA3改为totally stub区域，在AR5中查询LSDB并截图，与步骤5截图比较，指出差异地方；
7、把AREA3改为NSSA区域，查询AR5中LSDB，截图，并指出有几个NSSA-LSA；
8、查询AR6中的LSDB，截图，指出哪个LSA是从7类LSA转换成5类LSA，由哪个路由器产生；
9、提交ANS文档。

## 二、设备清单

| 设备 | 型号 | Console(Telnet)端口 | 关键参数 |
|---|---|---|---|
| AR1 | AR2220 | 2000 | - |
| AR2 | AR2220 | 2001 | - |
| AR3 | AR2220 | 2002 | - |
| AR4 | AR2220 | 2003 | - |
| AR5 | AR2220 | 2004 | - |
| AR6 | AR2220 | 2005 | - |
| AR8 | AR2220 | 2006 | - |
| AR9 | AR2220 | 2007 | - |

## 三、链路连接

- AR1 `GigabitEthernet0/0/0` ↔ AR2 `GigabitEthernet0/0/0`（Copper）
- AR2 `GigabitEthernet0/0/1` ↔ AR3 `GigabitEthernet0/0/0`（Copper）
- AR3 `GigabitEthernet0/0/1` ↔ AR4 `GigabitEthernet0/0/0`（Copper）
- AR4 `GigabitEthernet0/0/1` ↔ AR6 `GigabitEthernet0/0/0`（Copper）
- AR1 `GigabitEthernet0/0/1` ↔ AR5 `GigabitEthernet0/0/0`（Copper）
- AR5 `GigabitEthernet0/0/1` ↔ AR9 `GigabitEthernet0/0/0`（Copper）
- AR3 `GigabitEthernet0/0/2` ↔ AR8 `GigabitEthernet0/0/0`（Copper）

## 四、拓扑图上的文字标注

- `AREA 0`（贴近 AR1）
- `AREA 3`（贴近 AR1）
- `AREA2`（贴近 AR3）
- `AREA 0`（贴近 AR4）
- `AREA 4`（贴近 AR4）
- `10.10.12.0/24`（贴近 AR2）
- `10.10.34.0/24`（贴近 AR3）
- `10.10.46.0/24`（贴近 AR6）
- `10.10.23.0/24`（贴近 AR3）
- `10.10.15.0/24`（贴近 AR1）
- `Vlink`（贴近 AR3）
- `10.10.59.0/24`（贴近 AR9）
- `1`（贴近 AR5）
- `2`（贴近 AR9）
- `10.10.38.0/24`（贴近 AR8）
- `引入外部静态路由`（贴近 AR5）
- `引入外部静态路由`（贴近 AR3）
- `192.168.10.0/24`（贴近 AR9）
- `1`（贴近 AR3）
- `2`（贴近 AR8）
- `1`（贴近 AR1）
- `2`（贴近 AR2）
- `2`（贴近 AR2）
- `3`（贴近 AR3）
- `3`（贴近 AR3）
- `4`（贴近 AR4）
- `4`（贴近 AR4）
- `6`（贴近 AR6）
- `1`（贴近 AR1）
- `5`（贴近 AR5）

## 五、参考答案（从 .model 自动提取，按设备分组）

> 说明：该列表由实验包的「参考答案」文件提取，仅含命令文本、不含缩进层级；
> 部分行是设备默认配置，需结合题目与拓扑判断哪些是本题真正要求下发的配置。

### AR2

```
sysname AR2
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
ospf 1
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
ip address 10.10.12.2 255.255.255.0
ip address 10.10.23.2 255.255.255.0
area 0.0.0.0
area 0.0.0.2
authentication-mode password
network 10.10.12.0 0.0.0.255
network
network 10.10.23.0 0.0.0.255
vlink-peer 3.3.3.3
vlink-peer
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
ospf 1
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
ip address 10.10.34.4 255.255.255.0
ip address 10.10.46.4 255.255.255.0
area 0.0.0.0
area 0.0.0.4
authentication-mode password
network 10.10.34.0 0.0.0.255
network 10.10.46.0 0.0.0.255
```

### AR6

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
ospf 1
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
ip address 10.10.46.6 255.255.255.0
area 0.0.0.4
authentication-mode password
network 10.10.46.0 0.0.0.255
network
```

### AR5

```
sysname AR5
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
ospf 1
Begin with
ip route-static 192.168.10.0 255.255.255.0 10.10.59.2
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
ip address 10.10.15.5 255.255.255.0
ip address 10.10.59.1 255.255.255.0
import-route static
area 0.0.0.3
authentication-mode password
network 10.10.15.0 0.0.0.255
network
nssa
```

### AR1

```
sysname AR1
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
ospf 1 router-id 1.1.1.1
ospf 1
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
ip address 10.10.12.1 255.255.255.0
ip address 10.10.15.1 255.255.255.0
area 0.0.0.0
area 0.0.0.3
authentication-mode password
network 10.10.12.1 0.0.0.0
network
network 10.10.15.1 0.0.0.0
nssa
```

### AR3

```
sysname AR3
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
ospf 1
Begin with
ip route-static 192.168.1.0 255.255.255.0 10.10.38.2
ip route-static 192.168.2.0 255.255.255.0 10.10.38.2
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
ip address 10.10.34.3 255.255.255.0
ip address 10.10.38.1 255.255.255.0
import-route static
area 0.0.0.0
area 0.0.0.2
authentication-mode password
network 10.10.34.0 0.0.0.255
network
network 10.10.23.0 0.0.0.255
vlink-peer 2.2.2.2
vlink-pee
```

## 六、验收要点

（待本地模型跑通后回填：需连通的 PC 对、需隔离的 PC 对、关键验证命令）
