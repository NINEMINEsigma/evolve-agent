"""全局动态沙盒空间管理工具。

两个工具仅在 fast 模式可见，均为 critical；普通模式主Agent与多Agent模式
主Agent可调用。随意聊聊会话不加载 ``sandbox`` 工具集。
"""

from __future__ import annotations

from typing import Any, TYPE_CHECKING

from abstract.tools.registry import registry, tool_error, tool_result
from entity.constant import MAIN_AGENT_CHARACTER_NAME
from entity.puretype import DynamicSandboxSpace, ToolAvailability, ToolDangerLevel
from system.application import Application
from system.context import get_runtime_context

if TYPE_CHECKING:
    from entry.base_agent_loop import ToolContext


def _fast_mode_available() -> bool:
    """仅在 fast 模式暴露动态空间管理工具。"""
    return get_runtime_context().mode == "fast"


def _require_main_agent(context: ToolContext | None) -> str | None:
    """返回调用上下文错误；合法 fast 主Agent返回 None。"""
    if context is None:
        return "Dynamic sandbox space management requires ToolContext"
    if context.runtime_context.mode != "fast":
        return "Dynamic sandbox spaces can only be modified in fast mode"
    character_name = context.character_name or context.loop.current_character_agent
    if character_name != MAIN_AGENT_CHARACTER_NAME:
        return "Only the main Agent can modify global dynamic sandbox spaces"
    return None


def _non_empty_string(args: dict[str, Any], name: str) -> tuple[str, str | None]:
    value = args.get(name)
    if type(value) is not str or not value.strip():
        return "", f"'{name}' is required and must be a non-empty string"
    return value.strip(), None


def _space_payload(space: DynamicSandboxSpace) -> dict[str, Any]:
    return {
        "name": space.name,
        "namespace": f"{space.name}:",
        "path": space.path,
        "description": space.description,
        "is_readonly": space.is_readonly,
    }


def _handle_add_sandbox_space(
    args: dict[str, Any],
    context: ToolContext | None = None,
) -> dict:
    """新增全局动态沙盒空间；同名同配置时幂等成功。"""
    context_error = _require_main_agent(context)
    if context_error:
        return tool_error(context_error)

    name, error = _non_empty_string(args, "name")
    if error:
        return tool_error(error)
    raw_path = args.get("path")
    if type(raw_path) is not str or not raw_path.strip():
        return tool_error("'path' is required and must be a non-empty string")
    path = raw_path
    description, error = _non_empty_string(args, "description")
    if error:
        return tool_error(error)
    reason, error = _non_empty_string(args, "reason")
    if error:
        return tool_error(error)
    _ = reason

    is_readonly = args.get("is_readonly")
    if type(is_readonly) is not bool:
        return tool_error("'is_readonly' is required and must be a boolean")

    sandbox = Application.current().sandbox
    try:
        normalized_path = sandbox.normalize_dynamic_space_path(path)
    except (TypeError, ValueError) as exc:
        return tool_error(str(exc), path=path)
    if path != normalized_path:
        return tool_error(
            "The approved path is not normalized. Retry with normalized_path so the "
            "critical approval displays the exact persisted path.",
            path=path,
            normalized_path=normalized_path,
        )

    try:
        space, created = sandbox.add_dynamic_space(
            name=name,
            path=path,
            description=description,
            is_readonly=is_readonly,
            session_id=context.session_id if context is not None else "",
        )
    except Exception as exc:
        return tool_error(str(exc), name=name, path=path)
    return tool_result(
        success=True,
        created=created,
        space=_space_payload(space),
    )


def _handle_remove_sandbox_space(
    args: dict[str, Any],
    context: ToolContext | None = None,
) -> dict:
    """按名称删除全局动态沙盒空间；不存在时幂等成功。"""
    context_error = _require_main_agent(context)
    if context_error:
        return tool_error(context_error)

    name, error = _non_empty_string(args, "name")
    if error:
        return tool_error(error)
    reason, error = _non_empty_string(args, "reason")
    if error:
        return tool_error(error)
    _ = reason

    try:
        removed = Application.current().sandbox.remove_dynamic_space(
            name,
            session_id=context.session_id if context is not None else "",
        )
    except Exception as exc:
        return tool_error(str(exc), name=name)
    return tool_result(success=True, removed=removed, name=name)


registry.register(
    name="AddSandboxSpace",
    toolset="sandbox",
    schema={
        "description": """Add a persistent global dynamic sandbox namespace in fast mode.

This critical operation changes the filesystem scope shared by all Agents. Manual and handsfree modes require direct user approval; YOLO mode follows the global automatic-approval rule. The path must be an already normalized absolute directory path, but the directory may currently be absent. Names omit the trailing colon. Existing names are never overwritten: identical configuration is an idempotent success, while different configuration is rejected. To change a space, remove it and add it again.""",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Namespace name without a colon. Use ASCII letters, digits, and underscores; start with a letter or underscore.",
                },
                "path": {
                    "type": "string",
                    "description": "Normalized absolute directory path. The directory may currently be absent.",
                },
                "description": {
                    "type": "string",
                    "description": "Required user-facing description of this space's purpose, up to 1000 characters.",
                },
                "is_readonly": {
                    "type": "boolean",
                    "description": "Required explicit permission choice. True means Sandbox file APIs are read-only; this is not an OS-level ACL.",
                },
                "reason": {
                    "type": "string",
                    "description": "Why this global filesystem scope is required; shown in the critical approval request.",
                },
            },
            "required": ["name", "path", "description", "is_readonly", "reason"],
        },
    },
    handler=_handle_add_sandbox_space,
    check_fn=_fast_mode_available,
    danger_level=ToolDangerLevel.critical,
    availability=ToolAvailability.MAIN | ToolAvailability.MULTI_AGENT,
)


registry.register(
    name="RemoveSandboxSpace",
    toolset="sandbox",
    schema={
        "description": """Remove a persistent global dynamic sandbox namespace in fast mode.

This critical operation revokes future logical-path resolution for the named space. It does not stop subprocesses that already resolved the path. Removing a missing name is an idempotent success.""",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Dynamic namespace name without the trailing colon.",
                },
                "reason": {
                    "type": "string",
                    "description": "Why this global filesystem scope should be revoked; shown in the critical approval request.",
                },
            },
            "required": ["name", "reason"],
        },
    },
    handler=_handle_remove_sandbox_space,
    check_fn=_fast_mode_available,
    danger_level=ToolDangerLevel.critical,
    availability=ToolAvailability.MAIN | ToolAvailability.MULTI_AGENT,
)
