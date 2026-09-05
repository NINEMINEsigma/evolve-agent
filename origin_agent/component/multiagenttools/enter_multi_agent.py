"""
将当前主会话切换到多 Agent 协作模式。

进入后所有已注册子 Agent 自动全部参与协作，无需手动指定 agents 列表。
所有活跃子 Agent 将被停止，multiagent 工具集将被禁用。
此后所有用户消息均由 MultiAgentLoop 处理：所有参与 Agent 共享同一份对话历史，
每条用户消息触发一轮串行级联响应：初始响应者组成队列逐个执行，
每个 Agent 完成后可通过 response_characters 动态指定后续响应者，
级联持续直到队列清空或达到最大深度。
可通过 ExitMultiAgent 退出回普通模式。
"""

from __future__ import annotations

import logging
from typing import Any

from abstract.tools.registry import registry, tool_error, tool_result
from abstract.llm.loader import create_llm_client
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
        agents: list[str] — 可选，参与协作的 Agent 角色名列表。
                  缺省时自动使用全部已注册子 Agent。
    """
    session_id: str = str(args.get("_session_id", "")).strip()

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

    main_agent_name = parent_loop.current_character_agent

    # 确定参与者列表：优先使用显式传入的 agents，缺省时使用全部已注册子 Agent
    from component.multiagenttools._store import SubagentStore
    from system.context import get_runtime_context
    store = SubagentStore(get_runtime_context().agentspace)

    explicit_agents: list[str] = args.get("agents") or []
    if explicit_agents:
        agents = list(explicit_agents)
    else:
        # 自动使用全部已注册子 Agent
        agents = list(store.list().keys())
        if not agents:
            return tool_error(
                "No registered sub-agents found. "
                "Register at least one sub-agent using RegisterSubAgent before entering multi-agent mode."
            )

    # 将主 Agent 自身也加入参与者列表（它调用工具后自己也需要参与对话）
    if main_agent_name not in agents:
        agents.insert(0, main_agent_name)

    # 前置校验：除主 Agent 外，所有参与者必须有对应的 subagent profile
    missing = [name for name in agents if name != main_agent_name and store.get(name) is None]
    if missing:
        return tool_error(
            f"Subagent profiles not found: {', '.join(missing)}. "
            "Register them first using RegisterSubAgent."
        )

    # 停止所有子 Agent
    if app.subagent_orchestrator is not None:
        await app.subagent_orchestrator.shutdown(session_id)

    # 加载多 Agent 系统提示词模板
    template_path = get_templates_dir() / "multiagent" / "multi_agent_system_prompt.txt"
    with open(template_path, "r", encoding="utf-8") as f:
        system_prompt_template = f.read()

    # 获取父 Agent 的 LLM client 和工具定义
    from abstract.tools.registry import registry as tool_registry
    from component.multiagenttools.profile_builder import (
        build_multi_agent_tools,
        build_agent_profiles,
        agent_config_to_llm_profile,
    )
    from system.sandbox import Sandbox

    tools = build_multi_agent_tools(tool_registry)
    parent_ctx = get_runtime_context()
    sandbox = Sandbox(parent_ctx)

    from entity.puretype import LLMProfile as _LlmProfile
    # 从 loop active profile 获取主 agent 的 LlmProfile
    _main_profile: _LlmProfile | None = parent_loop.active_llm_profile

    agent_profiles = build_agent_profiles(
        agents=agents,
        main_agent_name=main_agent_name,
        parent_ctx=parent_loop._get_context(),
        llm_client_factory=lambda name, profile: create_llm_client(
            # 子 Agent 优先使用注册时冻结的 client_type，保证协议与 base_url 一致；
            # 主 Agent 用 active profile 的客户端类型。
            profile.client_type if profile is not None else (_main_profile.llm_client_name if _main_profile else ""),
            parent_ctx,
            profile=agent_config_to_llm_profile(profile) if profile is not None else _main_profile,
        ),
        system_prompt_template=system_prompt_template,
        sandbox=sandbox,
        store=store,
        session_id=session_id,
        skip_missing_subagent=False,
        main_profile=_main_profile,
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

    # [R3 修订]：不在此追加系统消息——T2（handler）先于 T1（consumer）完成，
    # 系统消息会插入到 assistant tool_calls 和 ToolResultMessage 之间，
    # 违反 Anthropic API 约束。tool_result 的 JSON 内容已包含切换成功信息。
    await app.session_manager.replace_loop(session_id, multi_loop)

    return tool_result(
        success=True,
        mode="multi_agent",
        agents=agents,
        message=f"Session {session_id} switched to multi-agent mode with agents: {', '.join(agents)}",
    )


registry.register(
    name="EnterMultiAgent",
    toolset="multiagent",
    availability=ToolAvailability.MAIN,
    danger_level=ToolDangerLevel.safe,
    schema={
        # 将当前主会话切换到多 Agent 协作模式。
        #
        # ## 功能
        # 把当前活跃主会话从 ParentAgentLoop 切换到 MultiAgentLoop。
        # 进入后所有已注册子 Agent 自动全部参与协作，共享同一份对话历史。
        # 用户每条消息触发一轮串行级联响应：
        # 初始 response_characters 组成队列，Agent 逐个执行，每个完成后可通过
        # response_characters 动态指定后续响应者（已在队列中则移到队首，不在则加到队尾），
        # 级联持续直到队列清空或达到最大深度。
        # 可通过 ExitMultiAgent 退出回普通模式。
        #
        # ## 前置条件
        # - 仅有活跃的主会话可以调用；子 Agent 会话不支持。
        # - 至少有一个已注册子 Agent（通过 RegisterSubAgent 注册）。
        #
        # ## 调用效果
        # - 所有活跃子 Agent 将被停止并清理。
        # - multiagent 工具集（run_subagent、chat_subagent 等）将被禁用。
        # - 此后所有用户消息由 MultiAgentLoop 处理：所有 Agent 共享同一 History，
        #   每条消息触发一轮串行级联响应：Agent 按队列逐个执行，
        #   通过 visible_characters 控制消息可见性，通过 response_characters 动态指定后续响应的 Agent。
        # - 级联按轮次进行，直到没有 Agent 指定下一响应者，或达到最大深度限制。
        #
        # ## 返回
        # ```json
        # { "success": true, "mode": "multi_agent", "agents": ["...", "..."], "message": "..." }
        # ```
        #
        # ## 何时使用
        # - 用户明确要求进入多 Agent 协作模式时。
        # - 已有至少一个已注册子 Agent，无需手动指定列表。
        #
        # ## 副作用 / 注意
        # - 当前会话的 loop 从 ParentAgentLoop 替换为 MultiAgentLoop。
        # - 所有活跃子 Agent 被停止并清理。
        # - multiagent 工具集被禁用。
        # - 主 Agent 会被无条件加入参与者列表。
        # - 可通过 ExitMultiAgent 退出回普通模式。
        # - 工具返回成功后，模式切换将在你本轮回复完成后生效。请直接给用户一个简短确认，不要再调用任何工具。
        #
        # ## 用户侧控制
        # - 用户每次发送消息时可从前端指定 visible_characters（消息对哪些 Agent 可见）
        #   和 response_characters（哪些 Agent 需要响应此消息）。
        # - 未指定时默认对所有 Agent 可见、所有 Agent 参与响应。
        # - 指定 @response(none) 或空列表时该消息不触发任何 Agent 响应。
        # - 因此并非每条消息都会触发全体级联——级联的参与者由用户指定的 response_characters 决定。
        "description": """Switch the current main session to multi-agent collaboration mode.

