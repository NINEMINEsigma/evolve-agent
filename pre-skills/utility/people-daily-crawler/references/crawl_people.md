# 人民网新闻爬虫参考文档

## 目录

1. [URL 格式说明](#1-url-格式说明)
2. [频道详解](#2-频道详解)
3. [输出格式详解](#3-输出格式详解)
4. [常见问题](#4-常见问题)
5. [进阶用法](#5-进阶用法)

---

## 1. URL 格式说明

### 标准新闻 URL

人民网新闻 URL 遵循统一格式，关键特征是路径中包含日期信息：

```
协议://子域名.people.com.cn/栏目/年份/月日/分类代码-文章ID.html
```

实际例子：

```
http://world.people.com.cn/n1/2026/0609/c1002-40736454.html
│      │                  │   │    │    └─ 文章唯一ID
│      │                  │   │    └── 分类代码 (c1002=国际新闻)
│      │                  │   └── 月日 (6月9日)
│      │                  └── 年份 (2026年)
│      └── 栏目路径 (n1=普通新闻)
└── 子域名 (world=国际频道)
```

### 日期位置

日期始终位于 URL 的第 4 和第 5 个路径段：

| URL 部分 | 示例 | 说明 |
|----------|------|------|
| 域名 | `world.people.com.cn` | 子频道 |
| 栏目 | `n1` | 新闻栏目代码 |
| 年份 | `2026` | 4 位年份 |
| 月日 | `0609` | 4 位月日 (MMDD) |
| 分类+ID | `c1002-40736454.html` | 分类代码 + 文章ID |

### 子域名映射

| 子域名 | 对应频道 |
|--------|----------|
| `world.people.com.cn` | 国际频道 |
| `www.people.com.cn` | 人民网首页 |
| `politics.people.com.cn` | 时政频道 |
| `finance.people.com.cn` | 经济频道 |
| `society.people.com.cn` | 社会频道 |
| `opinion.people.com.cn` | 观点频道 |
| `env.people.com.cn` | 环保频道 |
| `sn.people.com.cn` | 地方频道 |

---

## 2. 频道详解

### 国际频道 (world)

- **URL**: http://world.people.com.cn/
- **内容**: 国际新闻、外交动态、全球热点
- **特点**: 新闻最密集，每日更新量大
- **分类代码**: 通常为 `c1002`

### 人民网首页 (www)

- **URL**: http://www.people.com.cn/
- **内容**: 全站聚合，包含各频道精选
- **特点**: 页面结构复杂，链接分散在各区块
- **注意**: 首页直接爬取匹配数较少，建议通过各子频道获取完整覆盖

### 时政频道 (politics)

- **URL**: http://politics.people.com.cn/
- **内容**: 国内政治、政策解读

### 经济频道 (finance)

- **URL**: http://finance.people.com.cn/
- **内容**: 财经新闻、产业经济、科技
- **子板块**: 环保（env.people.com.cn）也归入此频道

### 社会频道 (society)

- **URL**: http://society.people.com.cn/
- **内容**: 社会民生、法治、天气等

---

## 3. 输出格式详解

### 顶层字段

| 字段 | 类型 | 说明 |
|------|------|------|
| `crawl_time` | string | 爬取执行时间 |
| `target_date` | string | 目标日期 (YYYY-MM-DD) |
| `total` | int | 新闻总条数 |
| `by_source` | object | 按频道统计数量 |
| `channels_crawled` | array | 实际爬取的频道列表 |
| `pages_per_channel` | int | 每频道爬取页数 |
| `news` | array | 新闻条目列表 |

### 新闻条目字段

| 字段 | 类型 | 说明 |
|------|------|------|
| `title` | string | 新闻标题 |
| `url` | string | 新闻完整 URL |
| `date` | string | 发布日期 |
| `source` | string | 来源频道中文名 |

---

## 4. 常见问题

### Q: 为什么有的频道显示 0 条？

可能原因：
1. 该频道当天确实没有更新
2. 分页 URL 格式不同（如 politics 频道需要特殊处理）
3. 网络请求超时

建议：尝试增加 `--timeout` 值或减少 `--pages`。

### Q: 如何确认爬取结果准确？

可以随机抽取几条 URL 用浏览器打开，核对文章发布日期是否与目标日期一致。

### Q: 爬虫被封了怎么办？

1. 适当增加请求间隔（脚本已内置合理延迟）
2. 检查 User-Agent 设置
3. 不要过于频繁地爬取

### Q: 如何添加新的频道？

在脚本的 `CHANNELS` 字典中添加新条目：

```python
CHANNELS = {
    ...
    "opinion": ("观点频道", "http://opinion.people.com.cn/"),
}
```

---

## 5. 进阶用法

### 与其他工具配合

```bash
# 爬取并统计各频道数量
python crawl_people.py --quiet | python -c "import sys,json; d=json.load(sys.stdin); print(json.dumps(d['by_source'], ensure_ascii=False, indent=2))"

# 提取所有 URL 列表
python crawl_people.py --quiet | python -c "import sys,json; [print(n['url']) for n in json.load(sys.stdin)['news']]" > urls.txt
```

### 用 Python 调用

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

### 定时爬取（Windows 任务计划程序）

创建批处理文件 `crawl_people.bat`：

```batch
@echo off
cd /d C:\path\to\script
python crawl_people.py --output C:\data\news\%date:~0,4%-%date:~5,2%-%date:~8,2%.json --quiet
```

然后在「任务计划程序」中设置为每天定时执行。

### 爬取历史数据

```bash
for d in $(python -c "from datetime import *; import sys; d=date.today()-timedelta(days=int(sys.argv[1])); print((d-timedelta(days=1)).isoformat())" 30); do
    python crawl_people.py --date $d --output "backfill/$d.json" --quiet
done
```

---

*文档版本: 1.0 | 最后更新: 2026-06-10*
