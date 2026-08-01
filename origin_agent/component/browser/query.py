"""browser_query — 在页面中定位元素，产出可复用的元素引用（readonly）。

按 CSS/XPath 选择器或子树文本定位，返回元素引用列表（含 path），
供 browser_read 消费。模块导入时通过 ``registry.register()`` 注册。
"""

from __future__ import annotations

import logging
from typing import Any

from abstract.tools.registry import registry, tool_error, tool_result
from component.browser import _connection
from entity.puretype import ToolDangerLevel

logger = logging.getLogger(__name__)

_NOT_CONNECTED: str = (
    "浏览器未连接或 CDP 端点不可达。请先调用 browser_connect；"
    "若 connect 曾返回指引，请先按指引让用户完成操作。"
)

_TAB_NOT_FOUND: str = (
    "未找到匹配的标签页。请先用 browser_list_tabs 确认现有标签页；"
    "若目标页面未在其中，请用户在浏览器中手动打开或切换到目标页面后重试。"
)


async def _handle_browser_query(args: dict[str, Any]) -> dict:
    tab: str = str(args.get("tab", "")).strip()
    selector: str = str(args.get("selector", "")).strip()
    text: str = str(args.get("text", "")).strip()
    max_results: int = int(args.get("max_results", _connection.QUERY_MAX_RESULTS))

    if not tab:
        return tool_error("tab is required")
    if not selector and not text:
        return tool_error("provide 'selector' or 'text' (at least one)")
    if max_results < 1:
        max_results = 1
    if max_results > _connection.QUERY_MAX_RESULTS_HARD:
        max_results = _connection.QUERY_MAX_RESULTS_HARD

    try:
        browser = await _connection.get_browser()
    except Exception as exc:
        logger.warning("browser_query: reconnect failed: %s: %s", type(exc).__name__, exc)
        return tool_error(_NOT_CONNECTED)

    page = await _connection.find_page(browser, tab)
    if page is None:
        return tool_error(_TAB_NOT_FOUND, tab=tab)

    if selector and text:
        # 交集：selector 定位后按子树文本过滤
        result = await _connection.dom_query_selector(page, selector, max_results, filter_text=text)
    elif selector:
        result = await _connection.dom_query_selector(page, selector, max_results)
    else:
        result = await _connection.dom_query_text(page, text, max_results)

    if "error" in result:
        return tool_error(result["error"], tab=tab)

    try:
        title = await page.title()
    except Exception:
        title = ""

    return tool_result(
        matches=result["matches"],
        total=result["total"],
        truncated=result["truncated"],
        tab_title=title,
        tab_url=page.url or "",
    )


registry.register(
    name="browser_query",
    toolset="browser",
    schema={
        # 在页面中定位元素，返回元素引用列表（含 path），供 browser_read 使用。
        #
        # ## 前置条件
        # - 已成功调用 browser_connect；目标标签页存在。
        #
        # ## 调用效果
        # - selector：CSS 选择器或 XPath（以 / 开头自动识别）。
        # - text：按子树可见文本包含匹配（含后代，大小写不敏感），返回"最深匹配"元素
        #   （某元素匹配时不再返回其内部的后代匹配），避免父子重复。
        # - selector 与 text 同时提供时取交集（先定位再按文本过滤）。
        # - max_results 默认 50，硬上限 200；超出时 truncated=true，请收窄条件。
        #
        # ## 返回
        # ```json
        # {"matches": [{"path": "0.2.1", "tag": "a", "id": "", "class": "", "text": "...", "child_count": 0, "leaf": true}], "total": 1, "truncated": false}
        # ```
        # path 可直接作为 browser_read 的 path 参数。
        #
        # ## 何时使用
        # - 需要精确定位页面元素（按钮、链接、输入框、内容区块）时。
        # - browser_read 之前先确认目标元素存在及其 path。
        # - 深嵌套页面优先用语义 selector（main/article/section）直达正文容器，
        #   再配合 browser_read(mode="text") 通读，避免从 body 逐层下钻。
        #
        # ## 副作用/注意
        # - 只读查询，不修改浏览器状态；正常模式下无需审批。
        "description": """Locates elements in the page and returns reusable element references (including path) for browser_read.

## Prerequisites
- browser_connect must have succeeded; the target tab must exist.

## Effect
- `selector`: CSS selector or XPath (auto-detected when starting with `/`).
- `text`: matches by subtree visible text (including descendants, case-insensitive); returns the deepest matching elements (an element is skipped if any descendant already matched) to avoid parent-child duplicates.
- When both `selector` and `text` are given they are combined (locate first, then filter by text).
- max_results defaults to 50 (hard cap 200); when exceeded, truncated=true — narrow the query instead.

## Returns
```json
{"matches": [{"path": "0.2.1", "tag": "a", "id": "", "class": "", "text": "...", "child_count": 0, "leaf": true}], "total": 1, "truncated": false}
```
The path can be passed directly as the path argument of browser_read.

## When to Use
- Pinpoint page elements (buttons, links, inputs, content blocks).
- Confirm a target element exists and get its path before browser_read.
- On deeply nested pages, prefer semantic selectors (main/article/section) to jump straight to the content container, then use browser_read(mode="text") for a fast full read instead of drilling from body.

## Side Effects / Notes
- Read-only; does not modify browser state; no approval needed in normal mode.""",
        "parameters": {
            "type": "object",
            "properties": {
                "tab": {
                    "type": "string",
                    # 目标标签页：browser_list_tabs 的 0 基 index（如 "0"），或 url/title 的子串。
                    "description": "Target tab: the 0-based index from browser_list_tabs (e.g. \"0\"), or a substring of its URL or title.",
                },
                "selector": {
                    "type": "string",
                    # CSS 选择器或 XPath（以 / 开头自动识别）。
                    "description": "CSS selector, or XPath when starting with '/'. Optional.",
                },
                "text": {
                    "type": "string",
                    # 子树可见文本包含（含后代，大小写不敏感），返回最深匹配元素。
                    "description": "Match elements whose subtree visible text contains this (descendants included, case-insensitive); returns deepest matches. Optional.",
                },
                "max_results": {
                    "type": "integer",
                    # 最大返回数（默认 50，硬上限 200）。
                    "description": "Maximum matches to return (default 50, hard cap 200).",
                    "default": 50,
                },
            },
            "required": ["tab"],
        },
    },
    handler=_handle_browser_query,
    check_fn=_connection.playwright_available,
    is_async=True,
    emoji="🔎",
    danger_level=ToolDangerLevel.readonly,
)