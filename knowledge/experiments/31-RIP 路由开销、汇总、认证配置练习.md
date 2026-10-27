# 实验 31：RIP 路由开销、汇总、认证配置练习

- 来源目录：`RIP 路由开销、汇总、认证配置练习`
- 拓扑文件：`RIP 路由开销、汇总、认证配置练习.topo`

## 一、题目要求

（未找到 instruction.txt）

## 二、设备清单

| 设备 | 型号 | Console(Telnet)端口 | 关键参数 |
|---|---|---|---|
| AR1 | AR2220 | 2000 | - |
| AR2 | AR2220 | 2001 | - |
| AR3 | AR2220 | 2002 | - |
| PC1 | PC | - | - |
| PC2 | PC | - | - |
| PC3 | PC | - | - |

## 三、链路连接

- AR1 `GigabitEthernet0/0/0` ↔ AR2 `GigabitEthernet0/0/0`（Copper）
- AR2 `GigabitEthernet0/0/1` ↔ AR3 `GigabitEthernet0/0/0`（Copper）
- AR1 `Ethernet0/0/0` ↔ AR3 `Ethernet0/0/0`（Serial）
- AR1 `GigabitEthernet0/0/1` ↔ PC1 `Ethernet0/0/0`（Copper）
- PC2 `Ethernet0/0/0` ↔ AR1 `GigabitEthernet0/0/2`（Copper）
- AR3 `GigabitEthernet0/0/1` ↔ PC3 `Ethernet0/0/0`（Copper）

## 四、拓扑图上的文字标注

- `10.10.13.0/24`（贴近 AR2）
- `1`（贴近 AR1）
- `3`（贴近 AR3）
- `10.10.12.0/24`（贴近 AR2）
- `1`（贴近 AR1）
- `2`（贴近 AR2）
- `2`（贴近 AR2）
- `3`（贴近 AR3）
- `10.10.23.0/24`（贴近 AR3）
- `RIP`（贴近 AR2）
- `192.168.1.16/28`（贴近 AR1）
- `22`（贴近 PC1）
- `21`（贴近 AR1）
- `192.168.1.32/28`（贴近 AR1）
- `41`（贴近 PC2）
- `40`（贴近 AR1）
- `192.168.30.0/24`（贴近 PC3）
- `1`（贴近 AR3）
- `10`（贴近 PC3）

## 六、验收要点

（待本地模型跑通后回填：需连通的 PC 对、需隔离的 PC 对、关键验证命令）
