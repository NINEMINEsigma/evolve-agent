"""向子 Agent 发送消息。

模块声明顶层 ``TOOLSET`` 对象，由 ToolDiscoverySystem 发现并注册。
父 Agent 通过此工具向指定子 Agent 发送消息，消息进入收件箱，
在子 Agent 工具链结束后合并注入上下文。
"""

from __future__ import annotations

from typing import Any

from abstract.tools.tool import (
    BaseTool,
    BaseToolSet,
    ToolExecution,
    ToolHandlerResult,
    tool_error,
    tool_result,
)
from entity.puretype import ToolAvailability, ToolDangerLevel


async def _handle_chat_subagent(args: dict[str, Any]) -> dict:
    """向子 Agent 发送消息。

    预期参数：
        session_id:    str — 目标子 Agent 会话 ID
        message:       str — 发送给子 Agent 的消息内容
        user_name:     str — 本轮发送者身份名称（必填）
        message_type:  str — "direct" 或 "overheard"（必填）
    """
    session_id: str = str(args.get("session_id", "")).strip()
    message: str = str(args.get("message", "")).strip()
    user_name: str = str(args.get("user_name", "")).strip()
    message_type: str = str(args.get("message_type", "")).strip().lower()

    if not session_id:
        return tool_error("'session_id' is required and must not be empty")
    if not message:
        return tool_error("'message' is required and must not be empty")
    if not user_name:
        return tool_error("'user_name' is required and must not be empty")
    if message_type not in ("direct", "overheard"):
        return tool_error("'message_type' must be 'direct' or 'overheard'")

    parent_session_id: str = str(args.get("_session_id", "")).strip()
    if not parent_session_id:
        return tool_error("'_session_id' is required and must not be empty")

    try:
        from system.application import Application
        from system.application import Application
        from subagent.orchestrator import SubAgentOrchestrator
        orch = Application.current().get_system(SubAgentOrchestrator)
        result = await orch.chat(parent_session_id=parent_session_id, session_id=session_id, message=message, user_name=user_name, message_type=message_type)
        return tool_result(result.model_dump(exclude_none=True))
    except Exception as exc:
        return tool_error(f"Failed to chat with subagent: {exc}")


class ChatSubAgentTool(BaseTool):
    def __init__(self) -> None:
        super().__init__(
        name="ChatSubAgent",
        toolset="multiagent",
        schema={
            # 向正在运行的子 Agent 会话发送一条消息。
            #
            # ## 前置条件
            # 目标子 Agent 必须已经处于活跃运行状态。
            # 在发送新消息前，应当已经收到子 Agent 的最新一轮回复；避免在上一轮工具调用链尚未结束时连续发送消息。
            #
            # ## 调用效果
            # 消息进入子 Agent 的收件箱队列，并在当前工具调用链完成后注入其上下文。
            # 可用于追加任务说明、回答问题、提供新上下文或纠正子 Agent 的行为。
            # 不要仅为了发送初始提示而调用本工具——初始提示应通过 run_subagent 的 initial_prompt 参数发送。
            #
            # ## 返回
            # ```json
            # {"feedback": ["..."], "success": true}
            # ```
            # feedback 是调用时从子 Agent 发件箱收集的文本响应列表，用于即时反馈，而非等待定期收集周期。
            #
            # ## 何时使用
            # - 子 Agent 运行过程中需要补充上下文或纠正方向。
            # - 子 Agent 提出问题时回复它。
            # - 需要立即获取子 Agent 的最新输出（通过 feedback）。
            #
            # ## 副作用/注意
            # - 消息不会立即打断子 Agent 当前的工具调用链，而是排队等待当前链结束后注入。
            # - 频繁发送消息可能让子 Agent 上下文变得混乱；应等待子 Agent 回复后再决定是否需要继续发送。
            "description": """Send a message to an active running sub-agent session.

## Prerequisites
The target sub-agent must already be active.
You MUST wait for the [subagent-result] message from the sub-agent before calling this tool.
Before sending a new message, you should have received the sub-agent's latest round of response. Avoid calling chat_subagent repeatedly while the previous tool-call chain is still in progress.
**NEVER use chat_subagent to check whether the sub-agent is alive, to ask "are you there", or to urge the sub-agent.** Such calls will be rejected by the system.

## Effect
The message is queued in the sub-agent's inbox and injected into its context after the current tool-call chain finishes.
Use it to add task instructions, answer questions, provide new context, or correct the sub-agent's behavior.
Do NOT use this tool solely to send the initial prompt — that should be passed via the initial_prompt parameter of run_subagent.

## Returns
```json
{"feedback": ["..."], "success": true}
```
The optional 'feedback' field is a list of text responses from the sub-agent's outbox collected at call time. Use it for instant feedback instead of waiting for the periodic collection cycle.
If the sub-agent has already produced feedback that you have not yet received, the call fails with:
```json
{"success": false, "feedback": ["..."], "_note": "Sub-agent has already produced feedback that you have not yet received. Please review the feedback first, then decide whether and how to reply via chat_subagent."}
```
You MUST review the returned `feedback` first, then decide whether and how to reply via `ChatSubAgent`.
If the sub-agent is still generating its current response, the call fails with:
```json
{"success": false, "error": "Sub-agent is still generating its current response. Wait for [subagent-result] before calling chat_subagent."}
```

## When to Use
- Reply to a question from the sub-agent.
- Add context or correct direction while the sub-agent is running AND after you have received its latest [subagent-result].
- Fetch the latest sub-agent output immediately (via feedback) ONLY after the sub-agent has produced a response.

## Side Effects / Notes
- The message does not interrupt the sub-agent's current tool-call chain; it is queued and injected after the chain ends.
- Calling this before the sub-agent has finished its current round fails.
- Frequent messages may clutter the sub-agent's context; wait for the sub-agent's response before deciding whether to send another message.""",
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
                    "user_name": {
                        "type": "string",
                        # 本轮消息的真实发送者名称（必填）。即使转述第三方内容，也应填你自己的身份。
                        "description": "The real sender's name for this turn (required). Use your own identity even when relaying third-party content.",
                    },
                    "message_type": {
                        "type": "string",
                        # 消息类型："direct" 表示直接对子 Agent 说，子 Agent 应响应；"overheard" 表示旁听。
                        "description": "Message type: 'direct' means addressed to the sub-agent (it should respond); 'overheard' means it is only listening in.",
                    },
                },
                "required": ["session_id", "message", "user_name", "message_type"],
            },
        },
        is_async=True,
        danger_level=ToolDangerLevel.safe,
        availability=ToolAvailability.MAIN,
        )

    async def handle(self, execution: ToolExecution) -> ToolHandlerResult:
        return ToolHandlerResult(result=await _handle_chat_subagent(execution.arguments))


TOOLSET = BaseToolSet(name="multiagent", tools=(ChatSubAgentTool(),))