## Prerequisites
- Only an active main session can call this; sub-agent sessions are not supported.
- At least one sub-agent must be registered (via `RegisterSubAgent`).

## Effect
- All active sub-agents will be stopped and cleaned up.
- The multiagent toolset (run_subagent, chat_subagent, etc.) will be disabled.
- From then on, all user messages are handled by MultiAgentLoop. All registered sub-agents automatically participate and share the same conversation history.
- Each user message triggers one round of serial cascading responses: the initial `response_characters` form a queue, agents execute one at a time, each waiting for the previous to fully complete before starting.
- Every agent reply may use `response_characters` to dynamically adjust the queue — agents already queued are moved to the front, new agents are appended to the back, self-nomination is ignored.
- The cascade continues until the queue is empty or the maximum depth (len(agents) * cascade_depth) is reached.
- Use `ExitMultiAgent` to switch back to normal mode.

## Returns
```json
{ "success": true, "mode": "multi_agent", "agents": ["...", "..."], "message": "..." }
```

## When to Use
- When the user explicitly asks to enter multi-agent collaboration mode.
- When at least one sub-agent is registered; no need to manually specify the agent list.

## Side Effects / Notes
- The session loop is replaced from ParentAgentLoop to MultiAgentLoop.
- All active sub-agents are stopped and cleaned up.
- The multiagent toolset is disabled.
- The main agent is always forcibly included in the participant list.
- Use `ExitMultiAgent` to exit back to normal mode.
- After this tool returns success, the mode switch takes effect after your current reply completes. Simply give the user a brief confirmation and do NOT call any other tools in your response. The new multi-agent loop will handle all subsequent user messages.

## User-Side Controls
- When sending each message, the user can specify `visible_characters` (which agents can see the message) and `response_characters` (which agents should respond) from the frontend.
- If not specified, the message is visible to all agents and all agents participate in the cascade.
- Specifying `@response(none)` or an empty list means no agent responds to that message.
- Therefore, not every message triggers a full cascade — the participants are determined by the user-specified `response_characters`.""",
        "parameters": {
            "type": "object",
            "properties": {
                "agents": {
                    "type": "array",
                    "items": { "type": "string" },
                    "description": "Optional list of registered sub-agent character names to participate. If omitted, all registered sub-agents are automatically included.",
                }
            },
        },
    },
    handler=_handle_enter_multi_agent,
    is_async=True,
)