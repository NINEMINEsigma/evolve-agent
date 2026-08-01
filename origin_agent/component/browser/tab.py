"""tab 工具组 — 标签页生命周期管理（write）。

browser_open_tab / browser_activate_tab / browser_close_tab。
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

_TAB_NOT_FOUND: str = (
    "未找到匹配的标签页。请先用 browser_list_tabs 确认现有标签页。"
)


async def _handle_browser_open_tab(args: dict[str, Any]) -> dict:
    url: str = str(args.get("url", "")).strip()
    if not url:
        return tool_error("url is required")

    try:
        browser = await _connection.get_browser()
    except Exception as exc:
        logger.warning("browser_open_tab: reconnect failed: %s: %s", type(exc).__name__, exc)
        return tool_error(_NOT_CONNECTED)

    try:
        if browser.contexts:
            context = browser.contexts[0]
        else:
            # connect_over_cdp 下一般已有 context；理论空列表时回退 new_context
            context = await browser.new_context()
        page = await context.new_page()
        await page.goto(url, wait_until="networkidle", timeout=30000)
    except Exception as exc:
        logger.warning("browser_open_tab failed: %s", exc)
        return tool_error(f"open tab failed: {type(exc).__name__}: {exc}", url=url)

    try:
        title = await page.title()
    except Exception:
        title = ""

    return tool_result(opened=True, url=page.url or "", tab_title=title)


async def _handle_browser_activate_tab(args: dict[str, Any]) -> dict:
    tab: str = str(args.get("tab", "")).strip()
    if not tab:
        return tool_error("tab is required")
    try:
        browser = await _connection.get_browser()
    except Exception as exc:
        logger.warning("browser_activate_tab: reconnect failed: %s: %s", type(exc).__name__, exc)
        return tool_error(_NOT_CONNECTED)
    page = await _connection.find_page(browser, tab)
    if page is None:
        return tool_error(_TAB_NOT_FOUND, tab=tab)

    try:
        await page.bring_to_front()
    except Exception as exc:
        return tool_error(f"activate failed: {type(exc).__name__}: {exc}")

    try:
        title = await page.title()
    except Exception:
        title = ""

    return tool_result(activated=True, url=page.url or "", tab_title=title)


async def _handle_browser_close_tab(args: dict[str, Any]) -> dict:
    tab: str = str(args.get("tab", "")).strip()
    if not tab:
        return tool_error("tab is required")
    try:
        browser = await _connection.get_browser()
    except Exception as exc:
        logger.warning("browser_close_tab: reconnect failed: %s: %s", type(exc).__name__, exc)
        return tool_error(_NOT_CONNECTED)
    page = await _connection.find_page(browser, tab)
    if page is None:
        return tool_error(_TAB_NOT_FOUND, tab=tab)

    try:
        await page.close()
    except Exception as exc:
        return tool_error(f"close failed: {type(exc).__name__}: {exc}")

    return tool_result(closed=True, tab=tab)


# ---------------------------------------------------------------------------
# 注册
# ---------------------------------------------------------------------------

registry.register(
    name="browser_open_tab",
    toolset="browser",
    schema={
        # 在浏览器中新开标签页并导航到指定 URL。
        #
        # ## 行为规范
        # - 新开标签是显式动作：打开前向用户说明目标 URL。
        # - 若目标可能重定向到登录页，先向用户说明并请其确认。
        #
        # ## 返回
        # ```json
        # {"opened": true, "url": "https://...", "tab_title": "..."}
        # ```
        # 新标签的 index 可随后用 browser_list_tabs 查询。
        "description": """Opens a new tab in the browser and navigates to the given URL.

## Behavior (user-confirmation norms)
- Opening a tab is an explicit action: state the target URL to the user before opening.
- If the target may redirect to a login page, explain this to the user and ask them to confirm first.

## Returns
```json
{"opened": true, "url": "https://...", "tab_title": "..."}
```
The new tab's index can be queried afterwards with browser_list_tabs.""",
        "parameters": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    # 新标签页要打开的 URL。
                    "description": "The URL to open in the new tab.",
                },
            },
            "required": ["url"],
        },
    },
    handler=_handle_browser_open_tab,
    check_fn=_connection.playwright_available,
    is_async=True,
    emoji="➕",
    danger_level=ToolDangerLevel.readonly,
)

registry.register(
    name="browser_activate_tab",
    toolset="browser",
    schema={
        # 激活/切换到指定标签页（bring to front），不改变导航状态。
        "description": """Brings the target tab to the front (activates it) without changing its navigation state.""",
        "parameters": {
            "type": "object",
            "properties": {
                "tab": {
                    "type": "string",
                    # 目标标签页：browser_list_tabs 的 0 基 index（如 "0"），或 url/title 的子串。
                    "description": "Target tab: the 0-based index from browser_list_tabs, or a substring of its URL or title.",
                },
            },
            "required": ["tab"],
        },
    },
    handler=_handle_browser_activate_tab,
    check_fn=_connection.playwright_available,
    is_async=True,
    emoji="🪟",
    danger_level=ToolDangerLevel.readonly,
)

registry.register(
    name="browser_close_tab",
    toolset="browser",
    schema={
        # 关闭指定标签页。
        #
        # ## 行为规范
        # - 关闭标签是显式动作：执行前向用户说明要关闭哪个标签页（url/title）。
        "description": """Closes the target tab.

## Behavior (user-confirmation norms)
- Closing a tab is an explicit action: tell the user which tab (url/title) is being closed before executing.""",
        "parameters": {
            "type": "object",
            "properties": {
                "tab": {
                    "type": "string",
                    # 目标标签页：browser_list_tabs 的 0 基 index（如 "0"），或 url/title 的子串。
                    "description": "Target tab: the 0-based index from browser_list_tabs, or a substring of its URL or title.",
                },
            },
            "required": ["tab"],
        },
    },
    handler=_handle_browser_close_tab,
    check_fn=_connection.playwright_available,
    is_async=True,
    emoji="🗑️",
    danger_level=ToolDangerLevel.readonly,
)