# 实验 32：RIPv1配置练习

- 来源目录：`RIPv1配置练习`
- 拓扑文件：`paper.topo`

## 一、题目要求

配置要求：
1、按照拓扑图信息配置路由器各个接口IP地址。
2、三个路由器分别配置RIPv1路由协议，通告所有接口网络，使全网互通。
3、把AR6接口G0/0/2配置为静默接口。

提交内容：
1、提交AR6的RIP路由邻居的截图
2、提交AR6路由表截图，并指出哪些路由是通过RIP学习得到的，是否已经具备网路中所有网络的路由。
3、使用WIRESHARK在AR6接口G0/0/1上抓包并截图，在截图中指出从AR7传递了哪些网络的路由。
4、使用WIRESHARK在AR6接口G0/0/2 分别在配置为静默接口前和配置为静默接口后进行抓包，观察前后信息的变化，截图说明。
5、提交 ans文档。

## 二、设备清单

| 设备 | 型号 | Console(Telnet)端口 | 关键参数 |
|---|---|---|---|
| AR6 | AR2220 | 2004 | - |
| AR7 | AR2220 | 2005 | - |
| AR8 | AR2220 | 2006 | - |
| LSW1 | S5700 | 2007 | - |
| LSW2 | S5700 | 2008 | - |
| PC5 | PC | - | IP 192.168.6.10/24，网关 192.168.6.1 |
| PC6 | PC | - | IP 172.16.1.10/24，网关 172.16.1.1 |
| PC7 | PC | - | IP 172.16.1.20/24，网关 172.16.1.1 |

## 三、链路连接

- AR6 `GigabitEthernet0/0/0` ↔ LSW1 `GigabitEthernet0/0/1`（Copper）
- LSW1 `GigabitEthernet0/0/2` ↔ AR8 `GigabitEthernet0/0/0`（Copper）
- AR6 `GigabitEthernet0/0/1` ↔ AR7 `GigabitEthernet0/0/0`（Copper）
- AR7 `GigabitEthernet0/0/1` ↔ AR8 `GigabitEthernet0/0/1`（Copper）
- AR8 `GigabitEthernet0/0/2` ↔ LSW2 `GigabitEthernet0/0/1`（Copper）
- LSW2 `GigabitEthernet0/0/2` ↔ PC6 `Ethernet0/0/0`（Copper）
- LSW2 `GigabitEthernet0/0/3` ↔ PC7 `Ethernet0/0/0`（Copper）
- AR6 `GigabitEthernet0/0/2` ↔ PC5 `Ethernet0/0/0`（Copper）

## 四、拓扑图上的文字标注

- `68.0.0.0/24`（贴近 LSW1）
- `6`（贴近 AR6）
- `8`（贴近 AR8）
- `172.16.1.1/16`（贴近 AR8）
- `172.16.1.10/24`（贴近 PC6）
- `172.16.1.20/16`（贴近 PC7）
- `67.0.0.0/24`（贴近 AR7）
- `6`（贴近 AR6）
- `7`（贴近 AR7）
- `7`（贴近 AR7）
- `8`（贴近 AR8）
- `192.168.6.0/24`（贴近 AR6）
- `10`（贴近 PC5）
- `1`（贴近 AR6）
- `网络1`（贴近 PC5）
- `网络2`（贴近 PC7）
- `78.0.0.0/24`（贴近 AR8）

## 五、参考答案（从 .model 自动提取，按设备分组）

> 说明：该列表由实验包的「参考答案」文件提取，仅含命令文本、不含缩进层级；
> 部分行是设备默认配置，需结合题目与拓扑判断哪些是本题真正要求下发的配置。

### AR7

```
sysname AR7
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
ip address 67.0.0.7 255.255.255.0
ip address 78.0.0.7 255.255.255.0
version 1
network 67.0.0.0
network 78.0.0.0
authentication-mode password
```

### AR8

```
sysname AR8
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
ip address 68.0.0.8 255.255.255.0
ip address 78.0.0.8 255.255.255.0
ip address 172.16.1.1 255.255.255.0
version 1
network 78.0.0.0
network 68.0.0.0
network 172.16.0.0
authentication-mode password
unknown
sysname AR4
portal local-server load portalpage.zip
ip route-static 192.168.1.0 255.255.255.0 10.10.34.3
ip route-static 192.168.2.0 255.255.255.0 10.10.24.2
ip address 10.10.34.4 255.255.255.0
ip address 10.10.24.4 255.255.255.0
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
ip address 68.0.0.6 255.255.255.0
ip address 67.0.0.6 255.255.255.0
ip address 192.168.6.1 255.255.255.0
version 1
network 192.168.6.0
network 68.0.0.0
network 67.0.0.0
silent-interface GigabitEthernet0/0/2
authentication-mode password
unknown
sysname AR1
portal local-server load portalpage.zip
ip route-static 0.0.0.0 0.0.0.0 10.10.13.3
ip route-static 0.0.0.0 0.0.0.0 10.10.12.2 preference 80
ip route-static 192.168.2.0 255.255.255.0 10.10.12.2
ip address 10.10.13.1 255.255.255.0
ip address 10.10.12.1 255.255.255.0
ip address 192.168.1.1 255.255.255.0
```

## 六、验收要点

（待本地模型跑通后回填：需连通的 PC 对、需隔离的 PC 对、关键验证命令）
