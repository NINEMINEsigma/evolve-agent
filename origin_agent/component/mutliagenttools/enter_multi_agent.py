"""
将当前主会话切换到多 Agent 协作模式。

切换后不可逆，所有活跃子 Agent 将被停止，multiagent 工具集将被禁用。
此后所有用户消息均由 MultiAgentLoop 处理：所有参与 Agent 共享同一份对话历史，
每条用户消息触发一轮并发响应；Agent 可在回复中通过 response_characters 指定
下一轮的响应者，按轮次级联直到无人指定或达到最大深度。
"""

from __future__ import annotations

import logging
from typing import Any

from abstract.tools.registry import registry, tool_error, tool_result
from entity.puretype import Role, ToolAvailability, ToolDangerLevel
from entity.constant import SYSTEM_CHARACTER_NAME
from entity.messages import CharacterConversationMessage
from entry.parent_agent_loop import ParentAgentLoop
from system.application import Application
from system.templates import get_templates_dir
from entry.multi_agent_loop import MultiAgentLoop

logger = logging.getLogger(__name__)


async def _handle_enter_multi_agent(args: dict[str, Any]) -> dict:
    """进入多 Agent 协作模式。

    预期参数:
        agents: list[str] — 参与协作的 Agent 角色名列表
    """
    agents: list[str] = args.get("agents", [])
    session_id: str = str(args.get("_session_id", "")).strip()

    if not agents:
        return tool_error("'agents' is required and must not be empty")
    if not session_id:
        return tool_error("'_session_id' is required")

    app = Application.current()
    if app.session_manager is None:
        return tool_error("SessionManager not available")

    # 获取当前 ParentAgentLoop
    _parent_loop = app.session_manager.get_loop(session_id)
    if _parent_loop is None:
        return tool_error(f"No active loop found for session {session_id}")
    elif isinstance(_parent_loop.loop, ParentAgentLoop):
        parent_loop = _parent_loop.loop
    else:
        return tool_error(f"loop is not {ParentAgentLoop.__name__}")

    # 将主 Agent 自身也加入参与者列表（它调用工具后自己也需要参与对话）
    main_agent_name = parent_loop.current_character_agent
    if main_agent_name not in agents:
        agents.insert(0, main_agent_name)

    # 前置校验：除主 Agent 外，所有参与者必须有对应的 subagent profile
    from component.mutliagenttools._store import SubagentStore
    from system.context import get_runtime_context
    store = SubagentStore(get_runtime_context().agentspace)
    missing = [name for name in agents if name != main_agent_name and store.get(name) is None]
    if missing:
        return tool_error(
            f"Subagent profiles not found: {', '.join(missing)}. "
            "Register them first using register_subagent or register_subagent_from_parent."
        )

    # 停止所有子 Agent
    if app.subagent_orchestrator is not None:
        await app.subagent_orchestrator.shutdown_parent(session_id)

    # 加载多 Agent 系统提示词模板
    template_path = get_templates_dir() / "multiagent" / "multi_agent_system_prompt.txt"
    with open(template_path, "r", encoding="utf-8") as f:
        system_prompt_template = f.read()

    # 获取父 Agent 的 LLM client 和工具定义
    from abstract.tools.registry import registry as tool_registry
    from component.mutliagenttools.profile_builder import (
        build_multi_agent_tools,
        build_agent_profiles,
    )
    from system.sandbox import Sandbox

    tools = build_multi_agent_tools(tool_registry)
    llm_client = parent_loop._get_llm_client()
    sandbox = Sandbox(get_runtime_context())

    agent_profiles = build_agent_profiles(
        agents=agents,
        main_agent_name=main_agent_name,
        parent_ctx=parent_loop._get_context(),
        llm_client_factory=lambda name, profile: llm_client,
        system_prompt_template=system_prompt_template,
        sandbox=sandbox,
        store=store,
        session_id=session_id,
        skip_missing_subagent=False,
    )

    # 回填统一 tools（build_agent_profiles 返回时 tools 为空列表）
    for profile in agent_profiles.values():
        profile.tools = tools

    # 获取共享 History 和 sink
    history = parent_loop.history
    sink = parent_loop.get_sink()

    # 创建 MultiAgentLoop 并替换
    multi_loop = MultiAgentLoop(
        app=app,
        session_id=session_id,
        history=history,
        agents=agent_profiles,
        sink=sink,
        history_store_dir=parent_loop.history_store_dir,
    )

    await app.session_manager.replace_loop(session_id, multi_loop)

    # 切换前清理父 loop 最后一条未完成的 assistant tool_calls
    for i in range(len(history.messages) - 1, -1, -1):
        msg = history.messages[i]
        if (
            isinstance(msg, CharacterConversationMessage)
            and msg.role == Role.ASSISTANT
            and msg.tool_calls
        ):
            history.messages[i] = msg.model_copy(update={"tool_calls": None})
            history.messages = history.messages[:i+1]
            history.add_message(CharacterConversationMessage(
                role=Role.USER,
                character_name=SYSTEM_CHARACTER_NAME,
                content="[System Result] Enter multi-agent mode successfully",
                visible_characters=[main_agent_name],
            ))
            break

    return tool_result(
        success=True,
        mode="multi_agent",
        agents=agents,
        message=f"Session {session_id} switched to multi-agent mode with agents: {', '.join(agents)}",
    )


