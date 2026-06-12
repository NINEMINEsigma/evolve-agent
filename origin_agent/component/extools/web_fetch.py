"""Web fetch tool — fetches a URL and returns its content as plain text.

Module-import-time registration via ``registry.register()``.
"""

from __future__ import annotations

import logging
import urllib.error
import urllib.request
from html.parser import HTMLParser
from typing import Any, Dict

from abstract.tools.registry import registry, tool_error, tool_result

logger = logging.getLogger(__name__)

_USER_AGENT: str = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)
_FETCH_TIMEOUT: int = 15
_MAX_CHARS: int = 50000


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

def _handle_web_fetch(args: Dict[str, Any]) -> dict:
    url: str = str(args.get("url", "")).strip()

    if not url:
        return tool_error("url is required")

    if not url.startswith(("http://", "https://")):
        return tool_error("url must start with http:// or https://")

    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": _USER_AGENT,
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

            truncated: bool = len(text) > _MAX_CHARS
            if truncated:
                text = text[:_MAX_CHARS] + "\n\n[... truncated ...]"

            return tool_result(
                content=text,
                url=url,
                content_type=content_type,
                status=resp.status,
                truncated=truncated,
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
        "description": (
            "Fetches a URL and returns its content as plain text. "
            "HTML pages are automatically converted to text (scripts and styles stripped). "
            "Useful for reading web pages, API responses, documentation, etc. "
            "Content is truncated at 50 000 characters."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "The URL to fetch (must start with http:// or https://).",
                },
            },
            "required": ["url"],
        },
    },
    handler=_handle_web_fetch,
    emoji="🌐",
)