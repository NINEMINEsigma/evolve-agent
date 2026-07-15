"""获取已注册子 Agent 列表及其当前运行会话。

模块导入时通过 ``registry.register()`` 注册 ``list_subagents`` 工具。
返回所有已注册子 Agent 的配置，并附带当前主会话下该子 Agent 的运行会话信息。
由于同一主会话下每个子 Agent 只能有一个活跃或排队实例，session 字段为空即表示未运行。
"""

from __future__ import annotations

import logging
from typing import Any

from abstract.tools.registry import registry, tool_result
from entity.puretype import ToolAvailability, ToolDangerLevel

from ._store import SubagentStore
from system.context import get_runtime_context

logger = logging.getLogger(__name__)


async def _handle_list_subagents(args: dict[str, Any]) -> dict:
    """获取所有已注册子 Agent 的配置及当前运行会话。

    自动从 ``_session_id`` 获取当前父会话 ID，查询每个子 Agent 是否已有运行中的会话。
    """
    parent_session_id: str = str(args.get("_session_id", "")).strip()

    # 按 name 索引当前运行中的子会话
    name_to_session: dict[str, dict[str, Any]] = {}
    if parent_session_id:
        try:
            from system.application import Application
            orch = Application.current().subagent_orchestrator
            snapshot = orch.get_snapshot(parent_session_id=parent_session_id)
            for session_id, info in snapshot.items():
                name = info.get("name", "")
                if name:
                    name_to_session[name] = {
                        "session_id": session_id,
                        "status": info.get("status", "unknown"),
                        "pending_approvals": info.get("pending_approvals", []),
                        "feedback_count": len(info.get("feedback", [])),
                    }
        except Exception:
            logger.warning("Failed to get subagent snapshot for session=%s", parent_session_id, exc_info=True)

    # 为每个注册项注入 session 字段
    store = SubagentStore(get_runtime_context().agentspace)
    agents: dict[str, dict[str, Any]] = {}
    for name, config in store.list().items():
        entry = config.model_dump()
        entry["session"] = name_to_session.get(name, None)
        agents[name] = entry

    return tool_result(
        success=True,
        count=len(agents),
        agents=agents,
    )


registry.register(
    name="list_subagents",
    toolset="multiagent",
    schema={
        # 返回所有当前已注册子 Agent 的完整配置，以及每个子 Agent 在当前主会话下的运行会话信息。
        #
        # ## 前置条件
        # 无。
        #
        # ## 调用效果
        # 纯查询，无副作用。返回以 name 为 key 的字典，每个 value 包含：
        # - 注册配置：base_url、model、api_key、system_prompt_paths、max_output_tokens、max_context_tokens
        # - session：当前运行会话信息（含 session_id、status、pending_approvals、feedback_count）；未运行时为 null
        #
        # ## 返回
        # ```json
        # {"success": true, "count": 2, "agents": {"coder": {"base_url": "...", "model": "...", "session": {"session_id": "...", "status": "running", "pending_approvals": [], "feedback_count": 0}}}}}
        # ```
        #
        # ## 何时使用
        # - 查看当前有哪些子 Agent 可用，以及它们是否正在运行。
        # - 在调用 run_subagent / chat_subagent / stop_subagent 前确认子 Agent 名称和当前会话状态。
        # - 需要决定是否需要注册/注销子 Agent 时。
        #
        # ## 副作用/注意
        # - 纯查询，不修改注册表。
        # - 返回的配置可能包含敏感信息（如 api_key），谨慎处理。
        # - 同一主会话下每个子 Agent 只能有一个会话实例，因此 session 字段唯一对应。
        "description": """Return the full configuration of all currently registered sub-agents, along with their current running session info under the current parent session.

## Prerequisites
None.

## Effect
Read-only query with no side effects. Returns a dictionary keyed by sub-agent name, where each value contains:
- Registration config: base_url, model, api_key, system_prompt_paths, max_output_tokens, max_context_tokens
- session: current running session info (session_id, status, pending_approvals, feedback_count); null if not running

## Returns
```json
{"success": true, "count": 2, "agents": {"coder": {"base_url": "...", "model": "...", "session": {"session_id": "...", "status": "running", "pending_approvals": [], "feedback_count": 0}}}}
```

## When to Use
- Check which sub-agents are available and whether they are currently running.
- Confirm a sub-agent's name and current session status before calling run_subagent / chat_subagent / stop_subagent.
- Decide whether to register or unregister a sub-agent.

## Side Effects / Notes
- Read-only query; does not modify the registry.
- Returned configurations may contain sensitive information such as api_key; handle with care.
- Each sub-agent can only have one session instance per parent session, so the session field is unique per name.""",
        "parameters": {
            "type": "object",
            "properties": {},
        },
    },
    handler=_handle_list_subagents,
    is_async=True,
    emoji="📋",
    danger_level=ToolDangerLevel.readonly,
    availability=ToolAvailability.MAIN,
)