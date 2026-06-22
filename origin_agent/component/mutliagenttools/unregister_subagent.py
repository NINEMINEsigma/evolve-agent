"""删除已注册的子 Agent。

模块导入时通过 ``registry.register()`` 注册 ``unregister_subagent`` 工具。
"""

from __future__ import annotations

import logging
from typing import Any

from abstract.tools.registry import registry, tool_error, tool_result

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
        # 通过唯一名称移除已注册的子 Agent。
        "description": """Remove a registered sub-agent by its unique name.""",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    # 要注销的子 Agent 的名称。
                    "description": "Name of the sub-agent to unregister.",
                },
            },
            "required": ["name"],
        },
    },
    handler=_handle_unregister_subagent,
    emoji="🗑️",
    danger_level="readonly",
)