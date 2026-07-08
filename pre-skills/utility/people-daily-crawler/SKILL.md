---
name: "people-daily-crawler"
description: 人民网新闻爬虫工具技能。爬取人民网（www.people.com.cn）及其子频道（国际、时政、经济、社会等）的新闻链接列表。通过 URL 路径中的日期信息（如 /2026/0609/）自动筛选指定日期的新闻，无需逐篇访问。支持多频道同时爬取、自动分页、结果去重，输出结构化 JSON 文件。适用于新闻聚合、舆情分析、信息收集等场景。
version: 1.0.0
author: Hermes Agent
category: utility
tags:
  - crawler
  - scraper
  - news
  - "people-daily"
  - 人民网
  - "web-scraping"
  - python
---

# people-daily-crawler

人民网新闻爬虫工具。爬取人民网主站及其子频道（国际、时政、经济、社会等）的新闻链接列表。

## 工作原理

人民网的新闻 URL 包含日期信息，格式为：

```
http://world.people.com.cn/n1/2026/0609/c1002-40736454.html
                              └──┬──┘
                            2026年6月9日
```

爬虫直接从 URL 路径中提取日期，**无需访问每篇文章的正文**来确认发布日期。这使其非常快速高效——爬取 5 个频道各 2 页仅需数秒。

## 安装

```bash
# 安装依赖
pip install requests beautifulsoup4 lxml
```

## 快速开始

```bash
# 爬取前一天的所有新闻（默认行为）
python crawl_people.py

# 指定日期
python crawl_people.py --date 2026-06-09

# 只爬取国际频道
python crawl_people.py --channels world

# 指定输出文件
python crawl_people.py --output my_news.json

# 爬取更多页（每个频道）
python crawl_people.py --pages 3
```

## 命令行参数

| 参数 | 缩写 | 默认值 | 说明 |
|------|------|--------|------|
| `--date` | `-d` | 前一天 | 目标日期，格式 `YYYY-MM-DD` |
| `--output` | `-o` | `./people_news_{date}.json` | 输出 JSON 文件路径 |
| `--channels` | `-c` | 全部 | 要爬取的频道，逗号分隔 |
| `--pages` | `-p` | `2` | 每个频道爬取的页数 |
| `--timeout` | `-t` | `10` | HTTP 请求超时（秒） |
| `--quiet` | `-q` | `False` | 安静模式，减少输出 |
| `--list-channels` | | | 列出所有支持的频道 |

## 支持的频道

| 频道名 | URL | 说明 |
|--------|-----|------|
| `world` | http://world.people.com.cn/ | 国际频道 |
| `www` | http://www.people.com.cn/ | 人民网首页（聚合） |
| `politics` | http://politics.people.com.cn/ | 时政频道 |
| `finance` | http://finance.people.com.cn/ | 经济频道 |
| `society` | http://society.people.com.cn/ | 社会频道 |

## 输出说明

### 输出方式：文件 + stdout 双通道

脚本采用**双通道输出**策略，兼顾人工查看和程序调用的需求：

#### 1️⃣ 主输出 → JSON 文件

完整的爬取结果以 JSON 格式保存到文件：

```bash
# 默认保存到当前目录
python crawl_people.py
→ ./people_news_2026-06-09.json

# 可用 --output 指定路径
python crawl_people.py --output /data/news/today.json
```

#### 2️⃣ 副本 → 标准输出流（stdout）

爬取完成后，JSON 结果也会打印到 **stdout**，方便管道操作：

```bash
# 接 Python 处理
python crawl_people.py --quiet | python -c "import sys,json; d=json.load(sys.stdin); print(d['total'], '条')"

# 提取所有 URL
python crawl_people.py --quiet | python -c "
import sys, json
for n in json.load(sys.stdin)['news']:
    print(n['url'])
" > urls.txt

# 统计各频道数量
python crawl_people.py --quiet | python -c "
import sys, json
d = json.load(sys.stdin)
for src, cnt in sorted(d['by_source'].items(), key=lambda x: -x[1]):
    print(f'{src}: {cnt}条')
"
```

