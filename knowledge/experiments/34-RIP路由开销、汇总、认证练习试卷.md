# 实验 34：RIP路由开销、汇总、认证练习试卷

- 来源目录：`RIP路由开销、汇总、认证练习试卷`
- 拓扑文件：`paper.topo`

## 一、题目要求

配置要求：
1、按照拓扑图中信息对各个设备接口进行配置，全网使用置RIPv2协议；
2、在所用需要向邻居通告路由的接口配置认证信息，认证密文为“huawei”，使用标准（usual）MD5 加密；
3、在AR1通告给邻居的接口上均进行手工路由汇总配置，要求进行精确汇总；
4、为保证高带宽路由优先选择，需要在AR1与AR2对于从串口上接收的路由信息增加5个metric。

提交要求：
1、ANS文档；
2、提交AR2路由表截图，指出AR3路由表中192.168.1.16.0/28和192.168.1.32/28两条路由是否已经被汇总路由所替代；
3、提交AR1路由表截图，指出192.168.30.0/24下一跳是哪个路由器；
4、把AR2的G0/0/0关闭，再提交AR1路由表。指出指出192.168.30.0/24下一跳是哪个路由器，路由开销是多少。

## 二、设备清单

| 设备 | 型号 | Console(Telnet)端口 | 关键参数 |
|---|---|---|---|
| AR1 | AR2220 | 2000 | - |
| AR2 | AR2220 | 2001 | - |
| AR3 | AR2220 | 2002 | - |
| PC1 | PC | - | - |
| PC2 | PC | - | - |
| PC3 | PC | - | - |

## 三、链路连接

- AR1 `GigabitEthernet0/0/0` ↔ AR2 `GigabitEthernet0/0/0`（Copper）
- AR2 `GigabitEthernet0/0/1` ↔ AR3 `GigabitEthernet0/0/0`（Copper）
- AR1 `Ethernet0/0/0` ↔ AR3 `Ethernet0/0/0`（Serial）
- AR1 `GigabitEthernet0/0/1` ↔ PC1 `Ethernet0/0/0`（Copper）
- PC2 `Ethernet0/0/0` ↔ AR1 `GigabitEthernet0/0/2`（Copper）
- AR3 `GigabitEthernet0/0/1` ↔ PC3 `Ethernet0/0/0`（Copper）

## 四、拓扑图上的文字标注

- `10.10.13.0/24`（贴近 AR2）
- `1`（贴近 AR1）
- `3`（贴近 AR3）
- `10.10.12.0/24`（贴近 AR2）
- `1`（贴近 AR1）
- `2`（贴近 AR2）
- `2`（贴近 AR2）
- `3`（贴近 AR3）
- `10.10.23.0/24`（贴近 AR3）
- `RIP`（贴近 AR2）
- `192.168.1.16/28`（贴近 AR1）
- `22`（贴近 PC1）
- `21`（贴近 AR1）
- `192.168.1.32/28`（贴近 AR1）
- `41`（贴近 PC2）
- `40`（贴近 AR1）
- `192.168.30.0/24`（贴近 PC3）
- `1`（贴近 AR3）
- `10`（贴近 PC3）
- `2M链路`（贴近 AR2）
- `千兆链路`（贴近 AR2）
- `千兆链路`（贴近 AR2）

## 五、参考答案（从 .model 自动提取，按设备分组）

> 说明：该列表由实验包的「参考答案」文件提取，仅含命令文本、不含缩进层级；
> 部分行是设备默认配置，需结合题目与拓扑判断哪些是本题真正要求下发的配置。

### AR3

```
sysname AR3
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
rip 1
rip
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
link-protocol ppp
ip address 10.10.13.3 255.255.255.0
rip authentication-mode md5 usual
rip metricin 5
Regular
ip address 10.10.23.3 255.255.255.0
ip address 192.168.30.1 255.255.255.0
version 2
network 10.0.0.0
network 192.168.30.0
authentication-mode password
```

### AR1

```
sysname AR1
board add 0/1 2SA
snmp-agent local-engineid 800007DB03000000000000
snmp-agent
clock timezone China-Standard-Time minus 08:00:00
portal local-server load portalpage.zip
drop illegal-mac alarm
set cpu-usage threshold 80 restore 75
aaa
firewall zone Local
interface Serial1/0/0
interface Serial1/0/1
interface GigabitEthernet0/0/0
interface GigabitEthernet0/0/1
interface GigabitEthernet0/0/2
interface NULL0
rip 1
rip
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
link-protocol ppp
ip address 10.10.13.1 255.255.255.0
rip authentication-mode md5 usual
rip metricin 5
Regular
rip summary-address 192.168.1.0 255.255.255.192
ip address 10.10.12.1 255.255.255.0
rip authentication-mode md5
ip address 192.168.1.21 255.255.255.240
ip address 192.168.1.40 255.255.255.240
version 2
network 192.168.1.0
network 10.0.0.0
authentication-mode password
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
aaa
firewall zone Local
interface GigabitEthernet0/0/0
interface GigabitEthernet0/0/1
interface GigabitEthernet0/0/2
interface NULL0
rip 1
rip
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
rip authentication-mode md5
ip address 10.10.23.2 255.255.255.0
rip authentication-mode md5 usual
version 2
network 10.0.0.0
authentication-mode password
```

## 六、验收要点

（待本地模型跑通后回填：需连通的 PC 对、需隔离的 PC 对、关键验证命令）
