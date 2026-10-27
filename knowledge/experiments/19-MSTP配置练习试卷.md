# 实验 19：MSTP配置练习试卷

- 来源目录：`MSTP配置练习试卷`
- 拓扑文件：`paper.topo`

## 一、题目要求

1、按照拓扑图信息完成下面的配置;
2、查看链路聚合配置是否成功；
3、查看当前那些VLAN没有使用最优路径进行通信；
4、在MSTP region1中建立两个实例:期中instance 10包含 VLAN10、20；instance 20 包含VLAN 30、40;
5、找出该网络当前的总跟桥是哪台交换机；
6、对于instance 10，LSW2配置为根桥，把LSW1配置为备用根桥；对于instance 20，LSW1配置为根桥，LSW2为备用根桥；
7、观察验证当前是否所有VLAN已经使用最优路径进行通信；
8、把LWS1 G0/0/1、G0/0/24关闭，看看相同VLAN 30中的PC之间是否依然互通，查看LWS2当前各个端口的STP的角色和状态；
9、保存配置，生成ANS文档提交。

## 二、设备清单

| 设备 | 型号 | Console(Telnet)端口 | 关键参数 |
|---|---|---|---|
| LSW1 | S5700 | 2000 | - |
| LSW2 | S5700 | 2001 | - |
| LSW3 | S5700 | 2002 | - |
| LSW4 | S5700 | 2003 | - |
| PC1 | PC | - | IP 192.168.10.10/24 |
| PC2 | PC | - | IP 192.168.20.20/24 |
| PC3 | PC | - | IP 192.168.30.30/24 |
| PC4 | PC | - | IP 192.168.40.40/24 |
| PC5 | PC | - | IP 192.168.10.50/24 |
| PC6 | PC | - | IP 192.168.20.60/24 |
| PC7 | PC | - | IP 192.168.30.70/24 |
| PC8 | PC | - | IP 192.168.40.80/24 |

## 三、链路连接

- LSW2 `GigabitEthernet0/0/23` ↔ LSW1 `GigabitEthernet0/0/23`（Copper）
- LSW2 `GigabitEthernet0/0/24` ↔ LSW1 `GigabitEthernet0/0/24`（Copper）
- LSW2 `GigabitEthernet0/0/22` ↔ LSW1 `GigabitEthernet0/0/22`（Copper）
- LSW2 `GigabitEthernet0/0/1` ↔ LSW3 `GigabitEthernet0/0/2`（Copper）
- LSW4 `GigabitEthernet0/0/2` ↔ LSW1 `GigabitEthernet0/0/1`（Copper）
- LSW2 `GigabitEthernet0/0/2` ↔ PC5 `Ethernet0/0/0`（Copper）
- LSW2 `GigabitEthernet0/0/3` ↔ PC6 `Ethernet0/0/0`（Copper）
- PC7 `Ethernet0/0/0` ↔ LSW1 `GigabitEthernet0/0/2`（Copper）
- PC8 `Ethernet0/0/0` ↔ LSW1 `GigabitEthernet0/0/3`（Copper）
- LSW3 `GigabitEthernet0/0/3` ↔ PC1 `Ethernet0/0/0`（Copper）
- LSW3 `GigabitEthernet0/0/4` ↔ PC2 `Ethernet0/0/0`（Copper）
- LSW4 `GigabitEthernet0/0/3` ↔ PC3 `Ethernet0/0/0`（Copper）
- LSW4 `GigabitEthernet0/0/4` ↔ PC4 `Ethernet0/0/0`（Copper）
- LSW3 `GigabitEthernet0/0/1` ↔ LSW1 `GigabitEthernet0/0/4`（Copper）
- LSW4 `GigabitEthernet0/0/1` ↔ LSW2 `GigabitEthernet0/0/4`（Copper）

## 四、拓扑图上的文字标注

- `VLAN 10`（贴近 LSW3）
- `VLAN 20`（贴近 PC2）
- `VLAN 30`（贴近 LSW4）
- `VLAN 40`（贴近 PC4）
- `VLAN 10`（贴近 LSW2）
- `VLAN 20`（贴近 PC6）
- `VLAN 30`（贴近 LSW1）
- `VLAN 40`（贴近 PC8）
- `192.168.10.10/24`（贴近 PC1）
- `192.168.20.20/24`（贴近 PC2）
- `192.168.30.30/24`（贴近 PC3）
- `192.168.40.40/24`（贴近 PC4）
- `192.168.10.50/24`（贴近 PC5）
- `192.168.20.60/24`（贴近 PC6）
- `192.168.30.70/24`（贴近 PC7）
- `192.168.40.80/24`（贴近 PC8）
- `trunk all`（贴近 LSW3）
- `trunk all`（贴近 LSW4）
- `trunk all`（贴近 LSW3）
- `trunk all`（贴近 LSW4）

## 五、参考答案（从 .model 自动提取，按设备分组）

> 说明：该列表由实验包的「参考答案」文件提取，仅含命令文本、不含缩进层级；
> 部分行是设备默认配置，需结合题目与拓扑判断哪些是本题真正要求下发的配置。

### LSW2

```
sysname LSW2
vlan batch 10 20 30 40
stp instance 10 root primary
stp instance 20 root secondary
cluster enable
ntdp enable
ndp enable
drop illegal-mac alarm
diffserv domain default
stp region-configuration
drop-profile default
aaa
interface Vlanif1
interface MEth0/0/1
interface Eth-Trunk0
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
region-name region1
region-name
Begin with
instance 10 vlan 10 20
instance 20 vlan 30 40
active region-configuration
authentication-scheme default
authorization-scheme default
accounting-scheme default
domain default
domain default_admin
local-user admin password simple admin
local-user admin service-type http
port link-type trunk
port trunk allow-pass vlan 2 to 4094
mode lacp-static
mode
port link-type access
port default vlan 10
port default vlan 20
eth-trunk 0
```

### LSW4

```
sysname LSW4
vlan batch 10 20 30 40
cluster enable
ntdp enable
ndp enable
drop illegal-mac alarm
diffserv domain default
stp region-configuration
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
region-name region1
instance 10 vlan 10 20
instance 20 vlan 30 40
active region-configuration
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
port default vlan 30
port default vlan 40
```

### LSW1

```
sysname LSW1
vlan batch 10 20 30 40
stp instance 10 root secondary
stp instance 20 root primary
cluster enable
ntdp enable
ndp enable
drop illegal-mac alarm
diffserv domain default
stp region-configuration
Begin with
drop-profile default
aaa
interface Vlanif1
interface MEth0/0/1
interface Eth-Trunk0
interface Eth-Trunk
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
region-name region1
region-name
instance 10 vlan 10 20
instance 20 vlan 30 40
active region-configuration
authentication-scheme default
authorization-scheme default
accounting-scheme default
domain default
domain default_admin
local-user admin password simple admin
local-user admin service-type http
port link-type trunk
port trunk allow-pass vlan 2 to 4094
mode lacp-static
mode
port link-type access
port default vlan 30
port default vlan 40
eth-trunk 0
```

### LSW3

```
sysname LSW3
vlan batch 10 20 30 40
cluster enable
ntdp enable
ndp enable
drop illegal-mac alarm
diffserv domain default
stp region-configuration
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
region-name region1
instance 10 vlan 10 20
instance 20 vlan 30 40
active region-configuration
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
port default vlan 10
port default vlan 20
```

## 六、验收要点

（待本地模型跑通后回填：需连通的 PC 对、需隔离的 PC 对、关键验证命令）
