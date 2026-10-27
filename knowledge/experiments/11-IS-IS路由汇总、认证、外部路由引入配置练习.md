# 实验 11：IS-IS路由汇总、认证、外部路由引入配置练习

- 来源目录：`IS-IS路由汇总、认证、外部路由引入配置练习`
- 拓扑文件：`paper.topo`

## 一、题目要求

SYSTEM-ID如下：
AR1:0000.0000.0001，AR2:0000.0000.0002，AR3:0000.0000.0003，AR4:0000.0000.0004。
配置要求：
1、按照拓扑图所示配置各接口IP地址及IS-IS网络路由协议；
2、LEVEL-1区域使用接口认证及区域认证；
3、LEVEL-2区域使用路由域证；
4、AR1引入静态路由；
5、AR4把默认路由发布到ISIS；
6、在AR3处对LEVEL的172.16.13.0/24、172.16.13.0/24、172.16.13.0/24三个网络进行精确汇总；

提交资料：
1、在AR5查看路由表，看看汇总路由是否生效；
2、查看AR4 LSP信息，看看那条LSP包含了默认路由发布；
3、在AR3查看LSDB,指出AR1有几条LSP信息，分别包含什么信息，查询AR1所有LSP详细信息截图；
4、提交ANS文档。

## 二、设备清单

| 设备 | 型号 | Console(Telnet)端口 | 关键参数 |
|---|---|---|---|
| AR1 | AR2220 | 2006 | - |
| AR2 | AR2220 | 2001 | - |
| AR3 | AR2220 | 2002 | - |
| AR4 | AR2220 | 2003 | - |
| AR5 | AR2220 | 2004 | - |
| AR6 | AR2220 | 2005 | - |
| PC1 | PC | - | - |
| PC2 | PC | - | - |

## 三、链路连接

- AR3 `GigabitEthernet0/0/0` ↔ AR4 `GigabitEthernet0/0/0`（Copper）
- AR4 `GigabitEthernet0/0/1` ↔ AR6 `GigabitEthernet0/0/0`（Copper）
- AR3 `GigabitEthernet0/0/2` ↔ AR2 `GigabitEthernet0/0/0`（Copper）
- AR2 `GigabitEthernet0/0/1` ↔ PC2 `Ethernet0/0/0`（Copper）
- AR3 `GigabitEthernet0/0/1` ↔ AR1 `GigabitEthernet0/0/0`（Copper）
- AR1 `GigabitEthernet0/0/1` ↔ PC1 `Ethernet0/0/0`（Copper）
- AR1 `GigabitEthernet0/0/2` ↔ AR5 `GigabitEthernet0/0/0`（Copper）

## 四、拓扑图上的文字标注

- `10.10.13.0/24`（贴近 AR3）
- `1`（贴近 AR1）
- `level-1`（贴近 AR1）
- `172.16.13.0/24`（贴近 AR5）
- `172.16.14.0/24`（贴近 PC1）
- `10.10.15.0/24`（贴近 AR1）
- `5`（贴近 AR5）
- `1`（贴近 AR1）
- `1`（贴近 AR1）
- `3`（贴近 AR3）
- `10.10.23.0/24`（贴近 AR3）
- `LEVEL-1-2`（贴近 AR3）
- `3`（贴近 AR3）
- `2`（贴近 AR2）
- `level-1`（贴近 AR2）
- `172.16.12.0/24`（贴近 AR2）
- `1`（贴近 AR2）
- `3`（贴近 AR3）
- `10.10.34.0/24`（贴近 AR4）
- `4`（贴近 AR4）
- `LEVLE-2`（贴近 AR4）
- `4`（贴近 AR4）
- `10.10.46.0/24`（贴近 AR6）
- `6`（贴近 AR6）
- `外部网络`（贴近 AR6）
- `静态路由到网络1`（贴近 AR1）
- `网络1`（贴近 AR5）
- `默认路由到外部网络`（贴近 AR4）
- `49.0002`（贴近 AR1）
- `49.0001`（贴近 AR4）

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
isis 1
isis
Begin with
firewall zone Local
interface GigabitEthernet0/0/0
interface GigabitEthernet0/0/1
interface GigabitEthernet0/0/2
interface NULL0
ip route-static 172.16.13.0 255.255.255.0 10.10.15.5
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
import-route static level-1
area-authentication-mode
priority 15
ip address 10.10.13.1 255.255.255.0
isis enable 1
isis enable
isis authentication-mode
ip address 172.16.14.1 255.255.255.0
ip address 10.10.15.1 255.255.255.0
authentication-mode password
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
aaa
isis 1
isis
Begin with
firewall zone Local
interface GigabitEthernet0/0/0
interface GigabitEthernet0/0/1
interface GigabitEthernet0/0/2
interface NULL0
ip route-static 0.0.0.0 0.0.0.0 10.10.46.6
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
default-route-advertise always
domain-authentication-mode
priority 15
ip address 10.10.34.4 255.255.255.0
isis enable 1
isis enable
ip address 10.10.46.4 255.255.255.0
authentication-mode password
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
isis 1
isis
Begin with
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
network-entity 49.0002.0000.0000.0003.00
area-authentication-mode
domain-authentication-mode
summary 172.16.12.0 255.255.252.0
priority 15
ip address 10.10.34.3 255.255.255.0
isis enable 1
isis enable
ip address 10.10.13.3 255.255.255.0
isis authentication-mode md5
ip address 10.10.23.3 255.255.255.0
authentication-mode password
```

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
isis 1
isis
Begin with
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
is-level level-1
network-entity 49.0002.0000.0000.0002.00
area-authentication-mode
priority 15
ip address 10.10.23.2 255.255.255.0
isis enable 1
isis enable
isis authentication-mode
ip address 172.16.12.1 255.255.255.0
authentication-mode password
```

## 六、验收要点

（待本地模型跑通后回填：需连通的 PC 对、需隔离的 PC 对、关键验证命令）
