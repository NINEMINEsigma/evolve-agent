"""子 Agent 向父 Agent 发送反馈消息的内部工具。

此工具仅注入到子 Agent 会话中，父 Agent 不可用。
handler 通过 ``contextvars.ContextVar`` 获取当前运行的 SubAgentLoop 实例，
将消息追加到其发件箱。

注意：调用此工具后子 Agent 的 LLM 循环不暂停。
"""

from __future__ import annotations

from contextvars import ContextVar
from typing import Any

from abstract.tools.registry import registry, tool_error, tool_result

# 由 SubAgentLoop 在每次工具执行前设置，handler 通过它找到当前 SubAgentLoop。
# 类型标注为 Any 以避免循环导入；实际类型为 subagent.loop.SubAgentLoop。
current_subagent_loop: ContextVar[Any] = ContextVar("current_subagent_loop")


def _handle_report_to_parent(args: dict[str, Any]) -> dict:
    """将消息追加到子 Agent 的发件箱。

    预期参数：
        message: str  — 发送给父 Agent 的消息内容
        is_final: bool — 是否代表最终答案（默认 false）
    """
    message: str = str(args.get("message", "")).strip()
    is_final: bool = bool(args.get("is_final", False))

    if not message:
        return tool_error("'message' is required and must not be empty")

    try:
        loop = current_subagent_loop.get()
    except LookupError:
        return tool_error("report_to_parent can only be called from within a sub-agent session")

    loop._outbox.append(message)
    if is_final:
        loop._completed = True

    return tool_result(
        success=True,
        message="Feedback sent to parent agent.",
    )


registry.register(
    name="report_to_parent",
    toolset="",  # 不绑定任何 toolset，仅用于子 Agent 注入
    schema={
        # 子 Agent 向父 Agent 发送反馈消息。不暂停 LLM 循环。
        # 设置 is_final: true 表示当前回复为任务的最终答案。
        # 此工具仅在子 Agent 会话中可用。
        "description": (
            "Send a feedback message to the parent agent (your sole communication partner). "
            "The parent agent assigned you the task and is your only 'user' — "
            "the end user will never see your messages directly. "
            "Does NOT pause the sub-agent's LLM loop. "
            "Set 'is_final: true' when this message represents the definitive "
            "answer to the assigned task. "
            "This tool is only available in sub-agent sessions."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "message": {
                    "type": "string",
                    # 发送给父 Agent 的消息内容。
                    "description": "The message content to send to the parent agent.",
                },
                "is_final": {
                    "type": "boolean",
                    # 是否代表最终答案。父 Agent 收到后可以 stop_subagent 结束子会话。
                    "description": "Whether this is the final answer to the task (default false).",
                    "default": False,
                },
            },
            "required": ["message"],
        },
    },
    handler=_handle_report_to_parent,
    emoji="📤",
    danger_level="readonly",
)