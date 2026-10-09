"""interact 工具组 — 元素交互（write）。

BrowserClick / BrowserType / BrowserPress / BrowserScroll。
元素定位复用 query 的 path|selector 双通道（path → XPath locator）。
行为规范：不可逆动作（删除/提交/发送）执行前必须征求用户同意；
type 可先行填写、提交前确认。模块导入时通过 ``registry.register()`` 注册。
"""

from __future__ import annotations

import logging
from typing import Any

from abstract.tools.registry import ToolRegistry, tool_error, tool_result
from abstract.tools.ui_event_router import UIEventRouter
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

_ELEMENT_NOT_FOUND: str = "Target element not found. Use BrowserQuery to confirm its path or selector first."

_DEFAULT_TIMEOUT_MS: int = 30000


def _browser_system() -> BrowserSystem:
    return Application.current().get_system(BrowserSystem)


async def _resolve_page_and_locator(
    args: dict[str, Any],
    require_element: bool = False,
) -> tuple[Any, Any, str]:
    """解析目标标签页与目标元素 locator。

    返回 (page, locator, error)。*require_element* 为 True 时 path/selector
    至少提供一个；否则两者可都缺省（press/scroll 的全局模式）。
    """
    tab: str = str(args.get("tab", "")).strip()
    path: str = str(args.get("path", "")).strip()
    selector: str = str(args.get("selector", "")).strip()

    if not tab:
        return None, None, "tab is required"
    if path and selector:
        return None, None, "provide either 'path' or 'selector', not both"
    if require_element and not path and not selector:
        return None, None, "provide 'path' or 'selector' (at least one)"

    try:
        browser = await _browser_system().get_browser()
    except Exception as exc:
        if requires_lifecycle_propagation(exc):
            raise
        logger.warning("interact: reconnect failed: %s: %s", type(exc).__name__, exc)
        return None, None, _NOT_CONNECTED
    page = await _connection.find_page(browser, tab)
    if page is None:
        return None, None, _TAB_NOT_FOUND

    locator = None
    if path or selector:
        try:
            locator = _connection.resolve_locator(page, path=path, selector=selector)
        except ValueError as exc:
            return None, None, str(exc)
        if locator.count() == 0:
            return None, None, _ELEMENT_NOT_FOUND

    return page, locator, ""


async def _handle_browser_click(args: dict[str, Any]) -> dict:
    page, locator, err = await _resolve_page_and_locator(args, require_element=True)
    if err:
        return tool_error(err)
    timeout: int = int(args.get("timeout", _DEFAULT_TIMEOUT_MS))
    try:
        await locator.first.click(timeout=timeout)
    except Exception as exc:
        return tool_error(f"click failed: {type(exc).__name__}: {exc}")

    try:
        title = await page.title()
    except Exception:
        title = ""
    return tool_result(clicked=True, url=page.url or "", tab_title=title)


async def _handle_browser_type(args: dict[str, Any]) -> dict:
    page, locator, err = await _resolve_page_and_locator(args, require_element=True)
    if err:
        return tool_error(err)
    text: str = str(args.get("text", ""))
    timeout: int = int(args.get("timeout", _DEFAULT_TIMEOUT_MS))
    try:
        await locator.first.fill(text, timeout=timeout)
    except Exception as exc:
        return tool_error(f"type failed: {type(exc).__name__}: {exc}")
    return tool_result(typed=True, chars=len(text))


async def _handle_browser_press(args: dict[str, Any]) -> dict:
    page, locator, err = await _resolve_page_and_locator(args, require_element=False)
    if err:
        return tool_error(err)
    key: str = str(args.get("key", "")).strip()
    if not key:
        return tool_error("key is required (e.g. 'Enter')")
    try:
        if locator is not None:
            await locator.first.press(key)
        else:
            await page.keyboard.press(key)
    except Exception as exc:
        return tool_error(f"press failed: {type(exc).__name__}: {exc}")
    return tool_result(pressed=key)


