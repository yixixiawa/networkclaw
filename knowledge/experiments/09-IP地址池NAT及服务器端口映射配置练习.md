# 实验 09：IP地址池NAT及服务器端口映射配置练习

- 来源目录：`IP地址池NAT及服务器端口映射配置练习`
- 拓扑文件：`paper.topo`

## 一、题目要求

要求：
1、按照拓扑图信息配置接口IP地址，内网出口使用默认路由，外网到内网的公网网段使用静态路由；
2、配置内网主机使用NAT访问Internet；
3、配置Web服务器映射，使Internet主机可以访问Web服务。
4、验证NAT配置，使PC1与PC2进行通信，在AR1的G0/0/0抓包，看PC1的IP地址是否已经转换成公网的IP地址。

## 二、设备清单

| 设备 | 型号 | Console(Telnet)端口 | 关键参数 |
|---|---|---|---|
| AR1 | AR2220 | 2000 | - |
| AR2 | AR2220 | 2001 | - |
| Client1 | Client | - | - |
| LSW1 | S5700 | 2002 | - |
| LSW2 | S5700 | 2003 | - |
| PC1 | PC | - | IP 192.168.10.10/24，网关 192.168.10.1 |
| PC2 | PC | - | IP 20.1.1.2/24，网关 20.1.1.1 |
| PC3 | PC | - | IP 192.168.10.20/24，网关 192.168.10.1 |
| Web server | Server | - | - |

## 三、链路连接

- AR1 `GigabitEthernet0/0/0` ↔ AR2 `GigabitEthernet0/0/0`（Copper）
- AR1 `GigabitEthernet0/0/1` ↔ Web server `Ethernet0/0/0`（Copper）
- AR1 `GigabitEthernet0/0/2` ↔ LSW1 `GigabitEthernet0/0/1`（Copper）
- LSW1 `GigabitEthernet0/0/2` ↔ PC1 `Ethernet0/0/0`（Copper）
- LSW1 `GigabitEthernet0/0/3` ↔ PC3 `Ethernet0/0/0`（Copper）
- AR2 `GigabitEthernet0/0/1` ↔ LSW2 `GigabitEthernet0/0/1`（Copper）
- PC2 `Ethernet0/0/0` ↔ LSW2 `GigabitEthernet0/0/2`（Copper）
- LSW2 `GigabitEthernet0/0/3` ↔ Client1 `Ethernet0/0/0`（Copper）

## 四、拓扑图上的文字标注

- `192.168.100.10/24`（贴近 LSW1）
- `192.168.10.10/24`（贴近 PC1）
- `192.168.100.1/24`（贴近 AR1）
- `192.168.10.1/24`（贴近 AR1）
- `201.10.10.2/30`（贴近 AR1）
- `201.10.10.1/30`（贴近 AR2）
- `192.168.10.20/24`（贴近 PC3）
- `20.1.1.1/24`（贴近 LSW2）
- `20.1.1.2/24`（贴近 PC2）
- `20.1.1.3/24`（贴近 Client1）
- `内部网络`（贴近 LSW1）
- `Internet`（贴近 Client1）

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
ip route-static 200.10.10.0 255.255.255.248 201.10.10.2
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
ip address 201.10.10.1 255.255.255.252
ip address 20.1.1.1 255.255.255.0
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
nat address-group 1 200.10.10.1 200.10.10.5
interface GigabitEthernet0/0/0
interface GigabitEthernet0/0/1
interface GigabitEthernet0/0/2
interface NULL0
ip route-static 0.0.0.0 0.0.0.0 201.10.10.1
user-interface con 0
user-interface vty 0 4
user-interface vty 16 20
wlan ac
rule 5 permit source 192.168.10.0 0.0.0.255
permit source 192.168.10.0 0.0.0.255
End with
authentication-scheme default
authorization-scheme default
accounting-scheme default
domain default
domain default_admin
local-user admin service-type http
priority 15
ip address 201.10.10.2 255.255.255.252
nat server protocol tcp global 200.10.10.6 8080 inside 192.168.100.10 www
nat outbound 2000 address-group 1
ip address 192.168.100.1 255.255.255.0
ip address 192.168.10.1 255.255.255.0
authentication-mode password
```

## 六、验收要点

（待本地模型跑通后回填：需连通的 PC 对、需隔离的 PC 对、关键验证命令）
