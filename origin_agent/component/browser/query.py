"""BrowserQuery — 在页面中定位元素，产出可复用的元素引用（safe）。

按 CSS/XPath 选择器或子树文本定位，返回元素引用列表（含 path），
供 BrowserClick / BrowserType / BrowserPress / BrowserScroll 等交互工具使用。
工具对象通过模块级 ``TOOLSET``（``BaseToolSet``）声明；导入期只创建无连接工具对象。
"""

from __future__ import annotations

from interface.browser_system import IBrowserSystem

import logging
from typing import Any

from abstract.tools.tool import BaseTool, BaseToolSet, ToolExecution, ToolHandlerResult, tool_error, tool_result
from component.browser import _connection
from entity.constant import QUERY_MAX_RESULTS, QUERY_MAX_RESULTS_HARD
from entity.puretype import ToolDangerLevel
from system.application import Application
from system.lifecycle import requires_lifecycle_propagation

logger = logging.getLogger(__name__)

_NOT_CONNECTED: str = (
    "Browser not connected or CDP endpoint unreachable. Call BrowserConnect first; "
    "if BrowserConnect returned guidance, follow those steps before retrying."
)

_TAB_NOT_FOUND: str = (
    "Tab not found. Use BrowserListTabs to confirm existing tabs; "
    "if the target page is not listed, ask the user to open or switch to it manually, then retry."
)


def _browser_system() -> IBrowserSystem:
    return Application.current().get_system(IBrowserSystem)


async def _handle_browser_query(args: dict[str, Any]) -> dict:
    tab: str = str(args.get("tab", "")).strip()
    selector: str = str(args.get("selector", "")).strip()
    text: str = str(args.get("text", "")).strip()
    max_results: int = int(args.get("max_results", QUERY_MAX_RESULTS))

    if not tab:
        return tool_error("tab is required")
    if not selector and not text:
        return tool_error("provide 'selector' or 'text' (at least one)")
    if max_results < 1:
        max_results = 1
    if max_results > QUERY_MAX_RESULTS_HARD:
        max_results = QUERY_MAX_RESULTS_HARD

    try:
        browser = await _browser_system().get_browser()
    except Exception as exc:
        if requires_lifecycle_propagation(exc):
            raise
        logger.warning("BrowserQuery: reconnect failed: %s: %s", type(exc).__name__, exc)
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


_BROWSER_QUERY_SCHEMA = {
    # 在页面中定位元素，返回元素引用列表（含 path），供 BrowserClick / BrowserType 等交互工具使用。
    #
    # ## 前置条件
    # - 已成功调用 BrowserConnect；目标标签页存在。
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
    # path 可直接作为 BrowserClick / BrowserType 等交互工具的 path 参数。
    #
    # ## 何时使用
    # - 需要精确定位页面元素（按钮、链接、输入框、内容区块）时。
    # - BrowserClick / BrowserType 等交互操作之前先确认目标元素存在及其 path。
    # - 深嵌套页面优先用语义 selector（main/article/section）直达正文容器，
    #   避免从 body 逐层下钻。
    #
    # ## 副作用/注意
    # - 只读查询，不修改浏览器状态；正常模式下无需审批。
    "description": """Locates elements in the page and returns reusable element references (including path) for BrowserClick / BrowserType / BrowserPress / BrowserScroll.

## Prerequisites
- BrowserConnect must have succeeded; the target tab must exist.

## Effect
- `selector`: CSS selector or XPath (auto-detected when starting with `/`).
- `text`: matches by subtree visible text (including descendants, case-insensitive); returns the deepest matching elements (an element is skipped if any descendant already matched) to avoid parent-child duplicates.
- When both `selector` and `text` are given they are combined (locate first, then filter by text).
- max_results defaults to 50 (hard cap 200); when exceeded, truncated=true — narrow the query instead.

## Returns
```json
{"matches": [{"path": "0.2.1", "tag": "a", "id": "", "class": "", "text": "...", "child_count": 0, "leaf": true}], "total": 1, "truncated": false}
```
The path can be passed directly as the path argument of BrowserClick / BrowserType / BrowserPress / BrowserScroll.

## When to Use
- Pinpoint page elements (buttons, links, inputs, content blocks).
- Confirm a target element exists and get its path before BrowserClick / BrowserType / BrowserPress / BrowserScroll.
- On deeply nested pages, prefer semantic selectors (main/article/section) to jump straight to the content container instead of drilling from body.

## Side Effects / Notes
- Read-only; does not modify browser state; no approval needed in normal mode.""",
    "parameters": {
        "type": "object",
        "properties": {
            "tab": {
                "type": "string",
                # 目标标签页：BrowserListTabs 的 0 基 index（如 "0"），或 url/title 的子串。
                "description": "Target tab: the 0-based index from BrowserListTabs (e.g. \"0\"), or a substring of its URL or title.",
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
}


class BrowserQueryTool(BaseTool):
    """在页面中定位元素并产出可复用的元素引用。"""

    def __init__(self) -> None:
        super().__init__(
            name="BrowserQuery",
            toolset="browser",
            schema=_BROWSER_QUERY_SCHEMA,
            is_async=True,
            check_fn=_connection.playwright_available,
            danger_level=ToolDangerLevel.safe,
        )

    async def handle(self, execution: ToolExecution) -> ToolHandlerResult:
        return ToolHandlerResult(await _handle_browser_query(execution.arguments))


TOOLSET = BaseToolSet(name="browser", tools=(BrowserQueryTool(),))
