"""动态端点工具 — agent 为自身注册 HTTP POST 端点，供前端按钮触发回调。

属于 extools，注册入口为顶层 ``register_tools(registry, ui_events)``，由
ToolDiscoverySystem 显式调用。注册三个工具：

  - ``RegisterDynamicEndpoint``   — 注册端点，返回 URL
  - ``UnregisterDynamicEndpoint`` — 解除注册
  - ``ListDynamicEndpoints``      — 列出当前会话的端点

注册表持久化至 ``workspace/dynamic_endpoints.json``，进程重启后
按会话存在性恢复（已删除/无效会话的端点保留在磁盘但不加载）。

agent 获得 URL 后，在消息中输出包含 ``<script>`` 标签的 HTML
（触发 SafeHtml iframe 渲染路径），按钮点击时通过 fetch POST
触发端点，端点向该 agent 投递一条仅自身可见的系统消息。

POST body 支持两种内容载体：

  - ``message`` (str)：纯文本消息（向后兼容，watching service 等既有调用方使用）。
  - ``content`` (str | list[dict])：多模态有序混合内容，格式与聊天输入框一致——
    block 数组中每项为 ``{type:"text", text:"..."}``、
    ``{type:"image_url", image_url:{url:"data:image/...;base64,..."}}``、
    ``{type:"input_audio", input_audio:{data:"<base64>", format:"mp3"}}``、
    ``{type:"video_url", video_url:{url:"data:video/...;base64,..."}}``。
    也可以是纯字符串（等价于 ``message``）。

``content`` 优先于 ``message``；``content`` 为空数组或空白字符串时回退到 ``message``。
block 数组严格校验，任一 block 不合法返回 400 并指明 block 索引。
"""

from __future__ import annotations

import logging
from typing import Any

from abstract.tools.registry import ToolRegistry, tool_error, tool_result
from abstract.tools.ui_event_router import UIEventRouter
from entry.base_agent_loop import ToolContext
from entity.puretype import ToolAvailability, ToolDangerLevel, DynamicEndpointInfo
from system.application import Application
from component.dynamic_endpoints import DynamicEndpointSystem

logger = logging.getLogger(__name__)

# 动态端点状态由 DynamicEndpointSystem 唯一持有；本模块只保留工具协议适配。


# ── System适配入口 ─────────────────────────────────────────

def _endpoint_system() -> DynamicEndpointSystem:
    return Application.current().get_system(DynamicEndpointSystem)


def lookup_endpoint(endpoint_name: str) -> DynamicEndpointInfo | None:
    return _endpoint_system().lookup_endpoint(endpoint_name)


def list_session_endpoints(session_id: str, agent_name: str | None = None) -> list[dict[str, Any]]:
    return _endpoint_system().list_session_endpoints(session_id, agent_name)


def migrate_session_endpoints(old_sid: str, new_sid: str) -> int:
    return _endpoint_system().migrate_session_endpoints(old_sid, new_sid)


def cleanup_session_endpoints(session_id: str) -> int:
    return _endpoint_system().cleanup_session_endpoints(session_id)


# ── handler ─────────────────────────────────────────────────



