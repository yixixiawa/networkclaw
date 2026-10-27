# 实验 26：OSPF综合实验

- 来源目录：`OSPF综合实验`
- 拓扑文件：`paper.topo`

## 一、题目要求

依照下面拓扑图信息进行配置，使得全网实现互通。
（1）路由器的名称为R1-学号后3位（如R1-101、R2-101）
（1）R7和R2之间创建Vlink
（2）R4、R6、R8相应接口应用静默接口
（3）area2区域认证，采用MD5
（4）四台PC机可以互通
上交文件的名称为 学号+姓名

## 二、设备清单

| 设备 | 型号 | Console(Telnet)端口 | 关键参数 |
|---|---|---|---|
| LSW1 | S5700 | 2009 | - |
| PC1 | PC | - | IP 192.168.6.10/24，网关 192.168.6.1 |
| PC2 | PC | - | IP 192.168.4.10/24，网关 192.168.4.1 |
| PC3 | PC | - | IP 192.168.8.10/24，网关 192.168.8.1 |
| PC4 | PC | - | IP 192.168.9.10/24，网关 192.168.9.1 |
| R1 | AR2220 | 2004 | - |
| R2 | AR2220 | 2003 | - |
| R3 | AR2220 | 2006 | - |
| R4 | AR2220 | 2005 | - |
| R5 | AR2220 | 2002 | - |
| R6 | AR2220 | 2000 | - |
| R7 | AR2220 | 2001 | - |
| R8 | AR2220 | 2007 | - |
| R9 | AR2220 | 2008 | - |

## 三、链路连接

- PC1 `Ethernet0/0/0` ↔ R6 `GigabitEthernet0/0/1`（Copper）
- R6 `GigabitEthernet0/0/0` ↔ R7 `GigabitEthernet0/0/1`（Copper）
- R7 `GigabitEthernet0/0/0` ↔ R5 `GigabitEthernet0/0/1`（Copper）
- R5 `GigabitEthernet0/0/0` ↔ R2 `GigabitEthernet0/0/1`（Copper）
- R2 `GigabitEthernet0/0/2` ↔ R9 `GigabitEthernet0/0/0`（Copper）
- PC4 `Ethernet0/0/0` ↔ R9 `GigabitEthernet0/0/1`（Copper）
- R2 `GigabitEthernet0/0/0` ↔ R1 `GigabitEthernet0/0/0`（Copper）
- R1 `GigabitEthernet0/0/1` ↔ LSW1 `GigabitEthernet0/0/1`（Copper）
- LSW1 `GigabitEthernet0/0/2` ↔ R4 `GigabitEthernet0/0/0`（Copper）
- LSW1 `GigabitEthernet0/0/3` ↔ R3 `GigabitEthernet0/0/0`（Copper）
- R4 `GigabitEthernet0/0/1` ↔ PC2 `Ethernet0/0/0`（Copper）
- R3 `GigabitEthernet0/0/2` ↔ R8 `GigabitEthernet0/0/0`（Copper）
- R8 `GigabitEthernet0/0/1` ↔ PC3 `Ethernet0/0/0`（Copper）

## 四、拓扑图上的文字标注

- `192.168.6.0/24`（贴近 R6）
- `10`（贴近 PC1）
- `1`（贴近 R6）
- `10.10.67.0/24`（贴近 R7）
- `6`（贴近 R6）
- `7`（贴近 R7）
- `10.10.57.0/24`（贴近 R5）
- `10.10.25.0/24`（贴近 R2）
- `5`（贴近 R5）
- `5`（贴近 R5）
- `7`（贴近 R7）
- `2`（贴近 R2）
- `Vlink`（贴近 R2）
- `区域认证：MD5 1 huawei`（贴近 R5）
- `192.168.9.0/24`（贴近 R9）
- `10`（贴近 PC4）
- `1`（贴近 R9）
- `10.10.29.0/24`（贴近 R9）
- `2`（贴近 R2）
- `9`（贴近 R9）
- `10.10.12.0/24`（贴近 R1）
- `1`（贴近 R1）
- `2`（贴近 R2）
- `10.10.134.0/24`（贴近 R4）
- `1`（贴近 LSW1）
- `3`（贴近 R3）
- `4`（贴近 R4）
- `192.168.4.0/24`（贴近 PC2）
- `1`（贴近 R4）
- `10`（贴近 PC2）
- `10.10.38.0/24`（贴近 R8）
- `3`（贴近 R3）
- `8`（贴近 R8）
- `192.168.8.0/24`（贴近 PC3）
- `1`（贴近 R8）
- `10`（贴近 PC3）
- `RID:6.6.6.6`（贴近 R6）
- `RID:7.7.7.7`（贴近 R7）
- `RID:5.5.5.5`（贴近 R5）
- `RID:2.2.2.2`（贴近 R2）
- `RID:8.8.8.8`（贴近 R8）
- `RID:3.3.3.3`（贴近 R3）
- `RID:10.10.10.10`（贴近 R1）
- `RID:4.4.4.4`（贴近 R4）
- `静态路由引入`（贴近 R9）

## 六、验收要点

（待本地模型跑通后回填：需连通的 PC 对、需隔离的 PC 对、关键验证命令）
