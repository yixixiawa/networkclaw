# 实验 24：OSPF基本配置

- 来源目录：`OSPF基本配置`
- 拓扑文件：`1OSPF基本配置.topo`

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

## 三、链路连接

- AR2 `GigabitEthernet0/0/0` ↔ AR1 `GigabitEthernet0/0/1`（Copper）
- AR1 `GigabitEthernet0/0/2` ↔ AR3 `GigabitEthernet0/0/0`（Copper）
- AR2 `GigabitEthernet0/0/1` ↔ AR4 `GigabitEthernet0/0/0`（Copper）
- AR3 `GigabitEthernet0/0/1` ↔ AR5 `GigabitEthernet0/0/1`（Copper）
- AR2 `Ethernet0/0/1` ↔ AR3 `Ethernet0/0/1`（Serial）

## 四、拓扑图上的文字标注

- `10.0.12.0/24`（贴近 AR2）
- `1`（贴近 AR1）
- `2`（贴近 AR2）
- `10.0.13.0/24`（贴近 AR3）
- `1`（贴近 AR1）
- `3`（贴近 AR3）
- `10.2.23.0/24`（贴近 AR3）
- `2`（贴近 AR2）
- `3`（贴近 AR3）
- `10.0.24.0/24`（贴近 AR4）
- `10.0.24.0/24`（贴近 AR5）
- `2`（贴近 AR2）
- `4`（贴近 AR4）
- `3`（贴近 AR3）
- `5`（贴近 AR5）
- `Area 0`（贴近 AR1）
- `Area1`（贴近 AR4）
- `Area2`（贴近 AR5）

## 六、验收要点

（待本地模型跑通后回填：需连通的 PC 对、需隔离的 PC 对、关键验证命令）
