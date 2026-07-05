"""
将当前主会话切换到多 Agent 协作模式。

切换后不可逆，所有活跃子 Agent 将被停止，multiagent 工具集将被禁用。
此后所有用户消息均由 MultiAgentLoop 处理，各 Agent 通过级联递归进行广播协作。
"""

from __future__ import annotations

from typing import Any

from abstract.tools.registry import registry, tool_error, tool_result
from entity.puretype import ToolAvailability, ToolDangerLevel
from entry.parent_agent_loop import ParentAgentLoop
from system.application import Application
from system.templates import get_templates_dir
from entry.multi_agent_loop import MultiAgentLoop, AgentProfile


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
    elif isinstance(_parent_loop, ParentAgentLoop):
        parent_loop = _parent_loop
    else:
        return tool_error(f"loop is not {ParentAgentLoop.__name__}")

    # 将主 Agent 自身也加入参与者列表（它调用工具后自己也需要参与对话）
    main_agent_name = parent_loop.current_character_agent
    if main_agent_name not in agents:
        agents.insert(0, main_agent_name)

    # 停止所有子 Agent
    if app.subagent_orchestrator is not None:
        await app.subagent_orchestrator.shutdown_parent(session_id)

    # 加载多 Agent 系统提示词模板
    template_path = get_templates_dir() / "multiagent" / "multi_agent_system_prompt.txt"
    with open(template_path, "r", encoding="utf-8") as f:
        system_prompt_template = f.read()

    # 获取父 Agent 的 LLM client 和工具定义
    llm_client = parent_loop._get_llm_client()
    tools = parent_loop._get_tool_definitions()

    # 过滤掉 multiagent 工具集（进入多 Agent 模式后禁用）
    from abstract.tools.registry import registry as tool_registry
    multiagent_tool_names: set[str] = set(tool_registry.get_tool_names_for_toolset("multiagent"))
    tools = [t for t in tools if t.get("function", {}).get("name") not in multiagent_tool_names]

    # 为每个 Agent 构造 Profile
    agent_profiles: dict[str, AgentProfile] = {}
    for name in agents:
        prompt = system_prompt_template.replace("{{CHARACTER_NAME}}", name)
        agent_profiles[name] = AgentProfile(
            character_name=name,
            system_prompt=prompt,
            tools=tools,
            llm_client=llm_client,
        )

    # 获取共享 History 和 sink
    history = parent_loop._history
    sink = parent_loop._get_sink()

    # 创建 MultiAgentLoop 并替换
    multi_loop = MultiAgentLoop(
        app=app,
        session_id=session_id,
        history=history,
        agents=agent_profiles,
        sink=sink,
    )

    app.session_manager.replace_loop(session_id, multi_loop)

    # 切换后立即让主 Agent 发言一次，弥补 loop 切换导致的中途静默
    await multi_loop._cascade([main_agent_name])

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
        # 将当前会话切换到多 Agent 协作模式。
        #
        # ## 前置条件
        # 仅有活跃的主会话可以切换；子 Agent 会话不支持。
        #
        # ## 调用效果
        # 切换后不可逆，无法退出多 Agent 模式。所有活跃子 Agent 将被停止。
        # multiagent 工具集（run_subagent、chat_subagent 等）将被禁用。
        # 此后所有用户消息由 MultiAgentLoop 处理，各 Agent 通过级联递归进行广播协作。
        # 每个 Agent 以 JSON 格式输出，通过 visible_characters 控制消息可见性，
        # 通过 response_characters 指定下一轮响应的 Agent。
        #
        # ## 返回
        # { success: true, mode: "multi_agent", agents: [...], message: "..." }
        #
        # ## 副作用
        # - 当前会话的 loop 从 ParentAgentLoop 永久替换为 MultiAgentLoop
        # - 所有活跃子 Agent 被停止并清理
        # - multiagent 工具集被禁用
        "description": (
            "Switch the current session to multi-agent collaboration mode. "
            "Irreversible. All active sub-agents will be stopped. "
            "Multi-agent tools will be disabled."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "agents": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of agent character names to participate in the collaboration",
                }
            },
            "required": ["agents"],
        },
    },
    handler=_handle_enter_multi_agent,
    is_async=True,
    emoji="",
)