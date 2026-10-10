# 拓扑图识读样例（data/topology_images/）

`vision_server.analyze_topology_image` 的**输入样例**：从 eNSP 画布截取的实验拓扑图，
供演示「看懂拓扑」能力与回归对比使用。

## 文件说明

| 文件 | 来源 |
|---|---|
| `topology_20260924_161137.png` | eNSP 画布截图（多交换机 VLAN 实验） |
| `topology_raw_20260929_19*.png` | 连拍样张（验证截图稳定性用） |

完整历史截图在 `logs/captures/`（不入库），本目录只保留代表性样张入库。

## 识读输出约定

`core/vision.py` 的识图输出为固定五段结构：
**拓扑概览 / 设备清单 / 连接关系 / IP 与网段 / 风险点**；
图中未标注的信息必须写「图中未标注」，禁止臆造。

## 采集方式

- 自动：`vision_server.capture_topology`（自动找 eNSP/VMware 窗口截图，长边缩到 1280px）
- 手动：把新样张直接放进本目录并在此表登记
