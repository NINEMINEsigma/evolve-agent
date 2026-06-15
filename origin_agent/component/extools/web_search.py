"""Web search tool — searches the web and returns a list of results.

Supports multiple search engines with automatic fallback:
1. DuckDuckGo Lite (primary) — no API key required
2. Bing (fallback) — accessible in China, clean HTML structure

Module-import-time registration via ``registry.register()``.

v3 当前运行版本 (2026-05-28):
  - DDG 超时: 8s (快速失败)
  - Bing 超时: 15s
  - 自动降级: DDG→Bing
"""

from __future__ import annotations

import logging
import re
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Tuple

from abstract.tools.registry import registry, tool_error, tool_result

logger = logging.getLogger(__name__)

_USER_AGENT: str = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)
_DDG_TIMEOUT: int = 8   # DDG often blocked in China — fail fast
_BING_TIMEOUT: int = 15  # Bing is responsive in China
_MAX_RESULTS_HARD: int = 20

# DuckDuckGo Lite — clean, minimal HTML table, easy to parse
_DDG_LITE_URL: str = "https://lite.duckduckgo.com/lite/"

# Bing search — accessible in China, clean HTML structure
_BING_SEARCH_URL: str = "https://cn.bing.com/search"


# ---------------------------------------------------------------------------
# DuckDuckGo Parser
# ---------------------------------------------------------------------------


def _parse_ddg_lite(html: str, max_results: int) -> list[dict[str, str]]:
    """Extract title/url/snippet tuples from DuckDuckGo Lite HTML.

    The lite endpoint returns results in a flat HTML table where each result
    spans two rows: one for the link, one for the snippet.
    """
    results: list[dict[str, str]] = []

    # 1) Extract ranked links inside <a rel="nofollow" href="...">
    links: list[tuple[str, str]] = re.findall(
        r'<a[^>]*href="(https?://[^\"]+)\"[^>]*rel=\"nofollow\"[^>]*>(.*?)</a>',
        html,
        re.IGNORECASE,
    )

    # 2) Extract snippets from <td class="result-snippet">...</td>
    snippets: list[str] = re.findall(
        r'<td[^>]*class="result-snippet"[^>]*>(.*?)</td>',
        html,
        re.IGNORECASE | re.DOTALL,
    )

    for i, (url, raw_title) in enumerate(links[:max_results]):
        title: str = re.sub(r"<[^>]+>", "", raw_title).strip()
        snippet: str = ""
        if i < len(snippets):
            snippet = re.sub(r"<[^>]+>", "", snippets[i]).strip()

        results.append({
            "title": title or "(no title)",
            "url": url,
            "snippet": snippet or "(no snippet)",
        })

    return results


# ---------------------------------------------------------------------------
# Bing Parser
# ---------------------------------------------------------------------------


def _parse_bing(html: str, max_results: int) -> list[dict[str, str]]:
    """Extract title/url/snippet tuples from Bing search HTML.

    Bing uses a clean structure:
    - Results in <li class="b_algo"> blocks
    - Titles in <h2><a href="..." title="...">text</a></h2>
    - Snippets in <p> tags within the block
    """
    results: list[dict[str, str]] = []

    # Extract result blocks
    blocks: list[str] = re.findall(
        r'<li[^>]*class="b_algo"[^>]*>(.*?)</li>',
        html,
        re.IGNORECASE | re.DOTALL,
    )

    for block in blocks[:max_results]:
        # Extract title link
        link_match = re.search(
            r'<h2[^>]*>.*?<a[^>]*href="([^"]+)"[^>]*>(.*?)</a>',
            block,
            re.IGNORECASE | re.DOTALL,
        )
        if not link_match:
            continue

        url: str = link_match.group(1)
        raw_title: str = link_match.group(2)
        title: str = re.sub(r"<[^>]+>", "", raw_title).strip()

        # Extract snippet — usually in the first <p> after the heading
        snippet: str = ""
        # Try b_caption first (contains description)
        caption_match = re.search(
            r'<p[^>]*class="b_caption"[^>]*>(.*?)</p>',
            block,
            re.IGNORECASE | re.DOTALL,
        )
        if caption_match:
            snippet = re.sub(r"<[^>]+>", "", caption_match.group(1)).strip()
        else:
            # Fallback: first <p> tag with text content after h2
            p_match = re.search(
                r'<p[^>]*>(.*?)</p>',
                block,
                re.IGNORECASE | re.DOTALL,
            )
            if p_match:
                snippet = re.sub(r"<[^>]+>", "", p_match.group(1)).strip()

        results.append({
            "title": title or "(no title)",
            "url": url,
            "snippet": snippet or "(no snippet)",
        })

    return results


