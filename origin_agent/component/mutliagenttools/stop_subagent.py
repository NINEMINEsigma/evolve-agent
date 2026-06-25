"""停止子 Agent 会话。

模块导入时通过 ``registry.register()`` 注册 ``stop_subagent`` 工具。
父 Agent 通过此工具强制终止指定子 Agent 会话，
落盘完整会话历史，并可能激活等待队列中的下一个子 Agent。
"""

from __future__ import annotations

from typing import Any

from abstract.tools.registry import registry, tool_error, tool_result


async def _handle_stop_subagent(args: dict[str, Any]) -> dict:
    """停止子 Agent 会话。

    预期参数：
        session_id: str — 要停止的子 Agent 会话 ID
    """
    session_id: str = str(args.get("session_id", "")).strip()

    if not session_id:
        return tool_error("'session_id' is required and must not be empty")

    try:
        from gateway.server import get_subagent_orchestrator
        orch = get_subagent_orchestrator()
        result = await orch.stop(session_id)
        return tool_result(**result)
    except Exception as exc:
        return tool_error(f"Failed to stop subagent: {exc}")


registry.register(
    name="stop_subagent",
    toolset="multiagent",
    schema={
        # 强制终止一个子 Agent 会话。
        #
        # ## 前置条件
        # 必须知道要停止的子 Agent 会话 ID。可以通过子 Agent 启动返回值或相关接口获取。
        #
        # ## 调用效果
        # 停止指定 session_id 的子 Agent 会话，并将完整会话历史保存为 JSONL 文件，返回文件路径 history_path。
        # 每次调用只能停止一个子 Agent。
        # 已经完成的子 Agent 不能再次停止。
        # 处于排队状态（尚未活跃）的子 Agent 会被移除，且不保存历史。
        # 如果等待队列非空，当前子 Agent 停止后会自动激活下一个排队的子 Agent。
        # 如果该子会话不是临时任务，或未来可能需要恢复/参考，应将返回的 history_path 复制到更安全的位置（如 ws: 下的专门目录），并重命名为具有标识性的名称（例如包含子 Agent 名称和任务摘要）。
        #
        # ## 返回
        # ```json
        # {"success": true, "session_id": "...", "history_path": "...", "message": "..."}
        # ```
        #
        # ## 何时使用
        # - 子 Agent 任务完成或需要提前终止时。
        # - 需要保存会话历史以便后续通过 history_path 恢复时。
        # - 需要释放活跃子 Agent 槽位以让队列中的子 Agent 运行时。
        #
        # ## 副作用/注意
        # - 强制终止会立即停止子 Agent 的执行。
        # - 活跃会话的历史被持久化到 JSONL 文件，原始路径随会话环境而定。
        # - 若需要长期保留或后续恢复，建议立即将 history_path 复制到受控位置并改名，避免被覆盖或误清理。
        # - 队列中的会话被移除且不留历史。
        # - 停止后会自动激活下一个排队会话（如果有）。
        "description": """Forcefully terminate a sub-agent session.

## Prerequisites
You must know the session_id of the sub-agent to stop. Obtain it from the sub-agent launch result or related interfaces.

## Effect
Stops the sub-agent session identified by session_id and persists the complete session history as a JSONL file. The file path is returned as history_path.
Only one sub-agent can be stopped per call.
An already-completed sub-agent cannot be stopped again.
Queued (not yet active) sub-agents are removed without saving history.
If the waiting queue is non-empty, the next queued sub-agent is automatically activated after this one stops.

If this sub-agent session is not a temporary task, or if it may need to be resumed or referenced later, copy the returned history_path to a safer location (e.g. a dedicated directory under ws:) and rename it to a descriptive name (such as one that includes the sub-agent name and a task summary).

## Returns
```json
{"success": true, "session_id": "...", "history_path": "...", "message": "..."}
```

## When to Use
- Stop a sub-agent after its task completes or when it must be terminated early.
- Save session history so it can be resumed later via history_path.
- Free an active sub-agent slot so a queued session can run.

## Side Effects / Notes
- Termination immediately halts the sub-agent's execution.
- Active session history is persisted to a JSONL file; the original path depends on the session environment.
- If long-term retention or later resumption is needed, copy history_path to a controlled location and rename it immediately to avoid accidental overwrite or cleanup.
- Queued sessions are removed without leaving history.
- The next queued session is automatically activated if one exists.""",
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
    emoji="🛑",
    danger_level="readonly",
)