#### 3️⃣ 运行进度 → 标准错误流（stderr）

爬取过程中的进度信息输出到 **stderr**。这样即使通过管道重定向 stdout，进度信息也不会混入结果数据中：

```bash
# stderr 进度不会干扰管道
python crawl_people.py --quiet 2>/dev/null | python process.py   ← 干净的 JSON

# 想同时看进度和结果
python crawl_people.py 2>&1 | tee output.log
```

`--quiet` 参数可减少 stderr 的输出量。

### 输出格式（JSON 文件 / stdout）

```json
{
  "crawl_time": "2026-06-10 17:51:48",
  "target_date": "2026-06-09",
  "total": 41,
  "by_source": {
    "国际频道": 13,
    "人民网首页": 2,
    "经济频道": 22,
    "社会频道": 4
  },
  "channels_crawled": ["world", "www", "politics", "finance", "society"],
  "pages_per_channel": 2,
  "news": [
    {
      "title": "卡塔尔游牧生活与文化展在国博开幕",
      "url": "http://world.people.com.cn/n1/2026/0609/c1002-40736454.html",
      "date": "2026-06-09",
      "source": "国际频道"
    }
  ]
}
```

### 顶层字段说明

| 字段 | 类型 | 说明 |
|------|------|------|
| `crawl_time` | string | 爬取执行时间 |
| `target_date` | string | 目标日期 (YYYY-MM-DD) |
| `total` | int | 新闻总条数 |
| `by_source` | object | 按频道统计的数量，如 `{"国际频道": 13, "经济频道": 22}` |
| `channels_crawled` | array | 实际爬取的频道标识符列表 |
| `pages_per_channel` | int | 每个频道爬取的页数 |
| `news` | array | 新闻条目列表 |

### 新闻条目字段

| 字段 | 类型 | 说明 |
|------|------|------|
| `title` | string | 新闻标题 |
| `url` | string | 新闻完整 URL |
| `date` | string | 发布日期 |
| `source` | string | 来源频道中文名（如"国际频道"） |

## 使用示例

### 1. 基本使用（爬取前一天全部频道）

```bash
pip install requests beautifulsoup4 lxml
python crawl_people.py
```

输出到 `./people_news_2026-06-09.json`

### 2. 监控特定频道

```bash
# 每天只爬国际 + 时政
python crawl_people.py --channels world,politics --date 2026-06-09
```

### 3. 定时任务（Linux cron）

```cron
# 每天早上8点爬取前一天的新闻
0 8 * * * cd /path/to/script && python crawl_people.py --output /data/news/$(date +\%Y-\%m-\%d).json --quiet
```

### 4. 批量处理历史日期

```bash
for date in 2026-06-07 2026-06-08 2026-06-09; do
    python crawl_people.py --date $date --output "news_$date.json"
done
```

### 5. 用 Python 程序调用

```python
import subprocess
import json

result = subprocess.run(
    ["python", "crawl_people.py", "--date", "2026-06-09", "--quiet"],
    capture_output=True, text=True
)
data = json.loads(result.stdout)
print(f"共 {data['total']} 条新闻")
for news in data['news']:
    print(f"  [{news['source']}] {news['title']}")
```

## 注意事项

- **频率限制**：人民网对请求频率有一定限制，请勿设置过短超时或过高并发
- **页面结构变化**：如果人民网改版，URL 格式可能变化，届时需要更新脚本
- **分页限制**：部分频道可能只有 1 页内容，`--pages` 设得再大也无效
- **首页特殊性**：`www.people.com.cn` 是聚合首页，新闻链接分散在各个子频道中，爬取首页时匹配到的结果可能较少
- **编码**：人民网使用 UTF-8 编码，脚本已正确处理
- **网络要求**：需要能够访问 `people.com.cn` 域名
- **脚本独立**：本脚本不依赖任何 AI agent 特有功能或沙箱路径，可在任何 Python 环境中直接运行

## 脚本位置

本 skill 包含的脚本位于 `scripts/crawl_people.py`，可通过 `python scripts/crawl_people.py` 直接运行。