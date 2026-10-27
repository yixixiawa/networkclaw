# 实验 22：OSPF-4-VLink-Nssa-static

- 来源目录：`OSPF-4-VLink-Nssa-static`
- 拓扑文件：`OSPF-VLink-Nssa-static.topo`

## 一、题目要求

（未找到 instruction.txt）

## 二、设备清单

| 设备 | 型号 | Console(Telnet)端口 | 关键参数 |
|---|---|---|---|
| AR1 | AR2220 | 2000 | - |
| AR2 | AR2220 | 2001 | - |
| AR3 | AR2220 | 2002 | - |
| AR4 | AR2220 | 2003 | - |
| AR5 | AR2220 | 2004 | - |
| AR6 | AR2220 | 2006 | - |
| AR7 | AR2220 | 2007 | - |

## 三、链路连接

- AR6 `GigabitEthernet0/0/0` ↔ AR5 `GigabitEthernet0/0/1`（Copper）
- AR5 `GigabitEthernet0/0/0` ↔ AR1 `GigabitEthernet0/0/1`（Copper）
- AR1 `GigabitEthernet0/0/0` ↔ AR2 `GigabitEthernet0/0/0`（Copper）
- AR2 `GigabitEthernet0/0/1` ↔ AR3 `GigabitEthernet0/0/0`（Copper）
- AR3 `GigabitEthernet0/0/2` ↔ AR7 `GigabitEthernet0/0/0`（Copper）
- AR3 `GigabitEthernet0/0/1` ↔ AR4 `GigabitEthernet0/0/0`（Copper）

## 四、拓扑图上的文字标注

- `vlink`（贴近 AR3）
- `10.10.12.0/24`（贴近 AR2）
- `10.10.15.0/24`（贴近 AR5）
- `10.10.56.0/24`（贴近 AR6）
- `10.10.23.0/24`（贴近 AR3）
- `10.10.37.0/24`（贴近 AR7）
- `10.10.34.0/24`（贴近 AR3）
- `引入外部静态路由`（贴近 AR5）
- `引入外部静态路由`（贴近 AR3）
- `1`（贴近 AR1）
- `5`（贴近 AR5）
- `1`（贴近 AR1）
- `2`（贴近 AR2）
- `2`（贴近 AR2）
- `3`（贴近 AR3）
- `3`（贴近 AR3）
- `4`（贴近 AR4）
- `3`（贴近 AR3）
- `7`（贴近 AR7）
- `5`（贴近 AR5）
- `6`（贴近 AR6）
- `RID:10.10.10.10`（贴近 AR1）
- `RID:2.2.2.2`（贴近 AR2）
- `RID:4.4.4.4`（贴近 AR4）
- `RID:3.3.3.3`（贴近 AR3）
- `RID:5.5.5.5`（贴近 AR5）

## 六、验收要点

（待本地模型跑通后回填：需连通的 PC 对、需隔离的 PC 对、关键验证命令）
