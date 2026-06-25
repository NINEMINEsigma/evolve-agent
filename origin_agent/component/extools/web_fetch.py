"""Web fetch tool — fetches a URL and returns its content as plain text.

Module-import-time registration via ``registry.register()``.
"""

from __future__ import annotations

import logging
import urllib.error
import urllib.request
from html.parser import HTMLParser
from typing import Any

from abstract.tools.registry import registry, tool_error, tool_result
from component.tools.filesystem import _s as _get_sandbox
from entity.constant import DEFAULT_USER_AGENT, TOOL_RESULT_PREVIEW_CHARS, WEB_FETCH_MAX_CHARS

logger = logging.getLogger(__name__)
_FETCH_TIMEOUT: int = 15


# ---------------------------------------------------------------------------
# Simple HTML → plain text converter
# ---------------------------------------------------------------------------

class _HTMLToTextParser(HTMLParser):
    """Strip tags, skip script/style content, insert newlines at block breaks."""

    def __init__(self) -> None:
        super().__init__()
        self._parts: list[str] = []
        self._skip: bool = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in ("script", "style", "noscript"):
            self._skip = True

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style", "noscript"):
            self._skip = False
            return
        if tag in ("p", "br", "div", "h1", "h2", "h3", "h4", "h5", "h6", "li", "tr", "blockquote"):
            self._parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._skip:
            text = data.strip()
            if text:
                self._parts.append(text)

    def get_text(self) -> str:
        return "\n".join(filter(None, self._parts))


def _strip_html(html: str) -> str:
    parser = _HTMLToTextParser()
    parser.feed(html)
    return parser.get_text()


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------

def _handle_web_fetch(args: dict[str, Any]) -> dict:
    url: str = str(args.get("url", "")).strip()

    if not url:
        return tool_error("url is required")

    if not url.startswith(("http://", "https://")):
        return tool_error("url must start with http:// or https://")

    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": DEFAULT_USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
        },
        method="GET",
    )

    try:
        with urllib.request.urlopen(req, timeout=_FETCH_TIMEOUT) as resp:
            content_type: str = (resp.headers.get("Content-Type") or "").split(";")[0].strip().lower()
            raw: bytes = resp.read()

            # best-effort encoding detection
            charset: str = "utf-8"
            ct_header: str = resp.headers.get("Content-Type") or ""
            if "charset=" in ct_header:
                charset = ct_header.split("charset=")[-1].split(";")[0].strip()

            text: str = raw.decode(charset, errors="replace")

            if content_type == "text/html":
                text = _strip_html(text)

            oversized: bool = len(text) > WEB_FETCH_MAX_CHARS
            if oversized:
                import uuid
                save_path = f"ws:logs/web_fetch/{uuid.uuid4().hex[:12]}.txt"
                _get_sandbox().write(save_path, text)
                preview = text[:TOOL_RESULT_PREVIEW_CHARS]
                return tool_result(
                    preview=preview,
                    url=url,
                    content_type=content_type,
                    status=resp.status,
                    saved_to=save_path,
                    total_chars=len(text),
                )

            return tool_result(
                content=text,
                url=url,
                content_type=content_type,
                status=resp.status,
            )

    except urllib.error.HTTPError as e:
        return tool_error(f"HTTP {e.code}: {e.reason}", url=url, status=e.code)
    except urllib.error.URLError as e:
        return tool_error(f"URL error: {e.reason}", url=url)
    except Exception as e:
        return tool_error(f"Fetch failed: {type(e).__name__}: {e}", url=url)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

registry.register(
    name="web_fetch",
    toolset="extools",
    schema={
        # 获取指定 URL 的内容并以纯文本形式返回。
        # HTML 页面会自动转换为文本（去除 script、style、noscript 标签）。
        # 内容超过 {WEB_FETCH_MAX_CHARS} 字符时，完整内容保存到 ws:logs/web_fetch/ 文件，
        # 仅返回前 {TOOL_RESULT_PREVIEW_CHARS} 字符的预览和文件路径。
        #
        # ## 前置条件
        # - url 必须以 http:// 或 https:// 开头。
        # - 目标 URL 必须可达（网络连接正常）。
        #
        # ## 调用效果
        # 发送 GET 请求获取 URL 内容。HTML 自动转纯文本，其他类型直接返回。
        # 内容超过 {WEB_FETCH_MAX_CHARS} 字符时，完整内容写入 ws:logs/web_fetch/{{uuid}}.txt，
        # 返回结果中包含 saved_to（文件路径）和 preview（前 {TOOL_RESULT_PREVIEW_CHARS} 字符）。
        # 未超限时直接返回完整 content。
        # 超时时间为 15 秒。
        #
        # ## 返回
        # 未超限时：
        # ```json
        # {"content": "...", "url": "https://example.com", "content_type": "text/html", "status": 200}
        # ```
        # 超限时：
        # ```json
        # {"preview": "...", "url": "https://example.com", "content_type": "text/html", "status": 200, "saved_to": "ws:logs/web_fetch/abc123.txt", "total_chars": 60000}
        # ```
        #
        # ## 何时使用
        # - 读取网页内容、API 响应、在线文档。
        # - 在 web_search 获取 URL 后进一步获取页面详情。
        #
        # ## 副作用/注意
        # - 依赖外部网络服务，可能因网络或反爬策略失败。
        # - HTML 转文本是尽力而为，复杂页面可能格式混乱。
        # - 超大内容自动保存为文件，需用 read_file 读取完整内容。
        "description": f"""Fetches a URL and returns its content as plain text. HTML pages are automatically converted to text (scripts and styles stripped). Useful for reading web pages, API responses, documentation, etc. Content exceeding {WEB_FETCH_MAX_CHARS} characters is saved to a file and a preview is returned.

## Prerequisites
- The URL must start with http:// or https://.
- The target URL must be reachable.

## Effect
Sends a GET request to fetch the URL content. HTML is automatically converted to plain text; other types are returned as-is. If content exceeds {WEB_FETCH_MAX_CHARS} characters, the full content is saved to ws:logs/web_fetch/{{uuid}}.txt and the result includes `saved_to` (file path) and `preview` (first {TOOL_RESULT_PREVIEW_CHARS} characters). Otherwise the full `content` is returned directly. Timeout is 15 seconds.

## Returns
Normal:
```json
{{"content": "...", "url": "https://example.com", "content_type": "text/html", "status": 200}}
```
Oversized:
```json
{{"preview": "...", "url": "https://example.com", "content_type": "text/html", "status": 200, "saved_to": "ws:logs/web_fetch/abc123.txt", "total_chars": 60000}}
```

## When to Use
- Read web page content, API responses, or online documentation.
- Fetch page details after obtaining a URL from web_search.

## Side Effects / Notes
- Depends on external network services; may fail due to network issues or anti-bot measures.
- HTML-to-text conversion is best-effort; complex pages may have poor formatting.
- Oversized content is automatically saved as a file; use read_file to retrieve the full content.""",
        "parameters": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    # 要获取的 URL。必须以 http:// 或 https:// 开头。
                    "description": "The URL to fetch. Must start with http:// or https://.",
                },
            },
            "required": ["url"],
        },
    },
    handler=_handle_web_fetch,
    emoji="🌐",
)