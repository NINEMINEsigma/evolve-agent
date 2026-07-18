"""注册子 Agent 鉴权参数。
以 name 为唯一标识，不允许覆盖已存在的注册项。
"""

from __future__ import annotations

import logging
import re
from typing import Any

from abstract.tools.registry import registry, tool_error, tool_result
from entity.constant import SUBAGENT_NAME_PATTERN
from entity.puretype import ToolAvailability, ToolDangerLevel, AgentConfig

from ._store import SubagentStore
from system.context import get_runtime_context

logger = logging.getLogger(__name__)


def _handle_register_subagent_from_parent(args: dict[str, Any]) -> dict:
    """以主 Agent 当前 LLM 配置为模板注册子 Agent，只需提供 name。"""
    name: str = str(args.get("name", "")).strip()
    system_prompt_paths: list[str] = args.get("system_prompt_paths") or []

    if not name:
        return tool_error("'name' is required and must not be empty")
    if not re.match(SUBAGENT_NAME_PATTERN, name):
        return tool_error(
            f"Subagent name '{name}' contains invalid characters. "
            "Allowed: English letters, digits, Chinese characters, '_' and '-'."
        )

    if not isinstance(system_prompt_paths, list):
        return tool_error("'system_prompt_paths' must be a list of strings")
    for p in system_prompt_paths:
        if not isinstance(p, str):
            return tool_error("'system_prompt_paths' must be a list of strings")

    store = SubagentStore(get_runtime_context().agentspace)
    if store.get(name) is not None:
        return tool_error(
            f"Subagent '{name}' already registered. "
            "Unregister it first if you need to replace.",
            registered=True,
        )

    ctx = get_runtime_context()

    profile = AgentConfig(
        base_url=ctx.llm_base_url,
        model=ctx.llm_model,
        api_key=ctx.llm_api_key or None,
        system_prompt_paths=system_prompt_paths,
        max_output_tokens=ctx.llm_max_output_tokens,
        max_context_tokens=ctx.llm_max_context_tokens,
        client_type=ctx.llm_client_name,
    )
    try:
        store.add(name, profile)
    except FileExistsError:
        return tool_error(
            f"Subagent '{name}' already registered. "
            "Unregister it first if you need to replace.",
            registered=True,
        )
    logger.info(
        "Registered subagent '%s' from parent config: %s @ %s",
        name, ctx.llm_model, ctx.llm_base_url,
    )
    return tool_result(
        success=True,
        name=name,
        base_url=ctx.llm_base_url,
        model=ctx.llm_model,
        max_output_tokens=ctx.llm_max_output_tokens,
        max_context_tokens=ctx.llm_max_context_tokens,
        client_type=ctx.llm_client_name,
        message=f"Subagent '{name}' registered using parent agent's LLM config.",
    )


registry.register(
    name="register_subagent_from_parent",
    toolset="multiagent",
    schema={
        # 使用主 Agent 当前的 LLM 配置作为模板注册一个子 Agent。
        #
        # ## 前置条件
        # 调用前必须向用户说明：将使用此工具从父 Agent 复制当前 LLM 配置到新子 Agent。
        # 必须明确告知用户哪些配置会被继承，并说明 api_key 也可能被复制和明文持久化。
        # 用户必须明确同意后才能调用此工具。
        # name 不能与其他已注册子 Agent 重复；如需更新，请先注销。
        #
        # ## 调用效果
        # 将主 Agent 的 base_url、model、api_key、max_output_tokens、max_context_tokens、
        # client_type 复制到新的子 Agent 配置中。
        # 可选的 system_prompt_paths 可指定自定义系统提示词文件列表。
        # 配置持久化到工作空间，供 run_subagent 等工具全局使用。
        #
        # ## 返回
        # { "success": true, "name": "...", "base_url": "...", "model": "...",
        #   "client_type": "...", "message": "..." }
        #
        # ## 何时使用
        # - 当用户希望子 Agent 使用与父 Agent 完全相同的 LLM 配置时使用本工具。
        # - 子 Agent 无法使用与主 Agent 不同的 LLM 后端或模型。
        #
        # ## 副作用/注意
        # - 注册信息持久化到磁盘。
        # - 同名已存在时会返回错误，不会覆盖。
        # - 继承自父 Agent 的 api_key 可能以明文形式持久化。
        "description": """Register a sub-agent using the parent agent's current LLM configuration as a template.

## Prerequisites
Before calling this tool, you MUST explain to the user that you are about to copy the parent agent's current LLM configuration (base_url, model, api_key, max_output_tokens, max_context_tokens, client_type) into a new sub-agent profile.
You MUST clearly tell the user which settings will be inherited and that api_key may also be copied and persisted in plaintext.
You MUST obtain explicit user consent before calling this tool.
The name must be unique among registered sub-agents; to update an existing profile, call unregister_subagent first.

## Effect
Copies the parent agent's base_url, model, api_key, max_output_tokens, max_context_tokens, and client_type into a new sub-agent profile.
An optional system_prompt_paths can specify a list of custom system prompt files as sandbox logical paths.
The profile is persisted to the workspace and used globally by tools such as run_subagent.

## Returns
{ "success": true, "name": "...", "base_url": "...", "model": "...", "client_type": "...", "message": "..." }

## When to Use
- Use this tool when the user wants the sub-agent to use the exact same LLM configuration as the parent agent.
- Sub-agents cannot use a different LLM backend or model than the parent agent.

## Side Effects / Notes
- Registration data is persisted to disk.
- If the name already exists, the call returns an error and does not overwrite.
- The inherited api_key may be persisted in plaintext.""",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    # 子 Agent 的唯一标识（注册名）。
                    "description": "Unique identifier (registration name) for the sub-agent.",
                },
                "system_prompt_paths": {
                    "type": "array",
                    "items": {"type": "string"},
                    # 可选的自定义系统提示词文件路径列表（沙箱逻辑路径，如 ws:prompts/subagent.txt）。若指定，启动时所有文件必须存在。
                    "description": "Optional list of sandbox logical paths to custom system prompt text files (e.g. ws:prompts/subagent.txt). All files must exist at sub-agent launch time if specified.",
                },
            },
            "required": ["name"],
        },
    },
    handler=_handle_register_subagent_from_parent,
    emoji="🤖",
    danger_level=ToolDangerLevel.readonly,
    availability=ToolAvailability.MAIN,
)