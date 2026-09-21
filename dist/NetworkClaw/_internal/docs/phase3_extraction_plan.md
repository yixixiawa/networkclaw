# 阶段三规划：从官方手册自动提取命令模板

> 前置条件：阶段一的手工模板积累到几百条、字段结构稳定之后再启动。
> 本文档描述完整方案；`tools/manual_extractor.py` 已提供可运行的脚手架。

## 1. 目标

把三家官方文档中的命令语法自动转为 `command_templates.csv` 格式的候选条目，
经人工审核后追加进主表，替代纯手工录入。

## 2. 数据源（官方文档入口）

| 厂商 | 文档源 | 形式 | 备注 |
|------|--------|------|------|
| Huawei | support.huawei.com（产品文档中心，VRP 配置指南「命令参考」） | HTML/PDF | 章节按命令名组织，有固定语法块 |
| H3C | www.h3c.com（产品支持文档，Comware V7 命令参考） | HTML/PDF/CHM | 命令参考结构统一：用途→语法→视图→参数 |
| Cisco | developer.cisco.com / cisco.com「Command References」（IOS 15.x / IOS-XE） | HTML | 每条命令一节，含 Syntax / Command Mode / Usage Guidelines |

建议优先抓取 **命令参考（Command Reference）** 而非配置指南——前者结构最规整。
下载时注意遵守各网站服务条款，控制抓取频率。

## 3. 提取流水线（五步）

```
原始文档 (HTML/PDF/CHM)
   │  ① 获取：按需下载/导出章节，存到 knowledge/manuals/<vendor>/
   ▼
② 解析：HTML 用 BeautifulSoup / PDF 用 pdfplumber / CHM 先转 HTML
   │   目标：抽出每条命令的「语法行 + 视图 + 说明」三段
   ▼
③ 结构化：正则 + 启发式规则清洗
   │   - 语法行去掉参数占位符里的花括号修饰，保留标准写法
   │   - 视图字段映射到统一枚举（系统视图/接口视图/用户视图/…）
   ▼
④ 去重与对齐：以 command 归一化（小写、压缩空白）为键去重；
   │   与主表已有条目比对，只保留新增
   ▼
⑤ 人工审核队列：输出 knowledge/review_queue.csv（新增候选），
       人工逐条确认后合并进 command_templates.csv
```

## 4. intent 字段的生成策略（关键）

CSV 里的 `intent`（用户意图）是语义检索的质量核心，机器生成的 intent 效果差，
建议分级处理：

1. **优先复用**：命令说明首句往往就是意图，直接截取并人工润色；
2. **LLM 辅助**：把「命令 + 说明」喂给本地 llama-server（8080 已就绪），
   用固定 prompt 生成一句中文意图，再人工抽检；
3. **兜底**：intent 留空但标记 `needs_intent=1`，人工补齐后才允许入主表。

## 5. 质量红线

- 未经人工审核的条目**只进 review_queue，不直接进主表**；
- 每条候选必须带来源（`source_doc` + 章节 URL/页码），便于回溯核对；
- 版本差异大（如 H3C password simple/hash）的命令在 note 里标明适用版本。

## 6. 脚手架使用

```bash
# 1. 把导出的手册文本放到 knowledge/manuals/ 下（每个厂商一个 txt）
# 2. 运行脚手架，产出候选队列
python tools/manual_extractor.py knowledge/manuals/huawei_vrp.txt --vendor Huawei
# 3. 打开 knowledge/review_queue.csv 逐条审核，确认后并入主表
```

脚手架内置了一个基于正则的粗提取器（识别命令语法行、视图行），真实文档的
解析规则需要在 ② 解析步骤里按实际 HTML 结构补充完善（代码中已标 TODO）。
