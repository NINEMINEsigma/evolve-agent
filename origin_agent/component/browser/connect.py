"""browser_connect — 通过 CDP 探测并接管用户的真实浏览器（dangerous）。

只建立 CDP 连接：不关闭、不修改用户浏览器，也不会自动打开任何页面。
模块导入时通过 ``registry.register()`` 注册。
"""

from __future__ import annotations

import logging
from typing import Any

from abstract.tools.registry import registry, tool_error, tool_result
from component.browser import _connection
from entity.puretype import ToolDangerLevel

logger = logging.getLogger(__name__)


async def _handle_browser_connect(args: dict[str, Any]) -> dict:
    endpoint: str = str(args.get("endpoint", "")).strip() or _connection.CDP_ENDPOINT_DEFAULT

    try:
        browser = await _connection.get_browser(endpoint)
    except Exception as exc:
        logger.warning("browser_connect failed: %s: %s", type(exc).__name__, exc)
        return tool_error(
            _connection.EDGE_DEBUG_GUIDE,
            endpoint=endpoint,
            detail=f"{type(exc).__name__}: {exc}",
        )

    return tool_result(
        connected=True,
        endpoint=_connection.current_endpoint(),
        tab_count=len(_connection.all_pages(browser)),
    )


registry.register(
    name="browser_connect",
    toolset="browser",
    schema={
        # 通过 CDP 接管用户真实浏览器，获得其全部标签页的访问权（含登录态、Cookie、本地存储）。
        # 只建立连接：不关闭/修改浏览器，不自动打开页面。
        #
        # ## 前置条件
        # - 已存在以调试参数启动的浏览器实例：--remote-debugging-port=9222
        #   + --user-data-dir=<非默认目录>（Chromium 136+ 在默认用户数据目录下会
        #   静默忽略调试端口参数）。若未启动，可先调用 browser_launch 自动拉起。
        # - 若端点不可达，返回的 error 中包含给用户的中文步骤指引，请原样转述给用户。
        # - 已安装 playwright 包（未安装时本工具不可见）。
        #
        # ## 调用效果
        # 经 CDP 附加到正在运行的浏览器。所有现有标签页随后可被
        # browser_list_tabs / browser_read_page / browser_screenshot 访问。
        # 连接跨调用复用；浏览器以调试端口重启后自动重连。
        #
        # ## 返回
        # ```json
        # {"connected": true, "endpoint": "http://localhost:9222", "tab_count": 3}
        # ```
        #
        # ## 何时使用
        # - 需要读取 JS 渲染或要求登录态的页面时，先于其他 browser_* 工具调用。
        #
        # ## 副作用/注意
        # - 需用户审批（dangerous）：agent 将获得用户已认证浏览器会话的访问能力。
        "description": """Connects to the user's real browser via CDP (Chrome DevTools Protocol), gaining access to all its existing tabs including login sessions, cookies, and local storage. Establishes the connection only — never closes or modifies the browser, and never opens pages on its own.

## Prerequisites
- A browser instance must already be running with debug flags: --remote-debugging-port=9222 plus a non-default --user-data-dir (Chromium 136+ silently ignores the debug port on the default user data directory). If not started yet, call browser_launch first to bring it up automatically.
- If the endpoint is unreachable, the returned error contains step-by-step instructions in Chinese for the user — relay them to the user verbatim.
- The playwright package must be installed (this tool is hidden otherwise).

## Effect
Attaches to the running browser over CDP. All existing tabs become accessible to browser_list_tabs / browser_read_page / browser_screenshot. The connection is reused across calls and re-established automatically if lost.

## Returns
```json
{"connected": true, "endpoint": "http://localhost:9222", "tab_count": 3}
```

## When to Use
- Before any other browser_* tool, when JS-rendered or login-required pages must be read.

## Side Effects / Notes
- Requires user approval (dangerous): the agent gains access to the user's authenticated browser sessions.""",
        "parameters": {
            "type": "object",
            "properties": {
                "endpoint": {
                    "type": "string",
                    # CDP 端点。留空使用默认值 http://localhost:9222。
                    "description": "CDP endpoint. Leave empty to use the default http://localhost:9222.",
                    "default": "",
                },
                "reason": {
                    "type": "string",
                    # 连接原因（用于审批提示）。
                    "description": "The reason for connecting to the user's browser (shown in the approval prompt).",
                },
            },
            "required": [],
        },
    },
    handler=_handle_browser_connect,
    check_fn=_connection.playwright_available,
    is_async=True,
    emoji="🔗",
    danger_level=ToolDangerLevel.dangerous,
)