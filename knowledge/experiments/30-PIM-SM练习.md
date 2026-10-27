# 实验 30：PIM-SM练习

- 来源目录：`PIM-SM练习`
- 拓扑文件：`paper.topo`

## 一、题目要求

实验步骤：
1、根据拓扑图信息完成所有设备接口、名称配置，全网使用OSPF路由协议实现互通；
2、按照组播路由配置信息完成各设备组播配置，AR1的G0/0/0及AR2的G0/0/0、G0/0/1接口激活IGMPv2；其余路由的所有接口激活PIM SM路由协议；
3、在AR5中查看当前的BSR及RP信息，观察当前的BSR和RP情况；
4、使PC1、PC2发送组播成员报告报文，观察当前AR1和AR2哪台是查询器，并且观察当前IGMP组有哪些，查看AR1中组播路由，看是否有组播路由信息；
5、组播源1启动VLC播放视频，PC2、PC3启动VLC进行接收，验证组播数据是否成功，成功后，在AR1、AR2中查看组播路由表，看看组播树是SPT还是RPT，RPT树的RP是哪个。
6、把AR1、AR2的G0/0/0接口改为IGMPv3，组播服务器2设置组播IP为224.1.1.1，PC2、PC3组播改为IGMPv3，组播地址均为224.1.1.1，PC1组播源为
10.10.20.100，PC2组播源为10.10.10.100，两台服务器均启动组播（播放不同的MP4文件），启动PC1、PC2 VLC进行接收，观察是否可以成功按照组播源接收视频。
7、保存，提交ans文档。

## 二、设备清单

| 设备 | 型号 | Console(Telnet)端口 | 关键参数 |
|---|---|---|---|
| AR1 | AR2220 | 2002 | - |
| AR2 | AR2220 | 2006 | - |
| AR4 | AR2220 | 2003 | - |
| AR5 | AR2220 | 2004 | - |
| AR6 | AR2220 | 2005 | - |
| LSW1 | S5700 | 2001 | - |
| PC1 | PC | - | IP 10.10.12.10/24 |
| PC2 | PC | - | IP 10.10.12.20/24 |
| PC3 | PC | - | IP 192.168.2.10/24 |
| 组播服务器1 | MCS | - | IP 10.10.10.100/24，网关 10.10.10.1 |
| 组播服务器2 | MCS | - | IP 10.10.20.100/24，网关 10.10.20.1 |

## 三、链路连接

- LSW1 `GigabitEthernet0/0/2` ↔ PC2 `Ethernet0/0/0`（Copper）
- LSW1 `GigabitEthernet0/0/3` ↔ PC1 `Ethernet0/0/0`（Copper）
- 组播服务器1 `Ethernet0/0/0` ↔ AR5 `GigabitEthernet0/0/0`（Copper）
- AR5 `GigabitEthernet0/0/1` ↔ AR6 `GigabitEthernet0/0/0`（Copper）
- AR6 `GigabitEthernet0/0/1` ↔ AR4 `GigabitEthernet0/0/0`（Copper）
- LSW1 `GigabitEthernet0/0/4` ↔ AR2 `GigabitEthernet0/0/0`（Copper）
- AR2 `GigabitEthernet0/0/1` ↔ AR4 `GigabitEthernet0/0/1`（Copper）
- AR2 `GigabitEthernet0/0/2` ↔ PC3 `Ethernet0/0/0`（Copper）
- AR4 `GigabitEthernet0/0/2` ↔ 组播服务器2 `Ethernet0/0/0`（Copper）
- AR1 `GigabitEthernet0/0/0` ↔ LSW1 `GigabitEthernet0/0/1`（Copper）
- AR6 `GigabitEthernet0/0/2` ↔ AR1 `GigabitEthernet0/0/1`（Copper）

## 四、拓扑图上的文字标注

- `组播IP:224.1.1.1`（贴近 组播服务器1）
- `10.10.12.0/24`（贴近 LSW1）
- `2`（贴近 AR2）
- `DM-SM组播网络`（贴近 AR4）
- `10.10.10.0/24`（贴近 AR5）
- `100`（贴近 组播服务器1）
- `1`（贴近 AR5）
- `10.10.56.0/24`（贴近 AR6）
- `5`（贴近 AR5）
- `6`（贴近 AR6）
- `4`（贴近 AR4）
- `10.10.46.0/24`（贴近 AR4）
- `6`（贴近 AR6）
- `10.10.16.0/24`（贴近 AR1）
- `1`（贴近 AR1）
- `6`（贴近 AR1）
- `10.10.24.0/24`（贴近 AR2）
- `4`（贴近 AR4）
- `2`（贴近 AR2）
- `1`（贴近 AR1）
- `192.168.2.0/24`（贴近 PC3）
- `1`（贴近 AR2）
- `10`（贴近 PC3）
- `组播IP:224.1.1.2`（贴近 PC3）
- `10.10.10.20.0/24`（贴近 组播服务器2）
- `1`（贴近 AR4）
- `100`（贴近 组播服务器2）
- `C-RP lo0:4.4.4.4/32`（贴近 组播服务器2）
- `C-RP lo0:6.6.6.6/32`（贴近 AR6）
- `C-BSR lo0:2.2.2.2/32`（贴近 PC3）
- `加入组播：224.1.1.1`（贴近 PC3）

