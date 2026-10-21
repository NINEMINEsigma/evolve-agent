"""tab 工具组 — 标签页生命周期管理（write）。

BrowserOpenTab / BrowserActivateTab / BrowserCloseTab。
工具对象通过模块级 ``TOOLSET``（``BaseToolSet``）声明；导入期只创建无连接工具对象。
"""

from __future__ import annotations

from interface.browser_system import IBrowserSystem

import logging
from typing import Any

from abstract.tools.tool import BaseTool, BaseToolSet, ToolExecution, ToolHandlerResult, tool_error, tool_result
from component.browser import _connection
from component.browser.system import BrowserSystem
from entity.puretype import ToolDangerLevel
from system.application import Application
from system.lifecycle import requires_lifecycle_propagation

logger = logging.getLogger(__name__)

_NOT_CONNECTED: str = (
    "Browser not connected or CDP endpoint unreachable. Call BrowserConnect first; "
    "if BrowserConnect returned guidance, follow those steps before retrying."
)

_TAB_NOT_FOUND: str = (
    "Tab not found. Use BrowserListTabs to confirm existing tabs."
)


def _browser_system() -> BrowserSystem:
    return Application.current().get_system(IBrowserSystem)


async def _handle_browser_open_tab(args: dict[str, Any]) -> dict:
    url: str = str(args.get("url", "")).strip()
    if not url:
        return tool_error("url is required")

    try:
        browser = await _browser_system().get_browser()
    except Exception as exc:
        if requires_lifecycle_propagation(exc):
            raise
        logger.warning("BrowserOpenTab: reconnect failed: %s: %s", type(exc).__name__, exc)
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
        logger.warning("BrowserOpenTab failed: %s", exc)
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
        browser = await _browser_system().get_browser()
    except Exception as exc:
        if requires_lifecycle_propagation(exc):
            raise
        logger.warning("BrowserActivateTab: reconnect failed: %s: %s", type(exc).__name__, exc)
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
        browser = await _browser_system().get_browser()
    except Exception as exc:
        if requires_lifecycle_propagation(exc):
            raise
        logger.warning("BrowserCloseTab: reconnect failed: %s: %s", type(exc).__name__, exc)
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
# 工具类与工具集
# ---------------------------------------------------------------------------

_BROWSER_OPEN_TAB_SCHEMA = {
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
    # 新标签的 index 可随后用 BrowserListTabs 查询。
    "description": """Opens a new tab in the browser and navigates to the given URL.

## Behavior (user-confirmation norms)
- Opening a tab is an explicit action: state the target URL to the user before opening.
- If the target may redirect to a login page, explain this to the user and ask them to confirm first.

## Returns
```json
{"opened": true, "url": "https://...", "tab_title": "..."}
```
The new tab's index can be queried afterwards with BrowserListTabs.""",
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
}

_BROWSER_ACTIVATE_TAB_SCHEMA = {
    # 激活/切换到指定标签页（bring to front），不改变导航状态。
    "description": """Brings the target tab to the front (activates it) without changing its navigation state.""",
    "parameters": {
        "type": "object",
        "properties": {
            "tab": {
                "type": "string",
                # 目标标签页：BrowserListTabs 的 0 基 index（如 "0"），或 url/title 的子串。
                "description": "Target tab: the 0-based index from BrowserListTabs, or a substring of its URL or title.",
            },
        },
        "required": ["tab"],
    },
}

_BROWSER_CLOSE_TAB_SCHEMA = {
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
                # 目标标签页：BrowserListTabs 的 0 基 index（如 "0"），或 url/title 的子串。
                "description": "Target tab: the 0-based index from BrowserListTabs, or a substring of its URL or title.",
            },
        },
        "required": ["tab"],
    },
}


class BrowserOpenTabTool(BaseTool):
    """在浏览器中新开标签页并导航到指定 URL。"""

    def __init__(self) -> None:
        super().__init__(
            name="BrowserOpenTab",
            toolset="browser",
            schema=_BROWSER_OPEN_TAB_SCHEMA,
            is_async=True,
            check_fn=_connection.playwright_available,
            danger_level=ToolDangerLevel.safe,
        )

    async def handle(self, execution: ToolExecution) -> ToolHandlerResult:
        return ToolHandlerResult(await _handle_browser_open_tab(execution.arguments))


class BrowserActivateTabTool(BaseTool):
    """激活/切换到指定标签页。"""

    def __init__(self) -> None:
        super().__init__(
            name="BrowserActivateTab",
            toolset="browser",
            schema=_BROWSER_ACTIVATE_TAB_SCHEMA,
            is_async=True,
            check_fn=_connection.playwright_available,
            danger_level=ToolDangerLevel.safe,
        )

    async def handle(self, execution: ToolExecution) -> ToolHandlerResult:
        return ToolHandlerResult(await _handle_browser_activate_tab(execution.arguments))


class BrowserCloseTabTool(BaseTool):
    """关闭指定标签页。"""

    def __init__(self) -> None:
        super().__init__(
            name="BrowserCloseTab",
            toolset="browser",
            schema=_BROWSER_CLOSE_TAB_SCHEMA,
            is_async=True,
            check_fn=_connection.playwright_available,
            danger_level=ToolDangerLevel.safe,
        )

    async def handle(self, execution: ToolExecution) -> ToolHandlerResult:
        return ToolHandlerResult(await _handle_browser_close_tab(execution.arguments))


TOOLSET = BaseToolSet(
    name="browser",
    tools=(BrowserOpenTabTool(), BrowserActivateTabTool(), BrowserCloseTabTool()),
)
