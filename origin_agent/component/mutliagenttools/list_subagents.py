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
        # 返回所有当前已注册子 Agent 的完整配置。
        #
        # ## 前置条件
        # 无。
        #
        # ## 调用效果
        # 纯查询，无副作用。返回以 name 为 key 的字典，每个 value 包含 base_url、model、api_key、system_prompt_path、max_output_tokens、max_context_tokens。
        #
        # ## 返回
        # ```json
        # {"success": true, "count": 2, "agents": {"sub1": {"base_url": "...", "model": "...", "api_key": "...", "system_prompt_path": "...", "max_output_tokens": 4096, "max_context_tokens": 8192}}}
        # ```
        #
        # ## 何时使用
        # - 查看当前有哪些子 Agent 可用。
        # - 在调用 run_subagent 前确认子 Agent 名称和配置。
        # - 需要决定是否需要注册/注销子 Agent 时。
        #
        # ## 副作用/注意
        # - 纯查询，不修改注册表。
        # - 返回的配置可能包含敏感信息（如 api_key），谨慎处理。
        "description": """Return the full configuration of all currently registered sub-agents.

## Prerequisites
None.

## Effect
Read-only query with no side effects. Returns a dictionary keyed by sub-agent name, where each value contains base_url, model, api_key, system_prompt_path, max_output_tokens, and max_context_tokens.

## Returns
```json
{"success": true, "count": 2, "agents": {"sub1": {"base_url": "...", "model": "...", "api_key": "...", "system_prompt_path": "...", "max_output_tokens": 4096, "max_context_tokens": 8192}}}
```

## When to Use
- Check which sub-agents are currently available.
- Confirm a sub-agent's name and configuration before calling run_subagent.
- Decide whether to register or unregister a sub-agent.

## Side Effects / Notes
- Read-only query; does not modify the registry.
- Returned configurations may contain sensitive information such as api_key; handle with care.""",
        "parameters": {
            "type": "object",
            "properties": {},
        },
    },
    handler=_handle_list_subagents,
    emoji="📋",
    danger_level="readonly",
)