async def _handle_register_dynamic_endpoint(
    args: dict[str, Any],
    context: ToolContext | None = None,
) -> dict:
    """注册一个动态 HTTP 端点，返回 URL 供 agent 在消息中渲染按钮。

    端点路径格式为 ``/dynamic/{session_id}/{agent_name}/{name}``。
    agent 获得 URL 后，在消息中输出包含 ``<script>`` 标签的 HTML
    （触发 SafeHtml iframe 渲染），按钮点击时通过 fetch POST 触发端点。

    POST body 支持两种内容载体：

    - ``message`` (str)：纯文本，投递格式为 ``[dynamic-endpoint] {name}\\n{message}``。
    - ``content`` (str | list[dict])：多模态有序混合内容，格式与聊天输入框一致——
      block 数组中每项为 ``{type:"text", text:"..."}``、
      ``{type:"image_url", image_url:{url:"data:image/...;base64,..."}}``、
      ``{type:"input_audio", input_audio:{data:"<base64>", format:"mp3"}}``、
      ``{type:"video_url", video_url:{url:"data:video/...;base64,..."}}``。
      也可以是纯字符串（等价于 ``message``）。

    ``content`` 优先于 ``message``；为空数组或空白字符串时回退到 ``message``。
    block 数组严格校验，任一 block 不合法返回 400 并指明 block 索引。
    """
    session_id: str = str(args.get("_session_id", ""))
    name: str = str(args.get("name", "")).strip()

    # 从 ToolContext 获取当前 agent 角色名
    # 从 ToolContext 获取当前 agent 角色名（由 ToolExecutor 注入）
    agent_name: str = ""
    if context is not None:
        try:
            agent_name = context.character_name
        except Exception:
            logger.warning("Failed to get agent name from context", exc_info=True)

    if not session_id:
        return tool_error("'_session_id' is required (injected by tool executor)")
    if not agent_name:
        return tool_error("Could not determine current agent name from context")
    if not name:
        return tool_error("'name' is required — it becomes part of the URL path")

    # 校验 name 只含路径安全字符
    safe_name = name.replace("/", "_").replace(" ", "-")
    if not safe_name or any(c in safe_name for c in "{}<>\"#?"):
        return tool_error(f"'name' contains invalid characters for URL path: {name!r}")

    info = _endpoint_system().register_endpoint(session_id, agent_name, safe_name)
    url: str = f"/dynamic/{session_id}/{agent_name}/{info.name}"

    from system.application import Application
    from system.runtime import RuntimeSystem
    ctx = Application.current().get_system(RuntimeSystem).context
    absolute_url: str = f"http://{ctx.gateway_host}:{ctx.gateway_port}{url}"

    logger.info(
        "Dynamic endpoint registered | name=%s session=%s agent=%s url=%s",
        safe_name, session_id, agent_name, url,
    )

    return tool_result(
        success=True,
        name=safe_name,
        url=url,
        absolute_url=absolute_url,
        agent_name=agent_name,
        _note=(
            f"Dynamic endpoint '{safe_name}' registered. POST to {absolute_url} to deliver a system message to yourself. "
            "Body accepts either {\"message\": \"text\"} (plain text) or "
            "{\"content\": [{\"type\": \"text\", \"text\": \"...\"}, {\"type\": \"image_url\", \"image_url\": {\"url\": \"data:image/...;base64,...\"}}, ...]} "
            "(multimodal blocks, same format as the chat input). 'content' takes priority over 'message'."
        ),
    )


async def _handle_unregister_dynamic_endpoint(
    args: dict[str, Any],
    context: ToolContext | None = None,  # noqa: ARG001 — 签名与 registry dispatch 一致
) -> dict:
    """解除注册指定端点，后续 POST 请求将返回 404。"""
    name: str = str(args.get("name", "")).strip()

    if not name:
        return tool_error("'name' is required")

    try:
        removed = _endpoint_system().unregister_endpoint(name)
    except LookupError:
        return tool_error(f"Endpoint not found: {name}")

    logger.info(
        "Dynamic endpoint unregistered | name=%s session=%s agent=%s",
        name, removed.session_id, removed.agent_name,
    )

    return tool_result(
        success=True,
        unregistered=True,
        name=name,
        message=f"Endpoint '{name}' unregistered. POST requests to it will now return 404.",
    )


async def _handle_list_dynamic_endpoints(
    args: dict[str, Any],
    context: ToolContext | None = None,
) -> dict:
    """列出当前会话中属于当前 agent 的动态端点。"""
    session_id: str = str(args.get("_session_id", ""))

    if not session_id:
        return tool_error("'_session_id' is required (injected by tool executor)")

    # 从 ToolContext 获取当前 agent 角色名（由 ToolExecutor 注入）
    character_name: str = ""
    if context is not None:
        try:
            character_name = context.character_name
        except Exception:
            logger.warning("Failed to get agent name from context", exc_info=True)

    endpoints = list_session_endpoints(session_id, agent_name=character_name or None)

    return tool_result(success=True, count=len(endpoints), endpoints=endpoints)


# ── 注册 ─────────────────────────────────────────────────────