async def _handle_browser_scroll(args: dict[str, Any]) -> dict:
    page, locator, err = await _resolve_page_and_locator(args, require_element=False)
    if err:
        return tool_error(err)
    delta_y: int = int(args.get("delta_y", 500))
    try:
        if locator is not None:
            await locator.first.scroll_into_view_if_needed()
        else:
            await page.mouse.wheel(0, delta_y)
    except Exception as exc:
        return tool_error(f"scroll failed: {type(exc).__name__}: {exc}")
    return tool_result(scrolled=True, to_element=locator is not None, delta_y=delta_y if locator is None else None)


# ---------------------------------------------------------------------------
# 注册
# ---------------------------------------------------------------------------

def register_tools(registry: ToolRegistry, ui_events: UIEventRouter) -> None:
    """Register browser interact tools into explicit runtime registries."""
    del ui_events
    registry.register(
        name="BrowserClick",
        toolset="browser",
        schema={
        # 点击指定元素（path 或 selector 定位，真实输入事件）。
        #
        # ## 行为规范
        # - 若点击可能导致不可逆影响（删除、提交、发送、下单等），
        #   **执行前必须向用户征求明确同意**。
        # - 提交/发送类按钮的点击尤其需要先与用户确认内容与后果。
        #
        # ## 参数
        # - path：BrowserQuery 产出的索引路径（XPath 定位）。
        # - selector：CSS 选择器（或 / 开头的 XPath）。
        # - 二者二选一，不可同时提供。
        "description": """Clicks an element (located by path or selector) with real input events.

## Behavior (user-confirmation norms)
- If the click may cause an irreversible effect (delete, submit, send, purchase, etc.), you MUST obtain explicit user consent BEFORE executing.
- For submit/send buttons in particular, confirm the content and consequences with the user first.

## Parameters
- `path`: index path from BrowserQuery (resolved as XPath).
- `selector`: CSS selector (or XPath when starting with `/`).
- Exactly one of path/selector is required.""",
        "parameters": {
            "type": "object",
            "properties": {
                "tab": {
                    "type": "string",
                    # 目标标签页：BrowserListTabs 的 0 基 index（如 "0"），或 url/title 的子串。
                    "description": "Target tab: the 0-based index from BrowserListTabs, or a substring of its URL or title.",
                },
                "path": {
                    "type": "string",
                    # 元素索引路径（点分隔数字，如 "0.2.1"）。与 selector 二选一。
                    "description": "Element index path (dot-separated numbers like \"0.2.1\"). Mutually exclusive with selector.",
                    "default": "",
                },
                "selector": {
                    "type": "string",
                    # CSS 选择器或 XPath（以 / 开头自动识别）。与 path 二选一。
                    "description": "CSS selector or XPath (auto-detected when starting with '/'). Mutually exclusive with path.",
                    "default": "",
                },
                "timeout": {
                    "type": "integer",
                    # 等待元素可操作的超时毫秒（默认 30000）。
                    "description": "Timeout in milliseconds waiting for the element to be actionable (default 30000).",
                    "default": 30000,
                },
            },
            "required": ["tab"],
        },
    },
    handler=_handle_browser_click,
    check_fn=_connection.playwright_available,
    is_async=True,
    danger_level=ToolDangerLevel.write,
    )

    registry.register(
        name="BrowserType",
        toolset="browser",
        schema={
        # 向指定元素输入文本（fill，真实输入事件）。
        #
        # ## 行为规范
        # - 填写表单内容可以先行（type 本身不提交）。
        # - 但提交/发送类动作（按 Enter、点击提交按钮）前必须征得用户同意。
        "description": """Types text into an element (fill, real input events).

## Behavior (user-confirmation norms)
- Filling form content is allowed in advance (typing itself does not submit).
- However, submit/send actions (pressing Enter, clicking the submit button) require user consent first.""",
        "parameters": {
            "type": "object",
            "properties": {
                "tab": {
                    "type": "string",
                    "description": "Target tab: the 0-based index from BrowserListTabs, or a substring of its URL or title.",
                },
                "path": {
                    "type": "string",
                    # 元素索引路径（点分隔数字）。与 selector 二选一。
                    "description": "Element index path (dot-separated numbers). Mutually exclusive with selector.",
                    "default": "",
                },
                "selector": {
                    "type": "string",
                    # CSS 选择器或 XPath（以 / 开头自动识别）。与 path 二选一。
                    "description": "CSS selector or XPath (auto-detected when starting with '/'). Mutually exclusive with path.",
                    "default": "",
                },
                "text": {
                    "type": "string",
                    # 要输入的文本（替换元素当前内容）。
                    "description": "The text to enter (replaces the element's current content).",
                },
                "timeout": {
                    "type": "integer",
                    "description": "Timeout in milliseconds (default 30000).",
                    "default": 30000,
                },
            },
            "required": ["tab"],
        },
    },
    handler=_handle_browser_type,
    check_fn=_connection.playwright_available,
    is_async=True,
    danger_level=ToolDangerLevel.write,
    )

    registry.register(
        name="BrowserPress",
        toolset="browser",
        schema={
        # 按下键盘按键。有元素定位时在该元素上按键，否则全局按键
        # （如 Enter 提交当前聚焦表单）。
        #
        # ## 行为规范
        # - Enter 提交、Ctrl+W 关标签等动作前必须征得用户同意。
        "description": """Presses a keyboard key. With an element target the key is sent to that element; otherwise globally (e.g. Enter submits the focused form).

## Behavior (user-confirmation norms)
- Actions like Enter (submit) or Ctrl+W (close tab) require user consent first.""",
        "parameters": {
            "type": "object",
            "properties": {
                "tab": {
                    "type": "string",
                    "description": "Target tab: the 0-based index from BrowserListTabs, or a substring of its URL or title.",
                },
                "key": {
                    "type": "string",
                    # 按键名（如 Enter、Tab、Escape、Ctrl+A）。
                    "description": "Key name (e.g. Enter, Tab, Escape, Ctrl+A).",
                },
                "path": {
                    "type": "string",
                    # 可选：目标元素索引路径（按键发送到该元素）。与 selector 二选一。
                    "description": "Optional: element index path (key sent to that element). Mutually exclusive with selector.",
                    "default": "",
                },
                "selector": {
                    "type": "string",
                    # 可选：CSS 选择器或 XPath。与 path 二选一。
                    "description": "Optional: CSS selector or XPath. Mutually exclusive with path.",
                    "default": "",
                },
            },
            "required": ["tab", "key"],
        },
    },
    handler=_handle_browser_press,
    check_fn=_connection.playwright_available,
    is_async=True,
    danger_level=ToolDangerLevel.write,
    )

    registry.register(
        name="BrowserScroll",
        toolset="browser",
        schema={
        # 滚动页面。有元素定位时滚动到该元素可见；否则按 delta_y 像素滚动。
        "description": """Scrolls the page. With an element target, scrolls until it is visible; otherwise scrolls by delta_y pixels (mouse wheel).""",
        "parameters": {
            "type": "object",
            "properties": {
                "tab": {
                    "type": "string",
                    "description": "Target tab: the 0-based index from BrowserListTabs, or a substring of its URL or title.",
                },
                "path": {
                    "type": "string",
                    # 可选：目标元素索引路径（滚动到该元素可见）。与 selector 二选一。
                    "description": "Optional: element index path (scroll until visible). Mutually exclusive with selector.",
                    "default": "",
                },
                "selector": {
                    "type": "string",
                    # 可选：CSS 选择器或 XPath。与 path 二选一。
                    "description": "Optional: CSS selector or XPath. Mutually exclusive with path.",
                    "default": "",
                },
                "delta_y": {
                    "type": "integer",
                    # 无元素定位时向下滚动的像素数（默认 500）。
                    "description": "Pixels to scroll down when no element target is given (default 500).",
                    "default": 500,
                },
            },
            "required": ["tab"],
        },
    },
    handler=_handle_browser_scroll,
    check_fn=_connection.playwright_available,
    is_async=True,
    danger_level=ToolDangerLevel.safe,
    )