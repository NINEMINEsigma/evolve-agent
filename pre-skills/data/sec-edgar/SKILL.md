---
name: sec-edgar
description: 美国上市公司 SEC EDGAR 披露数据——filings（10-K/10-Q/8-K）、XBRL 事实、财务报表、内部人交易（Form 4）、机构持仓（13F）、重大公司事件。当用户需要美国上市公司的官方披露文件、财务原文、XBRL 明细、内部人交易或机构持仓时使用。源自通用智能体工具包（Universal Agent Toolkit）。
category: data
version: 1.0.0-ea
author: "Eve (Evolve Agent 本地化)"
tags:
  - sec
  - edgar
  - filings
  - stocks
  - data
---

> **Evolve Agent 本地化注记**
>
> 本技能源自通用智能体工具包（Universal Agent Toolkit），由 Eve（Evolve Agent）本地化接入。
>
> - **数据源接入**：SEC EDGAR 提供公共 API（`https://data.sec.gov/...`、`https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=...`），用 `web_fetch` 调用；建议带上 User-Agent 标识请求方
> - **调用模式**：遵循下方"Describe → Call"两阶段模式；CIK 是公司主键
> - **引用规范**：引用 filings 事实时标明表格类型与期间（如"10-K, FY2025"）

# SEC EDGAR：美国上市公司披露数据（通用版）

> 对应能力：美国上市公司 filings 与财务数据——公司信息、10-K/10-Q/8-K 等 filings、XBRL 事实、财务报表、内部人交易、机构持仓、重大公司事件。

## 路由地位

美国上市公司（含 ADR）的**一手披露来源**：财报原文、重大事件、内部人交易以 EDGAR 为权威。快速行情与指标可用综合行情源（`financial-data-yahoo`），但披露类事实（"公司在 10-K 中披露……"）必须以 EDGAR 为准。

## 数据源通用调用模式

1. **Describe**：取数据源描述文档（公司与 filing 格式、全局约束、各 API 参数）。
2. **选 API**：公司信息 / filings 列表 / XBRL 事实 / 财务报表 / 内部人交易 / 机构持仓 / 重大事件。
3. **构造参数**：公司、ticker、CIK、表格类型（form type）、期间、日期、accession number、分页字段——只用 API 文档支持的字段。
4. **Call**：失败如实报告；成功先存文件再作答。

## 实务要点

- CIK 是 EDGAR 的公司主键；ticker → CIK 映射由数据源提供。
- 看"最新披露"用 filings 列表按日期排序；看"具体数字口径"用 XBRL 事实（带期间与单位）；看"完整报表"用财务报表接口。
- 8-K 对应重大事件；Form 4 对应内部人交易；13F 对应机构持仓。
- 引用 filings 事实时标明表格类型与期间（如"10-K, FY2025"）。

## 引用规范（强制）

数字或事实紧跟引用：`[来源: SEC EDGAR — 具体 filing/数据集, 截至日期]`。filing 名称、期间、日期只用工具实际返回的信息，绝不编造。
