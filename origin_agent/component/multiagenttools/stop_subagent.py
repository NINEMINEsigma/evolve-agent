"""停止子 Agent 会话。

注册入口为顶层 ``register_tools(registry, ui_events)``，由 ToolDiscoverySystem
显式调用。父 Agent 通过此工具强制终止指定子 Agent 会话，
落盘完整会话历史。
"""

from __future__ import annotations

from typing import Any

from abstract.tools.registry import ToolRegistry, tool_error, tool_result
from abstract.tools.ui_event_router import UIEventRouter
from entity.puretype import ToolAvailability, ToolDangerLevel


async def _handle_stop_subagent(args: dict[str, Any]) -> dict:
    """停止子 Agent 会话。

    预期参数：
        session_id: str — 要停止的子 Agent 会话 ID
    """
    session_id: str = str(args.get("session_id", "")).strip()

    if not session_id:
        return tool_error("'session_id' is required and must not be empty")

    parent_session_id: str = str(args.get("_session_id", "")).strip()
    if not parent_session_id:
        return tool_error("'_session_id' is required and must not be empty")

    try:
        from system.application import Application
        from subagent.orchestrator import SubAgentOrchestrator
        orch = Application.current().get_system(SubAgentOrchestrator)
        result = await orch.stop(parent_session_id=parent_session_id, session_id=session_id)
        return tool_result(result.model_dump(exclude_none=True))
    except Exception as exc:
        return tool_error(f"Failed to stop subagent: {exc}")


def register_tools(registry: ToolRegistry, ui_events: UIEventRouter) -> None:
    """Register stop subagent tool into the explicit runtime registry."""
    del ui_events
    registry.register(
        name="StopSubAgent",
        toolset="multiagent",
        schema={
            # 强制终止一个子 Agent 会话。
            #
            # ## 前置条件
            # 必须知道要停止的子 Agent 会话 ID。可以通过子 Agent 启动返回值或相关接口获取。
            #
            # ## 调用效果
            # 保存完整的 easysave `.es` 会话历史，返回默认临时路径 `ws:tmp/<session_id>.es`。
            # 每次调用只能停止一个子 Agent。
            # 已经完成的子 Agent 不能再次停止。
            # 返回的历史路径指向临时的 easysave `.es` 文件。
            # 如需长期保留，使用 Copy 或 Move 将 `ws:tmp/<session_id>.es` 移动到用户指定的角色目录或其他 `ws:` 路径。
            #
            # ## 返回
            # ```json
            # {"success": true, "session_id": "...", "session_path": "ws:tmp/<session_id>.es"}
            # ```
            #
            # ## 何时使用
            # - 子 Agent 任务完成或需要提前终止时。
            # - 需要保存会话历史以便后续通过 history_path 恢复时。
            #
            # ## 副作用/注意
            # - 强制终止会立即停止子 Agent 的执行。
            # - 活跃会话的历史被持久化到 `ws:tmp/<session_id>.es` easysave 文件。
            # - 自动保存到 `ws:tmp/<session_id>.es`，如需长期保留可自行使用 Copy 或 Move 移动。
            "description": """Forcefully terminate a sub-agent session.

## Prerequisites
You must know the session_id of the sub-agent to stop. Obtain it from the sub-agent launch result or related interfaces.

## Effect
Stops the sub-agent session identified by session_id and persists the complete session history as an easysave `.es` file at temporary path `ws:tmp/<session_id>.es`.
Only one sub-agent can be stopped per call.
An already-completed sub-agent cannot be stopped again.

The returned history path is temporary. Use Copy or Move if you want to retain the `.es` file under a character directory or another `ws:` path.

## Returns
```json
{"success": true, "session_id": "...", "session_path": "ws:tmp/<session_id>.es"}
```

## When to Use
- Stop a sub-agent after its task completes or when it must be terminated early.
- Save session history so it can be resumed later via history_path.

## Side Effects / Notes
- Termination immediately halts the sub-agent's execution.
- Active session history is persisted to `ws:tmp/<session_id>.es` in easysave format.
- The auto-saved history file is at a temporary location that may be overwritten or cleaned up. After receiving session_path, you must ask the user whether to copy or move it to a safer location for long-term retention.
- Termination is irreversible.""",
            "parameters": {
                "type": "object",
                "properties": {
                    "session_id": {
                        "type": "string",
                        # 要停止的子 Agent 的会话 ID。
                        "description": "Session ID of the sub-agent to stop.",
                    },
                },
                "required": ["session_id"],
            },
        },
        handler=_handle_stop_subagent,
        is_async=True,
        danger_level=ToolDangerLevel.safe,
        availability=ToolAvailability.MAIN,
    )
