"""
将当前多 Agent 协作模式会话退出回普通模式。

退出后 MultiAgentLoop 被替换为 ParentAgentLoop，共享对话历史保留。
multiagent 工具集重新可用，可正常使用 run_subagent / chat_subagent 等。
"""

from __future__ import annotations

import logging
from typing import Any, cast

from abstract.tools.tool import (
    BaseTool, BaseToolSet, ToolExecution, ToolHandlerResult, ToolPostprocessEffect,
    tool_error, tool_result,
)
from entity.puretype import Role, ToolAvailability, ToolDangerLevel
from entity.constant import SYSTEM_CHARACTER_NAME
from entity.messages import CharacterConversationMessage
from entry.agent_sink import FrontendSink
from entry.multi_agent_loop import MultiAgentLoop
from entry.parent_agent_loop import ParentAgentLoop
from system.application import Application

from gateway.session_manager import SessionManager

logger = logging.getLogger(__name__)


async def _prepare_exit_multi_agent(execution: ToolExecution) -> ToolHandlerResult:
    """退出多 Agent 协作模式，回到普通模式。

    预期参数: 无
    """
    session_id = execution.context.session_id
    app = execution.context.app

    # 获取当前 MultiAgentLoop
    _multi_loop = app.get_system(SessionManager).get_loop(session_id)
    if _multi_loop is None:
        return ToolHandlerResult(tool_error(f"No active loop found for session {session_id}"))
    elif isinstance(_multi_loop.loop, MultiAgentLoop):
        multi_loop = _multi_loop.loop
    else:
        return ToolHandlerResult(tool_error(f"Current loop is not {MultiAgentLoop.__name__}; already in normal mode"))

    # 目标Loop构造和真实替换必须晚于本工具结果的严格保存。
    return ToolHandlerResult(
        result=tool_result(
            success=True,
            mode="normal",
            message=f"Session {session_id} exited multi-agent mode, back to normal mode",
        ),
        state=multi_loop,
    )


class ExitMultiAgentTool(BaseTool):
    def __init__(self) -> None:
        super().__init__(
        name="ExitMultiAgent",
        toolset="multiagent",
        availability=ToolAvailability.MULTI_AGENT,
        danger_level=ToolDangerLevel.safe,
        schema={
            # 退出多 Agent 协作模式，回到普通模式。
            #
            # ## 功能
            # 将当前 MultiAgentLoop 替换为 ParentAgentLoop。
            # 共享对话历史保留不变，用户可继续以普通模式对话。
            # multiagent 工具集（run_subagent、chat_subagent 等）重新可用。
            #
            # ## 前置条件
            # - 当前会话必须处于多 Agent 协作模式。
            #
            # ## 调用效果
            # - 当前 MultiAgentLoop 被中断并替换为 ParentAgentLoop。
            # - 共享对话历史保留，无缝继续。
            # - multiagent 工具集重新可用。
            #
            # ## 返回
            # ```json
            # { "success": true, "mode": "normal", "message": "..." }
            # ```
            #
            # ## 何时使用
            # - 用户明确要求退出多 Agent 模式时。
            # - 需要回到普通模式使用 run_subagent 等工具时。
            #
            # ## 副作用 / 注意
            # - 当前会话的 loop 从 MultiAgentLoop 替换为 ParentAgentLoop。
            # - 正在进行的级联响应会被中断。
            # - 共享历史保留，但多 Agent 特有的 visible_characters / response_characters 元数据在普通模式下被忽略。
            # - 工具返回成功后，模式切换将在你本轮回复完成后生效。请直接给用户一个简短确认，不要再调用任何工具。
            "description": """Exit multi-agent collaboration mode and return to normal mode.

## Prerequisites
- The current session must be in multi-agent collaboration mode.

## Effect
- The current MultiAgentLoop is interrupted and replaced with a ParentAgentLoop.
- The shared conversation history is preserved, allowing seamless continuation.
- The multiagent toolset (run_subagent, chat_subagent, etc.) becomes available again.

## Returns
```json
{ "success": true, "mode": "normal", "message": "..." }
```

## When to Use
- When the user explicitly asks to exit multi-agent mode.
- When you need to return to normal mode to use run_subagent and similar tools.

## Side Effects / Notes
- The session loop is replaced from MultiAgentLoop to ParentAgentLoop.
- Any in-progress cascade response is interrupted.
- Shared history is preserved, but multi-agent specific metadata (visible_characters / response_characters) is ignored in normal mode.
- After this tool returns success, the mode switch takes effect after your current reply completes. Simply give the user a brief confirmation and do NOT call any other tools in your response. The normal single-agent loop will handle all subsequent user messages.""",
            "parameters": {
                "type": "object",
                "properties": {},
            },
        },
        is_async=True,
    )

    async def handle(self, execution: ToolExecution) -> ToolHandlerResult:
        return await _prepare_exit_multi_agent(execution)

    async def after_handle(self, execution: ToolExecution) -> ToolPostprocessEffect:
        if execution.state is None:
            return ToolPostprocessEffect()
        multi_loop = execution.state
        context = execution.context
        manager = context.app.get_system(SessionManager)
        current = manager.get_loop(context.session_id)
        if current is None or current.loop is not multi_loop:
            raise RuntimeError("Session Loop changed during normal-mode preparation")
        parent_loop = ParentAgentLoop(
            app=context.app, session_id=context.session_id,
            frontend_sink=cast(FrontendSink, multi_loop.get_sink()),
            history_store_dir=multi_loop.history_store_dir,
        )
        parent_loop.set_session_manager(manager)
        parent_loop.load_history(multi_loop.history)
        parent_loop.load_toolsets(list(multi_loop.get_loaded_toolsets()))
        await manager.replace_loop(context.session_id, parent_loop)
        return ToolPostprocessEffect(loop_replaced=True, stop_current_round=True)


TOOLSET = BaseToolSet(name="multiagent", tools=(ExitMultiAgentTool(),))
