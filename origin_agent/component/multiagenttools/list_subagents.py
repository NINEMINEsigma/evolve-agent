"""动态列出角色档案及其当前运行会话。"""

from __future__ import annotations

import logging
from typing import Any

from abstract.tools.registry import registry, tool_result
from entity.puretype import ToolAvailability, ToolDangerLevel
from system.application import Application
from subagent.profile import CharacterProfileResolver

logger = logging.getLogger(__name__)


async def _handle_list_subagents(args: dict[str, Any]) -> dict:
    """动态扫描角色档案并附加当前主会话下的运行状态。"""
    parent_session_id: str = str(args.get("_session_id", "")).strip()

    name_to_session: dict[str, dict[str, Any]] = {}
    if parent_session_id:
        try:
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
            logger.warning(
                "Failed to get subagent snapshot for session=%s",
                parent_session_id,
                exc_info=True,
            )

    app = Application.current()
    resolver = CharacterProfileResolver(app.sandbox, app.llm_profile_store)
    agents: list[dict[str, Any]] = []
    for profile in resolver.discover():
        agents.append({
            "name": profile.name,
            "type": profile.character_type,
            "profile_path": profile.profile_path,
            "llm_profile_name": profile.llm_profile_name,
            "profile_available": profile.error is None and profile.llm_profile is not None,
            "error": profile.error,
            "session": name_to_session.get(profile.name),
        })

    return tool_result(
        success=True,
        count=len(agents),
        agents=agents,
    )


registry.register(
    name="ListSubAgents",
    toolset="multiagent",
    schema={
        # 动态扫描所有角色档案，并返回当前主会话下的子Agent运行状态。
        #
        # ## 前置条件
        # 无。每次调用都会重新扫描 ws:characters/roleplay/ 和 ws:characters/task/。
        #
        # ## 调用效果
        # 纯查询，不修改角色目录、profile.md、profile.md.meta 或 LLM Profile。
        # agents 使用数组而不是以名称为 key 的字典，以保留重名错误条目。
        # 每个条目只返回角色名称、类型、profile.md 路径、LLM Profile 引用名称、
        # 可用性、错误和当前会话状态，不返回 api_key 或完整模型配置。
        #
        # ## 返回
        # {"success": true, "count": 1, "agents": [{"name": "coder", "type": "task", "profile_path": "ws:characters/task/coder/profile.md", "llm_profile_name": "coding-model", "profile_available": true, "error": null, "session": null}]}
        #
        # ## 何时使用
        # - 启动 RunSubAgent 前查看可用角色。
        # - 查看 profile.md、profile.md.meta（包括 [profile] 系统提示词路径）或 LLM Profile 引用错误。
        # - 查看当前主会话下角色是否已有运行中的子Agent。
        #
        # ## 副作用/注意
        # - 纯查询，无副作用。
        # - 缺失、无效和重名角色仍会展示，但不能启动。
        # - 返回结果不包含 API 密钥和完整模型配置。
        "description": """List dynamically discovered sub-agent character profiles and their current session status.

## Prerequisites
None.

## Effect
Read-only query. Scans `ws:characters/roleplay/` and `ws:characters/task/` on every call.
Each entry contains only:
- `name`: character directory name
- `type`: `roleplay` or `task`
- `profile_path`: logical path of `profile.md`
- `llm_profile_name`: name referenced by `profile.md.meta`
- `profile_available`: whether the complete profile is runnable
- `error`: validation or Profile reference error, if any
- `session`: current parent-session runtime status, or null

The `agents` result is an array so duplicate names and their individual errors remain visible. No complete LLM configuration or API key is returned.

## Returns
```json
{"success": true, "count": 1, "agents": [{"name": "coder", "type": "task", "profile_path": "ws:characters/task/coder/profile.md", "llm_profile_name": "coding-model", "profile_available": true, "error": null, "session": null}]}
```

## When to Use
- Check which character profiles are available before calling `RunSubAgent`.
- Inspect `profile.md`, the `[profile]` system-prompt paths in `profile.md.meta`, or LLM Profile reference errors.
- Check whether a character currently has a running sub-agent session.

## Side Effects / Notes
- Read-only query; does not create or modify character profiles.
- Invalid and duplicate-name profiles remain visible with an `error` field but cannot be started.
- The returned list does not contain API keys or complete model configurations.""",
        "parameters": {
            "type": "object",
            "properties": {},
        },
    },
    handler=_handle_list_subagents,
    is_async=True,
    danger_level=ToolDangerLevel.safe,
    availability=ToolAvailability.MAIN,
)
