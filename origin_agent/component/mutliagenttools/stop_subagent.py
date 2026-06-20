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
        # 强制终止一个子 Agent 会话。每次仅停止一个子 Agent。
        # 停止后完整会话历史保存到 workspace/logs/subagents/ 下的 JSONL 文件。
        # 已完成的子 Agent 无法再次停止。等待中的子 Agent 直接移除不落盘。
        # 若等待队列非空，停止后自动激活队列头部的一个子 Agent（一出一入）。
        "description": (
            "Forcefully terminate a sub-agent session. "
            "Only one sub-agent can be stopped per call. "
            "The complete session history is saved as a JSONL file. "
            "An already-completed sub-agent cannot be stopped again. "
            "Queued (not yet active) sub-agents are removed without saving history. "
            "If the waiting queue is non-empty, the next queued sub-agent is "
            "automatically activated after this one is stopped."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "session_id": {
                    "type": "string",
                    # 要停止的子 Agent 会话 ID。
                    "description": "Session ID of the sub-agent to stop.",
                },
            },
            "required": ["session_id"],
        },
    },
    handler=_handle_stop_subagent,
    is_async=True,
    emoji="🛑",
    danger_level="write",
)