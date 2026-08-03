"""
将当前多 Agent 协作模式会话退出回普通模式。

退出后 MultiAgentLoop 被替换为 ParentAgentLoop，共享对话历史保留。
multiagent 工具集重新可用，可正常使用 run_subagent / chat_subagent 等。
"""

from __future__ import annotations

import logging
from typing import Any, cast

from abstract.tools.registry import registry, tool_error, tool_result
from entity.puretype import Role, ToolAvailability, ToolDangerLevel
from entity.constant import SYSTEM_CHARACTER_NAME, MAIN_AGENT_CHARACTER_NAME
from entity.messages import CharacterConversationMessage
from entry.agent_sink import FrontendSink
from entry.multi_agent_loop import MultiAgentLoop
from entry.parent_agent_loop import ParentAgentLoop
from system.application import Application

logger = logging.getLogger(__name__)


async def _handle_exit_multi_agent(args: dict[str, Any]) -> dict:
    """退出多 Agent 协作模式，回到普通模式。

    预期参数: 无
    """
    session_id: str = str(args.get("_session_id", "")).strip()

    if not session_id:
        return tool_error("'_session_id' is required")

    app = Application.current()
    if app.session_manager is None:
        return tool_error("SessionManager not available")

    # 获取当前 MultiAgentLoop
    _multi_loop = app.session_manager.get_loop(session_id)
    if _multi_loop is None:
        return tool_error(f"No active loop found for session {session_id}")
    elif isinstance(_multi_loop.loop, MultiAgentLoop):
        multi_loop = _multi_loop.loop
    else:
        return tool_error(f"Current loop is not {MultiAgentLoop.__name__}; already in normal mode")

    # 中断当前级联（如有）
    multi_loop.interrupt()

    # 提取共享资源：history 和 sink
    # MultiAgentLoop._sink 实际存储的是 FrontendSink 实例（由 enter_multi_agent 传入），
    # 但 get_sink() 返回类型标注为 AgentSink 父类，需 cast 收窄。
    history = multi_loop.history
    sink = cast(FrontendSink, multi_loop.get_sink())
    history_store_dir = multi_loop.history_store_dir

    # 创建新的 ParentAgentLoop
    parent_loop = ParentAgentLoop(
        app=app,
        session_id=session_id,
        frontend_sink=sink,
        history_store_dir=history_store_dir,
    )
    parent_loop.set_session_manager(app.session_manager)

    # 用多 Agent 模式的共享历史覆盖 ParentAgentLoop 初始化时从磁盘加载的历史
    parent_loop.load_history(history)

    # 替换 loop
    await app.session_manager.replace_loop(session_id, parent_loop)

    # 追加系统消息标记退出成功
    history.add_message(CharacterConversationMessage(
        role=Role.USER,
        character_name=SYSTEM_CHARACTER_NAME,
        content="[System Result] Exited multi-agent mode, back to normal mode",
        visible_characters=[MAIN_AGENT_CHARACTER_NAME],
    ))
    parent_loop.save_history(session_id)

    return tool_result(
        success=True,
        mode="normal",
        message=f"Session {session_id} exited multi-agent mode, back to normal mode",
    )


registry.register(
    name="exit_multi_agent",
    toolset="multiagent",
    availability=ToolAvailability.MULTI_AGENT,
    danger_level=ToolDangerLevel.readonly,
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
- Shared history is preserved, but multi-agent specific metadata (visible_characters / response_characters) is ignored in normal mode.""",
        "parameters": {
            "type": "object",
            "properties": {},
        },
    },
    handler=_handle_exit_multi_agent,
    is_async=True,
    emoji="🚪",
)