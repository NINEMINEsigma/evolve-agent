---
name: news-summary-extractor
description: "新闻摘要提取工具。输入新闻 URL 列表，自动读取每篇文章的正文，提取完整标题（从页面 title 标签）和一句话概述（正文第一段），输出结构化数据。适用于从爬虫获取的链接列表生成新闻日报、简报等场景。支持批量处理、字数限制分批、Markdown 格式输出，可直接配合 WPS Webhook 等推送工具使用。"
version: 1.0.0
author: Hermes Agent
category: news
tags:
  - news
  - summary
  - extractor
  - crawler
  - markdown
  - report
  - python
  - beautifulsoup
---

# news-summary-extractor

新闻摘要提取工具。输入新闻 URL 列表，自动读取每篇文章的正文，提取 **完整标题** 和 **一句话概述**，输出结构化数据。

## 工作流程

```
URL 列表 (JSON) 
    │
    ▼
对每条 URL 发起 HTTP 请求
    │
    ▼
BeautifulSoup 解析 HTML
    │
    ├─ 从 <title> 标签 → 完整标题（去掉 "--人民网" 等后缀）
    └─ 从正文第一段 → 一句话概述（截取到第一个句号）
    │
    ▼
输出结构化 JSON / Markdown
```

## 安装

```bash
pip install requests beautifulsoup4 lxml
```

## 快速开始

### 方式一：从 JSON 文件输入

```bash
# 输入 JSON 格式：{"news": [{"title": "...", "url": "..."}, ...]}
python news_summary.py --input news_links.json --output result.json
```

### 方式二：直接传入 URL

```bash
python news_summary.py --urls "https://...","https://..."
```

### 方式三：管道输入

```bash
cat news_links.json | python news_summary.py --output result.json
```

## 命令行参数

| 参数 | 缩写 | 默认值 | 说明 |
|------|------|--------|------|
| `--input` | `-i` | `""` | 输入 JSON 文件路径 |
| `--output` | `-o` | `""` | 输出 JSON 文件路径（不指定则只打印到 stdout） |
| `--urls` | | `""` | 直接传入 URL，逗号分隔 |
| `--format` | `-f` | `json` | 输出格式：`json` 或 `markdown` |
| `--max-chars` | `-m` | `0` | Markdown 格式时单条消息最大字数（0=不限），超过时分批 |
| `--source` | `-s` | `"来源"` | 来源名称（标记在输出中） |
| `--timeout` | `-t` | `10` | HTTP 请求超时（秒） |
| `--quiet` | `-q` | `False` | 安静模式 |

## 输入 JSON 格式

```json
{
  "target_date": "2026-06-09",
  "news": [
    {
      "title": "原标题（可选，会被页面标题覆盖）",
      "url": "http://world.people.com.cn/n1/2026/0609/c1002-40736454.html",
      "source": "国际频道"
    }
  ]
}
```

## 输出 JSON 格式

```json
{
  "target_date": "2026-06-09",
  "total": 41,
  "by_source": {
    "国际频道": 13,
    "经济频道": 22
  },
  "news": [
    {
      "title": "卡塔尔游牧生活与文化展在国博开幕",
      "url": "http://world.people.com.cn/n1/2026/0609/c1002-40736454.html",
      "source": "国际频道",
      "summary": "6月8日，由中国国家博物馆与卡塔尔国家博物馆共同主办的"行·迹——卡塔尔游牧生活与文化展"在北京中国国家博物馆开幕。"
    }
  ]
}
```

## 输出 Markdown 格式

指定 `--format markdown` 时，输出可直接用于 WPS Webhook 等推送工具：

```markdown
# 人民网新闻日报
> 日期：2026-06-09 | 共 41 条新闻

### 🌍 国际频道（13条）

**1. 卡塔尔游牧生活与文化展在国博开幕**
> 6月8日，由中国国家博物馆与卡塔尔国家博物馆共同主办的"行·迹——卡塔尔游牧生活与文化展"在北京中国国家博物馆开幕。
[阅读原文](http://...)
```

配合 `--max-chars 3800` 可自动分批（超过字数时在输出中用 `---` 分隔）：

```bash
python news_summary.py --input links.json --format markdown --max-chars 3800
```

输出示例：
```
# 人民网新闻日报
...
---
> **第 1/2 批**
...
---
> **第 2/2 批**
...
```

## 核心提取逻辑

### 标题提取

从页面的 `<title>` 标签获取完整标题，自动清理站点后缀：

```
原始: "卡塔尔游牧生活与文化展在国博开幕--国际--人民网"
提取: "卡塔尔游牧生活与文化展在国博开幕"

原始: "国际观察：中希文明交流彰显古典文明的亘古永恒价值--国际--人民网"
提取: "国际观察：中希文明交流彰显古典文明的亘古永恒价值"
```

### 概述提取

1. 用 BeautifulSoup 提取页面纯文本
2. 按换行分割，跳过导航菜单等干扰行
3. 找到第一个长度 > 30 字且不含导航关键词的段落
4. 截取到第一个句号作为一句话概述

```
正文: "6月8日，由中国国家博物馆与卡塔尔国家博物馆共同主办的"行·迹——卡塔尔游牧生活与文化展"在北京中国国家博物馆开幕。展览从...（后略）"
概述: "6月8日，由中国国家博物馆与卡塔尔国家博物馆共同主办的"行·迹——卡塔尔游牧生活与文化展"在北京中国国家博物馆开幕。"
```

## 典型使用场景

```bash
# 1. 爬虫获取链接 → 提取摘要
python crawl_people.py --date 2026-06-09 --quiet | python news_summary.py --output report.json

# 2. 提取摘要 → 生成 Markdown → 推送到 WPS
python news_summary.py --input links.json --format markdown --max-chars 3800 > report.md
python wps_send.py --key YOUR_KEY --type markdown --file report.md

# 3. 完整流水线（一条命令）
python crawl_people.py --quiet | python news_summary.py --format markdown --max-chars 3800 > report.md \
  && python wps_send.py --key YOUR_KEY --type markdown --file report.md
```

## 注意事项

- 脚本会自动从页面获取 **完整标题**，覆盖输入 JSON 中可能被截断的标题
- 概述为正文第一段的第一句话，如果提取失败则回退到使用原标题
- 建议每条消息不超过 4000 字（WPS 等平台限制），使用 `--max-chars` 自动分批
- 对于无法访问的 URL，会自动回退到原标题作为概述
- 本脚本不依赖任何 AI agent 特有功能或沙箱路径，可在任何 Python 环境中直接运行