# 实验 10：is-is路由基本配置

- 来源目录：`is-is路由基本配置`
- 拓扑文件：`paper.topo`

## 一、题目要求

按照拓扑及下面路由器NET信息对个网络设备进行配置，
RA:49.0002.0000.0000.0001.00
RB:49.0002.0000.0000.0002.00
RC:49.0001.0000.0000.0003.00
RD:49.0001.0000.0000.0004.00

提交内容：
1、RB、RC邻居表截图
2、RA、RD路由表截图
3、提交ANS文档

## 二、设备清单

| 设备 | 型号 | Console(Telnet)端口 | 关键参数 |
|---|---|---|---|
| RA | AR2220 | 2000 | - |
| RB | AR1220 | 2001 | - |
| RC | AR1220 | 2002 | - |
| RD | AR1220 | 2003 | - |
| RE | AR2220 | 2006 | - |
| RF | AR1220 | 2004 | - |
| RG | AR2220 | 2007 | - |
| SW1 | S5700 | 2005 | - |

## 三、链路连接

- RA `GigabitEthernet0/0/0` ↔ SW1 `GigabitEthernet0/0/1`（Copper）
- SW1 `GigabitEthernet0/0/2` ↔ RB `GigabitEthernet0/0/0`（Copper）
- SW1 `GigabitEthernet0/0/3` ↔ RC `GigabitEthernet0/0/0`（Copper）
- RB `GigabitEthernet0/0/1` ↔ RD `GigabitEthernet0/0/0`（Copper）
- RC `Ethernet0/0/0` ↔ RD `Ethernet0/0/0`（Serial）
- RD `GigabitEthernet0/0/1` ↔ RE `GigabitEthernet0/0/0`（Copper）
- RF `GigabitEthernet0/0/0` ↔ RE `GigabitEthernet0/0/1`（Copper）
- RF `GigabitEthernet0/0/1` ↔ RG `GigabitEthernet0/0/0`（Copper）

## 四、拓扑图上的文字标注

- `49.0002`（贴近 RA）
- `49.0001`（贴近 RE）
- `LEVE1-1`（贴近 SW1）
- `LEVEL-2`（贴近 RE）
- `LEVEL-1-2`（贴近 RB）
- `LEVEL-1-2`（贴近 RC）
- `LEVEL-1`（贴近 RA）
- `LEVEL-2`（贴近 RD）
- `LEVEL-1-2`（贴近 RE）
- `10.10.123.0/24`（贴近 SW1）
- `.1`（贴近 RA）
- `.2`（贴近 RB）
- `.3`（贴近 RC）
- `10.10.24.0/24`（贴近 RD）
- `.2`（贴近 RB）
- `.4`（贴近 RD）
- `10.10.3.3/32`（贴近 RC）
- `10.10.45.0/24`（贴近 RE）
- `.4`（贴近 RD）
- `.5`（贴近 RE）
- `DIS`（贴近 RA）
- `LOOPBACK接口不激活ISIS`（贴近 RG）
- `LOOPBACK接口激活ISIS`（贴近 RA）
- `LEVEL-1 49.0003`（贴近 RG）
- `LEVEL-1-2`（贴近 RF）
- `LEVEL-1`（贴近 RG）
- `10.10.56.0/24`（贴近 RF）
- `5`（贴近 RE）
- `6`（贴近 RF）
- `10.10.67.0/24`（贴近 RF）
- `6`（贴近 RF）
- `7`（贴近 RG）
- `10.10.4.4/32`（贴近 RD）

## 六、验收要点

（待本地模型跑通后回填：需连通的 PC 对、需隔离的 PC 对、关键验证命令）
