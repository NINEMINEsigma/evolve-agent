"""动态端点工具 — agent 为自身注册 HTTP POST 端点，供前端按钮触发回调。

属于 extools，模块导入时通过 ``registry.register()`` 注册三个工具：

  - ``register_dynamic_endpoint``   — 注册端点，返回 URL
  - ``unregister_dynamic_endpoint`` — 解除注册
  - ``list_dynamic_endpoints``      — 列出当前会话的端点

注册表持久化至 ``workspace/dynamic_endpoints.json``，进程重启后
按会话存在性恢复（已删除/无效会话的端点保留在磁盘但不加载）。

agent 获得 URL 后，在消息中输出包含 ``<script>`` 标签的 HTML
（触发 SafeHtml iframe 渲染路径），按钮点击时通过 fetch POST
触发端点，端点向该 agent 投递一条仅自身可见的系统消息，
消息内容由 POST body 的 ``message`` 字段动态携带。
"""

from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path
from typing import Any

from abstract.tools.registry import registry, tool_error, tool_result
from entry.base_agent_loop import ToolContext
from entity.constant import DYNAMIC_ENDPOINTS_STORE_FILENAME
from entity.puretype import ToolAvailability, ToolDangerLevel, DynamicEndpointInfo
from system.atomic_io import write_text_atomic

logger = logging.getLogger(__name__)

# ── 内存注册表 ───────────────────────────────────────────────
# endpoint_name → DynamicEndpointInfo
# 磁盘镜像：workspace/dynamic_endpoints.json（name-keyed dict）。
# key 是 endpoint name（即 URL 路径段），全局唯一。

_dynamic_endpoints: dict[str, DynamicEndpointInfo] = {}
_endpoint_lock = threading.Lock()


# ── 公开 API（供 gateway/server.py 调用）────────────────────


def lookup_endpoint(endpoint_name: str) -> DynamicEndpointInfo | None:
    """查注册表，返回 ``DynamicEndpointInfo`` 或 ``None``。

    线程安全，持锁读取后立即释放。
    """
    with _endpoint_lock:
        return _dynamic_endpoints.get(endpoint_name)


# ── 持久化 ──────────────────────────────────────────────────


def _get_dynamic_endpoints_store_path() -> Path:
    """返回动态端点持久化文件路径。

    从 ``RuntimeContext.workspace`` 获取实际工作空间路径。
    RuntimeContext 未初始化时抛出 RuntimeError。
    """
    from system.context import get_runtime_context

    ctx = get_runtime_context()
    return ctx.workspace / DYNAMIC_ENDPOINTS_STORE_FILENAME


def _save_all_endpoints() -> None:
    """将内存注册表持久化到磁盘（原子写入）。

    合并式写盘：读现有磁盘文件，保留其中不在内存的幽灵条目
    （属于已删除/无效会话，恢复时被过滤跳过的部分），与内存条目
    合并后整体写回 — 保证"资源保留在硬盘上"的语义，unregister
    的显式删除走 ``_delete_endpoint_on_disk``。

    磁盘 schema：``{"<name>": {"session_id": ..., "agent_name": ..., "name": ..., "created_at": ...}}``，
    同名 key 以内存条目为准（覆盖磁盘）。
    """
    try:
        store_path = _get_dynamic_endpoints_store_path()
        store_path.parent.mkdir(parents=True, exist_ok=True)
        with _endpoint_lock:
            payload: dict[str, dict[str, Any]] = {}
            for eid, info in _dynamic_endpoints.items():
                payload[eid] = info.model_dump()
            # 保留磁盘上未加载的幽灵条目
            if store_path.exists():
                try:
                    raw: dict = json.loads(store_path.read_text(encoding="utf-8"))
                    for eid, data in raw.items():
                        if eid not in payload:
                            payload[eid] = data
                except Exception:
                    logger.warning("Failed to read existing dynamic endpoints store, skipping ghost merge", exc_info=True)
            write_text_atomic(
                store_path,
                json.dumps(payload, ensure_ascii=False, indent=2),
                tmp_suffix=".tmp",
            )
    except Exception as exc:
        logger.error("Failed to save dynamic endpoints: %s", exc)


def _delete_endpoint_on_disk(name: str) -> None:
    """从磁盘持久化文件显式删除单条记录（unregister 专用）。

    与 ``_save_all_endpoints`` 的合并语义配合：若走合并式写盘，
    被 unregister 的条目会被当作幽灵条目保留，故此处显式删除。
    """
    try:
        store_path = _get_dynamic_endpoints_store_path()
        if not store_path.exists():
            return
        with _endpoint_lock:
            raw: dict = json.loads(store_path.read_text(encoding="utf-8"))
            removed = raw.pop(name, None)
            if removed is None:
                return
            write_text_atomic(
                store_path,
                json.dumps(raw, ensure_ascii=False, indent=2),
                tmp_suffix=".tmp",
            )
    except Exception as exc:
        logger.warning("Failed to delete dynamic endpoint %s from disk: %s", name, exc)