registry.register(
    name="enter_multi_agent",
    toolset="multiagent",
    availability=ToolAvailability.MAIN,
    danger_level=ToolDangerLevel.readonly,
    schema={
        # 将当前主会话切换到多 Agent 协作模式。
        #
        # ## 功能
        # 把当前活跃主会话从 ParentAgentLoop 永久切换到 MultiAgentLoop。
        # 进入后所有参与 Agent 共享同一份对话历史，用户每条消息触发一轮并发响应；
        # Agent 可在 JSON 回复中通过 response_characters 指定下一轮响应者，按轮次级联直到结束。
        #
        # ## 前置条件
        # - 仅有活跃的主会话可以调用；子 Agent 会话不支持。
        # - 调用前必须先使用 list_subagents 查询当前已注册的子 Agent，确认要参与协作的角色名存在。
        #
        # ## 调用效果
        # - 切换后不可逆，无法退出多 Agent 模式。
        # - 所有活跃子 Agent 将被停止并清理。
        # - multiagent 工具集（run_subagent、chat_subagent 等）将被禁用。
        # - 此后所有用户消息由 MultiAgentLoop 处理：所有 Agent 共享同一 History，
        #   每条消息触发一轮 Agent 并发响应；每个 Agent 以 JSON 格式输出，
        #   通过 visible_characters 控制消息可见性，通过 response_characters 指定下一轮响应的 Agent。
        # - 级联按轮次进行，直到没有 Agent 指定下一响应者，或达到最大深度限制。
        #
        # ## 返回
        # ```json
        # { "success": true, "mode": "multi_agent", "agents": ["...", "..."], "message": "..." }
        # ```
        #
        # ## 何时使用
        # - 用户明确要求进入多 Agent 协作模式时。
        # - 已经通过 list_subagents 确认有可用的子 Agent 角色，并明确要让哪些角色参与协作。
        #
        # ## 副作用 / 注意
        # - 当前会话的 loop 从 ParentAgentLoop 永久替换为 MultiAgentLoop。
        # - 所有活跃子 Agent 被停止并清理。
        # - multiagent 工具集被禁用。
        # - agents 参数中的名称必须是已注册子 Agent 的名称，否则工具调用会失败。
        # - 主 Agent 会被无条件加入参与者列表（即使 agents 中未包含也会被自动插入首位）。
        "description": """Switch the current main session to multi-agent collaboration mode.

## Prerequisites
- Only an active main session can call this; sub-agent sessions are not supported.
- Before calling, use `list_subagents` to query currently registered sub-agents and confirm that the requested character names exist.

## Effect
- The switch is irreversible; there is no way to exit multi-agent mode.
- All active sub-agents will be stopped and cleaned up.
- The multiagent toolset (run_subagent, chat_subagent, etc.) will be disabled.
- From then on, all user messages are handled by MultiAgentLoop. All participating agents share the same conversation history.
- Each user message triggers one round of concurrent responses from the currently designated agents.
- Every agent reply is JSON and may use `response_characters` to name the agents that should respond in the next round; rounds cascade until no next agents are named or the maximum depth is reached.

## Returns
```json
{ "success": true, "mode": "multi_agent", "agents": ["...", "..."], "message": "..." }
```

## When to Use
- When the user explicitly asks to enter multi-agent collaboration mode.
- After confirming available sub-agent roles via `list_subagents` and deciding which roles should participate.

## Side Effects / Notes
- The session loop is permanently replaced from ParentAgentLoop to MultiAgentLoop.
- All active sub-agents are stopped and cleaned up.
- The multiagent toolset is disabled.
- Names in the `agents` parameter must correspond to registered sub-agents, otherwise the tool call will fail.
- The main agent is always forcibly included in the participant list (inserted at position 0 even if not specified in `agents`).""",
        "parameters": {
            "type": "object",
            "properties": {
                "agents": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of registered sub-agent character names to participate in the collaboration. Must be obtained from `list_subagents` first.",
                }
            },
            "required": ["agents"],
        },
    },
    handler=_handle_enter_multi_agent,
    is_async=True,
    emoji="👥",
)