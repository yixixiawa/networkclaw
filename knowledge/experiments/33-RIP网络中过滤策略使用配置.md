# 实验 33：RIP网络中过滤策略使用配置

- 来源目录：`RIP网络中过滤策略使用配置`
- 拓扑文件：`paper.topo`

## 一、题目要求

1、按照拓扑图中配置各网络设备接口IP地址、静态路由及动态路由协议；
2、在AR1配置引入静态路由，在AR3中引入OSPF路由；
3、在AR2路由器中查看路由表，看看当前是否有全部网络的路由，截图；
4、AR2到网络10.10.45.0/24的下一跳是哪个路由器，截图；
5、在AR2中使用ACL配置RIP路由接收路由过滤策略，不接收192.168.1.0/24网络路由，
配置完成后查看AR2路由表看是否除拒绝路由外，其他路由均正常，截图；
6、在AR2中使用IP-PREFIX配置RIP路由发送路由过滤策略，不向AR3发送192.168.2.0/24，
配置完成后，查看AR3路由表，看看是否有192.168.1.0/24及192.168.2.0/24路由，其他路由是否正常，截图；
7、在AR3中，配置RIP引入路由过滤策略，采用ACL配置，不向外发送10.10.45.0/24路由；
配置完成后，查看AR2路由表，看看网络10.10.45.0/24的下一跳是哪个路由器，并且查看34.1.10/24路由是否存在，截图；
8、提交ANS文档。

## 二、设备清单

| 设备 | 型号 | Console(Telnet)端口 | 关键参数 |
|---|---|---|---|
| AR1 | AR2220 | 2000 | - |
| AR2 | AR2220 | 2001 | - |
| AR3 | AR2220 | 2002 | - |
| AR4 | AR2220 | 2003 | - |
| AR5 | AR2220 | 2004 | - |

## 三、链路连接

- AR1 `GigabitEthernet0/0/0` ↔ AR2 `GigabitEthernet0/0/0`（Copper）
- AR2 `GigabitEthernet0/0/1` ↔ AR3 `GigabitEthernet0/0/0`（Copper）
- AR3 `GigabitEthernet0/0/1` ↔ AR4 `GigabitEthernet0/0/0`（Copper）
- AR4 `GigabitEthernet0/0/1` ↔ AR5 `GigabitEthernet0/0/1`（Copper）
- AR5 `GigabitEthernet0/0/0` ↔ AR1 `GigabitEthernet0/0/1`（Copper）

## 四、拓扑图上的文字标注

- `10.10.12.0/24`（贴近 AR2）
- `1`（贴近 AR1）
- `2`（贴近 AR2）
- `10.10.23.0/24`（贴近 AR3）
- `2`（贴近 AR2）
- `3`（贴近 AR3）
- `34.1.1.0/24`（贴近 AR4）
- `1`（贴近 AR1）
- `4`（贴近 AR4）
- `3`（贴近 AR3）
- `5`（贴近 AR5）
- `10.10.45.0/24`（贴近 AR4）
- `4`（贴近 AR4）
- `5`（贴近 AR5）
- `RIP`（贴近 AR2）
- `引入静态路由10.10.45.0/24`（贴近 AR1）
- `引入直连路由`（贴近 AR4）
- `15.1.1.0/24`（贴近 AR5）

## 五、参考答案（从 .model 自动提取，按设备分组）

> 说明：该列表由实验包的「参考答案」文件提取，仅含命令文本、不含缩进层级；
> 部分行是设备默认配置，需结合题目与拓扑判断哪些是本题真正要求下发的配置。

### AR2

```
sysname AR2
snmp-agent local-engineid 800007DB03000000000000
snmp-agent
clock timezone China-Standard-Time minus 08:00:00
portal local-server load portalpage.zip
drop illegal-mac alarm
set cpu-usage threshold 80 restore 75
acl number 2000
acl number
Begin with
aaa
firewall zone Local
interface GigabitEthernet0/0/0
interface GigabitEthernet0/0/1
interface GigabitEthernet0/0/2
interface NULL0
rip 1
rip
ip ip-prefix no-export index 10 deny 192.168.2.0 24
deny 192.168.2.0 24
End with
ip ip-prefix no-export index 20 permit 0.0.0.0 0 less-equal 32
user-interface con 0
user-interface vty 0 4
user-interface vty 16 20
wlan ac
rule 5 deny source 192.168.1.0 0
deny source 192.168.1.0 0
rule 10 permit
permit
authentication-scheme default
authorization-scheme default
accounting-scheme default
domain default
domain default_admin
local-user admin service-type http
priority 15
ip address 10.10.12.2 255.255.255.0
ip address 10.10.23.2 255.255.255.0
version 2
network 10.0.0.0
filter-policy 2000 import
import
Include
filter-policy ip-prefix no-export export
filter-policy ip-prefix
authentication-mode password
```

### AR3

```
sysname AR3
snmp-agent local-engineid 800007DB03000000000000
snmp-agent
clock timezone China-Standard-Time minus 08:00:00
portal local-server load portalpage.zip
drop illegal-mac alarm
set cpu-usage threshold 80 restore 75
acl number 2000
acl number
Begin with
aaa
firewall zone Local
interface GigabitEthernet0/0/0
interface GigabitEthernet0/0/1
interface GigabitEthernet0/0/2
interface NULL0
ospf 1
ospf
rip 1
rip
user-interface con 0
user-interface vty 0 4
user-interface vty 16 20
wlan ac
rule 5 deny source 10.10.45.0 0
deny source 10.10.45.0 0
End with
rule 10 permit
permit
authentication-scheme default
authorization-scheme default
accounting-scheme default
domain default
domain default_admin
local-user admin service-type http
priority 15
ip address 10.10.23.3 255.255.255.0
ip address 34.1.1.3 255.255.255.0
area 0.0.0.0
version 2
network 10.0.0.0
filter-policy 2000 export ospf 1
export ospf
Include
import-route ospf 1
import-route ospf
authentication-mode password
network 34.1.1.3 0.0.0.0
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
ip address 35.1.1.5 255.255.255.0
ip address 10.10.45.5 255.255.255.0
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
firewall zone Local
interface GigabitEthernet0/0/0
interface GigabitEthernet0/0/1
interface GigabitEthernet0/0/2
interface NULL0
ospf 1
ospf
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
ip address 34.1.1.4 255.255.255.0
ip address 10.10.45.4 255.255.255.0
import-route direct
area 0.0.0.0
authentication-mode password
network 34.1.1.4 0.0.0.0
network
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
interface LoopBack1
interface LoopBack2
interface LoopBack3
rip 1
rip
Begin with
ip route-static 10.10.45.0 255.255.255.0 15.1.1.5
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
ip address 15.1.1.1 255.255.255.0
ip address 192.168.1.1 255.255.255.0
ip address 192.168.2.1 255.255.255.0
ip address 192.168.3.1 255.255.255.0
version 2
network 10.0.0.0
network 192.168.1.0
network 192.168.2.0
network 192.168.3.0
network 15.0.0.0
import-route static
authentication-mode password
```

## 六、验收要点

（待本地模型跑通后回填：需连通的 PC 对、需隔离的 PC 对、关键验证命令）
