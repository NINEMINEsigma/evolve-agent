"""向子 Agent 发送消息。

模块导入时通过 ``registry.register()`` 注册 ``chat_subagent`` 工具。
父 Agent 通过此工具向指定子 Agent 发送消息，消息进入收件箱，
在子 Agent 工具链结束后合并注入上下文。
"""

from __future__ import annotations

from typing import Any

from abstract.tools.registry import registry, tool_error, tool_result


def _handle_chat_subagent(args: dict[str, Any]) -> dict:
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

    # TODO: 实现消息排队到子 Agent 收件箱的逻辑
    # 1. 通过编排器查找 session_id 对应的 SubAgentLoop
    # 2. 将 message 追加到该子 Agent 的收件箱
    # 3. 如果子 Agent 处于等待状态则报错

    return tool_result(
        success=True,
        session_id=session_id,
        message="Message queued for sub-agent. Execution not yet implemented.",
    )


registry.register(
    name="chat_subagent",
    toolset="multiagent",
    schema={
        # 向指定子 Agent 会话发送一条消息，消息进入收件箱并在子 Agent 工具链结束后合并注入上下文。
        # 子 Agent 处于等待队列（未活跃）时不可发送消息。
        "description": (
            "Send a message to a running sub-agent session. "
            "The message is queued in the sub-agent's inbox and injected into its context "
            "after the current tool-call chain finishes. "
            "Cannot be used on sub-agents that are queued (not yet active)."
        ),
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
    emoji="💬",
    danger_level="readonly",
)