#!/usr/bin/env python3
"""
人民网新闻爬虫 (People's Daily News Crawler)

爬取人民网（www.people.com.cn）及其子频道的新闻链接列表。
通过 URL 路径中的日期信息自动筛选指定日期的新闻。

用法:
    pip install requests beautifulsoup4 lxml
    python crawl_people.py
    python crawl_people.py --date 2026-06-09 --channels world,finance
"""
import argparse
import json
import os
import re
import sys
from datetime import datetime, timedelta
from html.parser import HTMLParser
from urllib.parse import urljoin

import requests


# ── 支持的频道配置 ──────────────────────────────────────────────

CHANNELS = {
    "world":    ("国际频道", "http://world.people.com.cn/"),
    "www":      ("人民网首页", "http://www.people.com.cn/"),
    "politics": ("时政频道", "http://politics.people.com.cn/"),
    "finance":  ("经济频道", "http://finance.people.com.cn/"),
    "society":  ("社会频道", "http://society.people.com.cn/"),
}


# ── HTML 解析器 ────────────────────────────────────────────────

class LinkExtractor(HTMLParser):
    """从 HTML 中提取所有链接与其文本。"""

    def __init__(self):
        super().__init__()
        self.links = []
        self._text = ""
        self._in_a = False
        self._href = ""

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self._in_a = True
            self._text = ""
            self._href = ""
            for name, value in attrs:
                if name == "href":
                    self._href = value

    def handle_endtag(self, tag):
        if tag == "a" and self._in_a and self._href:
            text = self._text.strip()
            if text:
                self.links.append((text[:80], self._href))
            self._in_a = False

    def handle_data(self, data):
        if self._in_a:
            self._text += data


# ── 网络请求 ────────────────────────────────────────────────────

def fetch_links(url, timeout=10):
    """抓取一个页面的所有链接。"""
    try:
        resp = requests.get(
            url,
            timeout=timeout,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            },
        )
        resp.encoding = "utf-8"
        parser = LinkExtractor()
        parser.feed(resp.text)
        return parser.links
    except Exception as exc:
        print(f"  [WARN] 请求失败: {url}", file=sys.stderr)
        print(f"         {exc}", file=sys.stderr)
        return []


# ── URL 处理 ────────────────────────────────────────────────────

def normalize_url(href, base_url):
    """将相对路径补全为绝对 URL，统一为 http:// 协议。"""
    if href.startswith("//"):
        href = "http:" + href
    elif not href.startswith("http"):
        href = urljoin(base_url, href)
    # 统一协议以便去重
    href = href.replace("https://", "http://")
    return href


def is_news_article(url):
    """判断 URL 是否为新闻文章链接。
    
    人民网新闻 URL 格式：domain/section/YYYY/MMDD/code-id.html
    """
    return bool(re.search(r"people\.com\.cn/\w+/\d{4}/\d{4}/[a-z]\d+-", url))


def extract_date(url):
    """从 URL 中提取日期字符串。
    
    例: /2026/0609/ → "2026-06-09"
    """
    match = re.search(r"/(\d{4})/(\d{4})/", url)
    if match:
        year = match.group(1)
        month = match.group(2)[:2]
        day = match.group(2)[2:]
        return f"{year}-{month}-{day}"
    return None


def build_page_url(channel_url, page):
    """构造分页 URL。"""
    if page == 1:
        return channel_url

    base = channel_url.rstrip("/")

    # 尝试替换 index 模式
    if "/index" in base:
        return re.sub(r"index\d*\.html", f"index{page}.html", base)

    # 追加 index 模式
    if base.endswith(".html"):
        return base.replace(".html", f"/index{page}.html")

    return f"{base}/index{page}.html"


# ── 爬取核心逻辑 ────────────────────────────────────────────────

def crawl_channel(name, url, target_date, max_pages=2, timeout=10):
    """爬取单个频道，返回匹配目标日期的新闻列表。"""
    results = []

    for page in range(1, max_pages + 1):
        page_url = build_page_url(url, page)
        links = fetch_links(page_url, timeout=timeout)

        page_hits = 0
        for title, href in links:
            full_url = normalize_url(href, url)
            if not is_news_article(full_url):
                continue
            if extract_date(full_url) != target_date:
                continue
            results.append({
                "title": title.strip(),
                "url": full_url,
                "date": target_date,
                "source": name,
            })
            page_hits += 1

        print(f"  [页 {page}] +{page_hits} 条 (累计 {len(results)})", file=sys.stderr, flush=True)

    return results


