# 实验 08：Hybrid与GVRP协议配置练习

- 来源目录：`Hybrid与GVRP协议配置练习`
- 拓扑文件：`paper.topo`

## 一、题目要求

要求：
1、按照拓扑图中信息配置个网络设备；
2、LSW1和LSW2配置GVRP协议动态创建VLAN，LSW3和LSW4的G0/0/1端口激活GVRP协议；
3、配置完成后，观察并回答以下问题：
   PC1与PC3是否可以互通，为什么？
   PC1与PC4是否可以互通，为什么？
   PC2与PC4是否可以互通，为什么？
4、提交ans文档。

## 二、设备清单

| 设备 | 型号 | Console(Telnet)端口 | 关键参数 |
|---|---|---|---|
| LSW1 | S5700 | 2000 | - |
| LSW2 | S5700 | 2001 | - |
| LSW3 | S5700 | 2002 | - |
| LSW4 | S5700 | 2003 | - |
| PC1 | PC | - | IP 192.168.10.10/24 |
| PC2 | PC | - | IP 192.168.10.20/24 |
| PC3 | PC | - | IP 192.168.10.30/24 |
| PC4 | PC | - | IP 192.168.10.40/24 |

## 三、链路连接

- LSW2 `GigabitEthernet0/0/1` ↔ LSW1 `GigabitEthernet0/0/1`（Copper）
- LSW2 `GigabitEthernet0/0/2` ↔ LSW4 `GigabitEthernet0/0/1`（Copper）
- LSW1 `GigabitEthernet0/0/2` ↔ LSW3 `GigabitEthernet0/0/1`（Copper）
- LSW4 `GigabitEthernet0/0/2` ↔ PC1 `Ethernet0/0/0`（Copper）
- LSW4 `GigabitEthernet0/0/3` ↔ PC2 `Ethernet0/0/0`（Copper）
- LSW3 `GigabitEthernet0/0/2` ↔ PC3 `Ethernet0/0/0`（Copper）
- LSW3 `GigabitEthernet0/0/3` ↔ PC4 `Ethernet0/0/0`（Copper）

## 四、拓扑图上的文字标注

- `VLAN 20`（贴近 PC2）
- `VLAN 10`（贴近 PC3）
- `192.168.10.10/24`（贴近 PC1）
- `192.168.10.20/24`（贴近 PC2）
- `192.168.10.30/24`（贴近 PC3）
- `192.168.10.40/24`（贴近 PC4）
- `TRUNK ALL`（贴近 LSW4）
- `TRUNK ALL`（贴近 LSW3）
- `TRUNK ALL`（贴近 LSW1）

## 五、参考答案（从 .model 自动提取，按设备分组）

> 说明：该列表由实验包的「参考答案」文件提取，仅含命令文本、不含缩进层级；
> 部分行是设备默认配置，需结合题目与拓扑判断哪些是本题真正要求下发的配置。

### LSW1

```
sysname LSW1
gvrp
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
```

### LSW2

```
sysname LSW2
gvrp
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
```

### LSW3

```
sysname LSW3
vlan batch 10 20
gvrp
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
port link-type access
port default vlan 10
port hybrid pvid vlan 20
port hybrid tagged vlan 20
port hybrid untagged vlan 10
```

### LSW4

```
sysname LSW4
vlan batch 10 20
gvrp
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
port-group link-ty
authentication-scheme default
authorization-scheme default
accounting-scheme default
domain default
domain default_admin
local-user admin password simple admin
local-user admin service-type http
port link-type trunk
port trunk allow-pass vlan 2 to 4094
port hybrid pvid vlan 10
port hybrid untagged vlan 10 20
port link-type access
port default vlan 20
```

## 六、验收要点

（待本地模型跑通后回填：需连通的 PC 对、需隔离的 PC 对、关键验证命令）
