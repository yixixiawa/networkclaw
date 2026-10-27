# 实验 45：基于VLAN的MAC地址漂移检测与应对

- 来源目录：`基于VLAN的MAC地址漂移检测与应对`
- 拓扑文件：`paper.topo`

## 一、题目要求

基于VLAN的地址漂移检测与应对配置练习
1）配置LSW1 VLAN 1MAC地址漂移检测；
2）持续让PC1与PC3、PC2与PC3通信，在LSW1中观察地址漂移是否有发生；
3）停止所有PC的通信，清空LSW1、LSW2动态MAC地址表；
4）让PC2与PC3持续进行通信，LSW1 G0/0/2接口配置MAC地址学习优先级为3，再使
PC1与PC3进行通信，观察当前PC2是否还能与PC3通信？
5）停止所有PC的通信，清空LSW1、LSW2动态MAC地址表；
6）撤销LSW1 G0/0/2 的MAC地址学习优先级配置，在全局配置试图下，配置禁止MAC
地址学习优先级为0的端口发生地址漂移，再持续让PC1与PC3、PC2与PC3通信，看看
哪个成功，哪个失败，分析原因；
7）撤销配置禁止MAC地址学习优先级为0的端口发生地址漂移配置，停止所有PC的通
信，清空LSW1、LSW2动态MAC地址表；
8）先使PC1与PC3持续进行通信，然后使PC2与PC3、PC6与PC3、PC5与PC7持续进行通
信，观察MAC地址漂移是否发生，然后在LSW1中配置VLAN 1启动MAC地址漂移检测，动
作为接口阻断，具体为阻断10秒后恢复，若冲突次数到达3次，就永久阻断，查看
VLAN 1的地址漂移检测情况，观察上述PC间的通信情况，说明PC间通信成功与失败
的原因；
9）停止所有PC间的通信，恢复阻断的接口，先使PC2与PC3持续通信，再使PC1与PC3、
PC6与PC3、PC5与PC7持续进行通信，观察MAC地址漂移是否发生，查看VLAN 1的地址
漂移检测情况，观察上述PC间的通信情况，思考PC间通信成功与失败的原因；
10）停止所有PC间的通信，恢复阻断的接口，把LSW1中配置VLAN 1改为如果检测到地
址漂移动作为MAC地址阻断，具体为阻断10秒后恢复，再检测到发生漂移，就永久阻
断，观察PC1与PC3、PC2与PC4、PC4与PC6、PC4与间的通信，说明PC间通信成功与失
败的原因。
11）停止PC2与PC3的通信，手工恢复被阻塞的MAC地址，观察PC1与PC3的通信是否恢复。

## 二、设备清单

| 设备 | 型号 | Console(Telnet)端口 | 关键参数 |
|---|---|---|---|
| HUB1 | HUB | - | - |
| HUB2 | HUB | - | - |
| LSW1 | S5700 | 2000 | - |
| LSW2 | S5700 | 2001 | - |
| PC1 | PC | - | IP 192.168.1.10/24 |
| PC2 | PC | - | IP 192.168.1.20/24 |
| PC3 | PC | - | IP 192.168.1.30/24 |
| PC4 | PC | - | IP 192.168.1.40/24 |
| PC5 | PC | - | IP 192.168.10.50/24 |
| PC6 | PC | - | IP 192.168.1.60/24 |
| PC7 | PC | - | IP 192.168.10.70/24 |

## 三、链路连接

- LSW1 `GigabitEthernet0/0/1` ↔ LSW2 `GigabitEthernet0/0/1`（Copper）
- PC3 `Ethernet0/0/0` ↔ LSW1 `GigabitEthernet0/0/3`（Copper）
- LSW1 `GigabitEthernet0/0/2` ↔ HUB1 `Ethernet0/0/0`（Copper）
- HUB1 `Ethernet0/0/1` ↔ PC4 `Ethernet0/0/0`（Copper）
- HUB1 `Ethernet0/0/2` ↔ PC1 `Ethernet0/0/0`（Copper）
- LSW2 `GigabitEthernet0/0/3` ↔ PC5 `Ethernet0/0/0`（Copper）
- PC7 `Ethernet0/0/0` ↔ LSW1 `GigabitEthernet0/0/4`（Copper）
- LSW2 `GigabitEthernet0/0/2` ↔ HUB2 `Ethernet0/0/0`（Copper）
- HUB2 `Ethernet0/0/1` ↔ PC6 `Ethernet0/0/0`（Copper）
- HUB2 `Ethernet0/0/2` ↔ PC2 `Ethernet0/0/0`（Copper）

## 四、拓扑图上的文字标注

- `192.168.1.40/24`（贴近 PC4）
- `192.168.1.30/24`（贴近 PC3）
- `192.168.10.50/24`（贴近 PC6）
- `192.168.10.70/24`（贴近 PC7）
- `VLAN 10`（贴近 LSW1）
- `VLAN 10`（贴近 PC5）
- `TRUNK 1 10`（贴近 LSW2）
- `192.168.1.60/24`（贴近 PC6）
- `VLAN 1`（贴近 LSW1）
- `VLAN 1`（贴近 LSW1）
- `VLAN 1`（贴近 HUB2）

## 五、参考答案（从 .model 自动提取，按设备分组）

> 说明：该列表由实验包的「参考答案」文件提取，仅含命令文本、不含缩进层级；
> 部分行是设备默认配置，需结合题目与拓扑判断哪些是本题真正要求下发的配置。

### LSW1

```
sysname LSW1
vlan batch 10
cluster enable
ntdp enable
ndp enable
drop illegal-mac alarm
diffserv domain default
drop-profile default
vlan 1
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
loop-detect eth-loop block-mac block-time 10 retry-times 2
authentication-scheme default
authorization-scheme default
accounting-scheme default
domain default
domain default_admin
local-user admin password simple admin
local-user admin service-type http
port link-type trunk
port trunk allow-pass vlan 10
port link-type access
port default vlan 10
```

### LSW2

```
sysname Huawei
vlan batch 10
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
port trunk allow-pass vlan 10
port link-type access
port default vlan 10
```

## 六、验收要点

（待本地模型跑通后回填：需连通的 PC 对、需隔离的 PC 对、关键验证命令）
