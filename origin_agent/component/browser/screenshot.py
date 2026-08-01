"""browser_screenshot — 对已接管浏览器中的指定标签页截图（write）。

截图经 sandbox resolve_write 直接写入 ws:logs/browser_screenshots/，
返回 ws: 逻辑路径，可配合 read_image 查看页面画面。
模块导入时通过 ``registry.register()`` 注册。
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from abstract.tools.registry import registry, tool_error, tool_result
from component.browser import _connection
from component.tools.filesystem import _s as _get_sandbox
from entity.puretype import ToolDangerLevel

logger = logging.getLogger(__name__)

_NOT_CONNECTED: str = (
    "浏览器未连接或 CDP 端点不可达。请先调用 browser_connect；"
    "若 connect 曾返回指引，请先按指引让用户完成操作。"
)

_TAB_NOT_FOUND: str = (
    "未找到匹配的标签页。请先用 browser_list_tabs 确认现有标签页；"
    "若目标页面未在其中，请用户在浏览器中手动打开或切换到目标页面后重试。"
    "本工具不会自动打开任何页面。"
)


async def _handle_browser_screenshot(args: dict[str, Any]) -> dict:
    tab: str = str(args.get("tab", "")).strip()
    if not tab:
        return tool_error("tab is required")
    full_page: bool = bool(args.get("full_page", False))

    try:
        browser = await _connection.get_browser()
    except Exception as exc:
        logger.warning("browser_screenshot: reconnect failed: %s: %s", type(exc).__name__, exc)
        return tool_error(_NOT_CONNECTED)

    page = await _connection.find_page(browser, tab)
    if page is None:
        return tool_error(_TAB_NOT_FOUND, tab=tab)

    logical = f"ws:logs/browser_screenshots/{uuid.uuid4().hex[:12]}.png"
    resolved = _get_sandbox().resolve_write(logical)
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


registry.register(
    name="browser_screenshot",
    toolset="browser",
    schema={
        # 对已接管浏览器中的指定标签页截图，返回用户视野一致的页面画面。
        #
        # ## 前置条件
        # - 已成功调用 browser_connect。
        # - 目标标签页已存在（可用 browser_list_tabs 确认）。
        #
        # ## 调用效果
        # tab 定位规则与 browser_read_page 相同（index 或 url/title 子串）；
        # 未命中返回错误并请求用户手动操作——本工具不会自动打开任何页面。
        # 截图写入 ws:logs/browser_screenshots/{{uuid}}.png，full_page=true 时截取整页。
        #
        # ## 返回
        # ```json
        # {"saved_to": "ws:logs/browser_screenshots/abc123.png", "tab_title": "...", "tab_url": "...", "full_page": false}
        # ```
        #
        # ## 何时使用
        # - browser_read_page 的文本不足以判断页面状态（布局、图片、验证码、弹窗等）。
        # - 用 read_image 读取 saved_to 路径即可看到与用户视野一致的画面。
        #
        # ## 副作用/注意
        # - 只读操作，不修改浏览器状态；截图文件持久化在 agentspace 中。
        "description": """Takes a screenshot of a tab in the connected browser, capturing exactly what the user sees.

## Prerequisites
- browser_connect must have succeeded.
- The target tab must already exist (confirm with browser_list_tabs).

## Effect
Tab location follows the same rules as browser_read_page (0-based index, or URL/title substring). If no tab matches, an error is returned asking the user to act manually — this tool never opens pages on its own. The screenshot is written to ws:logs/browser_screenshots/{uuid}.png; pass full_page=true to capture the entire scrollable page.

## Returns
```json
{"saved_to": "ws:logs/browser_screenshots/abc123.png", "tab_title": "...", "tab_url": "...", "full_page": false}
```

## When to Use
- When text from browser_read_page is insufficient to judge page state (layout, images, captchas, modals).
- Use read_image on the saved_to path to see the same view as the user.

## Side Effects / Notes
- Read-only; does not modify browser state. Screenshot files persist in the agentspace.""",
        "parameters": {
            "type": "object",
            "properties": {
                "tab": {
                    "type": "string",
                    # 目标标签页：list_tabs 的 0 基 index（如 "0"），或 url/title 的子串。
                    "description": "Target tab: the 0-based index from browser_list_tabs (e.g. \"0\"), or a substring of its URL or title.",
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
    },
    handler=_handle_browser_screenshot,
    check_fn=_connection.playwright_available,
    is_async=True,
    emoji="📸",
    danger_level=ToolDangerLevel.write,
)