## 五、参考答案（从 .model 自动提取，按设备分组）

> 说明：该列表由实验包的「参考答案」文件提取，仅含命令文本、不含缩进层级；
> 部分行是设备默认配置，需结合题目与拓扑判断哪些是本题真正要求下发的配置。

### AR4

```
sysname AR4
snmp-agent local-engineid 800007DB03000000000000
snmp-agent
clock timezone China-Standard-Time minus 08:00:00
portal local-server load flash:/portalpage.zip
drop illegal-mac alarm
multicast routing-enable
wlan ac-global carrier id other ac id 0
set cpu-usage threshold 80 restore 75
aaa
firewall zone Local
interface GigabitEthernet0/0/0
interface GigabitEthernet0/0/1
interface GigabitEthernet0/0/2
interface NULL0
interface LoopBack0
ospf 1
ospf
Begin with
pim
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
ip address 10.10.46.4 255.255.255.0
pim sm
ip address 10.10.24.4 255.255.255.0
ip address 10.10.20.1 255.255.255.0
ip address 4.4.4.4 255.255.255.255
area 0.0.0.0
area
c-rp LoopBack0
authentication-mode password
network 0.0.0.0 255.255.255.255
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
multicast routing-enable
wlan ac-global carrier id other ac id 0
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
ip address 10.10.10.1 255.255.255.0
pim sm
ip address 10.10.56.5 255.255.255.0
area 0.0.0.0
area
authentication-mode password
network 0.0.0.0 255.255.255.255
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
multicast routing-enable
wlan ac-global carrier id other ac id 0
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
ip address 10.10.12.1 255.255.255.0
igmp enable
igmp version 3
ip address 10.10.16.1 255.255.255.0
pim sm
area 0.0.0.0
area
authentication-mode password
network 0.0.0.0 255.255.255.255
network
```

### LSW1

```
sysname LSW1
undo info-center enable
vlan batch 10
stp disable
cluster enable
ntdp enable
ndp enable
drop illegal-mac alarm
diffserv domain default
drop-profile default
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
authentication-scheme default
authorization-scheme default
accounting-scheme default
domain default
domain default_admin
local-user admin password simple admin
local-user admin service-type http
port link-type access
port default vlan 10
```

### AR2

```
sysname AR2
snmp-agent local-engineid 800007DB03000000000000
snmp-agent
clock timezone China-Standard-Time minus 08:00:00
portal local-server load flash:/portalpage.zip
drop illegal-mac alarm
multicast routing-enable
wlan ac-global carrier id other ac id 0
set cpu-usage threshold 80 restore 75
aaa
firewall zone Local
interface GigabitEthernet0/0/0
interface GigabitEthernet0/0/1
interface GigabitEthernet0/0/2
interface NULL0
interface LoopBack0
ospf 1
ospf
Begin with
pim
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
igmp enable
igmp version 3
ip address 10.10.24.2 255.255.255.0
pim sm
ip address 192.168.2.1 255.255.255.0
ip address 2.2.2.2 255.255.255.255
area 0.0.0.0
area
c-bsr LoopBack0
authentication-mode password
network 0.0.0.0 255.255.255.255
network
```

### AR6

```
sysname AR6
snmp-agent local-engineid 800007DB03000000000000
snmp-agent
clock timezone China-Standard-Time minus 08:00:00
portal local-server load flash:/portalpage.zip
drop illegal-mac alarm
multicast routing-enable
wlan ac-global carrier id other ac id 0
set cpu-usage threshold 80 restore 75
aaa
firewall zone Local
interface GigabitEthernet0/0/0
interface GigabitEthernet0/0/1
interface GigabitEthernet0/0/2
interface NULL0
interface LoopBack0
ospf 1
ospf
Begin with
pim
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
ip address 10.10.56.6 255.255.255.0
pim sm
ip address 10.10.46.6 255.255.255.0
ip address 10.10.16.6 255.255.255.0
ip address 6.6.6.6 255.255.255.255
area 0.0.0.0
area
c-rp LoopBack0
authentication-mode password
network 0.0.0.0 255.255.255.255
network
```

## 六、验收要点

（待本地模型跑通后回填：需连通的 PC 对、需隔离的 PC 对、关键验证命令）
