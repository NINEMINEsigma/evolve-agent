"""动态端点工具 — agent 为自身注册 HTTP POST 端点，供前端按钮触发回调。

属于 extools，模块导入时通过 ``registry.register()`` 注册两个工具：

  - ``register_dynamic_endpoint``   — 注册端点，返回 URL
  - ``unregister_dynamic_endpoint`` — 解除注册

注册表为内存态，不持久化，进程重启后端点失效。
会话删除时自动清理关联端点。

agent 获得 URL 后，在消息中输出包含 ``<script>`` 标签的 HTML
（触发 SafeHtml iframe 渲染路径），按钮点击时通过 fetch POST
触发端点，端点向该 agent 投递一条仅自身可见的系统消息，
消息内容由 POST body 的 ``message`` 字段动态携带。
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from typing import Any

from abstract.tools.registry import registry, tool_error, tool_result
from entry.base_agent_loop import ToolContext
from entity.puretype import ToolAvailability, ToolDangerLevel

logger = logging.getLogger(__name__)

# ── 内存注册表 ───────────────────────────────────────────────
# endpoint_id → {"session_id": str, "agent_name": str, "created_at": float}
# 不持久化，进程重启后全部失效。

_dynamic_endpoints: dict[str, dict[str, Any]] = {}
_endpoint_lock = threading.Lock()


# ── 公开 API（供 gateway/server.py 调用）────────────────────


def lookup_endpoint(endpoint_id: str) -> dict[str, Any] | None:
    """查注册表，返回 ``{session_id, agent_name, created_at}`` 或 ``None``。

    线程安全，持锁读取后立即释放。
    """
    with _endpoint_lock:
        return _dynamic_endpoints.get(endpoint_id)


def cleanup_session_endpoints(session_id: str) -> int:
    """清理指定会话的所有动态端点，返回清理数量。

    在 ``delete_session`` 时调用，防止端点悬空。
    """
    count = 0
    with _endpoint_lock:
        to_remove = [
            eid for eid, info in _dynamic_endpoints.items()
            if info.get("session_id") == session_id
        ]
        for eid in to_remove:
            _dynamic_endpoints.pop(eid, None)
            count += 1
    if count:
        logger.info(
            "Cleaned up %d dynamic endpoints for session=%s", count, session_id,
        )
    return count


# ── handler ─────────────────────────────────────────────────


async def _handle_register_dynamic_endpoint(
    args: dict[str, Any],
    context: ToolContext | None = None,
) -> dict:
    """注册一个动态 HTTP 端点，返回 URL 供 agent 在消息中渲染按钮。

    端点路径格式为 ``/dynamic/{session_id}/{agent_name}/{endpoint_id}``。
    agent 获得 URL 后，在消息中输出包含 ``<script>`` 标签的 HTML
    （触发 SafeHtml iframe 渲染），按钮点击时 ``fetch(url, {method:'POST', body: JSON.stringify({message: '...'})})``
    触发端点，端点向该 agent 投递一条格式为
    ``[dynamic-endpoint] {endpoint_id}\\n{message}`` 的系统消息。
    """
    session_id: str = str(args.get("_session_id", ""))

    # 从 ToolContext 获取当前 agent 角色名
    agent_name: str = ""
    if context is not None:
        try:
            agent_name = context.loop.current_character_agent
        except Exception:
            logger.warning("Failed to get current_character_agent from context", exc_info=True)

    if not session_id:
        return tool_error("'_session_id' is required (injected by tool executor)")
    if not agent_name:
        return tool_error("Could not determine current agent name from context")

    endpoint_id: str = uuid.uuid4().hex[:12]
    url: str = f"/dynamic/{session_id}/{agent_name}/{endpoint_id}"

    with _endpoint_lock:
        _dynamic_endpoints[endpoint_id] = {
            "session_id": session_id,
            "agent_name": agent_name,
            "created_at": time.time(),
        }

    logger.info(
        "Dynamic endpoint registered | endpoint=%s session=%s agent=%s url=%s",
        endpoint_id, session_id, agent_name, url,
    )

    return tool_result(
        success=True,
        endpoint_id=endpoint_id,
        url=url,
        agent_name=agent_name,
        message=f"Dynamic endpoint registered. POST to {url} with body {{\"message\": \"...\"}} to deliver a system message to yourself.",
    )


async def _handle_unregister_dynamic_endpoint(
    args: dict[str, Any],
    context: ToolContext | None = None,  # noqa: ARG001 — 签名与 registry dispatch 一致
) -> dict:
    """解除注册指定端点，后续 POST 请求将返回 404。"""
    endpoint_id: str = str(args.get("endpoint_id", "")).strip()

    if not endpoint_id:
        return tool_error("'endpoint_id' is required")

    with _endpoint_lock:
        removed = _dynamic_endpoints.pop(endpoint_id, None)

    if removed is None:
        return tool_error(f"Endpoint not found: {endpoint_id}")

    logger.info(
        "Dynamic endpoint unregistered | endpoint=%s session=%s agent=%s",
        endpoint_id, removed.get("session_id"), removed.get("agent_name"),
    )

    return tool_result(
        success=True,
        unregistered=True,
        endpoint_id=endpoint_id,
        message=f"Endpoint {endpoint_id} unregistered. POST requests to it will now return 404.",
    )


# ── 注册 ─────────────────────────────────────────────────────

registry.register(
    name="register_dynamic_endpoint",
    toolset="dynamic",
    schema={
        # 注册一个动态 HTTP POST 端点，返回 URL 供 agent 在消息中渲染可点击按钮。
        #
        # ## 前置条件
        # 无特殊前置条件，任意会话中的 agent 均可调用。
        # 当前 agent 角色名和 session_id 从 ToolContext 自动获取，无需传入。
        #
        # ## 调用效果
        # 在内存注册表中创建一条端点记录，路径格式为
        # /dynamic/{session_id}/{agent_name}/{endpoint_id}。
        # 注册表为内存态，进程重启后失效，会话删除时自动清理。
        #
        # ## 返回
        # ```json
        # {"success": true, "endpoint_id": "abc123", "url": "/dynamic/sid/agent/abc123", "agent_name": "...", "message": "..."}
        # ```
        #
        # ## 何时使用
        # - 需要用户通过点击按钮触发回调时。
        # - 需要向自己投递一条自定义内容的系统消息时。
        #
        # ## 副作用/注意
        # - 仅内存写入，无持久化副作用。
        # - agent 输出按钮时必须包含 <script> 标签才能触发 SafeHtml iframe 渲染路径，
        #   纯 <button onclick="..."> 不含 <script> 时走 ReactMarkdown 路径，onclick 不生效。
        # - POST body 的 message 字段会成为投递给 agent 的消息内容。
        # - 投递的消息格式为 [dynamic-endpoint] {endpoint_id}\n{message}。
        # - 端点无鉴权，与现有 API 一致（localhost 信任模型）。
        "description": """Register a dynamic HTTP POST endpoint that delivers a self-visible system message when triggered.