# ── 主入口 ──────────────────────────────────────────────────────

def parse_args():
    """解析命令行参数。"""
    parser = argparse.ArgumentParser(
        description="人民网新闻爬虫 — 爬取指定日期的新闻链接",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  crawl_people.py
  crawl_people.py --date 2026-06-09
  crawl_people.py --channels world,finance --pages 3
  crawl_people.py --output my_news.json --quiet
        """,
    )
    parser.add_argument(
        "-d", "--date",
        default=None,
        help="目标日期 (YYYY-MM-DD)，默认前一天",
    )
    parser.add_argument(
        "-o", "--output",
        default=None,
        help="输出 JSON 文件路径",
    )
    parser.add_argument(
        "-c", "--channels",
        default="",
        help="频道列表，逗号分隔。可用: " + ", ".join(sorted(CHANNELS.keys())),
    )
    parser.add_argument(
        "-p", "--pages",
        type=int,
        default=2,
        help="每个频道爬取页数 (默认: 2)",
    )
    parser.add_argument(
        "-t", "--timeout",
        type=int,
        default=10,
        help="HTTP 请求超时秒数 (默认: 10)",
    )
    parser.add_argument(
        "-q", "--quiet",
        action="store_true",
        help="安静模式，减少输出",
    )
    parser.add_argument(
        "--list-channels",
        action="store_true",
        help="列出所有支持的频道并退出",
    )
    return parser.parse_args()


def main():
    args = parse_args()

    # 列出频道
    if args.list_channels:
        print("\n支持的频道:")
        print(f"  {'名称':<12} {'说明':<14} URL")
        print(f"  {'-'*12} {'-'*14} {'-'*40}")
        for key, (name, url) in sorted(CHANNELS.items()):
            print(f"  {key:<12} {name:<14} {url}")
        print()
        return

    # 目标日期
    if args.date:
        target_date = args.date
    else:
        target_date = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

    # 选择频道
    if args.channels:
        selected = [c.strip() for c in args.channels.split(",") if c.strip()]
        channel_list = [(k, CHANNELS[k]) for k in selected if k in CHANNELS]
        if not channel_list:
            print(f"[ERROR] 无效的频道名称。可用: {', '.join(sorted(CHANNELS.keys()))}")
            sys.exit(1)
    else:
        channel_list = list(CHANNELS.items())

    # 输出文件
    if args.output:
        output_path = args.output
    else:
        output_path = f"./people_news_{target_date}.json"

    if not args.quiet:
        print("=" * 55)
        print(f"  人民网新闻爬虫")
        print(f"  目标日期: {target_date}")
        print(f"  频道数:   {len(channel_list)}")
        print(f"  每频道爬取: {args.pages} 页")
        print(f"  输出文件: {output_path}")
        print("=" * 55)

    # 执行爬取
    all_news = []
    for key, (name, url) in channel_list:
        if not args.quiet:
            print(f"\n[{name}] {url}")
        try:
            news = crawl_channel(name, url, target_date, args.pages, args.timeout)
            all_news.extend(news)
        except Exception as exc:
            print(f"  [ERROR] {name}: {exc}", file=sys.stderr)

    # 去重
    seen = set()
    unique_news = []
    for item in all_news:
        if item["url"] not in seen:
            seen.add(item["url"])
            unique_news.append(item)

    # 按频道统计
    by_source = {}
    for item in unique_news:
        by_source.setdefault(item["source"], 0)
        by_source[item["source"]] += 1

    # 输出 JSON
    result = {
        "crawl_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "target_date": target_date,
        "total": len(unique_news),
        "by_source": by_source,
        "channels_crawled": [k for k, _ in channel_list],
        "pages_per_channel": args.pages,
        "news": unique_news,
    }

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    if not args.quiet:
        print(f"\n{'=' * 55}")
        print(f"  爬取完成! 共 {len(unique_news)} 条新闻")
        print(f"  结果已保存: {os.path.abspath(output_path)}")
        print(f"{'=' * 55}")

        for src, count in sorted(by_source.items(), key=lambda x: -x[1]):
            print(f"  {src}: {count} 条")

    # 同时输出 JSON 到 stdout，方便管道处理
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
