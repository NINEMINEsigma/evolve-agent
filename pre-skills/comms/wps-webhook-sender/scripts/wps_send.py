#!/usr/bin/env python3
"""
WPS Webhook 消息发送器

发送 Markdown、文本、链接卡片消息到 WPS 群聊机器人。
Webhook URL 中的 key 作为参数传入，不硬编码。

用法:
    pip install requests
    python wps_send.py --key YOUR_KEY --type markdown --text "# Hello"
    python wps_send.py --key YOUR_KEY --type text --text "你好"
    echo "# 标题" | python wps_send.py --key YOUR_KEY --type markdown
    python wps_send.py --key YOUR_KEY --type link --title "标题" --text "摘要" --url "https://..."
"""
import argparse
import json
import sys

import requests


def parse_args():
    """解析命令行参数"""
    parser = argparse.ArgumentParser(
        description="WPS Webhook 消息发送器",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  wps_send.py --key abc123 --type markdown --text "# Hello"
  wps_send.py --key abc123 --type text --text "你好"
  cat msg.md | wps_send.py --key abc123 --type markdown
  wps_send.py --key abc123 --type link --title "标题" --text "摘要" --url "https://example.com"
        """,
    )
    parser.add_argument(
        "-k", "--key",
        required=True,
        help="Webhook key (URL 中 key= 后面的值)",
    )
    parser.add_argument(
        "-u", "--url",
        default="https://xz.wps.cn/api/v1/webhook/send",
        help="Webhook 基础 URL (默认: https://xz.wps.cn/api/v1/webhook/send)",
    )
    parser.add_argument(
        "-t", "--type",
        choices=["markdown", "text", "link"],
        default="markdown",
        help="消息类型 (默认: markdown)",
    )
    parser.add_argument(
        "--text",
        default="",
        help="消息正文 (markdown 或 text 类型)",
    )
    parser.add_argument(
        "--title",
        default="",
        help="链接卡片标题 (仅 link 类型)",
    )
    parser.add_argument(
        "--url-link",
        default="",
        dest="message_url",
        help="链接卡片跳转地址 (仅 link 类型)",
    )
    parser.add_argument(
        "--btn",
        default="查看详情",
        help="链接卡片按钮文字 (默认: 查看详情，仅 link 类型)",
    )
    parser.add_argument(
        "-f", "--file",
        default="",
        help="从文件读取消息内容",
    )
    parser.add_argument(
        "-q", "--quiet",
        action="store_true",
        help="安静模式",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="仅打印消息 JSON，不发送",
    )
    return parser.parse_args()


def read_content(args):
    """读取消息内容：优先管道，其次文件，最后 --text 参数"""
    # 检查是否有管道输入
    if not sys.stdin.isatty():
        return sys.stdin.read()
    # 从文件读取
    if args.file:
        with open(args.file, "r", encoding="utf-8") as f:
            return f.read()
    # 使用 --text 参数
    return args.text


def build_payload(args, content):
    """根据消息类型构建 payload"""
    if args.type == "markdown":
        return {
            "msgtype": "markdown",
            "markdown": {"text": content},
        }
    elif args.type == "text":
        return {
            "msgtype": "text",
            "text": {"content": content},
        }
    elif args.type == "link":
        return {
            "msgtype": "link",
            "link": {
                "title": args.title,
                "text": content or args.text,
                "messageUrl": args.message_url,
                "btnTitle": args.btn,
            },
        }
    return {}


def main():
    args = parse_args()

    # 读取内容
    content = read_content(args)

    if not content and args.type != "link":
        print("错误: 未指定消息内容。使用 --text、--file 或管道输入。", file=sys.stderr)
        sys.exit(1)

    if args.type == "link" and not args.title:
        print("错误: link 类型需要 --title 参数", file=sys.stderr)
        sys.exit(1)

    # 构建 payload
    payload = build_payload(args, content)

    # Dry-run 模式
    if args.dry_run:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return

    # 构建完整 URL
    webhook_url = f"{args.url.rstrip('/')}?key={args.key}"

    if not args.quiet:
        print(f"发送消息 | 类型: {args.type} | 长度: {len(content)} 字", file=sys.stderr)
        print(f"URL: {webhook_url}", file=sys.stderr)

    # 按 RS 分隔符(\x1e)拆分多批消息
    parts = [p.strip() for p in content.split("\x1e") if p.strip()]

    if not args.quiet:
        print(f"发送消息 | 类型: {args.type} | 共 {len(parts)} 批 | URL: {webhook_url}", file=sys.stderr)

    total_ok = 0
    total_fail = 0

    for i, part in enumerate(parts):
        if not args.quiet and len(parts) > 1:
            print(f"第 {i+1}/{len(parts)} 批 ({len(part)} 字)...", file=sys.stderr)

        payload = build_payload(args, part)

        # Dry-run 模式
        if args.dry_run:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            continue

        try:
            resp = requests.post(
                webhook_url,
                json=payload,
                timeout=15,
                headers={"Content-Type": "application/json"},
            )
            result = resp.json()
            if resp.status_code == 200 and result.get("result") == "ok":
                total_ok += 1
            else:
                total_fail += 1
                print(f"第 {i+1} 批发送失败: HTTP {resp.status_code} {resp.text[:200]}", file=sys.stderr)
        except Exception as e:
            total_fail += 1
            print(f"第 {i+1} 批发送异常: {e}", file=sys.stderr)

        # 批次间稍作延迟，防止频率限制
        if i < len(parts) - 1:
            import time
            time.sleep(1)

    if not args.dry_run:
        if total_fail == 0:
            print(json.dumps({"success": True, "total": total_ok}))
        else:
            print(json.dumps({"success": False, "ok": total_ok, "fail": total_fail}))


if __name__ == "__main__":
    main()
