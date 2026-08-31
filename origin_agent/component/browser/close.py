"""BrowserClose — 关闭浏览器并断开 CDP 连接（safe，幂等）。

断开 CDP 连接（释放 playwright）；若存在由 ``BrowserLaunch`` 以 headless
模式启动的浏览器进程，则强制终止（无头窗口不可见，用户无法手动关闭）。
有头浏览器窗口不会被本工具关闭——其进程未被追踪，且用户可手动关闭；
CDP 连接断开后浏览器照常运行，下次调用 browser 工具时会自动重连。
模块导入时通过 ``registry.register()`` 注册。
"""

from __future__ import annotations

import logging
from typing import Any

from abstract.tools.registry import registry, tool_result
from component.browser import _connection
from entity.puretype import ToolDangerLevel

logger = logging.getLogger(__name__)


async def _handle_browser_close(args: dict[str, Any]) -> dict:
    endpoint: str = _connection.current_endpoint()

    # 1. 断开 CDP 连接（不关闭有头浏览器），释放 playwright
    await _connection.teardown()

    # 2. 终止无头浏览器进程（若有）：无头窗口不可见，用户无法手动关闭
    headless_killed: int = _connection.cleanup_headless_browser()

    logger.info(
        "BrowserClose: CDP disconnected (endpoint=%s), headless processes killed=%d",
        endpoint,
        headless_killed,
    )

    return tool_result(
        closed=True,
        cdp_disconnected=True,
        headless_killed=headless_killed,
        endpoint=endpoint,
    )


registry.register(
    name="BrowserClose",
    toolset="browser",
    schema={
        # 关闭浏览器：断开 CDP 连接 + 终止无头浏览器进程（若有）。
        #
        # ## 行为细节
        # - 断开 CDP 连接（释放 playwright 资源），幂等：未连接时也安全调用。
        # - 若 BrowserLaunch 以 headless=true 启动了无头浏览器，强制终止该进程
        #   （无头窗口不可见，用户无法手动关闭）。
        # - 有头浏览器窗口不会被关闭：其进程未被追踪，且用户可手动关闭窗口。
        #   CDP 连接断开后浏览器照常运行；下次调用 browser 工具时会自动重连。
        #
        # ## 返回
        # ```json
        # {"closed": true, "cdp_disconnected": true, "headless_killed": 1, "endpoint": "http://localhost:9222"}
        # ```
        # headless_killed 为被终止的无头进程数（0 表示无无头进程在运行）。
        #
        # ## 何时使用
        # - 自动化任务完成后清理资源，尤其是 headless 模式下启动的浏览器。
        # - 需要释放 CDP 连接时。
        #
        # ## 副作用/注意
        # - 无头浏览器进程被强制终止（未保存的页面状态丢失，但 profile 持久化在 agentspace）。
        # - 有头浏览器不受影响，仅断开 agent 侧的 CDP 连接。
        "description": """Closes the browser: disconnects the CDP connection and terminates any headless browser process launched by BrowserLaunch (idempotent).

## Behavior
- Disconnects the CDP connection and releases playwright resources. Safe to call even when not connected.
- If BrowserLaunch started a headless browser (headless=true), forcefully terminates that process — headless windows are invisible and cannot be closed manually by the user.
- Headed (visible) browser windows are NOT closed by this tool: their process is not tracked and the user can close them manually. After the CDP disconnect the browser keeps running; the next browser tool call will reconnect automatically.

## Returns
```json
{"closed": true, "cdp_disconnected": true, "headless_killed": 1, "endpoint": "http://localhost:9222"}
```
`headless_killed` is the number of headless processes terminated (0 means none were running).

## When to Use
- Clean up resources after an automation task completes, especially for headless browsers.
- When you need to release the CDP connection.

## Side Effects / Notes
- The headless browser process is forcefully terminated (unsaved page state is lost, but the profile persists in the agentspace).
- The headed browser is unaffected; only the agent's CDP connection is dropped.""",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    handler=_handle_browser_close,
    check_fn=_connection.playwright_available,
    is_async=True,
    emoji="🔒",
    danger_level=ToolDangerLevel.safe,
)