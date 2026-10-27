# 实验 29：PBR三个实验

- 来源目录：`PBR三个实验`
- 拓扑文件：`PBR-1-基本配置.topo`

## 一、题目要求

1、按拓扑结构完成路由器名称和IP地址配置，路由器名称AR序号-学号后三位（如AR1-101、AR2-101）
2、按拓扑结构配置OSPF
3、本地策略路由：
（1）源地址为192.168.1.0/24，目的地址为172.16.1.0/24的报文从AR2方向发送
（2）源地址为192.168.2.0/24，目的地址为172.16.2.0/24的报文从AR3方向发送
4、保存的文件名为学号-姓名的ans文件并上传

## 二、设备清单

| 设备 | 型号 | Console(Telnet)端口 | 关键参数 |
|---|---|---|---|
| AR1 | AR2220 | 2000 | - |
| AR2 | AR2220 | 2001 | - |
| AR3 | AR2220 | 2002 | - |
| AR4 | AR2220 | 2003 | - |

## 三、链路连接

- AR1 `GigabitEthernet0/0/0` ↔ AR2 `GigabitEthernet0/0/1`（Copper）
- AR1 `GigabitEthernet0/0/1` ↔ AR3 `GigabitEthernet0/0/0`（Copper）
- AR2 `GigabitEthernet0/0/0` ↔ AR4 `GigabitEthernet0/0/1`（Copper）
- AR3 `GigabitEthernet0/0/1` ↔ AR4 `GigabitEthernet0/0/0`（Copper）

## 四、拓扑图上的文字标注

- `OSPF area 0`（贴近 AR3）
- `10.10.12.0/24`（贴近 AR1）
- `10.10.24.0/24`（贴近 AR4）
- `10.10.13.0/24`（贴近 AR3）
- `10.10.34.0/24`（贴近 AR4）
- `1`（贴近 AR1）
- `1`（贴近 AR1）
- `2`（贴近 AR2）
- `2`（贴近 AR2）
- `3`（贴近 AR3）
- `3`（贴近 AR3）
- `4`（贴近 AR4）
- `4`（贴近 AR4）

## 五、参考答案（从 .model 自动提取，按设备分组）

> 说明：该列表由实验包的「参考答案」文件提取，仅含命令文本、不含缩进层级；
> 部分行是设备默认配置，需结合题目与拓扑判断哪些是本题真正要求下发的配置。

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
firewall zone Local
interface GigabitEthernet0/0/0
interface GigabitEthernet0/0/1
interface GigabitEthernet0/0/2
interface NULL0
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
ip address 10.10.13.3 255.255.255.0
ip address 10.10.34.3 255.255.255.0
area 0.0.0.0
authentication-mode password
network 10.10.13.0 0.0.0.255
network 10.10.34.0 0.0.0.255
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
firewall zone Local
interface GigabitEthernet0/0/0
interface GigabitEthernet0/0/1
interface GigabitEthernet0/0/2
interface NULL0
interface LoopBack0
interface LoopBack1
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
ip address 10.10.34.4 255.255.255.0
ip address 10.10.24.4 255.255.255.0
ip address 172.16.1.1 255.255.255.0
ip address 172.16.2.1 255.255.255.0
area 0.0.0.0
authentication-mode password
network 10.10.24.0 0.0.0.255
network 10.10.34.0 0.0.0.255
network 172.16.1.0 0.0.0.255
network 172.16.2.0 0.0.0.255
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
ip local policy-based-route test
undo info-center enable
set cpu-usage threshold 80 restore 75
acl number 3000
acl number 3001
aaa
firewall zone Local
interface GigabitEthernet0/0/0
interface GigabitEthernet0/0/1
interface GigabitEthernet0/0/2
interface NULL0
interface LoopBack0
interface LoopBack1
interface LoopBack2
ospf 1 router-id 1.1.1.1
user-interface con 0
user-interface vty 0 4
user-interface vty 16 20
policy-based-route test permit node 10
policy-based-route test permit node 20
wlan ac
rule 5 permit ip source 192.168.1.0 0.0.0.255 destination 172.16.1.0 0.0.0.255
rule 10 deny ip
rule 5 permit ip source 192.168.2.0 0.0.0.255 destination 172.16.2.0 0.0.0.255
authentication-scheme default
authorization-scheme default
accounting-scheme default
domain default
domain default_admin
local-user admin service-type http
priority 15
ip address 10.10.12.1 255.255.255.0
ip address 10.10.13.1 255.255.255.0
ip address 192.168.1.1 255.255.255.0
ip address 192.168.2.1 255.255.255.0
ip address 192.168.3.1 255.255.255.0
area 0.0.0.0
authentication-mode password
if-match acl 3000
apply ip-address next-hop 10.10.12.2
if-match acl 3001
apply ip-address next-hop 10.10.13.3
network 10.10.12.0 0.0.0.255
network 10.10.13.0 0.0.0.255
network 192.168.1.0 0.0.0.255
network 192.168.2.0 0.0.0.255
network 192.168.3.0 0.0.0.255
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
ip address 10.10.24.2 255.255.255.0
ip address 10.10.12.2 255.255.255.0
area 0.0.0.0
authentication-mode password
network 10.10.12.0 0.0.0.255
network 10.10.24.0 0.0.0.255
```

## 六、验收要点

（待本地模型跑通后回填：需连通的 PC 对、需隔离的 PC 对、关键验证命令）
