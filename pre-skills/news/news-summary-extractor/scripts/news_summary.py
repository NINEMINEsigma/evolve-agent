#!/usr/bin/env python3
"""
新闻摘要提取工具

输入新闻 URL 列表，自动读取每篇文章的正文，提取完整标题和一句话概述。

用法:
    pip install requests beautifulsoup4 lxml
    python news_summary.py --input links.json --output result.json
    python news_summary.py --input links.json --format markdown --max-chars 3800
    cat links.json | python news_summary.py --format markdown
"""
import argparse
import json
import re
import sys

import requests
from bs4 import BeautifulSoup

# 导航关键词，用于跳过干扰行
SKIP_KEYWORDS = [
    "人民网", "首页", "党政", "登录", "注册", "English",
    "客户端", "无障碍", "举报", "合作网站", "毛主席",
    "周恩来", "邓小平", "学习强国", "版权", "公安机关",
]

# 站点后缀，从标题中清理
SITE_SUFFIXES = ["--国际--人民网", "--人民网", "_国际_人民网"]


def parse_args():
    parser = argparse.ArgumentParser(
        description="新闻摘要提取工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("-i", "--input", default="", help="输入 JSON 文件路径")
    parser.add_argument("-o", "--output", default="", help="输出 JSON 文件路径")
    parser.add_argument("--urls", default="", help="直接传入 URL，逗号分隔")
    parser.add_argument(
        "-f", "--format", choices=["json", "markdown"], default="json",
        help="输出格式 (默认: json)",
    )
    parser.add_argument(
        "-m", "--max-chars", type=int, default=0,
        help="Markdown 格式时单批最大字数 (0=不限)",
    )
    parser.add_argument("-s", "--source", default="来源", help="来源名称")
    parser.add_argument("-t", "--timeout", type=int, default=10, help="HTTP 超时秒数")
    parser.add_argument("-q", "--quiet", action="store_true", help="安静模式")
    return parser.parse_args()


def read_input(args):
    """读取输入：优先 --urls，其次 --input 文件，最后 stdin"""
    if args.urls:
        urls = [u.strip() for u in args.urls.split(",") if u.strip()]
        return {
            "target_date": "",
            "news": [{"title": "", "url": u, "source": args.source} for u in urls],
        }
    if args.input:
        with open(args.input, "r", encoding="utf-8") as f:
            return json.load(f)
    if not sys.stdin.isatty():
        return json.load(sys.stdin)
    print("错误: 请指定 --input、--urls 或通过管道传入数据", file=sys.stderr)
    sys.exit(1)


def extract_title(soup):
    """从页面提取完整标题"""
    if not soup.title:
        return ""
    raw = soup.title.get_text(strip=True)
    for suffix in SITE_SUFFIXES:
        if suffix in raw:
            raw = raw.split(suffix)[0].strip()
            break
    return raw if len(raw) > 5 else ""


def extract_summary(soup):
    """从页面提取正文第一段作为概述"""
    text = soup.get_text("\n", strip=True)
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    for line in lines:
        if len(line) > 30 and not any(k in line for k in SKIP_KEYWORDS):
            dot = line.find("。")
            if dot > 15:
                return line[: dot + 1]
            return line[:100]
    return ""


def fetch_article(url, timeout=10):
    """抓取一篇文章，返回 (完整标题, 概述)"""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept-Language": "zh-CN,zh;q=0.9",
    }
    try:
        r = requests.get(url, timeout=timeout, headers=headers)
        r.encoding = "utf-8"
        soup = BeautifulSoup(r.text, "lxml")
        title = extract_title(soup)
        summary = extract_summary(soup)
        return title, summary
    except Exception as e:
        return "", ""


def build_markdown(news_list, max_chars=0):
    """将新闻列表组装为 Markdown 格式，支持分批"""
    def make_batch(batch, batch_no, total):
        lines = []
        if batch_no == 1:
            lines.append("# 新闻简报")
            lines.append("")
        if total > 1:
            lines.append("---")
            lines.append(f"> **第 {batch_no}/{total} 批**")
            lines.append("")
        # 按来源分组
        by_src = {}
        for n in batch:
            by_src.setdefault(n.get("source", "未知"), []).append(n)
        for src, items in by_src.items():
            lines.append("")
            lines.append(f"### {src}（{len(items)}条）")
            for i, n in enumerate(items, 1):
                summary = n.get("summary", "") or n.get("title", "")
                lines.append("")
                lines.append(f"**{i}. {n['title']}**")
                lines.append(f"> {summary[:150]}")
                lines.append(f"[阅读原文]({n['url']})")
        lines.append("")
        lines.append("---")
        lines.append("*由 news-summary-extractor 生成*")
        return "\n".join(lines)

    if max_chars <= 0:
        return [make_batch(news_list, 1, 1)]

    batches = []
    cur = []
    for n in news_list:
        test = make_batch(cur + [n], 1, 1)
        if len(test) > max_chars and cur:
            batches.append(cur)
            cur = [n]
        else:
            cur = cur + [n]
    if cur:
        batches.append(cur)

    return [make_batch(b, i + 1, len(batches)) for i, b in enumerate(batches)]


def main():
    args = parse_args()

    # 读取输入
    data = read_input(args)
    news_list = data.get("news", [])
    target_date = data.get("target_date", "")

    if not news_list:
        print("错误: 输入中未找到新闻列表", file=sys.stderr)
        sys.exit(1)

    if not args.quiet:
        print(f"处理 {len(news_list)} 篇文章...", file=sys.stderr)

    # 逐篇抓取
    results = []
    for i, n in enumerate(news_list):
        url = n.get("url", "")
        if not url:
            continue
        title, summary = fetch_article(url, args.timeout)
        results.append({
            "title": title or n.get("title", ""),
            "url": url,
            "source": n.get("source", args.source),
            "summary": summary or n.get("title", ""),
        })
        if not args.quiet:
            status = "OK" if (title and summary) else "FALLBACK"
            print(f"  [{i+1}/{len(news_list)}] {status}", file=sys.stderr)

    # 按来源统计
    by_source = {}
    for n in results:
        by_source[n["source"]] = by_source.get(n["source"], 0) + 1

    # 构建输出
    if args.format == "markdown":
        batches = build_markdown(results, args.max_chars)
        if args.output:
            with open(args.output, "w", encoding="utf-8") as f:
                for batch in batches:
                    f.write(batch + "\n")
        else:
            # 管道模式：分批输出，用 RS 分隔符(\x1e)隔开
            for i, batch in enumerate(batches):
                if i > 0:
                    sys.stdout.write("\x1e\n")
                sys.stdout.write(batch + "\n")
    else:
        output = {
            "target_date": target_date,
            "total": len(results),
            "by_source": by_source,
            "news": results,
        }
        output_json = json.dumps(output, ensure_ascii=False, indent=2)
        if args.output:
            with open(args.output, "w", encoding="utf-8") as f:
                f.write(output_json)
        print(output_json)

    if not args.quiet:
        print(f"\n完成! 共 {len(results)} 篇", file=sys.stderr)


if __name__ == "__main__":
    main()
