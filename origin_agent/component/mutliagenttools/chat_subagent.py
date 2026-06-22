"""向子 Agent 发送消息。

模块导入时通过 ``registry.register()`` 注册 ``chat_subagent`` 工具。
父 Agent 通过此工具向指定子 Agent 发送消息，消息进入收件箱，
在子 Agent 工具链结束后合并注入上下文。
"""

from __future__ import annotations

from typing import Any

from abstract.tools.registry import registry, tool_error, tool_result


async def _handle_chat_subagent(args: dict[str, Any]) -> dict:
    """向子 Agent 发送消息。

    预期参数：
        session_id: str — 目标子 Agent 会话 ID
        message:    str — 发送给子 Agent 的消息内容
    """
    session_id: str = str(args.get("session_id", "")).strip()
    message: str = str(args.get("message", "")).strip()

    if not session_id:
        return tool_error("'session_id' is required and must not be empty")
    if not message:
        return tool_error("'message' is required and must not be empty")

    try:
        from gateway.server import get_subagent_orchestrator
        orch = get_subagent_orchestrator()
        result = await orch.chat(session_id, message)
        return tool_result(**result)
    except Exception as exc:
        return tool_error(f"Failed to chat with subagent: {exc}")


registry.register(
    name="chat_subagent",
    toolset="multiagent",
    schema={
        # 向正在运行的子 Agent 会话发送一条消息。
        # 消息进入子 Agent 收件箱队列，在当前工具调用链完成后注入其上下文。
        # 不能用于已排队（尚未活跃）的子 Agent。
        # 返回可选的 'feedback' 字段——调用时从子 Agent 发件箱收集的文本响应列表。用于即时反馈，而非等待定期收集周期。
        "description": """Send a message to a running sub-agent session. The message is queued in the sub-agent's inbox and injected into its context after the current tool-call chain finishes. Cannot be used on sub-agents that are queued (not yet active).

Returns an optional 'feedback' field — a list of text responses from the sub-agent's outbox collected at call time. Use this for instant feedback instead of waiting for the periodic collection cycle.""",
        "parameters": {
            "type": "object",
            "properties": {
                "session_id": {
                    "type": "string",
                    # 目标子 Agent 的会话 ID。
                    "description": "Session ID of the target sub-agent.",
                },
                "message": {
                    "type": "string",
                    # 发送给子 Agent 的消息内容。
                    "description": "The message content to send to the sub-agent.",
                },
            },
            "required": ["session_id", "message"],
        },
    },
    handler=_handle_chat_subagent,
    is_async=True,
    emoji="💬",
    danger_level="readonly",
)