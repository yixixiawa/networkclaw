# 实验 28：OSPF配置实验

- 来源目录：`OSPF配置实验`
- 拓扑文件：`paper.topo`

## 一、题目要求

1、完成拓扑中各路由器的名称及IP地址配置。要求：路由器名称为AR1-学号后三位（如：AR1-101、AR2-101）。
2、配置OSPF协议，AR1、AR2、AR6为area2，AR2、AR3为area0，AR3、AR4和AR5为area1。
3、配置OSPF的认证功能。
要求：（1）area2为区域认证，采用简单的明文方式，密码：Huawei。
      （2）area0为接口认证，采用MD5密文方式。密码：Huawei。
4、操作完成保存文件并上交，文件名：学号-姓名

## 二、设备清单

| 设备 | 型号 | Console(Telnet)端口 | 关键参数 |
|---|---|---|---|
| AR1 | AR2220 | 2000 | - |
| AR2 | AR2220 | 2001 | - |
| AR3 | AR2220 | 2002 | - |
| AR4 | AR2220 | 2003 | - |
| AR5 | AR2220 | 2004 | - |
| AR6 | AR2220 | 2005 | - |
| LSW1 | S5700 | 2006 | - |

## 三、链路连接

- AR1 `GigabitEthernet0/0/0` ↔ LSW1 `GigabitEthernet0/0/1`（Copper）
- LSW1 `GigabitEthernet0/0/2` ↔ AR2 `GigabitEthernet0/0/0`（Copper）
- AR6 `GigabitEthernet0/0/0` ↔ LSW1 `GigabitEthernet0/0/3`（Copper）
- AR2 `Ethernet0/0/0` ↔ AR3 `Ethernet0/0/1`（Serial）
- AR3 `Ethernet0/0/0` ↔ AR4 `Ethernet0/0/1`（Serial）
- AR4 `Ethernet0/0/0` ↔ AR5 `Ethernet0/0/1`（Serial）

## 四、拓扑图上的文字标注

- `10.10.126.0/24`（贴近 LSW1）
- `1`（贴近 AR1）
- `2`（贴近 AR2）
- `6`（贴近 AR6）
- `10.10.23.0/24`（贴近 AR3）
- `2`（贴近 AR2）
- `3`（贴近 AR3）
- `10.10.34.0/24`（贴近 AR4）
- `3`（贴近 AR3）
- `4`（贴近 AR4）
- `10.10.45.0/24`（贴近 AR5）
- `4`（贴近 AR4）
- `5`（贴近 AR5）
- `area 2`（贴近 AR2）
- `area 0`（贴近 AR3）
- `area 1`（贴近 AR4）

## 五、参考答案（从 .model 自动提取，按设备分组）

> 说明：该列表由实验包的「参考答案」文件提取，仅含命令文本、不含缩进层级；
> 部分行是设备默认配置，需结合题目与拓扑判断哪些是本题真正要求下发的配置。

### AR2

```
sysname AR2
AR2-
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
link-protocol ppp
ip address 10.10.23.2 255.255.255.0
ospf authentication-mode md5
ip address 10.10.126.2 255.255.255.0
ip address 2.2.2.2 255.255.255.255
area 0.0.0.0
area 0.0.0.2
authentication-mode password
network 10.10.23.0 0.0.0.255
authentication-mode simple plain Huawei
network 2.2.2.2 0.0.0.0
network 10.10.126.0 0.0.0.255
```

### AR5

```
sysname AR5
AR5-
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
ip address 10.10.45.5 255.255.255.0
ip address 5.5.5.5 255.255.255.255
area 0.0.0.1
authentication-mode password
network 5.5.5.5 0.0.0.0
network 10.10.45.0 0.0.0.255
```

### AR4

```
sysname AR4
AR4-
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
link-protocol ppp
ip address 10.10.45.4 255.255.255.0
ip address 10.10.34.4 255.255.255.0
ip address 4.4.4.4 255.255.255.255
area 0.0.0.1
authentication-mode password
network 4.4.4.4 0.0.0.0
network 10.10.34.0 0.0.0.255
network 10.10.45.0 0.0.0.255
```

### AR6

```
sysname AR6
AR6-
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
ospf 1 router-id 6.6.6.6
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
ip address 10.10.126.6 255.255.255.0
ip address 6.6.6.6 255.255.255.255
area 0.0.0.2
authentication-mode password
authentication-mode simple plain Huawei
network 6.6.6.6 0.0.0.0
network 10.10.126.0 0.0.0.255
```

### AR1

```
sysname AR1
AR1-
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
interface LoopBack9
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
ip address 10.10.126.1 255.255.255.0
ip address 1.1.1.1 255.255.255.255
area 0.0.0.2
authentication-mode password
authentication-mode simple plain Huawei
network 1.1.1.1 0.0.0.0
network 10.10.126.0 0.0.0.255
```

### AR3

```
sysname AR3
AR3-
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
link-protocol ppp
ip address 10.10.34.3 255.255.255.0
ip address 10.10.23.3 255.255.255.0
ospf authentication-mode md5
ip address 3.3.3.3 255.255.255.255
area 0.0.0.0
area 0.0.0.1
authentication-mode password
network 10.10.23.0 0.0.0.255
network 3.3.3.3 0.0.0.0
network 10.10.34.0 0.0.0.255
```

## 六、验收要点

（待本地模型跑通后回填：需连通的 PC 对、需隔离的 PC 对、关键验证命令）
