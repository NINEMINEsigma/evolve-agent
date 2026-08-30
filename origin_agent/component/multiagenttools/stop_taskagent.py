"""强制停止运行中的 taskagent。

模块导入时通过 ``registry.register()`` 注册 ``StopTaskAgent`` 工具。
父 Agent 通过此工具强制终止指定 taskagent 会话，不保存历史。
"""

from __future__ import annotations

from typing import Any

from abstract.tools.registry import registry, tool_error, tool_result
from entity.puretype import ToolAvailability, ToolDangerLevel


async def _handle_stop_taskagent(args: dict[str, Any]) -> dict:
    """强制停止 taskagent。

    预期参数：
        session_id: str — 要停止的 taskagent 会话 ID
    """
    session_id: str = str(args.get("session_id", "")).strip()
    parent_session_id: str = str(args.get("_session_id", "")).strip()

    if not session_id:
        return tool_error("'session_id' is required and must not be empty")
    if not parent_session_id:
        return tool_error("'_session_id' is required and must not be empty")

    try:
        from system.application import Application
        orch = Application.current().subagent_orchestrator
        result = await orch.stop_taskagent(
            parent_session_id=parent_session_id,
            session_id=session_id,
        )
        return tool_result(**result)
    except Exception as exc:
        return tool_error(f"Failed to stop taskagent: {exc}")


registry.register(
    name="StopTaskAgent",
    toolset="multiagent",
    schema={
        # 强制终止一个运行中的 taskagent 会话。
        #
        # ## 前置条件
        # 必须知道要停止的 taskagent 会话 ID，从 run_taskagent 的返回值获取。
        #
        # ## 调用效果
        # 停止指定 session_id 的 taskagent，不保存任何历史。
        # 已经完成的 taskagent 不能再次停止。
        # 停止后会自动激活下一个排队的子 Agent（如果有）。
        #
        # ## 返回
        # ```json
        # {"success": true, "session_id": "..."}
        # ```
        #
        # ## 何时使用
        # - taskagent 执行时间过长需要提前终止时。
        # - 需要释放活跃子 Agent 槽位时。
        #
        # ## 副作用/注意
        # - 终止后不保存历史，无法恢复。
        # - 终止是不可逆操作。
        "description": """Forcefully terminate a running task agent.

## Prerequisites
You must know the session_id of the task agent to stop. Obtain it from the run_taskagent return value.

## Effect
Stops the task agent identified by session_id. No history is saved. An already-completed task agent cannot be stopped again.

## Returns
```json
{"success": true, "session_id": "..."}
```
On failure:
```json
{"success": false, "error": "..."}
```

## When to Use
- A task agent is taking too long and must be terminated early.
- Free an active sub-agent slot.

## Side Effects / Notes
- No history is saved; the task agent cannot be resumed.
- Termination is irreversible.""",
        "parameters": {
            "type": "object",
            "properties": {
                "session_id": {
                    "type": "string",
                    # 要停止的 taskagent 的会话 ID。
                    "description": "Session ID of the task agent to stop.",
                },
            },
            "required": ["session_id"],
        },
    },
    handler=_handle_stop_taskagent,
    is_async=True,
    emoji="🛑",
    danger_level=ToolDangerLevel.safe,
    availability=ToolAvailability.MAIN,
)