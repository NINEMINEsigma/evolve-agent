"""删除已注册的子 Agent。

模块导入时通过 ``registry.register()`` 注册 ``unregister_subagent`` 工具。
"""

from __future__ import annotations

import logging
from typing import Any

from abstract.tools.registry import registry, tool_error, tool_result
from entity.puretype import ToolAvailability, ToolDangerLevel

from ._store import _save_subagents, _subagent_registry

logger = logging.getLogger(__name__)


def _handle_unregister_subagent(args: dict[str, Any]) -> dict:
    """删除指定名称的子 Agent。"""
    name: str = str(args.get("name", "")).strip()

    if not name:
        return tool_error("'name' is required and must not be empty")

    if name not in _subagent_registry:
        return tool_error(
            f"Subagent '{name}' not found.",
            found=False,
        )

    del _subagent_registry[name]
    _save_subagents()
    logger.info("Unregistered subagent: %s", name)
    return tool_result(
        success=True,
        name=name,
        message=f"Subagent '{name}' unregistered successfully.",
    )


registry.register(
    name="unregister_subagent",
    toolset="multiagent",
    schema={
        # 通过唯一名称移除已注册的子 Agent 配置。
        #
        # ## 前置条件
        # 要注销的子 Agent 必须已存在。
        # 若该子 Agent 正在运行，本工具不会停止其会话；需先调用 stop_subagent。
        #
        # ## 调用效果
        # 从持久化注册表中删除指定 name 的子 Agent 配置，并立即保存到磁盘。
        # 删除后无法通过 run_subagent 启动该名称的子 Agent，直到重新注册。
        #
        # ## 返回
        # ```json
        # {"success": true, "name": "...", "message": "Subagent '...' unregistered successfully."}
        # ```
        #
        # ## 何时使用
        # - 需要更新子 Agent 的 LLM 配置时（先注销再重新注册）。
        # - 清理不再使用的子 Agent 配置。
        #
        # ## 副作用/注意
        # - 仅删除注册配置，不影响正在运行的会话。
        # - 注销操作会立即保存到磁盘，删除结果在后续启动中仍然生效。
        # - 删除不存在的 name 会返回错误。
        "description": """Remove a registered sub-agent profile by its unique name.

## Prerequisites
The sub-agent to unregister must exist.
If the sub-agent is currently running, this tool does NOT stop its session; call stop_subagent first if needed.

## Effect
Deletes the named sub-agent profile from the persistent registry and saves the change to disk immediately.
After deletion, the name cannot be used with run_subagent until it is re-registered.

## Returns
```json
{"success": true, "name": "...", "message": "Subagent '...' unregistered successfully."}
```

## When to Use
- Update a sub-agent's LLM configuration (unregister then re-register).
- Clean up sub-agent profiles that are no longer needed.

## Side Effects / Notes
- Only removes the registration profile; running sessions are not affected.
- The removal is persisted to disk immediately and remains effective after subsequent restarts.
- Unregistering a non-existent name returns an error.""",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    # 要注销的子 Agent 注册名。
                    "description": "Registration name of the sub-agent to unregister.",
                },
            },
            "required": ["name"],
        },
    },
    handler=_handle_unregister_subagent,
    emoji="🗑️",
    danger_level=ToolDangerLevel.readonly,
    availability=ToolAvailability.MAIN,
)