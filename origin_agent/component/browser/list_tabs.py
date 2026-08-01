"""browser_list_tabs — 枚举已接管浏览器中的全部标签页（write）。

模块导入时通过 ``registry.register()`` 注册。
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


async def _handle_browser_list_tabs(args: dict[str, Any]) -> dict:
    try:
        browser = await _connection.get_browser()
    except Exception as exc:
        logger.warning("browser_list_tabs: reconnect failed: %s: %s", type(exc).__name__, exc)
        return tool_error(_NOT_CONNECTED)

    tabs: list[dict[str, Any]] = []
    for idx, page in enumerate(_connection.all_pages(browser)):
        try:
            title = await page.title()
        except Exception:
            title = ""  # 页面可能正在关闭，降级为空串
        tabs.append({"index": idx, "title": title or "", "url": page.url or ""})

    return tool_result(
        tabs=tabs,
        total=len(tabs),
        endpoint=_connection.current_endpoint(),
    )


registry.register(
    name="browser_list_tabs",
    toolset="browser",
    schema={
        # 枚举已接管浏览器中的全部标签页，返回 index/title/url 列表。
        # index 可直接作为 browser_read_page / browser_screenshot 的 tab 参数。
        #
        # ## 前置条件
        # - 已成功调用 browser_connect（或连接仍可自动重建）。
        #
        # ## 调用效果
        # 展平所有浏览器窗口的标签页，按枚举顺序编号（0 基）。
        #
        # ## 返回
        # ```json
        # {"tabs": [{"index": 0, "title": "...", "url": "..."}], "total": 3, "endpoint": "http://localhost:9222"}
        # ```
        #
        # ## 何时使用
        # - 读取页面前先确认目标标签页是否存在及其 index。
        # - 用户描述模糊时，用 title/url 列表定位目标页面。
        #
        # ## 副作用/注意
        # - 只读操作，不修改浏览器状态。
        "description": """Lists all tabs in the connected browser with index, title, and URL. The index can be passed directly as the `tab` argument of browser_read_page / browser_screenshot.

## Prerequisites
- browser_connect must have succeeded (or the connection can still be re-established automatically).

## Effect
Flattens tabs across all browser windows, numbered 0-based in enumeration order.

## Returns
```json
{"tabs": [{"index": 0, "title": "...", "url": "..."}], "total": 3, "endpoint": "http://localhost:9222"}
```

## When to Use
- Confirm the target tab exists and get its index before reading a page.
- Locate the target page by title/URL when the user's description is vague.

## Side Effects / Notes
- Read-only; does not modify browser state.""",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    handler=_handle_browser_list_tabs,
    check_fn=_connection.playwright_available,
    is_async=True,
    emoji="📑",
    danger_level=ToolDangerLevel.write,
)