def register_tools(registry: ToolRegistry, ui_events: UIEventRouter) -> None:
    """Register dynamic endpoint tools into the explicit runtime registry."""
    del ui_events
    registry.register(
        name="RegisterDynamicEndpoint",
        toolset="dynamic",
        schema={
            # 注册一个动态 HTTP POST 端点，返回 URL 供 agent 在消息中渲染可点击按钮。
            #
            # ## 前置条件
            # 无特殊前置条件，任意会话中的 agent 均可调用。
            # 当前 agent 角色名和 session_id 从 ToolContext 自动获取，无需传入。
            #
            # ## 调用效果
            # 在注册表中创建一条端点记录，路径格式为
            # /dynamic/{session_id}/{agent_name}/{endpoint_id}。
            # 注册表持久化至 workspace/dynamic_endpoints.json，
            # 进程重启后按会话存在性恢复，unregister 后端点立即失效。
            #
            # ## 返回
            # ```json
            # {"success": true, "name": "my-button", "url": "/dynamic/sid/agent/my-button", "absolute_url": "http://127.0.0.1:8765/dynamic/sid/agent/my-button", "agent_name": "...", "message": "..."}
            # ```
            #
            # ## 何时使用
            # - 需要用户通过点击按钮触发回调时。
            # - 需要向自己投递一条自定义内容的系统消息时。
            #
            # ## 副作用/注意
            # - 注册写入持久化文件（workspace 下），重启后可恢复。
            # - agent 输出按钮时必须包含 <script> 标签才能触发 SafeHtml iframe 渲染路径，
            #   纯 <button onclick="..."> 不含 <script> 时走 ReactMarkdown 路径，onclick 不生效。
            # - POST body 支持两种内容载体：
            #   message (str)：纯文本消息（向后兼容，watching service 等既有调用方使用）。
            #   content (str | list[dict])：多模态有序混合内容，格式与聊天输入框一致——
            #     block 数组中每项为 {type:"text", text:"..."}、
            #     {type:"image_url", image_url:{url:"data:image/...;base64,..."}}、
            #     {type:"input_audio", input_audio:{data:"<base64>", format:"mp3"}}、
            #     {type:"video_url", video_url:{url:"data:video/...;base64,..."}}。
            #     也可以是纯字符串（等价于 message）。
            # - content 优先于 message；content 为空数组或空白字符串时回退到 message。
            # - block 数组严格校验，任一 block 不合法返回 400 并指明 block 索引。
            # - 投递的消息格式为 [dynamic-endpoint] {endpoint_id}\n{message}；
            #   使用 content block 数组时，前缀作为独立的首个 text block 注入。
            # - 端点无鉴权，与现有 API 一致（localhost 信任模型）。
            "description": """Register a dynamic HTTP POST endpoint that delivers a self-visible system message when triggered.

## Prerequisites
No special prerequisites. Any agent in any session can call this. The current agent name and session_id are automatically obtained from the ToolContext.

## Effect
Creates an endpoint registration with path format /dynamic/{session_id}/{agent_name}/{name}. The registry is persisted to workspace/dynamic_endpoints.json; endpoints are restored on process restart for still-existing sessions, and unregister_dynamic_endpoint removes them immediately.

## Returns
```json
{"success": true, "name": "my-button", "url": "/dynamic/sid/agent/my-button", "absolute_url": "http://127.0.0.1:8765/dynamic/sid/agent/my-button", "agent_name": "...", "message": "..."}
```

## When to Use
- When you need the user to trigger a callback by clicking a button.
- When you need to deliver a custom-content system message to yourself.

## Side Effects / Notes
- Registration is persisted to disk (workspace/dynamic_endpoints.json) and restored after restart.
- When outputting a button, you MUST include a <script> tag in the HTML to trigger the SafeHtml iframe rendering path. A bare <button onclick="..."> without <script> goes through ReactMarkdown where onclick does not work.
- POST body accepts two content carriers:
  - `message` (str): plain text message (backward compatible, used by watching service and other existing callers).
  - `content` (str | list[dict]): multimodal ordered mixed content, same format as the chat input — each block is {"type": "text", "text": "..."}, {"type": "image_url", "image_url": {"url": "data:image/...;base64,..."}}, {"type": "input_audio", "input_audio": {"data": "<base64>", "format": "mp3"}}, or {"type": "video_url", "video_url": {"url": "data:video/...;base64,..."}}. Can also be a plain string (equivalent to `message`).
  In an iframe button page, use FileReader.readAsDataURL to construct data URLs from user-selected files.
- `content` takes priority over `message`; when both are provided, `message` is ignored. An empty array or blank string falls back to `message`.
- Block arrays are strictly validated; any invalid block returns 400 with the block index in the error.
- The delivered message format is: [dynamic-endpoint] {name}\\n{message}; when using `content` blocks, the prefix is injected as a separate leading text block.
- Endpoints have no authentication, consistent with existing APIs (localhost trust model).
- Use unregister_dynamic_endpoint to remove the endpoint when no longer needed.""",
            "parameters": {
                "type": "object",
                "properties": {
                    "reason": {
                        "type": "string",
                        # 注册此端点的原因说明。
                        "description": """Reason for registering this dynamic endpoint.""",
                    },
                    "name": {
                        "type": "string",
                        # 端点名称，直接作为 URL 路径段。同一 session+agent 下必须唯一。
                        "description": """Name for the endpoint, used directly as the URL path segment (/dynamic/{session_id}/{agent_name}/{name}). Must be unique per session+agent. Allowed characters: alphanumeric, hyphens, underscores.""",
                    },
                },
                "required": ["reason", "name"],
            },
        },
        handler=_handle_register_dynamic_endpoint,
        is_async=True,
        danger_level=ToolDangerLevel.safe,
        availability=ToolAvailability.MAIN | ToolAvailability.MULTI_AGENT,
    )

    registry.register(
        name="UnregisterDynamicEndpoint",
        toolset="dynamic",
        schema={
            # 解除注册指定端点，后续 POST 请求将返回 404。
            #
            # ## 前置条件
            # name 必须是由 register_dynamic_endpoint 注册的有效端点名称。
            #
            # ## 调用效果
            # 从注册表删除该端点并同步移除持久化记录，
            # 后续 POST 请求将因找不到注册而返回 404。
            #
            # ## 返回
            # ```json
            # {"success": true, "unregistered": true, "name": "my-button", "message": "..."}
            # ```
            #
            # ## 何时使用
            # - 端点不再需要时。
            # - 防止旧端点被意外触发时。
            #
            # ## 副作用/注意
            # - 同时从持久化文件（workspace 下）删除该记录。
            # - 已经发出的 POST 请求不受影响（在途请求仍会处理）。
            "description": """Unregister a dynamic endpoint by its name. Subsequent POST requests to it will return 404.

## Prerequisites
name must be a valid endpoint name returned by register_dynamic_endpoint.

## Effect
Removes the endpoint from the registry and its persisted record. Subsequent POST requests will fail with 404 because the endpoint no longer exists.

## Returns
```json
{"success": true, "unregistered": true, "name": "my-button", "message": "..."}
```

## When to Use
- When the endpoint is no longer needed.
- To prevent stale endpoints from being accidentally triggered.

## Side Effects / Notes
- The persisted record is also removed from disk; the endpoint cannot be restored after restart.
- In-flight POST requests that have already been received are not affected.""",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        # register_dynamic_endpoint 注册时使用的端点名称。
                        "description": """Name of the endpoint to unregister (same name used in register_dynamic_endpoint).""",
                    },
                },
                "required": ["name"],
            },
        },
        handler=_handle_unregister_dynamic_endpoint,
        is_async=True,
        danger_level=ToolDangerLevel.safe,
        availability=ToolAvailability.MAIN | ToolAvailability.MULTI_AGENT,
    )

    registry.register(
        name="ListDynamicEndpoints",
        toolset="dynamic",
        schema={
            # 列出当前 agent 自己注册的动态端点（按 agent 过滤，看不到其他 agent 的端点）。
            #
            # ## 前置条件
            # 无。
            #
            # ## 调用效果
            # 返回当前 agent 自己注册的所有动态端点，包括 name、url 等信息。
            # 在多 agent 模式下，只能看到自己注册的端点，看不到其他 agent 的端点。
            #
            # ## 返回
            # ```json
            # {"success": true, "count": 2, "endpoints": [{"name": "...", "url": "/dynamic/sid/agent/eid", "absolute_url": "http://127.0.0.1:8765/dynamic/sid/agent/eid", "agent_name": "...", "created_at": 1234567890}]}
            # ```
            #
            # ## 何时使用
            # - 查看自己当前有哪些动态端点。
            # - 获取 endpoint_id 以便取消注册。
            #
            # ## 副作用/注意
            # - 纯查询，不会修改端点状态。
            # - 只返回当前 agent 自己注册的端点，不含其他 agent 的端点。
            "description": """List dynamic endpoints registered by the current agent (not all agents' endpoints).

## Prerequisites
None.

## Effect
Returns metadata for all dynamic endpoints registered by the current agent, including endpoint_id, name, url, agent_name, and created_at. In multi-agent mode, only the current agent's own endpoints are returned; other agents' endpoints are not visible.

## Returns
```json
{"success": true, "count": 2, "endpoints": [{"name": "...", "url": "/dynamic/sid/agent/eid", "absolute_url": "http://127.0.0.1:8765/dynamic/sid/agent/eid", "agent_name": "...", "created_at": 1234567890}]}
```

## When to Use
- Check what dynamic endpoints you have registered.
- Obtain endpoint_id values for unregister_dynamic_endpoint.

## Side Effects / Notes
- Read-only query; does not modify endpoint state.
- Only returns the current agent's own endpoints, not those of other agents.""",
            "parameters": {
                "type": "object",
                "properties": {},
            },
        },
        handler=_handle_list_dynamic_endpoints,
        is_async=True,
        danger_level=ToolDangerLevel.safe,
        availability=ToolAvailability.MAIN | ToolAvailability.MULTI_AGENT,
    )
