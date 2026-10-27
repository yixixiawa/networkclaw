# 实验 07：DHCP服务器防假冒、饿死攻击

- 来源目录：`DHCP服务器防假冒、饿死攻击`
- 拓扑文件：`paper.topo`

## 一、题目要求

1、按照拓扑图中信息配置交换机及路由器,PC1-PC4使用DHCP获取IP地址，并且查看当前PC获取的IP地址;
2、交换机ACC全局激活DHCP SNOOPING，在所有的端口上激活DHCP SNOOPING，让全部PC重新获取IP地址，观察是否成功；
3、交换机ACC分别在VLAN 1和VLAN 10中配置G0/0/1为可信端口，再让全部PC重新获取IP地址，观察是否成功；
4、在ACC的G0/0/2-G0/0/7中配置防DHCP服务器饿死攻击，设定端口可绑定MAC地址数量为1；
5、保存配置，提交ans文档。

## 二、设备清单

| 设备 | 型号 | Console(Telnet)端口 | 关键参数 |
|---|---|---|---|
| ACC | S5700 | 2000 | - |
| AR1 | AR2220 | 2001 | - |
| AR2 | AR2220 | 2002 | - |
| CORE | S5700 | 2003 | - |
| HUB1 | HUB | - | - |
| PC1 | PC | - | IP 192.168.1.253/24，网关 192.168.1.1 |
| PC2 | PC | - | IP 192.168.10.254/24，网关 192.168.10.1 |
| PC3 | PC | - | IP 192.168.1.252/24，网关 192.168.1.1 |
| PC4 | PC | - | IP 192.168.10.253/24，网关 192.168.10.1 |
| PC5 | PC | - | IP 192.168.1.254/24，网关 192.168.1.1 |

## 三、链路连接

- ACC `GigabitEthernet0/0/1` ↔ CORE `GigabitEthernet0/0/1`（Copper）
- ACC `GigabitEthernet0/0/2` ↔ AR1 `GigabitEthernet0/0/0`（Copper）
- ACC `GigabitEthernet0/0/3` ↔ AR2 `GigabitEthernet0/0/0`（Copper）
- ACC `GigabitEthernet0/0/4` ↔ PC3 `Ethernet0/0/0`（Copper）
- ACC `GigabitEthernet0/0/6` ↔ PC2 `Ethernet0/0/0`（Copper）
- ACC `GigabitEthernet0/0/7` ↔ PC4 `Ethernet0/0/0`（Copper）
- HUB1 `Ethernet0/0/0` ↔ ACC `GigabitEthernet0/0/5`（Copper）
- HUB1 `Ethernet0/0/1` ↔ PC1 `Ethernet0/0/0`（Copper）
- HUB1 `Ethernet0/0/2` ↔ PC5 `Ethernet0/0/0`（Copper）

## 四、拓扑图上的文字标注

- `TRUNK ALL`（贴近 ACC）
- `VLAN 1`（贴近 PC3）
- `172.16.1.1/24`（贴近 ACC）
- `VLAN 10`（贴近 PC4）
- `172.16.10.1/24`（贴近 AR2）

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
dhcp enable
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
ip address 172.16.1.1 255.255.255.0
dhcp select interface
authentication-mode password
```

### ACC

```
sysname ACC
vlan batch 10
cluster enable
ntdp enable
ndp enable
drop illegal-mac alarm
dhcp enable
dhcp snooping enable
diffserv domain default
drop-profile default
vlan 1
vlan 10
aaa
interface Vlanif1
interface MEth0/0/1
interface GigabitEthernet0/0/1
interface GigabitEthernet0/0/2
interface GigabitEthernet0/0/3
interface GigabitEthernet0/0/4
interface GigabitEthernet0/0/5
interface GigabitEthernet0/0/6
interface GigabitEthernet0/0/7
interface GigabitEthernet0/0/8
interface GigabitEthernet0/0/9
interface GigabitEthernet0/0/10
interface GigabitEthernet0/0/11
interface GigabitEthernet0/0/12
interface GigabitEthernet0/0/13
interface GigabitEthernet0/0/14
interface GigabitEthernet0/0/15
interface GigabitEthernet0/0/16
interface GigabitEthernet0/0/17
interface GigabitEthernet0/0/18
interface GigabitEthernet0/0/19
interface GigabitEthernet0/0/20
interface GigabitEthernet0/0/21
interface GigabitEthernet0/0/22
interface GigabitEthernet0/0/23
interface GigabitEthernet0/0/24
interface NULL0
user-interface con 0
user-interface vty 0 4
port-group 1
port-group 2
dhcp snooping trusted interface GigabitEthernet0/0/1
authentication-scheme default
authorization-scheme default
accounting-scheme default
domain default
domain default_admin
local-user admin password simple admin
local-user admin service-type http
port link-type trunk
port trunk allow-pass vlan 2 to 4094
port link-type access
dhcp snooping check dhcp-chaddr enable
dhcp snooping max-user-number 1
port default vlan 10
group-member GigabitEthernet0/0/2
group-member GigabitEthernet0/0/3
group-member GigabitEthernet0/0/4
group-member GigabitEthernet0/0/5
group-member GigabitEthernet0/0/6
group-member GigabitEthernet0/0/7
group-member GigabitEthernet0/0/1
```

### CORE

```
sysname CORE
undo info-center enable
vlan batch 10
stp disable
cluster enable
ntdp enable
ndp enable
drop illegal-mac alarm
dhcp enable
diffserv domain default
drop-profile default
aaa
interface Vlanif1
interface Vlanif10
interface MEth0/0/1
interface GigabitEthernet0/0/1
interface GigabitEthernet0/0/2
interface GigabitEthernet0/0/3
interface GigabitEthernet0/0/4
interface GigabitEthernet0/0/5
interface GigabitEthernet0/0/6
interface GigabitEthernet0/0/7
interface GigabitEthernet0/0/8
interface GigabitEthernet0/0/9
interface GigabitEthernet0/0/10
interface GigabitEthernet0/0/11
interface GigabitEthernet0/0/12
interface GigabitEthernet0/0/13
interface GigabitEthernet0/0/14
interface GigabitEthernet0/0/15
interface GigabitEthernet0/0/16
interface GigabitEthernet0/0/17
interface GigabitEthernet0/0/18
interface GigabitEthernet0/0/19
interface GigabitEthernet0/0/20
interface GigabitEthernet0/0/21
interface GigabitEthernet0/0/22
interface GigabitEthernet0/0/23
interface GigabitEthernet0/0/24
interface NULL0
user-interface con 0
user-interface vty 0 4
authentication-scheme default
authorization-scheme default
accounting-scheme default
domain default
domain default_admin
local-user admin password simple admin
local-user admin service-type http
ip address 192.168.1.1 255.255.255.0
dhcp select interface
ip address 192.168.10.1 255.255.255.0
port link-type trunk
port trunk allow-pass vlan 2 to 4094
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
dhcp enable
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
ip address 172.16.10.1 255.255.255.0
dhcp select interface
authentication-mode password
```

## 六、验收要点

（待本地模型跑通后回填：需连通的 PC 对、需隔离的 PC 对、关键验证命令）
