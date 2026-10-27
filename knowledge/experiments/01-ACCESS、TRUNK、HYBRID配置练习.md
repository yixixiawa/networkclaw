# 实验 01：ACCESS、TRUNK、HYBRID配置练习

- 来源目录：`ACCESS、TRUNK、HYBRID配置练习`
- 拓扑文件：`paper.topo`

## 一、题目要求

照拓扑图及信息，对交换机进行配置，除标明的配置信息外，其他的配置自行决定，达如下效果：
1、PC1、CP4可以互通。
2、PC2、PC3可以互通。
3、PC2、PC5、PC6可以互通
4、除上述三种情况外，其余不能互通。

提交资料：
1、ans文档；
2、PC上述PC互通情况截图。

## 二、设备清单

| 设备 | 型号 | Console(Telnet)端口 | 关键参数 |
|---|---|---|---|
| HUB1 | HUB | - | - |
| LSW1 | S5700 | 2000 | - |
| LSW2 | S3700 | 2001 | - |
| LSW3 | S3700 | 2002 | - |
| PC1 | PC | - | IP 192.168.1.10/24 |
| PC2 | PC | - | IP 192.168.1.20/24 |
| PC3 | PC | - | IP 192.168.1.30/24 |
| PC4 | PC | - | IP 192.168.1.40/24 |
| PC5 | PC | - | IP 192.168.1.50/24 |
| PC6 | PC | - | IP 192.168.1.60/24 |

## 三、链路连接

- LSW1 `GigabitEthernet0/0/2` ↔ LSW3 `Ethernet0/0/1`（Copper）
- LSW2 `Ethernet0/0/2` ↔ PC1 `Ethernet0/0/0`（Copper）
- LSW2 `Ethernet0/0/3` ↔ PC2 `Ethernet0/0/0`（Copper）
- LSW3 `Ethernet0/0/2` ↔ PC3 `Ethernet0/0/0`（Copper）
- LSW3 `Ethernet0/0/3` ↔ PC4 `Ethernet0/0/0`（Copper）
- LSW1 `GigabitEthernet0/0/3` ↔ PC5 `Ethernet0/0/0`（Copper）
- LSW2 `Ethernet0/0/1` ↔ HUB1 `Ethernet0/0/0`（Copper）
- HUB1 `Ethernet0/0/1` ↔ LSW1 `GigabitEthernet0/0/1`（Copper）
- PC6 `Ethernet0/0/0` ↔ HUB1 `Ethernet0/0/2`（Copper）

## 四、拓扑图上的文字标注

- `VLAN 10`（贴近 PC1）
- `Hybrid PVID 20`（贴近 PC3）
- `vlan 30`（贴近 LSW1）
- `trunk`（贴近 LSW2）
- `trunk`（贴近 LSW3）
- `VLAN 20`（贴近 PC2）
- `VLAN 10`（贴近 PC4）
- `192.168.1.10/24`（贴近 PC2）
- `192.168.1.20/24`（贴近 PC2）
- `192.168.1.30/24`（贴近 PC3）
- `192.168.1.40/24`（贴近 PC4）
- `trunk`（贴近 LSW1）
- `192.168.1.50/24`（贴近 PC5）
- `192.168.1.60/24`（贴近 PC6）
- `trunk`（贴近 LSW1）

## 五、参考答案（从 .model 自动提取，按设备分组）

> 说明：该列表由实验包的「参考答案」文件提取，仅含命令文本、不含缩进层级；
> 部分行是设备默认配置，需结合题目与拓扑判断哪些是本题真正要求下发的配置。

### LSW1

```
sysname LSW1
undo info-center enable
vlan batch 10 20 30
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
port trunk pvid vlan 30
port trunk allow-pass vlan 10 20 30
port link-type access
port default vlan 30
```

### LSW2

```
sysname LSW2
undo info-center enable
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
interface Ethernet0/0/1
interface Ethernet0/0/2
interface Ethernet0/0/3
interface Ethernet0/0/4
interface Ethernet0/0/5
interface Ethernet0/0/6
interface Ethernet0/0/7
interface Ethernet0/0/8
interface Ethernet0/0/9
interface Ethernet0/0/10
interface Ethernet0/0/11
interface Ethernet0/0/12
interface Ethernet0/0/13
interface Ethernet0/0/14
interface Ethernet0/0/15
interface Ethernet0/0/16
interface Ethernet0/0/17
interface Ethernet0/0/18
interface Ethernet0/0/19
interface Ethernet0/0/20
interface Ethernet0/0/21
interface Ethernet0/0/22
interface GigabitEthernet0/0/1
interface GigabitEthernet0/0/2
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
port trunk pvid vlan 20
port trunk allow-pass vlan 10 20
port link-type access
port default vlan 10
port default vlan 20
```

### LSW3

```
sysname LSW3
undo info-center enable
vlan batch 10 20 30
cluster enable
ntdp enable
ndp enable
drop illegal-mac alarm
diffserv domain default
drop-profile default
aaa
interface Vlanif1
interface MEth0/0/1
interface Ethernet0/0/1
interface Ethernet0/0/2
interface Ethernet0/0/3
interface Ethernet0/0/4
interface Ethernet0/0/5
interface Ethernet0/0/6
interface Ethernet0/0/7
interface Ethernet0/0/8
interface Ethernet0/0/9
interface Ethernet0/0/10
interface Ethernet0/0/11
interface Ethernet0/0/12
interface Ethernet0/0/13
interface Ethernet0/0/14
interface Ethernet0/0/15
interface Ethernet0/0/16
interface Ethernet0/0/17
interface Ethernet0/0/18
interface Ethernet0/0/19
interface Ethernet0/0/20
interface Ethernet0/0/21
interface Ethernet0/0/22
interface GigabitEthernet0/0/1
interface GigabitEthernet0/0/2
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
port trunk allow-pass vlan 10 20 30
port hybrid pvid vlan 20
port hybrid untagged vlan 20 30
port link-type access
port default vlan 10
```

## 六、验收要点

（待本地模型跑通后回填：需连通的 PC 对、需隔离的 PC 对、关键验证命令）
