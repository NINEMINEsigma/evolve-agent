"""browser_launch — 以调试参数启动 Edge（dangerous，幂等）。

profile（user-data-dir）持久化在 agentspace（ws:browser_profile），
登录态跨会话保留；启动的是调试专用实例，与日常 Edge 并存；
不打开任何具体页面。端口已就绪时直接返回（幂等）。
模块导入时通过 ``registry.register()`` 注册。
"""

from __future__ import annotations

import asyncio
import logging
import subprocess  # nosec
from typing import Any

from abstract.tools.registry import registry, tool_error, tool_result
from component.browser import _connection
from component.tools.filesystem import _s as _get_sandbox
from entity.puretype import ToolDangerLevel

logger = logging.getLogger(__name__)

_PROFILE_LOGICAL: str = "ws:browser_profile"


def _launch_edge_process(user_data_dir_real: str, endpoint: str) -> None:
    """以调试参数启动 Edge（不等待退出，Edge 常驻）。"""
    port: str = endpoint.rsplit(":", 1)[-1] if ":" in endpoint else "9222"
    cmd: list[str] = [
        _connection.edge_executable_path(),  # type: ignore[arg-type] — 调用方已确保非 None
        f"--remote-debugging-port={port}",
        f"--user-data-dir={user_data_dir_real}",
        "--no-first-run",
        "--no-default-browser-check",
    ]
    # 重定向输出避免管道积压阻塞子进程；参数全部受控，无 shell 注入面。
    subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)  # nosec B603


async def _handle_browser_launch(args: dict[str, Any]) -> dict:
    endpoint: str = str(args.get("endpoint", "")).strip() or _connection.CDP_ENDPOINT_DEFAULT
    timeout: int = int(args.get("timeout", 20))

    # 幂等：端口已就绪（无论由谁拉起）直接返回
    if await asyncio.to_thread(_connection.probe_cdp_endpoint, endpoint, 2.0):
        return tool_result(launched=True, already_running=True, endpoint=endpoint)

    exe: str | None = _connection.edge_executable_path()
    if exe is None:
        return tool_error(
            "未找到 Edge 可执行文件。请安装 Microsoft Edge，或手动以调试参数启动浏览器。",
            searched=list(_connection.EDGE_CANDIDATE_PATHS),
        )

    resolved = _get_sandbox().resolve_write(_PROFILE_LOGICAL)
    resolved.real.mkdir(parents=True, exist_ok=True)
    _launch_edge_process(str(resolved.real), endpoint)
    logger.info("browser_launch: started Edge, user-data-dir=%s, endpoint=%s", resolved.real, endpoint)

    if not await _connection.wait_for_endpoint(endpoint, timeout_s=float(timeout)):
        return tool_error(
            "Edge 已启动但 CDP 端口在规定时间内未就绪。请检查是否已有另一个实例占用了该 user-data-dir 或端口。",
            endpoint=endpoint,
            user_data_dir=_PROFILE_LOGICAL,
        )

    return tool_result(
        launched=True,
        already_running=False,
        endpoint=endpoint,
        user_data_dir=_PROFILE_LOGICAL,
    )


registry.register(
    name="browser_launch",
    toolset="browser",
    schema={
        # 以调试参数启动 Edge（幂等：端口已就绪时直接返回）。
        # profile（user-data-dir）持久化在 agentspace（ws:browser_profile），
        # 登录态、Cookie 跨会话保留；调试实例与日常 Edge 并存；
        # 不打开任何具体页面。Chromium 136+ 必须配合非默认 user-data-dir
        # 调试端口才会监听，本工具已自动处理。
        #
        # ## 前置条件
        # - 系统已安装 Microsoft Edge（自动探测两个标准安装路径）。
        # - 端口 9222 未被其他进程占用。
        #
        # ## 调用效果
        # 若 CDP 端点已可达 → 直接返回 already_running=true（不重复拉起）。
        # 否则启动 Edge（--remote-debugging-port + --user-data-dir=ws:browser_profile
        # 解析出的 agentspace 路径），轮询等待端口就绪（默认 20s）后返回。
        # 后续可调用 browser_connect 建立连接。
        #
        # ## 返回
        # ```json
        # {"launched": true, "already_running": false, "endpoint": "http://localhost:9222", "user_data_dir": "ws:browser_profile"}
        # ```
        #
        # ## 何时使用
        # - 首次使用 browser 工具组、或检测到端口不可达时，先于 browser_connect 调用。
        #
        # ## 副作用/注意
        # - 需用户审批（dangerous）：启动带调试端口的浏览器进程并暴露本机调试端口。
        # - profile 数据（登录态等）持久化在 agentspace 中，删除 ws:browser_profile 即重置。
        "description": """Starts Edge with debug flags so the browser toolset can take it over (idempotent: returns immediately if the CDP endpoint is already reachable).

## Prerequisites
- Microsoft Edge must be installed (two standard install paths are auto-detected).
- Port 9222 must not be occupied by another process.

## Effect
If the CDP endpoint is already reachable, returns `already_running: true` without launching a duplicate. Otherwise starts Edge with --remote-debugging-port plus --user-data-dir pointing at the agentspace path resolved from ws:browser_profile (Chromium 136+ silently ignores the debug port on the default user data directory — this tool handles that automatically). Polls until the port is ready (default 20s) and returns. Call browser_connect afterwards to attach.

## Returns
```json
{"launched": true, "already_running": false, "endpoint": "http://localhost:9222", "user_data_dir": "ws:browser_profile"}
```

## When to Use
- First-time use of the browser toolset, or when the endpoint is unreachable — before browser_connect.

## Side Effects / Notes
- Requires user approval (dangerous): launches a browser process with a debug port exposed on the local machine.
- Profile data (login sessions, cookies) persists in the agentspace; deleting ws:browser_profile resets it.""",
        "parameters": {
            "type": "object",
            "properties": {
                "endpoint": {
                    "type": "string",
                    # CDP 端点。留空使用默认值 http://localhost:9222。
                    "description": "CDP endpoint. Leave empty to use the default http://localhost:9222.",
                    "default": "",
                },
                "timeout": {
                    "type": "integer",
                    # 等待端口就绪的秒数（默认 20）。
                    "description": "Seconds to wait for the CDP port to become ready (default 20).",
                    "default": 20,
                },
                "reason": {
                    "type": "string",
                    # 启动浏览器的原因（用于审批提示）。
                    "description": "The reason for launching the browser (shown in the approval prompt).",
                },
            },
            "required": [],
        },
    },
    handler=_handle_browser_launch,
    check_fn=_connection.playwright_available,
    is_async=True,
    emoji="🚀",
    danger_level=ToolDangerLevel.dangerous,
)