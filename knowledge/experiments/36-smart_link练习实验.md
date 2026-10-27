# 实验 36：smart_link练习实验

- 来源目录：`smart_link练习实验`
- 拓扑文件：`paper.topo`

## 一、题目要求

smart link配置练习：
1. 按照图中所示配置设备名称创建对应VLAN和配置接口链路
2. 配置smart link group 主从模式，使正常情况流量通过master上行；
    master链路如果发生故障（包括LSW4--LSW2及LSW2--LSW1之间链路及端口故障）
自动切换到slave链路；master链路故障排除后，自动切换回master链路，回切等待时间设置为30秒。
3. 测试PC1与PC3的连通性，同时观察在LSW4 G0/0/1和G0/0/2抓取报文情况。
4. 保持PC1与PC3的通信，关闭LSW1的G0/0/1端口，观察PC1与PC3的通信情况。
5. 恢复LSW1的G0/0/1端口，观察PC1与PC3的通信情况。

## 二、设备清单

| 设备 | 型号 | Console(Telnet)端口 | 关键参数 |
|---|---|---|---|
| LSW1 | S5700 | 2000 | - |
| LSW2 | S5700 | 2001 | - |
| LSW3 | S5700 | 2002 | - |
| LSW4 | S5700 | 2003 | - |
| PC1 | PC | - | IP 192.168.1.10/24 |
| PC2 | PC | - | IP 192.168.2.10/24 |
| PC3 | PC | - | IP 192.168.1.20/24 |
| PC4 | PC | - | IP 192.168.2.20/24 |

## 三、链路连接

- LSW1 `GigabitEthernet0/0/1` ↔ LSW2 `GigabitEthernet0/0/1`（Copper）
- LSW2 `GigabitEthernet0/0/2` ↔ LSW4 `GigabitEthernet0/0/1`（Copper）
- LSW4 `GigabitEthernet0/0/2` ↔ LSW3 `GigabitEthernet0/0/1`（Copper）
- LSW3 `GigabitEthernet0/0/2` ↔ LSW1 `GigabitEthernet0/0/2`（Copper）
- PC3 `Ethernet0/0/0` ↔ LSW1 `GigabitEthernet0/0/3`（Copper）
- PC4 `Ethernet0/0/0` ↔ LSW1 `GigabitEthernet0/0/4`（Copper）
- LSW4 `GigabitEthernet0/0/3` ↔ PC1 `Ethernet0/0/0`（Copper）
- LSW4 `GigabitEthernet0/0/4` ↔ PC2 `Ethernet0/0/0`（Copper）

## 四、拓扑图上的文字标注

- `trunk 10 20`（贴近 LSW4）
- `trunk 10 20`（贴近 PC2）
- `trunk 10 20`（贴近 LSW1）
- `trunk 10 20`（贴近 LSW3）
- `vlan 10`（贴近 LSW1）
- `vlan 20`（贴近 PC4）
- `vlan 10`（贴近 LSW4）
- `vlan 20`（贴近 PC2）
- `master`（贴近 LSW4）
- `slave`（贴近 LSW4）

## 五、参考答案（从 .model 自动提取，按设备分组）

> 说明：该列表由实验包的「参考答案」文件提取，仅含命令文本、不含缩进层级；
> 部分行是设备默认配置，需结合题目与拓扑判断哪些是本题真正要求下发的配置。

### LSW2

```
sysname Huawei
vlan batch 10 20
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
monitor-link group 1
monitor-link group
Begin with
user-interface con 0
user-interface vty 0 4
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
stp disable
smart-link flush receive control-vlan 10
smart-link flush receive control-vlan
port GigabitEthernet0/0/1 uplink
port GigabitEthernet0/0/2 downlink 1
```

### LSW1

```
sysname Huawei
vlan batch 10 20
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
port link-type trunk
port trunk allow-pass vlan 2 to 4094
port trunk allow-pass vlan
Begin with
port link-type access
port default vlan 10
port default vlan 20
```

### LSW3

```
sysname Huawei
vlan batch 10 20
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
monitor-link group 1
user-interface con 0
user-interface vty 0 4
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
stp disable
smart-link flush receive control-vlan 10
smart-link flush receive control-vlan
port GigabitEthernet0/0/2 uplink
port GigabitEthernet0/0/1 downlink 1
```

### LSW4

```
sysname Huawei
vlan batch 10 20
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
smart-link group 1
user-interface con 0
user-interface vty 0 4
authentication-scheme default
authorization-scheme default
accounting-scheme default
domain default
domain default_admin
local-user admin password simple admin
local-user admin service-type http
port link-type trunk
port trunk allow-pass vlan 2 to 4094
stp disable
port link-type access
port default vlan 10
port default vlan 20
restore enable
smart-link enable
port GigabitEthernet0/0/1 master
port GigabitEthernet0/0/2 slave
timer wtr 30
flush send control-vlan 10
flush send control-vlan
Begin with
```

## 六、验收要点

（待本地模型跑通后回填：需连通的 PC 对、需隔离的 PC 对、关键验证命令）
