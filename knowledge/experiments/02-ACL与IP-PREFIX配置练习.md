# 实验 02：ACL与IP-PREFIX配置练习

- 来源目录：`ACL与IP-PREFIX配置练习`
- 拓扑文件：`paper.topo`

## 一、题目要求

1、按照拓扑图所示信息配置各个设备；
2、配置完成后，查看AR1路由表并截图，观察此时AR1到192.168.3.0/24及192.168.30.0/24的路由的下一跳分别是哪个路由器；
3、在AR1配置一条基本ACL，规则是允许192.168.3.0/24网络通过；
4、在AR1配置一个IP-PREFIX网路前缀，允许92.168.30.0/24通过；
5、在接口上配置增加RIP接收路由开销，使得192.168.3.0/24的下一条是AR2，192.168.30.0/24的下一跳是AR4。
6、查看路由表并截图，观察是否实现上面目标；
7、提交ANS文档。

## 二、设备清单

| 设备 | 型号 | Console(Telnet)端口 | 关键参数 |
|---|---|---|---|
| AR1 | AR2220 | 2000 | - |
| AR2 | AR2220 | 2001 | - |
| AR3 | AR2220 | 2002 | - |
| AR4 | AR2220 | 2003 | - |
| LSW1 | S5700 | 2004 | - |
| PC1 | PC | - | - |
| PC2 | PC | - | - |
| PC4 | PC | - | - |
| PC5 | PC | - | - |

## 三、链路连接

- AR1 `GigabitEthernet0/0/0` ↔ AR2 `GigabitEthernet0/0/0`（Copper）
- AR1 `GigabitEthernet0/0/1` ↔ AR4 `GigabitEthernet0/0/0`（Copper）
- AR4 `GigabitEthernet0/0/1` ↔ AR3 `GigabitEthernet0/0/0`（Copper）
- AR3 `GigabitEthernet0/0/1` ↔ AR2 `GigabitEthernet0/0/1`（Copper）
- AR3 `GigabitEthernet0/0/2` ↔ LSW1 `GigabitEthernet0/0/1`（Copper）
- LSW1 `GigabitEthernet0/0/2` ↔ PC1 `Ethernet0/0/0`（Copper）
- LSW1 `GigabitEthernet0/0/3` ↔ PC2 `Ethernet0/0/0`（Copper）
- LSW1 `GigabitEthernet0/0/4` ↔ PC4 `Ethernet0/0/0`（Copper）
- LSW1 `GigabitEthernet0/0/5` ↔ PC5 `Ethernet0/0/0`（Copper）

## 四、拓扑图上的文字标注

- `192.168.3.10/24`（贴近 PC1）
- `192.168.30.10/24`（贴近 PC5）
- `10.10.12.0/24`（贴近 AR2）
- `1`（贴近 AR1）
- `2`（贴近 AR2）
- `1`（贴近 AR1）
- `4`（贴近 AR4）
- `Ripv2`（贴近 AR4）
- `10.10.14.0/24`（贴近 AR4）
- `10.10.23.0/24`（贴近 AR3）
- `2`（贴近 AR2）
- `3`（贴近 AR3）
- `3`（贴近 AR3）
- `4`（贴近 AR4）
- `10.10.34.0/24`（贴近 AR3）
- `192.168.130.10/24`（贴近 PC4）

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
aaa
firewall zone Local
interface GigabitEthernet0/0/0
interface GigabitEthernet0/0/1
interface GigabitEthernet0/0/2
interface NULL0
rip 1
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
version 2
network 10.0.0.0
authentication-mode password
```

### AR1

```
sysname AR1
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
ip ip-prefix route-test index 10 permit 192.168.30.0 24
permit 192.168.30.0 24
End with
user-interface con 0
user-interface vty 0 4
user-interface vty 16 20
wlan ac
rule 5 permit source 192.168.3.0 0
permit source 192.168.3.0 0
authentication-scheme default
authorization-scheme default
accounting-scheme default
domain default
domain default_admin
local-user admin service-type http
priority 15
ip address 10.10.12.1 255.255.255.0
rip metricin ip-prefix route-test 5
rip metricin ip-prefix
ip address 10.10.14.1 255.255.255.0
rip metricin 2000 5
rip metricin
version 2
network 10.0.0.0
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
ip address 10.10.14.4 255.255.255.0
ip address 10.10.34.4 255.255.255.0
version 2
network 10.0.0.0
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
ip address 10.10.34.3 255.255.255.0
ip address 10.10.23.3 255.255.255.0
ip address 192.168.3.1 255.255.255.0
ip address 192.168.30.1 255.255.255.0 sub
version 2
network 10.0.0.0
network 192.168.3.0
network 192.168.30.0
authentication-mode password
```

## 六、验收要点

（待本地模型跑通后回填：需连通的 PC 对、需隔离的 PC 对、关键验证命令）