def _load_all_endpoints() -> None:
    """进程重启后从磁盘恢复动态端点。

    恢复时检查会话是否存在：仅加载 ``Application.current().session_manager.exists(sid)``
    为真的端点；已删除/无效会话的条目跳过加载，但保留在磁盘文件中，
    待下一次写盘时作为幽灵条目留存。
    """
    try:
        store_path = _get_dynamic_endpoints_store_path()
    except RuntimeError:
        return
    if not store_path.exists():
        return
    try:
        raw: dict = json.loads(store_path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("Failed to load dynamic endpoints: %s", exc)
        return

    from system.application import Application
    sm = Application.current().session_manager
    restored = 0
    skipped = 0
    with _endpoint_lock:
        for eid, data in raw.items():
            try:
                info = DynamicEndpointInfo.model_validate(data)
                if sm is not None and sm.exists(info.session_id):
                    _dynamic_endpoints[eid] = info
                    restored += 1
                else:
                    skipped += 1
            except Exception as exc:
                logger.warning("Failed to restore dynamic endpoint %s: %s", eid, exc)
    if restored or skipped:
        logger.info(
            "Dynamic endpoints restored | loaded=%d skipped=%d (invalid/deleted sessions, kept on disk)",
            restored, skipped,
        )


# ── 会话级查询与迁移 ────────────────────────────────────────


def list_session_endpoints(session_id: str) -> list[dict[str, Any]]:
    """返回指定会话的所有动态端点（序列化列表，供 API 层消费）。

    返回 ``[{name, url, agent_name, created_at}]``，url 由会话与角色派生。
    线程安全，持锁读取后立即释放。
    """
    with _endpoint_lock:
        return [
            {
                "name": info.name,
                "url": f"/dynamic/{info.session_id}/{info.agent_name}/{info.name}",
                "agent_name": info.agent_name,
                "created_at": info.created_at,
            }
            for info in _dynamic_endpoints.values()
            if info.session_id == session_id
        ]


def migrate_session_endpoints(old_sid: str, new_sid: str) -> int:
    """将会话旋转（上下文超限续写）时的动态端点迁移到继承会话。

    仅更新条目 ``session_id`` 字段（key 不变），随后持久化。
    手动终结（terminate）路径不调用本函数，端点不继承。
    """
    count = 0
    with _endpoint_lock:
        for info in _dynamic_endpoints.values():
            if info.session_id == old_sid:
                info.session_id = new_sid
                count += 1
    if count:
        logger.info(
            "Migrated %d dynamic endpoints | old=%s new=%s", count, old_sid, new_sid,
        )
        _save_all_endpoints()
    return count


# ── handler ─────────────────────────────────────────────────


async def _handle_register_dynamic_endpoint(
    args: dict[str, Any],
    context: ToolContext | None = None,
) -> dict:
    """注册一个动态 HTTP 端点，返回 URL 供 agent 在消息中渲染按钮。

    端点路径格式为 ``/dynamic/{session_id}/{agent_name}/{name}``。
    agent 获得 URL 后，在消息中输出包含 ``<script>`` 标签的 HTML
    （触发 SafeHtml iframe 渲染），按钮点击时 ``fetch(url, {method:'POST', body: JSON.stringify({message: '...'})})``
    触发端点，端点向该 agent 投递一条格式为
    ``[dynamic-endpoint] {name}\\n{message}`` 的系统消息。
    """
    session_id: str = str(args.get("_session_id", ""))
    name: str = str(args.get("name", "")).strip()

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
    if not name:
        return tool_error("'name' is required — it becomes part of the URL path")

    # 校验 name 只含路径安全字符
    safe_name = name.replace("/", "_").replace(" ", "-")
    if not safe_name or any(c in safe_name for c in "{}<>\"#?"):
        return tool_error(f"'name' contains invalid characters for URL path: {name!r}")

    # 同一 session+agent 下 name 必须唯一
    with _endpoint_lock:
        for info in _dynamic_endpoints.values():
            if (info.session_id == session_id
                    and info.agent_name == agent_name
                    and info.name == safe_name):
                return tool_error(
                    f"Endpoint name '{safe_name}' already registered for this session+agent"
                )

        _dynamic_endpoints[safe_name] = DynamicEndpointInfo(
            session_id=session_id,
            agent_name=agent_name,
            name=safe_name,
            created_at=time.time(),
        )

    _save_all_endpoints()

    url: str = f"/dynamic/{session_id}/{agent_name}/{safe_name}"

    logger.info(
        "Dynamic endpoint registered | name=%s session=%s agent=%s url=%s",
        safe_name, session_id, agent_name, url,
    )

    return tool_result(
        success=True,
        name=safe_name,
        url=url,
        agent_name=agent_name,
        message=f"Dynamic endpoint '{safe_name}' registered. POST to {url} with body {{\"message\": \"...\"}} to deliver a system message to yourself.",
    )


async def _handle_unregister_dynamic_endpoint(
    args: dict[str, Any],
    context: ToolContext | None = None,  # noqa: ARG001 — 签名与 registry dispatch 一致
) -> dict:
    """解除注册指定端点，后续 POST 请求将返回 404。"""
    name: str = str(args.get("name", "")).strip()

    if not name:
        return tool_error("'name' is required")

    with _endpoint_lock:
        removed = _dynamic_endpoints.pop(name, None)

    if removed is None:
        return tool_error(f"Endpoint not found: {name}")

    _delete_endpoint_on_disk(name)

    # 级联停止引用此端点的 watching service
    try:
        from component.extools.bg_registry import stop_watching_by_endpoint
        stopped_count = stop_watching_by_endpoint(name)
        if stopped_count:
            logger.info(
                "Cascade stopped %d watching service(s) for endpoint %s",
                stopped_count, name,
            )
    except Exception:
        logger.warning("Failed to cascade stop watching services for %s", name, exc_info=True)

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
    context: ToolContext | None = None,  # noqa: ARG001 — 签名与 registry dispatch 一致
) -> dict:
    """列出当前会话的所有动态端点。"""
    session_id: str = str(args.get("_session_id", ""))

    if not session_id:
        return tool_error("'_session_id' is required (injected by tool executor)")

    endpoints = list_session_endpoints(session_id)

    return tool_result(success=True, count=len(endpoints), endpoints=endpoints)


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
        # 在注册表中创建一条端点记录，路径格式为
        # /dynamic/{session_id}/{agent_name}/{endpoint_id}。
        # 注册表持久化至 workspace/dynamic_endpoints.json，
        # 进程重启后按会话存在性恢复，unregister 后端点立即失效。
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
        # - 注册写入持久化文件（workspace 下），重启后可恢复。
        # - agent 输出按钮时必须包含 <script> 标签才能触发 SafeHtml iframe 渲染路径，
        #   纯 <button onclick="..."> 不含 <script> 时走 ReactMarkdown 路径，onclick 不生效。
        # - POST body 的 message 字段会成为投递给 agent 的消息内容。
        # - 投递的消息格式为 [dynamic-endpoint] {endpoint_id}\n{message}。
        # - 端点无鉴权，与现有 API 一致（localhost 信任模型）。
        "description": """Register a dynamic HTTP POST endpoint that delivers a self-visible system message when triggered.

## Prerequisites
No special prerequisites. Any agent in any session can call this. The current agent name and session_id are automatically obtained from the ToolContext.

## Effect
Creates an endpoint registration with path format /dynamic/{session_id}/{agent_name}/{name}. The registry is persisted to workspace/dynamic_endpoints.json; endpoints are restored on process restart for still-existing sessions, and unregister_dynamic_endpoint removes them immediately.

## Returns
```json
{"success": true, "name": "my-button", "url": "/dynamic/sid/agent/my-button", "agent_name": "...", "message": "..."}
```

## When to Use
- When you need the user to trigger a callback by clicking a button.
- When you need to deliver a custom-content system message to yourself.

## Side Effects / Notes
- Registration is persisted to disk (workspace/dynamic_endpoints.json) and restored after restart.
- When outputting a button, you MUST include a <script> tag in the HTML to trigger the SafeHtml iframe rendering path. A bare <button onclick="..."> without <script> goes through ReactMarkdown where onclick does not work.
- The POST body's `message` field becomes the message content delivered to the agent.
- The delivered message format is: [dynamic-endpoint] {name}\\n{message}.
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
    emoji="✂",
    danger_level=ToolDangerLevel.readonly,
    availability=ToolAvailability.MAIN | ToolAvailability.MULTI_AGENT,
)

registry.register(
    name="list_dynamic_endpoints",
    toolset="dynamic",
    schema={
        # 列出当前会话的所有动态端点。
        #
        # ## 前置条件
        # 无。
        #
        # ## 调用效果
        # 返回当前会话中所有已注册的动态端点，包括 endpoint_id、name、url 等信息。
        #
        # ## 返回
        # ```json
        # {"success": true, "count": 2, "endpoints": [{"endpoint_id": "...", "name": "...", "url": "...", "agent_name": "...", "created_at": 1234567890}]}
        # ```
        #
        # ## 何时使用
        # - 查看当前有哪些动态端点。
        # - 获取 endpoint_id 以便取消注册。
        #
        # ## 副作用/注意
        # - 纯查询，不会修改端点状态。
        "description": """List all registered dynamic endpoints for the current session.

## Prerequisites
None.

## Effect
Returns metadata for all dynamic endpoints in the current session, including endpoint_id, name, url, agent_name, and created_at.

## Returns
```json
{"success": true, "count": 2, "endpoints": [{"endpoint_id": "...", "name": "...", "url": "/dynamic/sid/agent/eid", "agent_name": "...", "created_at": 1234567890}]}
```

## When to Use
- Check what dynamic endpoints are currently registered.
- Obtain endpoint_id values for unregister_dynamic_endpoint.

## Side Effects / Notes
- Read-only query; does not modify endpoint state.""",
        "parameters": {
            "type": "object",
            "properties": {},
        },
    },
    handler=_handle_list_dynamic_endpoints,
    is_async=True,
    emoji="📋",
    danger_level=ToolDangerLevel.readonly,
    availability=ToolAvailability.MAIN | ToolAvailability.MULTI_AGENT,
)