# 实验 47：多交换机MUX_VLAN配置练习

- 来源目录：`多交换机MUX_VLAN配置练习`
- 拓扑文件：`paper.topo`

## 一、题目要求

在二层网络中配置MUX VLAN，实现如下功能：
1、业务部、财务部、访客三个VLAN不能互通
2、业务部内部可以互通，财务部内部可以互通，均可以访问服务器(vlan 50)。
3、访客电脑之间不能互通，只能访问服务器。

## 二、设备清单

| 设备 | 型号 | Console(Telnet)端口 | 关键参数 |
|---|---|---|---|
| A客户 | PC | - | IP 192.168.10.50/24 |
| B客户 | PC | - | IP 192.168.10.60/24 |
| PC1 | PC | - | IP 192.168.10.10/24 |
| PC2 | PC | - | IP 192.168.10.20/24 |
| PC3 | PC | - | IP 192.168.10.30/24 |
| PC4 | PC | - | IP 192.168.10.40/24 |
| SW1 | S5700 | 2000 | - |
| SW2 | S5700 | 2001 | - |
| SW3 | S5700 | 2002 | - |
| 服务器 | PC | - | IP 192.168.10.70/24 |

## 三、链路连接

- SW1 `GigabitEthernet0/0/1` ↔ SW2 `GigabitEthernet0/0/1`（Copper）
- SW1 `GigabitEthernet0/0/2` ↔ SW3 `GigabitEthernet0/0/1`（Copper）
- SW1 `GigabitEthernet0/0/3` ↔ 服务器 `Ethernet0/0/0`（Copper）
- SW2 `GigabitEthernet0/0/2` ↔ PC1 `Ethernet0/0/0`（Copper）
- SW2 `GigabitEthernet0/0/3` ↔ PC2 `Ethernet0/0/0`（Copper）
- SW2 `GigabitEthernet0/0/4` ↔ PC3 `Ethernet0/0/0`（Copper）
- SW2 `GigabitEthernet0/0/5` ↔ PC4 `Ethernet0/0/0`（Copper）
- SW3 `GigabitEthernet0/0/2` ↔ A客户 `Ethernet0/0/0`（Copper）
- SW3 `GigabitEthernet0/0/3` ↔ B客户 `Ethernet0/0/0`（Copper）

## 四、拓扑图上的文字标注

- `VLAN 50`（贴近 服务器）
- `192.168.10.10/24`（贴近 PC1）
- `192.168.10.20/24`（贴近 PC2）
- `192.168.10.30/24`（贴近 PC3）
- `192.168.10.40/24`（贴近 PC4）
- `192.168.10.50/24`（贴近 A客户）
- `192.168.10.60/24`（贴近 B客户）
- `192.168.10.70/24`（贴近 服务器）

## 五、参考答案（从 .model 自动提取，按设备分组）

> 说明：该列表由实验包的「参考答案」文件提取，仅含命令文本、不含缩进层级；
> 部分行是设备默认配置，需结合题目与拓扑判断哪些是本题真正要求下发的配置。

### SW2

```
sysname SW2
vlan batch 10 20 50
Include
cluster enable
ntdp enable
ndp enable
drop illegal-mac alarm
diffserv domain default
drop-profile default
vlan 50
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
mux-vlan
subordinate group 10 20
authentication-scheme default
authorization-scheme default
accounting-scheme default
domain default
domain default_admin
local-user admin password simple admin
local-user admin service-type http
port link-type trunk
port trunk allow-pass vlan 2 to 4094
port trunk allow-pass vlan
Begin with
port link-type access
port default vlan 10
port mux-vlan enable
port default vlan 20
```

### SW3

```
sysname SW3
vlan batch 30 50
Include
cluster enable
ntdp enable
ndp enable
drop illegal-mac alarm
diffserv domain default
drop-profile default
vlan 50
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
mux-vlan
subordinate separate 30
authentication-scheme default
authorization-scheme default
accounting-scheme default
domain default
domain default_admin
local-user admin password simple admin
local-user admin service-type http
port link-type trunk
port trunk allow-pass vlan 2 to 4094
port trunk allow-pass vlan
Begin with
port link-type access
port default vlan 30
port mux-vlan enable
```

### SW1

```
sysname SW1
vlan batch 10 20 30 50
cluster enable
ntdp enable
ndp enable
drop illegal-mac alarm
diffserv domain default
drop-profile default
vlan 50
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
mux-vlan
subordinate separate 30
Include
subordinate group 10 20
authentication-scheme default
authorization-scheme default
accounting-scheme default
domain default
domain default_admin
local-user admin password simple admin
local-user admin service-type http
port link-type trunk
port trunk allow-pass vlan 2 to 4094
port trunk allow-pass vlan
Begin with
port link-type access
port default vlan 50
port mux-vlan enable
```

## 六、验收要点

（待本地模型跑通后回填：需连通的 PC 对、需隔离的 PC 对、关键验证命令）
