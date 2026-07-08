---
name: local-http-server
description: "启动本地HTTP服务器提供ws:目录文件服务，并通过iframe内嵌渲染的工作流。支持UTF-8编码、自定义端口和目录、多种MIME类型映射，配合start_background_service和iframe实现本地文件可视化"
version: 1.0.0
author: Evolve-Agent
category: utility
tags:
  - http
  - server
  - utf8
  - preview
  - iframe
  - local-server
---

# local-http-server Skill

在本地启动 HTTP 服务器提供 `ws:`（workspace）目录下的文件服务，并通过 iframe 内嵌渲染到消息气泡中的完整工作流。

## 适用场景

- 需要把工作区中的 HTML / 图片 / 文本 / Markdown 等文件在消息气泡里可视化展示
- 需要预览生成的前端页面、图片、报告等
- 需要向主人展示工作区中的文件内容（含中文）

## 工作流

### 第一步：启动后台 HTTP 服务

使用 `start_background_service` 启动自定义的 UTF-8 HTTP 服务器：

```python
start_background_service(
    command=["python", "scripts/utf8-server.py", "<PORT>", "<DIR>"],
    reason="启动本地HTTP服务器提供文件服务用于内嵌渲染",
    cwd="ws:"
)
```

参数说明：
- `<PORT>`：端口号，建议使用 18000-19000 之间的端口避免冲突
- `<DIR>`：服务目录，传入 `"."` 表示 serve 当前 `ws:` 目录（`cwd` 已设为 `ws:`）
- `cwd` 必须设为 `ws:`

#### 端口选择建议
- 推荐范围：18000-19000
- 避免常见端口（如 8000, 8080, 3000, 5000 等）
- 建议使用随机高位端口，如 18765

### 第二步：验证服务

启动后建议用 `web_fetch` 验证服务是否正常响应：

```python
web_fetch(url="http://127.0.0.1:<PORT>/<文件名>")
```

预期返回 `status: 200`。

### 第三步：通过 iframe 内嵌渲染

在助手消息中直接嵌入 `<iframe>` HTML 标签：

```html
<iframe src="http://127.0.0.1:<PORT>/<文件路径>"
        style="width:100%; max-width:800px; height:400px;
               border:none; border-radius:14px; margin:6px 0;
               background:#0d0b15; box-shadow:0 2px 20px rgba(0,0,0,0.3);"
        scrolling="auto"></iframe>
```

渲染效果说明：
- 前端消息气泡支持原生 HTML 渲染，iframe 可直接嵌入
- 支持的文件类型：.html（完整网页）、.md（纯文本/Markdown）、.txt（纯文本）、.png/.jpg/.gif（图片）、.json/.csv/.log（文本格式）
- 目录路径会显示文件索引列表

### 第四步：停止服务（任务完成后）

```python
stop_background_service(task_id="<task_id>")
```

`task_id` 来自第一步返回结果中的 `task_id` 字段。

## 内置脚本：utf8-server.py

本 skill 附带了一个自定义 HTTP 服务器脚本 `scripts/utf8-server.py`。

### 功能特性

- **强制 UTF-8 编码**：所有文本类型文件都带上 `charset=utf-8`，解决中文乱码
- **完整 MIME 类型映射**：`.md` → `text/markdown`、`.py` → `text/x-python` 等 20+ 种类型
- **禁用缓存**：`Cache-Control: no-cache`，文件更新后立即生效
- **目录索引**：自动生成目录文件列表，可点击浏览

### 命令行参数

```
python utf8-server.py [PORT] [DIRECTORY]
```

- `PORT`：端口号（默认 18765）
- `DIRECTORY`：服务根目录（默认当前目录）

两者均可省略，使用默认值。

### MIME 类型映射表

| 扩展名 | Content-Type |
|--------|-------------|
| `.html` / `.htm` | text/html; charset=utf-8 |
| `.md` | text/markdown; charset=utf-8 |
| `.txt` / `.log` | text/plain; charset=utf-8 |
| `.json` | application/json; charset=utf-8 |
| `.csv` | text/csv; charset=utf-8 |
| `.py` | text/x-python; charset=utf-8 |
| `.js` | text/javascript; charset=utf-8 |
| `.css` | text/css; charset=utf-8 |
| `.xml` | text/xml; charset=utf-8 |
| `.yaml` / `.yml` | text/vnd.yaml; charset=utf-8 |
| `.toml` / `.ini` / `.cfg` / `.conf` | text/plain; charset=utf-8 |
| 其他 text/* 类型 | 自动追加 charset=utf-8 |
| 非文本类型 | 使用默认 MIME 类型 |

## 完整示例

```python
# 1. 启动服务
result = start_background_service(
    command=["python", "scripts/utf8-server.py", "18765", "."],
    reason="启动HTTP服务器展示文件",
    cwd="ws:"
)
task_id = result["task_id"]

# 2. 验证服务
web_fetch(url="http://127.0.0.1:18765/SOUL.md")

# 3. 在消息中内嵌渲染
# <iframe src="http://127.0.0.1:18765/eve-site.html" ...>

# 4. 停止服务
stop_background_service(task_id=task_id)
```

## 注意事项

- 使用 `start_background_service` 启动后，进程在后台运行，不会阻塞消息响应
- 服务默认监听 `0.0.0.0`，仅在本地网络可访问
- 如果端口被占用，更换端口号重试
- 主机关闭或后台服务超时后，服务自动终止
- 每次启动新服务前，确保旧服务已停止
- iframe 内嵌渲染依赖前端对 HTML 标签的支持