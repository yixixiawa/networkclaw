# 实验 12：ISIS-1-基本配置

- 来源目录：`ISIS-1-基本配置`
- 拓扑文件：`paper.topo`

## 一、题目要求

1、按照拓扑图配置IP地址
要求：路由器名称为AR序号-学号后3位（如：AR-101）
2、按拓扑图完成配置IS-IS路由配置
要求：
（1）所有ISIS 进程为100
（2）49.0002采用区域认证MD5 密码：kaoshi
（3）AR4和AR5采用接口认证 MD5 密码：huawei
3、配置完成后要求网络互通

## 二、设备清单

| 设备 | 型号 | Console(Telnet)端口 | 关键参数 |
|---|---|---|---|
| AR1 | AR2220 | 2000 | - |
| AR2 | AR2220 | 2001 | - |
| AR3 | AR2220 | 2002 | - |
| AR4 | AR2220 | 2003 | - |
| AR5 | AR2220 | 2004 | - |
| AR6 | AR2220 | 2005 | - |
| AR7 | AR2220 | 2006 | - |
| SW1 | S5700 | 2007 | - |

## 三、链路连接

- AR1 `GigabitEthernet0/0/0` ↔ SW1 `GigabitEthernet0/0/1`（Copper）
- SW1 `GigabitEthernet0/0/2` ↔ AR2 `GigabitEthernet0/0/0`（Copper）
- SW1 `GigabitEthernet0/0/3` ↔ AR3 `GigabitEthernet0/0/0`（Copper）
- AR2 `GigabitEthernet0/0/1` ↔ AR4 `GigabitEthernet0/0/0`（Copper）
- AR3 `Ethernet0/0/0` ↔ AR4 `Ethernet0/0/0`（Serial）
- AR4 `GigabitEthernet0/0/1` ↔ AR5 `GigabitEthernet0/0/0`（Copper）
- AR5 `GigabitEthernet0/0/1` ↔ AR6 `GigabitEthernet0/0/0`（Copper）
- AR6 `GigabitEthernet0/0/1` ↔ AR7 `GigabitEthernet0/0/0`（Copper）

## 四、拓扑图上的文字标注

- `Lo0:172.16.1.1/24`（贴近 AR1）
- `Lo接口激活ISIS`（贴近 AR1）
- `49.0002`（贴近 AR1）
- `level-1`（贴近 SW1）
- `Level-1`（贴近 AR1）
- `DIS`（贴近 AR1）
- `10.10.123.0/24`（贴近 SW1）
- `1`（贴近 AR1）
- `2`（贴近 AR2）
- `3`（贴近 AR3）
- `Level-1-2`（贴近 AR2）
- `Level-1-2`（贴近 AR3）
- `10.10.24.0/24`（贴近 AR4）
- `10.10.34.0/24`（贴近 AR7）
- `2`（贴近 AR2）
- `3`（贴近 AR3）
- `4`（贴近 AR4）
- `4`（贴近 AR4）
- `4`（贴近 AR4）
- `5`（贴近 AR5）
- `5`（贴近 AR5）
- `6`（贴近 AR6）
- `6`（贴近 AR6）
- `7`（贴近 AR7）
- `10.10.67.0/24`（贴近 AR6）
- `10.10.45.0/24`（贴近 AR5）
- `10.10.56.0/24`（贴近 AR6）
- `Level-1`（贴近 AR7）
- `49.0003`（贴近 AR7）
- `Lo0:192.168.1.1/24`（贴近 AR7）
- `Level-1`（贴近 AR7）
- `Lo接口激活ISIS`（贴近 AR7）
- `Lever-2`（贴近 AR4）
- `Level-2`（贴近 AR5）
- `Level-1-2`（贴近 AR6）
- `49.0001`（贴近 AR2）
- `Level-2`（贴近 AR4）
- `Lo0：10.10.10.5/24`（贴近 AR5）
- `Lo0接口不激活ISIS，引入直连路由`（贴近 AR5）

## 五、参考答案（从 .model 自动提取，按设备分组）

> 说明：该列表由实验包的「参考答案」文件提取，仅含命令文本、不含缩进层级；
> 部分行是设备默认配置，需结合题目与拓扑判断哪些是本题真正要求下发的配置。

### AR5

```
sysname AR5
AR5-
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
isis 100
firewall zone Local
interface GigabitEthernet0/0/0
interface GigabitEthernet0/0/1
interface GigabitEthernet0/0/2
interface NULL0
interface LoopBack0
interface LoopBack1
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
network-entity 49.0001.0000.0000.0005.00
import-route direct
priority 15
ip address 10.10.45.5 255.255.255.0
isis enable 100
isis authentication-mode md5
ip address 10.10.56.5 255.255.255.0
ip address 10.10.10.5 255.255.255.0
authentication-mode password
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
isis 100
firewall zone Local
interface GigabitEthernet0/0/0
interface GigabitEthernet0/0/1
interface GigabitEthernet0/0/2
interface NULL0
interface LoopBack0
interface LoopBack1
interface LoopBack2
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
network-entity 49.0002.0000.0000.0001.00
area-authentication-mode md5
priority 15
ip address 10.10.123.1 255.255.255.0
isis enable 100
ip address 172.16.1.1 255.255.255.0
authentication-mode password
```

### AR2

```
sysname AR2
AR2-
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
network-entity 49.0002.0000.0000.0002.00
area-authentication-mode md5
priority 15
ip address 10.10.123.2 255.255.255.0
isis enable 100
ip address 10.10.24.2 255.255.255.0
authentication-mode password
```

### AR6

```
sysname AR6
AR6-
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
network-entity 49.0003.0000.0000.0006.00
priority 15
ip address 10.10.56.6 255.255.255.0
isis enable 100
ip address 10.10.67.6 255.255.255.0
authentication-mode password
```

### AR7

```
sysname AR7
AR7-
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
interface LoopBack1
interface LoopBack2
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
network-entity 49.0003.0000.0000.0007.00
priority 15
ip address 10.10.67.7 255.255.255.0
isis enable 100
ip address 192.168.1.1 255.255.255.0
authentication-mode password
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
isis 100
firewall zone Local
interface Serial1/0/0
interface Serial1/0/1
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
network-entity 49.0002.0000.0000.0003.00
area-authentication-mode md5
priority 15
link-protocol ppp
ip address 10.10.34.3 255.255.255.0
isis enable 100
ip address 10.10.123.3 255.255.255.0
authentication-mode password
```

### AR4

```
sysname AR4
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
isis 100
firewall zone Local
interface Serial1/0/0
interface Serial1/0/1
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
network-entity 49.0001.0000.0000.0004.00
priority 15
link-protocol ppp
ip address 10.10.34.4 255.255.255.0
isis enable 100
ip address 10.10.24.4 255.255.255.0
ip address 10.10.45.4 255.255.255.0
isis authentication-mode md5
authentication-mode password
```

## 六、验收要点

（待本地模型跑通后回填：需连通的 PC 对、需隔离的 PC 对、关键验证命令）
