# 实验 06：DHCP服务器配置练习V2

- 来源目录：`DHCP服务器配置练习V2`
- 拓扑文件：`paper.topo`

## 一、题目要求

要求如下：
1、按照拓扑中标示信息配置各网络设备，交换机连接终端的接口均为ACCESS模式，交换机只创建必要的VLAN;
2、配置DHCP服务，具体如下：
   1）SW1中VLAN 10 使用接口模式配置DHCP服务；
   2）在SW1中配置全局DHCP服务器，为VLAN 20、30分配IP地址，网关分别为192.168.10.1、192.168.20.1，，DNS服务器为114.114.114.114；
   3）在SW1中配置为VLAN 40中继DHCP服务器，DHCP服务器为AR1（IP 192.168.100.1）;
   4）在AR1中配置全局DHCP服务，为VLAN 40动态分配IP地址，网关为192.168.40.2，192.168.40.1、192.168.40.250-192.168.40.254为保留地址；
3、配置最优的路由，使得内网均可以与外网互通，所有路由均使用静态明细路由；
4、验证各个VLAN终端通过DHCP获取IP地址，所内网所有VLAN与外网互通，截图提交；
5、保存配置，生成ans文档提交。

## 二、设备清单

| 设备 | 型号 | Console(Telnet)端口 | 关键参数 |
|---|---|---|---|
| AR1 | AR2220 | 2000 | - |
| PC1 | PC | - | IP 10.10.10.10/24，网关 10.10.10.1 |
| PC2 | PC | - | IP 192.168.10.254/24，网关 192.168.10.1 |
| PC3 | PC | - | IP 192.168.20.254/24，网关 192.168.20.1 |
| PC4 | PC | - | IP 192.168.30.254/24，网关 192.168.30.1 |
| PC5 | PC | - | IP 192.168.40.249/24，网关 192.168.40.2 |
| SW1 | S5700 | 2001 | - |
| SW2 | S5700 | 2003 | - |

## 三、链路连接

- SW1 `GigabitEthernet0/0/1` ↔ AR1 `GigabitEthernet0/0/0`（Copper）
- SW1 `GigabitEthernet0/0/2` ↔ PC2 `Ethernet0/0/0`（Copper）
- SW1 `GigabitEthernet0/0/3` ↔ PC3 `Ethernet0/0/0`（Copper）
- SW1 `GigabitEthernet0/0/4` ↔ PC4 `Ethernet0/0/0`（Copper）
- SW1 `GigabitEthernet0/0/5` ↔ SW2 `GigabitEthernet0/0/3`（Copper）
- SW2 `GigabitEthernet0/0/1` ↔ PC5 `Ethernet0/0/0`（Copper）
- AR1 `GigabitEthernet0/0/2` ↔ SW2 `GigabitEthernet0/0/4`（Copper）
- AR1 `GigabitEthernet0/0/1` ↔ PC1 `Ethernet0/0/0`（Copper）

## 四、拓扑图上的文字标注

- `VLAN 10`（贴近 SW1）
- `VLAN 20`（贴近 PC3）
- `VLAN 30`（贴近 PC4）
- `VLAN 40`（贴近 SW2）
- `TRUNK ALL`（贴近 SW2）
- `10.10.10.0/24`（贴近 PC1）
- `10`（贴近 PC1）
- `1`（贴近 AR1）
- `192.168.100.0/24`（贴近 SW1）
- `1`（贴近 AR1）
- `2`（贴近 SW1）
- `192.168.200.1/24`（贴近 SW2）
- `内网`（贴近 PC4）
- `外网`（贴近 PC1）

## 五、参考答案（从 .model 自动提取，按设备分组）

> 说明：该列表由实验包的「参考答案」文件提取，仅含命令文本、不含缩进层级；
> 部分行是设备默认配置，需结合题目与拓扑判断哪些是本题真正要求下发的配置。

### SW2

```
sysname SW2
vlan batch 40 200
cluster enable
ntdp enable
ndp enable
drop illegal-mac alarm
diffserv domain default
drop-profile default
aaa
interface Vlanif1
interface Vlanif40
interface Vlanif200
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
ip route-static 10.10.10.0 255.255.255.0 192.168.200.1
user-interface con 0
user-interface vty 0 4
authentication-scheme default
authorization-scheme default
accounting-scheme default
domain default
domain default_admin
local-user admin password simple admin
local-user admin service-type http
ip address 192.168.40.2 255.255.255.0
ip address 192.168.200.2 255.255.255.0
port link-type access
port default vlan 40
port link-type trunk
port trunk allow-pass vlan 2 to 4094
port default vlan 200
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
dhcp enable
ip pool VLAN-40
ip pool
Begin with
aaa
firewall zone Local
interface GigabitEthernet0/0/0
interface GigabitEthernet0/0/1
interface GigabitEthernet0/0/2
interface NULL0
ip route-static 192.168.10.0 255.255.255.0 192.168.100.2
ip route-static 192.168.20.0 255.255.255.0 192.168.100.2
ip route-static 192.168.30.0 255.255.255.0 192.168.100.2
ip route-static 192.168.40.0 255.255.255.0 192.168.200.2
user-interface con 0
user-interface vty 0 4
user-interface vty 16 20
wlan ac
gateway-list 192.168.40.2
network 192.168.40.0 mask 255.255.255.0
excluded-ip-address 192.168.40.1
excluded-ip-address 192.168.40.250 192.168.40.254
authentication-scheme default
authorization-scheme default
accounting-scheme default
domain default
domain default_admin
local-user admin service-type http
priority 15
ip address 192.168.100.1 255.255.255.0
dhcp select global
ip address 10.10.10.1 255.255.255.0
ip address 192.168.200.1 255.255.255.0
authentication-mode password
```

### SW1

```
sysname SW1
vlan batch 10 20 30 40 100
cluster enable
ntdp enable
ndp enable
drop illegal-mac alarm
dhcp enable
diffserv domain default
drop-profile default
ip pool vlan-20
ip pool
Begin with
ip pool vlan-30
aaa
interface Vlanif1
interface Vlanif10
interface Vlanif20
interface Vlanif30
interface Vlanif40
interface Vlanif100
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
ip route-static 10.10.10.0 255.255.255.0 192.168.100.1
user-interface con 0
user-interface vty 0 4
gateway-list 192.168.20.1
network 192.168.20.0 mask 255.255.255.0
dns-list 114.114.114.114
gateway-list 192.168.30.1
network 192.168.30.0 mask 255.255.255.0
authentication-scheme default
authorization-scheme default
accounting-scheme default
domain default
domain default_admin
local-user admin password simple admin
local-user admin service-type http
ip address 192.168.10.1 255.255.255.0
dhcp select interface
ip address 192.168.20.1 255.255.255.0
dhcp select global
ip address 192.168.30.1 255.255.255.0
ip address 192.168.40.1 255.255.255.0
dhcp select relay
dhcp relay server-ip 192.168.100.1
ip address 192.168.100.2 255.255.255.0
port link-type access
port default vlan 100
port default vlan 10
port default vlan 20
port default vlan 30
port link-type trunk
port trunk allow-pass vlan 2 to 4094
```

## 六、验收要点

（待本地模型跑通后回填：需连通的 PC 对、需隔离的 PC 对、关键验证命令）
