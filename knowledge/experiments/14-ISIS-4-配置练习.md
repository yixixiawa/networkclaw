# 实验 14：ISIS-4-配置练习

- 来源目录：`ISIS-4-配置练习`
- 拓扑文件：`paper.topo`

## 一、题目要求

1、按拓扑结构完成ISIS路由协议配置使全网互通
要求：
（1）路由器名称为AR序号-学号后3位（如AR1-101）
（2）ISIS的进程为100
2、交卷文件名为学号-姓名，交上交。
3、在学习通里上交截图如下：
（1）AR3、AR4的ISIS邻居表
（2）AR2、AR5的ISIS的LSDB
（3）AR1、AR4、AR6的IP路由表

## 二、设备清单

| 设备 | 型号 | Console(Telnet)端口 | 关键参数 |
|---|---|---|---|
| AR1 | AR2220 | 2000 | - |
| AR2 | AR2220 | 2001 | - |
| AR3 | AR2220 | 2002 | - |
| AR4 | AR2220 | 2003 | - |
| AR5 | AR2220 | 2004 | - |
| AR6 | AR2220 | 2005 | - |

## 三、链路连接

- AR1 `GigabitEthernet0/0/0` ↔ AR2 `GigabitEthernet0/0/0`（Copper）
- AR1 `GigabitEthernet0/0/1` ↔ AR3 `GigabitEthernet0/0/1`（Copper）
- AR2 `GigabitEthernet0/0/2` ↔ AR3 `GigabitEthernet0/0/2`（Copper）
- AR3 `GigabitEthernet0/0/0` ↔ AR4 `GigabitEthernet0/0/0`（Copper）
- AR4 `GigabitEthernet0/0/1` ↔ AR5 `GigabitEthernet0/0/1`（Copper）
- AR6 `GigabitEthernet0/0/0` ↔ AR5 `GigabitEthernet0/0/0`（Copper）

## 四、拓扑图上的文字标注

- `10.10.12.0/24`（贴近 AR2）
- `10.10.13.0/24`（贴近 AR3）
- `10.10.23.0/24`（贴近 AR3）
- `10.10.34.0/24`（贴近 AR4）
- `3`（贴近 AR3）
- `4`（贴近 AR4）
- `1`（贴近 AR1）
- `1`（贴近 AR1）
- `2`（贴近 AR2）
- `2`（贴近 AR2）
- `3`（贴近 AR3）
- `3`（贴近 AR3）
- `10.10.45.0/24`（贴近 AR5）
- `4`（贴近 AR4）
- `5`（贴近 AR5）
- `10.10.56.0/24`（贴近 AR5）
- `6`（贴近 AR6）
- `5`（贴近 AR5）
- `49.0123`（贴近 AR3）
- `49.0004`（贴近 AR4）
- `49.0056`（贴近 AR6）
- `公司部门A网络`（贴近 AR3）
- `公司骨干网络`（贴近 AR4）
- `公司部门B网络`（贴近 AR5）
- `Lo0:10.0.1.1/32`（贴近 AR1）
- `Lo0:10.0.2.2/32`（贴近 AR2）
- `Lo0:10.0.6.6/32`（贴近 AR6）
- `L-2`（贴近 AR4）
- `L-1-2`（贴近 AR3）
- `L-1-2`（贴近 AR5）
- `L-1`（贴近 AR6）
- `L-1`（贴近 AR1）
- `L-1`（贴近 AR2）

## 五、参考答案（从 .model 自动提取，按设备分组）

> 说明：该列表由实验包的「参考答案」文件提取，仅含命令文本、不含缩进层级；
> 部分行是设备默认配置，需结合题目与拓扑判断哪些是本题真正要求下发的配置。

### AR6

```
sysname AR6
Include
snmp-agent local-engineid 800007DB03000000000000
snmp-agent
clock timezone China-Standard-Time minus 08:00:00
portal local-server load portalpage.zip
drop illegal-mac alarm
undo info-center enable
set cpu-usage threshold 80 restore 75
aaa
isis 100
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
is-level level-1
network-entity 49.0056.0000.0000.0006.00
priority 15
ip address 10.10.56.6 255.255.255.0
isis enable 100
ip address 10.0.6.6 255.255.255.255
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
isis 100
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
is-level level-1
network-entity 49.0123.0000.0000.0002.00
priority 15
ip address 10.10.12.2 255.255.255.0
isis enable 100
ip address 10.10.23.2 255.255.255.0
ip address 10.0.2.2 255.255.255.255
authentication-mode password
```

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
isis 100
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
is-level level-2
network-entity 49.0004.0000.0000.0004.00
priority 15
ip address 10.10.34.4 255.255.255.0
isis enable 100
ip address 10.10.45.4 255.255.255.0
authentication-mode password
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
isis 100
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
is-level level-1
network-entity 49.0123.0000.0000.0001.00
priority 15
ip address 10.10.12.1 255.255.255.0
isis enable 100
ip address 10.10.13.1 255.255.255.0
ip address 10.0.1.1 255.255.255.255
authentication-mode password
```

### AR5

```
sysname AR5
Include
snmp-agent local-engineid 800007DB03000000000000
snmp-agent
clock timezone China-Standard-Time minus 08:00:00
portal local-server load portalpage.zip
drop illegal-mac alarm
undo info-center enable
set cpu-usage threshold 80 restore 75
aaa
isis 100
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
network-entity 49.0056.0000.0000.0005.00
priority 15
ip address 10.10.56.5 255.255.255.0
isis enable 100
ip address 10.10.45.5 255.255.255.0
authentication-mode password
```

### AR3

```
sysname AR3
Include
snmp-agent local-engineid 800007DB03000000000000
snmp-agent
clock timezone China-Standard-Time minus 08:00:00
portal local-server load portalpage.zip
drop illegal-mac alarm
undo info-center enable
set cpu-usage threshold 80 restore 75
aaa
isis 100
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
network-entity 49.0123.0000.0000.0003.00
priority 15
ip address 10.10.34.3 255.255.255.0
isis enable 100
ip address 10.10.13.3 255.255.255.0
ip address 10.10.23.3 255.255.255.0
authentication-mode password
```

## 六、验收要点

（待本地模型跑通后回填：需连通的 PC 对、需隔离的 PC 对、关键验证命令）
