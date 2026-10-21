"""navigate 工具组 — 页面导航（write）。

BrowserGoto / BrowserRefresh / BrowserBack / BrowserForward。
所有导航都是改变浏览器状态的显式动作：schema 行为规范要求
跳转前与用户确认目标；可能重定向到登录页的目标先向用户说明。
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
    "Tab not found. Use BrowserListTabs to confirm existing tabs; "
    "if the target page is not listed, ask the user to open or switch to it manually, then retry."
)

_VALID_WAIT: tuple[str, ...] = ("commit", "domcontentloaded", "load", "networkidle")
_DEFAULT_WAIT: str = "networkidle"
_DEFAULT_TIMEOUT_MS: int = 30000


def _browser_system() -> BrowserSystem:
    return Application.current().get_system(IBrowserSystem)


async def _resolve_page(args: dict[str, Any]) -> tuple[Any, str]:
    """定位目标标签页，返回 (page, tab_title)；失败返回 (None, error)。"""
    tab: str = str(args.get("tab", "")).strip()
    if not tab:
        return None, "tab is required"
    try:
        browser = await _browser_system().get_browser()
    except Exception as exc:
        if requires_lifecycle_propagation(exc):
            raise
        logger.warning("navigate: reconnect failed: %s: %s", type(exc).__name__, exc)
        return None, _NOT_CONNECTED
    page = await _connection.find_page(browser, tab)
    if page is None:
        return None, _TAB_NOT_FOUND
    return page, ""


async def _page_summary(page: Any) -> dict[str, Any]:
    try:
        title = await page.title()
    except Exception:
        title = ""
    return {"url": page.url or "", "tab_title": title}


async def _handle_browser_goto(args: dict[str, Any]) -> dict:
    url: str = str(args.get("url", "")).strip()
    wait: str = str(args.get("wait", _DEFAULT_WAIT)).strip().lower()
    timeout: int = int(args.get("timeout", _DEFAULT_TIMEOUT_MS))

    if not url:
        return tool_error("url is required")
    if wait not in _VALID_WAIT:
        return tool_error(f"wait must be one of {list(_VALID_WAIT)}")

    page, err = await _resolve_page(args)
    if err:
        return tool_error(err)

    try:
        await page.goto(url, wait_until=wait, timeout=timeout)
    except Exception as exc:
        logger.warning("BrowserGoto failed: %s", exc)
        return tool_error(f"goto failed: {type(exc).__name__}: {exc}", url=url)

    return tool_result(goto=url, **await _page_summary(page))


async def _handle_browser_refresh(args: dict[str, Any]) -> dict:
    page, err = await _resolve_page(args)
    if err:
        return tool_error(err)
    try:
        await page.reload(wait_until=_DEFAULT_WAIT, timeout=_DEFAULT_TIMEOUT_MS)
    except Exception as exc:
        return tool_error(f"refresh failed: {type(exc).__name__}: {exc}")
    return tool_result(refreshed=True, **await _page_summary(page))


async def _handle_browser_back(args: dict[str, Any]) -> dict:
    page, err = await _resolve_page(args)
    if err:
        return tool_error(err)
    try:
        prev = await page.go_back(wait_until=_DEFAULT_WAIT, timeout=_DEFAULT_TIMEOUT_MS)
    except Exception as exc:
        return tool_error(f"go_back failed: {type(exc).__name__}: {exc}")
    if prev is None:
        return tool_error("no history to go back")
    return tool_result(back=True, **await _page_summary(page))


async def _handle_browser_forward(args: dict[str, Any]) -> dict:
    page, err = await _resolve_page(args)
    if err:
        return tool_error(err)
    try:
        nxt = await page.go_forward(wait_until=_DEFAULT_WAIT, timeout=_DEFAULT_TIMEOUT_MS)
    except Exception as exc:
        return tool_error(f"go_forward failed: {type(exc).__name__}: {exc}")
    if nxt is None:
        return tool_error("no history to go forward")
    return tool_result(forward=True, **await _page_summary(page))


# ---------------------------------------------------------------------------
# 工具类与工具集
# ---------------------------------------------------------------------------

_GOTO_DESCRIPTION = """Navigates the current tab to a URL and waits for the page to load.

## Prerequisites
- BrowserConnect must have succeeded; the target tab exists.

## Behavior (user-confirmation norms)
- Navigation is an explicit state change: before navigating, confirm the target URL with the user.
- If the target is likely to redirect to a login page (requires an authenticated session), explain this to the user and ask them to confirm or intervene first.

## Effect
Navigates to `url`, waiting for the given load state (default networkidle). Returns the resulting URL and page title.

## Returns
```json
{"goto": "https://...", "url": "https://...", "tab_title": "..."}
```

