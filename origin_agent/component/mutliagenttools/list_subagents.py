"""获取已注册子 Agent 列表。

模块导入时通过 ``registry.register()`` 注册 ``list_subagents`` 工具。
"""

from __future__ import annotations

from typing import Any

from abstract.tools.registry import registry, tool_result

from ._store import _subagent_registry


def _handle_list_subagents(_args: dict[str, Any]) -> dict:
    """获取所有已注册子 Agent 的完整配置。"""
    return tool_result(
        success=True,
        count=len(_subagent_registry),
        agents=_subagent_registry,
    )


registry.register(
    name="list_subagents",
    toolset="multiagent",
    schema={
        # 返回所有当前已注册子 Agent 的完整配置，key 为名称，value 包含 base_url、model、api_key。
        "description": """Return the full configuration of all currently registered sub-agents, keyed by name with base_url, model, and api_key fields.""",
        "parameters": {
            "type": "object",
            "properties": {},
        },
    },
    handler=_handle_list_subagents,
    emoji="📋",
    danger_level="readonly",
)