# ---------------------------------------------------------------------------
# Search Engine Adapters
# ---------------------------------------------------------------------------


def _search_ddg(query: str, max_results: int) -> Tuple[list[dict[str, str]] | None, str | None]:
    """Try searching via DuckDuckGo. Returns (results, error)."""
    encoded: str = urllib.parse.quote(query, safe="")
    search_url: str = f"{_DDG_LITE_URL}?q={encoded}"

    req = urllib.request.Request(
        search_url,
        headers={"User-Agent": _USER_AGENT},
        method="GET",
    )

    try:
        with urllib.request.urlopen(req, timeout=_DDG_TIMEOUT) as resp:
            html: str = resp.read().decode("utf-8", errors="replace")
        results = _parse_ddg_lite(html, max_results)
        return results, None
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"


def _search_bing(query: str, max_results: int) -> Tuple[list[dict[str, str]] | None, str | None]:
    """Try searching via Bing. Returns (results, error)."""
    encoded: str = urllib.parse.quote(query, safe="")
    search_url: str = f"{_BING_SEARCH_URL}?q={encoded}"

    req = urllib.request.Request(
        search_url,
        headers={
            "User-Agent": _USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        },
        method="GET",
    )

    try:
        with urllib.request.urlopen(req, timeout=_BING_TIMEOUT) as resp:
            html: str = resp.read().decode("utf-8", errors="replace")
        results = _parse_bing(html, max_results)
        return results, None
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------


def _handle_web_search(args: dict[str, Any]) -> dict:
    query: str = str(args.get("query", "")).strip()
    max_results: int = int(args.get("max_results", 5))

    if not query:
        return tool_error("query is required")

    if max_results < 1:
        max_results = 5
    if max_results > _MAX_RESULTS_HARD:
        max_results = _MAX_RESULTS_HARD

    # Try DuckDuckGo first
    results, ddg_error = _search_ddg(query, max_results)

    if results is not None:
        return tool_result(
            query=query,
            results=results,
            total=len(results),
            engine="duckduckgo",
        )

    logger.warning("DuckDuckGo search failed (%s), falling back to Bing", ddg_error)

    # Fallback to Bing
    results, bing_error = _search_bing(query, max_results)

    if results is not None:
        return tool_result(
            query=query,
            results=results,
            total=len(results),
            engine="bing",
            fallback=True,
        )

    # Both engines failed
    return tool_error(
        f"All search engines failed. DDG: {ddg_error} | Bing: {bing_error}",
        query=query,
    )


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

registry.register(
    name="web_search",
    toolset="extools",
    schema={
        "description": (
            "Searches the web using DuckDuckGo (primary) or Bing (fallback) "
            "and returns a list of results with title, URL, and snippet for each. "
            "Automatically falls back to Bing if DuckDuckGo is unavailable. "
            "Use this tool when you need up-to-date information, documentation, "
            "or any knowledge not available in your training data."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The search query.",
                },
                "max_results": {
                    "type": "integer",
                    "description": "Maximum number of results (default 5, max 20).",
                    "default": 5,
                },
            },
            "required": ["query"],
        },
    },
    handler=_handle_web_search,
    emoji="🔍",
)