## Side Effects / Notes
- Changes browser state (navigation); reversible via back/forward.
- Do NOT use for destructive flows without user consent."""

_BROWSER_GOTO_SCHEMA = {
    # 导航当前标签页到指定 URL 并等待加载完成。
    #
    # ## 行为规范
    # - 导航是显式状态变更：执行前与用户确认目标 URL。
    # - 若目标可能重定向到登录页，先向用户说明并请其确认或介入。
    "description": _GOTO_DESCRIPTION,
    "parameters": {
        "type": "object",
        "properties": {
            "tab": {
                "type": "string",
                # 目标标签页：BrowserListTabs 的 0 基 index（如 "0"），或 url/title 的子串。
                "description": "Target tab: the 0-based index from BrowserListTabs (e.g. \"0\"), or a substring of its URL or title.",
            },
            "url": {
                "type": "string",
                # 目标 URL。必须以 http:// 或 https:// 开头。
                "description": "The URL to navigate to. Must start with http:// or https://.",
            },
            "wait": {
                "type": "string",
                # 等待的加载状态：commit / domcontentloaded / load / networkidle（默认）。
                "description": "Load state to wait for: commit / domcontentloaded / load / networkidle (default).",
                "default": "networkidle",
            },
            "timeout": {
                "type": "integer",
                # 导航超时毫秒（默认 30000）。
                "description": "Navigation timeout in milliseconds (default 30000).",
                "default": 30000,
            },
        },
        "required": ["tab"],
    },
}

_BROWSER_REFRESH_SCHEMA = {
    # 刷新当前页面并等待网络空闲。可逆状态变更。
    "description": "Reloads the current page and waits for network idle. Returns the resulting URL and title. Reversible state change.",
    "parameters": {
        "type": "object",
        "properties": {
            "tab": {
                "type": "string",
                "description": "Target tab: the 0-based index from BrowserListTabs, or a substring of its URL or title.",
            },
        },
        "required": ["tab"],
    },
}

_BROWSER_BACK_SCHEMA = {
    # 历史后退。返回跳转后 URL 与标题；无历史时报错。
    "description": "Navigates back in history. Returns the resulting URL and title; errors when there is no history.",
    "parameters": {
        "type": "object",
        "properties": {
            "tab": {
                "type": "string",
                "description": "Target tab: the 0-based index from BrowserListTabs, or a substring of its URL or title.",
            },
        },
        "required": ["tab"],
    },
}

_BROWSER_FORWARD_SCHEMA = {
    # 历史前进。返回跳转后 URL 与标题；无前向历史时报错。
    "description": "Navigates forward in history. Returns the resulting URL and title; errors when there is no forward history.",
    "parameters": {
        "type": "object",
        "properties": {
            "tab": {
                "type": "string",
                "description": "Target tab: the 0-based index from BrowserListTabs, or a substring of its URL or title.",
            },
        },
        "required": ["tab"],
    },
}


class BrowserGotoTool(BaseTool):
    """导航当前标签页到指定 URL。"""

    def __init__(self) -> None:
        super().__init__(
            name="BrowserGoto",
            toolset="browser",
            schema=_BROWSER_GOTO_SCHEMA,
            is_async=True,
            check_fn=_connection.playwright_available,
            danger_level=ToolDangerLevel.safe,
        )

    async def handle(self, execution: ToolExecution) -> ToolHandlerResult:
        return ToolHandlerResult(await _handle_browser_goto(execution.arguments))


class BrowserRefreshTool(BaseTool):
    """刷新当前页面并等待网络空闲。"""

    def __init__(self) -> None:
        super().__init__(
            name="BrowserRefresh",
            toolset="browser",
            schema=_BROWSER_REFRESH_SCHEMA,
            is_async=True,
            check_fn=_connection.playwright_available,
            danger_level=ToolDangerLevel.safe,
        )

    async def handle(self, execution: ToolExecution) -> ToolHandlerResult:
        return ToolHandlerResult(await _handle_browser_refresh(execution.arguments))


class BrowserBackTool(BaseTool):
    """历史后退。"""

    def __init__(self) -> None:
        super().__init__(
            name="BrowserBack",
            toolset="browser",
            schema=_BROWSER_BACK_SCHEMA,
            is_async=True,
            check_fn=_connection.playwright_available,
            danger_level=ToolDangerLevel.safe,
        )

    async def handle(self, execution: ToolExecution) -> ToolHandlerResult:
        return ToolHandlerResult(await _handle_browser_back(execution.arguments))


class BrowserForwardTool(BaseTool):
    """历史前进。"""

    def __init__(self) -> None:
        super().__init__(
            name="BrowserForward",
            toolset="browser",
            schema=_BROWSER_FORWARD_SCHEMA,
            is_async=True,
            check_fn=_connection.playwright_available,
            danger_level=ToolDangerLevel.safe,
        )

    async def handle(self, execution: ToolExecution) -> ToolHandlerResult:
        return ToolHandlerResult(await _handle_browser_forward(execution.arguments))


TOOLSET = BaseToolSet(
    name="browser",
    tools=(BrowserGotoTool(), BrowserRefreshTool(), BrowserBackTool(), BrowserForwardTool()),
)