## Prerequisites
No special prerequisites. Any agent in any session can call this. The current agent name and session_id are automatically obtained from the ToolContext.

## Effect
Creates an in-memory endpoint registration with path format /dynamic/{session_id}/{agent_name}/{endpoint_id}. The registry is memory-only; endpoints are lost on process restart and auto-cleaned when the session is deleted.

## Returns
```json
{"success": true, "endpoint_id": "abc123", "url": "/dynamic/sid/agent/abc123", "agent_name": "...", "message": "..."}
```

## When to Use
- When you need the user to trigger a callback by clicking a button.
- When you need to deliver a custom-content system message to yourself.

## Side Effects / Notes
- Memory-only write, no persistence side effects.
- When outputting a button, you MUST include a <script> tag in the HTML to trigger the SafeHtml iframe rendering path. A bare <button onclick="..."> without <script> goes through ReactMarkdown where onclick does not work.
- The POST body's `message` field becomes the message content delivered to the agent.
- The delivered message format is: [dynamic-endpoint] {endpoint_id}\\n{message}.
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
            },
            "required": ["reason"],
        },
    },
    handler=_handle_register_dynamic_endpoint,
    is_async=True,
    emoji="🔌",
    danger_level=ToolDangerLevel.readonly,
    availability=ToolAvailability.MAIN | ToolAvailability.MULTI_AGENT,
)

registry.register(
    name="unregister_dynamic_endpoint",
    toolset="dynamic",
    schema={
        # 解除注册指定端点，后续 POST 请求将返回 404。
        #
        # ## 前置条件
        # endpoint_id 必须是由 register_dynamic_endpoint 返回的有效 ID。
        #
        # ## 调用效果
        # 从内存注册表中删除该端点，后续 POST 请求将因找不到注册而返回 404。
        #
        # ## 返回
        # ```json
        # {"success": true, "unregistered": true, "endpoint_id": "abc123", "message": "..."}
        # ```
        #
        # ## 何时使用
        # - 端点不再需要时。
        # - 防止旧端点被意外触发时。
        #
        # ## 副作用/注意
        # - 仅内存操作，无持久化影响。
        # - 已经发出的 POST 请求不受影响（在途请求仍会处理）。
        "description": """Unregister a dynamic endpoint by its endpoint_id. Subsequent POST requests to it will return 404.

## Prerequisites
endpoint_id must be a valid ID returned by register_dynamic_endpoint.

## Effect
Removes the endpoint from the in-memory registry. Subsequent POST requests will fail with 404 because the endpoint no longer exists.

## Returns
```json
{"success": true, "unregistered": true, "endpoint_id": "abc123", "message": "..."}
```

## When to Use
- When the endpoint is no longer needed.
- To prevent stale endpoints from being accidentally triggered.

## Side Effects / Notes
- Memory-only operation, no persistence impact.
- In-flight POST requests that have already been received are not affected.""",
        "parameters": {
            "type": "object",
            "properties": {
                "endpoint_id": {
                    "type": "string",
                    # register_dynamic_endpoint 返回的端点 ID。
                    "description": """endpoint_id returned by register_dynamic_endpoint.""",
                },
            },
            "required": ["endpoint_id"],
        },
    },
    handler=_handle_unregister_dynamic_endpoint,
    is_async=True,
    emoji="✂",
    danger_level=ToolDangerLevel.readonly,
    availability=ToolAvailability.MAIN | ToolAvailability.MULTI_AGENT,
)