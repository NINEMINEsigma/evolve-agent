"""browser_wait — 等待页面/元素达到指定状态（readonly）。

供 goto/click 等操作后同步状态：等网络空闲或等元素可见/隐藏。
无任何副作用。模块导入时通过 ``registry.register()`` 注册。
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

_VALID_STATES: tuple[str, ...] = ("attached", "detached", "visible", "hidden")
_DEFAULT_TIMEOUT_MS: int = 2000


async def _handle_browser_wait(args: dict[str, Any]) -> dict:
    tab: str = str(args.get("tab", "")).strip()
    selector: str = str(args.get("selector", "")).strip()
    state: str = str(args.get("state", "visible")).strip().lower()
    timeout: int = int(args.get("timeout_ms", _DEFAULT_TIMEOUT_MS))

    if not tab:
        return tool_error("tab is required")
    if state not in _VALID_STATES:
        return tool_error(f"state must be one of {list(_VALID_STATES)}")
    if timeout < 0:
        return tool_error("timeout_ms cannot be negative")

    try:
        browser = await _connection.get_browser()
    except Exception as exc:
        logger.warning("browser_wait: reconnect failed: %s: %s", type(exc).__name__, exc)
        return tool_error(_NOT_CONNECTED)
    page = await _connection.find_page(browser, tab)
    if page is None:
        return tool_error(_TAB_NOT_FOUND, tab=tab)

    try:
        if selector:
            await page.wait_for_selector(selector, state=state, timeout=timeout)
        else:
            await page.wait_for_load_state("networkidle", timeout=timeout)
    except Exception as exc:
        return tool_error(
            f"wait condition not met within {timeout}ms: {type(exc).__name__}: {exc}",
            selector=selector or None,
            state=state,
        )

    return tool_result(waited=True, condition=selector or "networkidle", state=state if selector else None)


registry.register(
    name="browser_wait",
    toolset="browser",
    schema={
        # 等待页面或元素达到指定状态。
        #
        # ## 调用效果
        # - 提供 selector：等待该元素达到 state（attached/detached/visible/hidden，默认 visible）。
        # - 不提供 selector：等待页面网络空闲（networkidle）。
        # - 超时（默认 2000ms）未满足则返回错误。
        #
        # ## 何时使用
        # - browser_goto / browser_click 等操作后同步页面状态。
        # - 等待动态加载的元素出现后再读取。
        #
        # ## 副作用/注意
        # - 只读等待，无副作用；正常模式下无需审批。
        "description": """Waits for the page or an element to reach a given state.

## Effect
- With `selector`: waits until that element reaches `state` (attached/detached/visible/hidden, default visible).
- Without `selector`: waits for the page network to be idle (networkidle).
- Errors when the condition is not met within `timeout_ms` (default 2000).

## When to Use
- Sync page state after browser_goto / browser_click.
- Wait for dynamically loaded elements before reading them.

## Side Effects / Notes
- Read-only wait; no side effects; no approval needed in normal mode.""",
        "parameters": {
            "type": "object",
            "properties": {
                "tab": {
                    "type": "string",
                    # 目标标签页：browser_list_tabs 的 0 基 index（如 "0"），或 url/title 的子串。
                    "description": "Target tab: the 0-based index from browser_list_tabs, or a substring of its URL or title.",
                },
                "selector": {
                    "type": "string",
                    # 可选：CSS 选择器，等待该元素达到 state。缺省时等待网络空闲。
                    "description": "Optional: CSS selector to wait for. Omit to wait for network idle.",
                    "default": "",
                },
                "state": {
                    "type": "string",
                    # 元素状态：attached / detached / visible / hidden（默认 visible）。仅与 selector 搭配。
                    "description": "Element state to wait for: attached / detached / visible / hidden (default visible). Only used with selector.",
                    "default": "visible",
                },
                "timeout_ms": {
                    "type": "integer",
                    # 等待超时毫秒（默认 2000）。
                    "description": "Timeout in milliseconds (default 2000).",
                    "default": 2000,
                },
            },
            "required": ["tab"],
        },
    },
    handler=_handle_browser_wait,
    check_fn=_connection.playwright_available,
    is_async=True,
    emoji="⏳",
    danger_level=ToolDangerLevel.readonly,
)