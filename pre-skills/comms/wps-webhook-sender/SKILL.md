---
name: wps-webhook-sender
description: "WPS  Webhook 机器人消息推送工具。支持发送 Markdown、纯文本、链接卡片三种消息类型。Webhook URL 作为参数传入，不硬编码在脚本中。适用于将 AI 处理结果推送到 WPS 群聊/机器人场景，如新闻日报推送、告警通知、定时报告等。"
version: 1.0.0
author: Hermes Agent
category: comms
tags:
  - wps
  - webhook
  - message
  - notification
  - bot
  - markdown
  - python
---

# wps-webhook-sender

WPS Webhook 机器人消息推送工具。支持发送 **Markdown**、**纯文本**、**链接卡片** 三种消息类型到 WPS 群聊机器人。

## 工作原理

WPS Webhook 机器人通过 HTTP POST 接收 JSON 消息。每条消息需指定 `msgtype`（消息类型）和对应的内容字段。

## 安装

```bash
# 安装依赖（仅需 requests）
pip install requests
```

## 快速开始

```bash
# 发送 Markdown 消息
python wps_send.py --key YOUR_KEY --type markdown --text "# Hello\n这是 **Markdown** 消息"

# 发送纯文本
python wps_send.py --key YOUR_KEY --type text --text "你好，这是一条纯文本消息"

# 发送链接卡片
python wps_send.py --key YOUR_KEY --type link \
  --title "新闻标题" --text "内容摘要" --url "https://example.com"

# 从文件读取内容（适合长消息）
python wps_send.py --key YOUR_KEY --type markdown --file message.md

# 通过管道传入内容
cat report.md | python wps_send.py --key YOUR_KEY --type markdown
```

## 命令行参数

| 参数 | 缩写 | 默认值 | 说明 |
|------|------|--------|------|
| `--key` | `-k` | **必填** | Webhook 的 key 参数值 |
| `--url` | `-u` | `https://xz.wps.cn/api/v1/webhook/send` | Webhook 基础 URL |
| `--type` | `-t` | `markdown` | 消息类型：`markdown`、`text`、`link` |
| `--text` | | `""` | 消息正文（Markdown 或纯文本） |
| `--title` | | `""` | 链接卡片标题（仅 link 类型） |
| `--url-link` | | `""` | 链接卡片跳转地址（仅 link 类型） |
| `--btn` | | `"查看详情"` | 链接卡片按钮文字（仅 link 类型） |
| `--file` | `-f` | `""` | 从文件读取消息内容 |
| `--quiet` | `-q` | `False` | 安静模式，只输出结果 |
| `--dry-run` | | `False` | 仅打印消息内容，不实际发送 |

## 消息类型详解

### Markdown 消息（推荐）

```bash
python wps_send.py --key YOUR_KEY --type markdown --text "
# 今日新闻
> 2026-06-09 | 共 41 条

## 国际频道
**1. 标题**
> 概述内容
[阅读原文](https://...)
"
```

发送的 JSON 结构：
```json
{
  "msgtype": "markdown",
  "markdown": {
    "text": "# 今日新闻\n..."
  }
}
```

### 纯文本消息

```bash
python wps_send.py --key YOUR_KEY --type text --text "你好，世界"
```

### 链接卡片消息

```bash
python wps_send.py --key YOUR_KEY --type link \
  --title "新闻标题" \
  --text "这是一段摘要内容" \
  --url "https://example.com/article/123" \
  --btn "查看原文"
```

## 字数限制

WPS Webhook 对消息体有字数限制，建议单条消息不超过 **4000 字**。超长消息请自行分多条发送。

## 注意事项

- `--key` 参数就是 Webhook URL 中 `key=` 后面的值，如 `https://xz.wps.cn/api/v1/webhook/send?key=xxx` 中的 `xxx`
- Markdown 支持：标题、加粗、斜体、链接、列表、引用、代码块等基本语法
- 不支持图片直接显示，但支持 Markdown 图片链接
- 脚本使用 `sys.stdin.read()` 读取管道输入，因此管道模式时 `--text` 和 `--file` 会被忽略
- 网络要求：需要能够访问 `xz.wps.cn` 域名

## 脚本位置

本 skill 包含的脚本位于 `scripts/wps_send.py`，可通过 `python scripts/wps_send.py` 直接运行。