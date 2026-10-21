"""BrowserScreenshot — 对已接管浏览器中的指定标签页截图（write）。

截图经 sandbox resolve_write 直接写入 ws:logs/browser_screenshots/，
返回 ws: 逻辑路径，可配合 Read 查看页面画面。
工具对象通过模块级 ``TOOLSET``（``BaseToolSet``）声明；导入期只创建无连接工具对象。
"""

from __future__ import annotations

from interface.browser_system import IBrowserSystem
from interface.sandbox import ISandbox

import logging
import uuid
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
    "if the target page is not listed, ask the user to open or switch to it manually, then retry. "
    "This tool does not open any page."
)


def _browser_system() -> BrowserSystem:
    return Application.current().get_system(IBrowserSystem)


async def _handle_browser_screenshot(args: dict[str, Any]) -> dict:
    tab: str = str(args.get("tab", "")).strip()
    if not tab:
        return tool_error("tab is required")
    full_page: bool = bool(args.get("full_page", False))

    try:
        browser = await _browser_system().get_browser()
    except Exception as exc:
        if requires_lifecycle_propagation(exc):
            raise
        logger.warning("BrowserScreenshot: reconnect failed: %s: %s", type(exc).__name__, exc)
        return tool_error(_NOT_CONNECTED)

    page = await _connection.find_page(browser, tab)
    if page is None:
        return tool_error(_TAB_NOT_FOUND, tab=tab)

    logical = f"ws:logs/browser_screenshots/{uuid.uuid4().hex[:12]}.png"
    resolved = Application.current().get_system(ISandbox).resolve_write(logical)
    resolved.real.parent.mkdir(parents=True, exist_ok=True)
    await page.screenshot(path=str(resolved.real), full_page=full_page)

    try:
        title = await page.title()
    except Exception:
        title = ""

    return tool_result(
        saved_to=logical,
        tab_title=title,
        tab_url=page.url or "",
        full_page=full_page,
    )


_BROWSER_SCREENSHOT_SCHEMA = {
    # 对已接管浏览器中的指定标签页截图，返回用户视野一致的页面画面。
    #
    # ## 前置条件
    # - 已成功调用 BrowserConnect。
    # - 目标标签页已存在（可用 BrowserListTabs 确认）。
    #
    # ## 调用效果
    # tab 定位规则与 BrowserScreenshot 相同（index 或 url/title 子串）；
    # 未命中返回错误并请求用户手动操作——本工具不会自动打开任何页面。
    # 截图写入 ws:logs/browser_screenshots/{{uuid}}.png，full_page=true 时截取整页。
    #
    # ## 返回
    # ```json
    # {"saved_to": "ws:logs/browser_screenshots/abc123.png", "tab_title": "...", "tab_url": "...", "full_page": false}
    # ```
    #
    # ## 何时使用
    # - BrowserScreenshot 是了解页面视觉状态的主要手段（布局、图片、验证码、弹窗等）。
    # - 用 Read 读取 saved_to 路径即可看到与用户视野一致的画面。
    #
    # ## 副作用/注意
    # - 只读操作，不修改浏览器状态；截图文件持久化在 agentspace 中。
    "description": """Takes a screenshot of a tab in the connected browser, capturing exactly what the user sees.

## Prerequisites
- BrowserConnect must have succeeded.
- The target tab must already exist (confirm with BrowserListTabs).

## Effect
Tab location follows the same rules as BrowserScreenshot (0-based index, or URL/title substring). If no tab matches, an error is returned asking the user to act manually — this tool never opens pages on its own. The screenshot is written to ws:logs/browser_screenshots/{uuid}.png; pass full_page=true to capture the entire scrollable page.

## Returns
```json
{"saved_to": "ws:logs/browser_screenshots/abc123.png", "tab_title": "...", "tab_url": "...", "full_page": false}
```

## When to Use
- When you need to judge page state visually (layout, images, captchas, modals).
- Use Read on the saved_to path to see the same view as the user.

## Side Effects / Notes
- Read-only; does not modify browser state. Screenshot files persist in the agentspace.""",
    "parameters": {
        "type": "object",
        "properties": {
            "tab": {
                "type": "string",
                # 目标标签页：list_tabs 的 0 基 index（如 "0"），或 url/title 的子串。
                "description": "Target tab: the 0-based index from BrowserListTabs (e.g. \"0\"), or a substring of its URL or title.",
            },
            "full_page": {
                "type": "boolean",
                # 是否截取完整可滚动页面（默认 false，仅当前视口）。
                "description": "Capture the full scrollable page instead of just the viewport (default false).",
                "default": False,
            },
        },
        "required": ["tab"],
    },
}


class BrowserScreenshotTool(BaseTool):
    """对已接管浏览器中的指定标签页截图。"""

    def __init__(self) -> None:
        super().__init__(
            name="BrowserScreenshot",
            toolset="browser",
            schema=_BROWSER_SCREENSHOT_SCHEMA,
            is_async=True,
            check_fn=_connection.playwright_available,
            danger_level=ToolDangerLevel.write,
        )

    async def handle(self, execution: ToolExecution) -> ToolHandlerResult:
        return ToolHandlerResult(await _handle_browser_screenshot(execution.arguments))


TOOLSET = BaseToolSet(name="browser", tools=(BrowserScreenshotTool(),))
