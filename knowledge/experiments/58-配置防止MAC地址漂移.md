# 实验 58：配置防止MAC地址漂移

- 来源目录：`配置防止MAC地址漂移`
- 拓扑文件：`paper.topo`

## 一、题目要求

（题目为空）

## 二、设备清单

| 设备 | 型号 | Console(Telnet)端口 | 关键参数 |
|---|---|---|---|
| LSW5 | S5700 | 2003 | - |
| PC10 | PC | - | IP 192.168.1.110/24 |
| PC11 | PC | - | IP 192.168.1.111/24 |
| PC13 | PC | - | IP 192.168.1.113/24 |

## 三、链路连接

- LSW5 `GigabitEthernet0/0/1` ↔ PC10 `Ethernet0/0/0`（Copper）
- LSW5 `GigabitEthernet0/0/2` ↔ PC11 `Ethernet0/0/0`（Copper）
- LSW5 `GigabitEthernet0/0/3` ↔ PC13 `Ethernet0/0/0`（Copper）

## 四、拓扑图上的文字标注

- `192.168.1.113/24`（贴近 PC13）

## 五、参考答案（从 .model 自动提取，按设备分组）

> 说明：该列表由实验包的「参考答案」文件提取，仅含命令文本、不含缩进层级；
> 部分行是设备默认配置，需结合题目与拓扑判断哪些是本题真正要求下发的配置。

### LSW5

```
sysname Huawei
cluster enable
ntdp enable
ndp enable
drop illegal-mac alarm
mac-address update arp
undo mac-learning priority 0 allow-flapping
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
mac-learning priority 3
```

## 六、验收要点

（待本地模型跑通后回填：需连通的 PC 对、需隔离的 PC 对、关键验证命令）
