# 实验 15：ISIS-OSPF相互引入工程

- 来源目录：`ISIS-OSPF相互引入工程`
- 拓扑文件：`paper.topo`

## 一、题目要求

1、按拓扑结构图完成路由器的基本配置，要求路由器名称为ARX-学号后三位（如：AR1-101、AR2-101）
2、配置OSPF的Area0区域 
3、配置ISIS的Area49.0345区域 路由器L2
4、查看AR1的路由表，截图
5、查看AR5的路由表，截图
6、在AR3上把ISIS的路由引入OSPF，再次查看AR1路由表，截图
7、在AR3上把OSPF的路由引入ISIS，再次查看AR5路由表，截图
8、全网互通，使用ping命令测试AR1到AR5是否连通，截图
9、保存此工程，工程名称为学号-姓名，并上交工程ans文档，截图提交学习通

## 二、设备清单

| 设备 | 型号 | Console(Telnet)端口 | 关键参数 |
|---|---|---|---|
| AR1 | AR2220 | 2000 | - |
| AR2 | AR2220 | 2001 | - |
| AR3 | AR2220 | 2002 | - |
| AR4 | AR2220 | 2003 | - |
| AR5 | AR2220 | 2004 | - |

## 三、链路连接

- AR1 `GigabitEthernet0/0/0` ↔ AR2 `GigabitEthernet0/0/1`（Copper）
- AR2 `GigabitEthernet0/0/0` ↔ AR3 `GigabitEthernet0/0/1`（Copper）
- AR3 `GigabitEthernet0/0/0` ↔ AR4 `GigabitEthernet0/0/1`（Copper）
- AR4 `GigabitEthernet0/0/0` ↔ AR5 `GigabitEthernet0/0/1`（Copper）

## 四、拓扑图上的文字标注

- `10.10.12.0/24`（贴近 AR2）
- `1`（贴近 AR1）
- `2`（贴近 AR2）
- `10.10.23.0/24`（贴近 AR3）
- `2`（贴近 AR2）
- `3`（贴近 AR3）
- `10.10.34.0/24`（贴近 AR4）
- `3`（贴近 AR3）
- `4`（贴近 AR4）
- `10.10.45.0/24`（贴近 AR5）
- `4`（贴近 AR4）
- `5`（贴近 AR5）
- `Lo0:1.1.1.1/32`（贴近 AR1）
- `Lo0:2.2.2.2/32`（贴近 AR2）
- `Lo0:3.3.3.3/32`（贴近 AR3）
- `Lo0:4.4.4.4/32`（贴近 AR4）
- `Lo0:5.5.5.5/32`（贴近 AR5）

## 五、参考答案（从 .model 自动提取，按设备分组）

> 说明：该列表由实验包的「参考答案」文件提取，仅含命令文本、不含缩进层级；
> 部分行是设备默认配置，需结合题目与拓扑判断哪些是本题真正要求下发的配置。

### AR4

```
sysname AR4
AR4-
Include
snmp-agent local-engineid 800007DB03000000000000
snmp-agent
clock timezone China-Standard-Time minus 08:00:00
portal local-server load portalpage.zip
drop illegal-mac alarm
undo info-center enable
set cpu-usage threshold 80 restore 75
aaa
isis 1
firewall zone Local
interface GigabitEthernet0/0/0
interface GigabitEthernet0/0/1
interface GigabitEthernet0/0/2
interface NULL0
interface LoopBack0
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
is-level level-2
network-entity 49.0345.0000.0000.0004.00
priority 15
ip address 10.10.45.4 255.255.255.0
isis enable 1
ip address 10.10.34.4 255.255.255.0
ip address 4.4.4.4 255.255.255.255
authentication-mode password
```

### AR5

```
sysname AR5
AR5-
Include
snmp-agent local-engineid 800007DB03000000000000
snmp-agent
clock timezone China-Standard-Time minus 08:00:00
portal local-server load portalpage.zip
drop illegal-mac alarm
undo info-center enable
set cpu-usage threshold 80 restore 75
aaa
isis 1
firewall zone Local
interface GigabitEthernet0/0/0
interface GigabitEthernet0/0/1
interface GigabitEthernet0/0/2
interface NULL0
interface LoopBack0
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
is-level level-2
network-entity 49.0345.0000.0000.0005.00
priority 15
ip address 10.10.45.5 255.255.255.0
isis enable 1
ip address 5.5.5.5 255.255.255.255
authentication-mode password
```

### AR3

```
sysname AR3
AR3-
Include
snmp-agent local-engineid 800007DB03000000000000
snmp-agent
clock timezone China-Standard-Time minus 08:00:00
portal local-server load portalpage.zip
drop illegal-mac alarm
undo info-center enable
set cpu-usage threshold 80 restore 75
aaa
isis 1
firewall zone Local
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
is-level level-2
network-entity 49.0345.0000.0000.0003.00
import-route ospf 1
priority 15
ip address 10.10.34.3 255.255.255.0
isis enable 1
ip address 10.10.23.3 255.255.255.0
ip address 3.3.3.3 255.255.255.255
import-route isis 1
area 0.0.0.0
authentication-mode password
network 3.3.3.3 0.0.0.0
network 10.10.23.0 0.0.0.255
```

### AR2

```
sysname AR2
AR2-
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
ip address 10.10.23.2 255.255.255.0
ip address 10.10.12.2 255.255.255.0
ip address 2.2.2.2 255.255.255.255
area 0.0.0.0
authentication-mode password
network 2.2.2.2 0.0.0.0
network 10.10.12.0 0.0.0.255
network 10.10.23.0 0.0.0.255
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
ip address 1.1.1.1 255.255.255.255
area 0.0.0.0
authentication-mode password
network 1.1.1.1 0.0.0.0
network 10.10.12.0 0.0.0.255
```

## 六、验收要点

（待本地模型跑通后回填：需连通的 PC 对、需隔离的 PC 对、关键验证命令）
