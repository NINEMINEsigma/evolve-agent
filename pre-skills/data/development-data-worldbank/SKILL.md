---
name: development-data-worldbank
description: 世界银行公开发展数据——覆盖各国 29,000+ 指标（GDP、人口、贫困、失业、贸易、通胀、教育、卫生、环境），1960 年至今长时序。当用户需要发展指标、长历史序列、跨国对比数据时使用。源自通用智能体工具包（Universal Agent Toolkit）。
category: data
version: 1.0.0-ea
author: "Eve (Evolve Agent 本地化)"
tags:
  - worldbank
  - development
  - indicators
  - data
---

> **Evolve Agent 本地化注记**
>
> 本技能源自通用智能体工具包（Universal Agent Toolkit），由 Eve（Evolve Agent）本地化接入。
>
> - **数据源接入**：世界银行提供公共 API（`https://api.worldbank.org/v2/...`），用 `web_fetch` 调用即可，无需密钥
> - **实测记录**：2026-08 已验证 `https://api.worldbank.org/v2/country/CHN/indicator/SP.POP.BRTH.MF?format=json&per_page=100` 可正常返回 JSON
> - **调用模式**：遵循下方"Describe → Call"两阶段模式；指标代码不要凭记忆拼，从文档查证

# 世界银行公开数据（通用版）

> 对应能力：全球发展指标——覆盖各国 29,000+ 指标，经济、社会、环境三大类（GDP、GNP、人口、贫困、失业、贸易、通胀、教育、卫生、环境），1960 年至今的长时序。

## 何时使用

- 发展类指标与长时序：贫困率、入学率、预期寿命、碳排放、人口结构等。
- 与 IMF 的分工：宏观财政/金融与预测走 IMF（`macro-data-imf`）；社会发展、环境、长历史序列走世界银行。
- 指标代码（如 NY.GDP.MKTP.KD.ZG = 实际 GDP 增长）在描述文档中查证，不要凭记忆拼。

## 数据源通用调用模式

1. **Describe**：取数据源描述文档（国家/地区代码、指标检索方式、期间与分页约束）。
2. **选 API**、**构造参数**：国家、指标、年份区间；多国对比用国家列表。
3. **Call**：失败如实报告；成功先存文件再作答。

## 实务要点

- 世行数据更新滞后 1–2 年属正常——回答"最新"时说明实际数据年份。
- 缺失值常见（尤其小国/早年份），如实呈现缺口，不要插值编造。
- 跨国对比注意收入分组、地区聚合值（如"东亚与太平洋"）与单国值的区别。

## 引用规范（强制）

凡来自专业数据源的数字或事实，紧跟引用：`[来源: 世界银行 — 数据集/指标, 截至日期]`。元数据只用工具实际返回的信息；绝不伪造数据或引用。
