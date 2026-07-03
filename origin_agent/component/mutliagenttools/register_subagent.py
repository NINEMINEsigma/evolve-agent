"""注册子 Agent 鉴权参数。
以 name 为唯一标识，不允许覆盖已存在的注册项。
"""

from __future__ import annotations

import logging
import re
from typing import Any

from abstract.tools.registry import registry, tool_error, tool_result
from entity.constant import SUBAGENT_NAME_PATTERN
from entity.puretype import ToolAvailability, ToolDangerLevel

from ._store import SubagentStore
from system.context import get_runtime_context

logger = logging.getLogger(__name__)


def _handle_register_subagent(args: dict[str, Any]) -> dict:
    """注册子 Agent 鉴权参数。"""
    name: str = str(args.get("name", "")).strip()
    base_url: str = str(args.get("base_url", "")).strip()
    model: str = str(args.get("model", "")).strip()
    api_key: str | None = args.get("api_key")
    system_prompt_paths: list[str] = args.get("system_prompt_paths") or []
    max_output_tokens: int | None = args.get("max_output_tokens")
    max_context_tokens: int | None = args.get("max_context_tokens")

    if not name:
        return tool_error("'name' is required and must not be empty")
    if not re.match(SUBAGENT_NAME_PATTERN, name):
        return tool_error(
            f"Subagent name '{name}' contains invalid characters. "
            "Allowed: English letters, digits, Chinese characters, '_' and '-'."
        )
    if not base_url:
        return tool_error("'base_url' is required and must not be empty")
    if not model:
        return tool_error("'model' is required and must not be empty")
    if max_output_tokens is None:
        return tool_error("'max_output_tokens' is required")
    if max_context_tokens is None:
        return tool_error("'max_context_tokens' is required")
    if not isinstance(max_output_tokens, int) or max_output_tokens <= 0:
        return tool_error("'max_output_tokens' must be a positive integer")
    if not isinstance(max_context_tokens, int) or max_context_tokens <= 0:
        return tool_error("'max_context_tokens' must be a positive integer")

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

    profile = {
        "base_url": base_url,
        "model": model,
        "api_key": api_key if api_key is not None else None,
        "system_prompt_paths": system_prompt_paths,
        "max_output_tokens": max_output_tokens,
        "max_context_tokens": max_context_tokens,
    }
    try:
        store.add(name, profile)
    except FileExistsError:
        return tool_error(
            f"Subagent '{name}' already registered. "
            "Unregister it first if you need to replace.",
            registered=True,
        )
    logger.info("Registered subagent: %s @ %s (%s)", name, base_url, model)
    return tool_result(
        success=True,
        name=name,
        message=f"Subagent '{name}' registered successfully.",
    )


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

    profile = {
        "base_url": ctx.llm_base_url,
        "model": ctx.llm_model,
        "api_key": ctx.llm_api_key or None,
        "system_prompt_paths": system_prompt_paths,
        "max_output_tokens": ctx.llm_max_output_tokens,
        "max_context_tokens": ctx.llm_max_context_tokens,
    }
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
        message=f"Subagent '{name}' registered using parent agent's LLM config.",
    )


registry.register(
    name="register_subagent",
    toolset="multiagent",
    schema={
        # 注册一个子 Agent 的 LLM 配置。
        #
        # ## 前置条件
        # 调用前必须向用户说明：将使用此工具手动配置一个子 Agent，需要用户提供或确认以下参数：name、base_url、model、api_key、system_prompt_paths、max_output_tokens、max_context_tokens。
        # 用户必须明确同意后才能调用此工具；不得在未经用户确认的情况下推测或填写任何参数（尤其是 api_key 和 base_url）。
        # 必须与用户共同决定：本次注册是使用手动配置的 register_subagent，还是使用继承父 Agent 配置的 register_subagent_from_parent。
        # name 不能与其他已注册子 Agent 重复；如需更新，请先调用 unregister_subagent 注销。
        #
        # ## 调用效果
        # 以 name 为唯一标识保存子 Agent 配置。配置持久化到工作空间，供 run_subagent 等工具全局使用。
        # system_prompt_paths 仅保存文件路径列表，文件内容在子 Agent 启动时读取，因此修改提示词文件不需要重新注册。
        # 若要更改 base_url、model、token 限制等参数，必须先注销再重新注册。
        #
        # ## 返回
        # ```json
        # {"success": true, "name": "...", "message": "Subagent '...' registered successfully."}
        # ```
        #
        # ## 何时使用
        # - 当用户希望子 Agent 使用与父 Agent 不同的 LLM 端点/模型时使用本工具。
        # - 如果用户希望子 Agent 继承父 Agent 的当前 LLM 配置，应使用 register_subagent_from_parent，而不是本工具。
        # - 为子 Agent 指定自定义系统提示词文件。
        # - 配置子 Agent 的输出和上下文 token 限制。
        #
        # ## 副作用/注意
        # - 注册信息持久化到磁盘，可被其他多 Agent 工具读取。
        # - 同名已存在时会返回错误，不会覆盖。
        # - api_key 可能以明文形式持久化，注意避免泄露。
        "description": """Register a sub-agent's LLM configuration.

## Prerequisites
Before calling this tool, you MUST explain to the user that you are about to manually configure a sub-agent and ask them to provide or confirm the following parameters: name, base_url, model, api_key, system_prompt_paths, max_output_tokens, and max_context_tokens.
You MUST obtain explicit user consent before calling this tool. Do NOT guess or fill in any parameters — especially api_key and base_url — without user confirmation.
You and the user MUST jointly decide whether to use this manual tool (register_subagent) or the parent-config template tool (register_subagent_from_parent).
The name must be unique among registered sub-agents; to update an existing profile, call unregister_subagent first.

## Effect
Saves the sub-agent profile keyed by name. The profile is persisted to the workspace and used globally by tools such as run_subagent.
system_prompt_paths stores only the file paths; the file contents are read at sub-agent launch time, so editing the prompt files does NOT require re-registration.
To change base_url, model, token limits, or other core parameters, unregister and re-register.

## Returns
```json
{"success": true, "name": "...", "message": "Subagent '...' registered successfully."}
```

## When to Use
- Use this tool when the user wants the sub-agent to use a different LLM endpoint or model than the parent agent.
- If the user wants the sub-agent to inherit the parent agent's current LLM configuration, use register_subagent_from_parent instead.
- Specify custom system prompt files for the sub-agent.
- Configure output and context token limits for the sub-agent.

## Side Effects / Notes
- Registration data is persisted to disk and may be read by other multi-agent tools.
- If the name already exists, the call returns an error and does not overwrite.
- api_key may be persisted in plaintext; avoid leaking it.""",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    # 子 Agent 的唯一标识（注册名）。
                    "description": "Unique identifier (registration name) for the sub-agent.",
                },
                "base_url": {
                    "type": "string",
                    # 子 Agent LLM API 端点的基础 URL。
                    "description": "Base URL of the sub-agent LLM API endpoint.",
                },
                "model": {
                    "type": "string",
                    # 子 Agent 使用的模型名称。
                    "description": "Model name used by the sub-agent.",
                },
                "api_key": {
                    "type": "string",
                    # 可选的 API 密钥。本地模型可省略。
                    "description": "Optional API key. May be omitted for local models.",
                },
                "system_prompt_paths": {
                    "type": "array",
                    "items": {"type": "string"},
                    # 可选的自定义系统提示词文件路径列表（沙箱逻辑路径，如 ws:prompts/subagent.txt）。若指定，启动时所有文件必须存在。
                    "description": "Optional list of sandbox logical paths to custom system prompt text files (e.g. ws:prompts/subagent.txt). All files must exist at sub-agent launch time if specified.",
                },
                "max_output_tokens": {
                    "type": "integer",
                    # 子 Agent 每次 LLM 响应可生成的最大 token 数。必须为正整数。
                    "description": "Maximum number of tokens the sub-agent can generate per LLM response. Must be a positive integer.",
                },
                "max_context_tokens": {
                    "type": "integer",
                    # 最大上下文窗口大小（token 数）。用于会话轮转控制。必须为正整数。
                    "description": "Maximum context window size in tokens. Used for session rotation control. Must be a positive integer.",
                },
            },
            "required": ["name", "base_url", "model", "max_output_tokens", "max_context_tokens"],
        },
    },
    handler=_handle_register_subagent,
    emoji="🤖",
    danger_level=ToolDangerLevel.readonly,
    availability=ToolAvailability.MAIN,
)

registry.register(
    name="register_subagent_from_parent",
    toolset="multiagent",
    schema={
        # 使用主 Agent 当前的 LLM 配置作为模板注册一个子 Agent。
        #
        # ## 前置条件
        # 调用前必须向用户说明：将使用此工具从父 Agent 复制当前 LLM 配置（base_url、model、api_key、max_output_tokens、max_context_tokens）到新子 Agent。
        # 必须明确告知用户哪些配置会被继承，并说明 api_key 也可能被复制和明文持久化。
        # 用户必须明确同意后才能调用此工具。
        # 必须与用户共同决定：本次注册是使用继承父 Agent 配置的 register_subagent_from_parent，还是手动指定参数的 register_subagent。
        # name 不能与其他已注册子 Agent 重复；如需更新，请先注销。
        #
        # ## 调用效果
        # 将主 Agent 的 base_url、model、api_key、max_output_tokens、max_context_tokens 复制到新的子 Agent 配置中。
        # 可选的 system_prompt_paths 可指定自定义系统提示词文件列表（沙箱逻辑路径，如 ws:prompts/subagent.txt）。
        # 配置持久化到工作空间，供 run_subagent 等工具全局使用。
        #
        # ## 返回
        # ```json
        # {"success": true, "name": "...", "base_url": "...", "model": "...", "max_output_tokens": 4096, "max_context_tokens": 8192, "message": "..."}
        # ```
        #
        # ## 何时使用
        # - 当用户希望子 Agent 使用与父 Agent 完全相同的 LLM 配置时使用本工具。
        # - 如果用户希望子 Agent 使用不同的端点、模型或参数，应使用 register_subagent 手动配置，而不是本工具。
        #
        # ## 副作用/注意
        # - 注册信息持久化到磁盘。
        # - 同名已存在时会返回错误，不会覆盖。
        # - 继承自父 Agent 的 api_key 可能以明文形式持久化。
        "description": """Register a sub-agent using the parent agent's current LLM configuration as a template.

## Prerequisites
Before calling this tool, you MUST explain to the user that you are about to copy the parent agent's current LLM configuration (base_url, model, api_key, max_output_tokens, max_context_tokens) into a new sub-agent profile.
You MUST clearly tell the user which settings will be inherited and that api_key may also be copied and persisted in plaintext.
You MUST obtain explicit user consent before calling this tool.
You and the user MUST jointly decide whether to use this parent-config template tool (register_subagent_from_parent) or the manual configuration tool (register_subagent).
The name must be unique among registered sub-agents; to update an existing profile, call unregister_subagent first.

## Effect
Copies the parent agent's base_url, model, api_key, max_output_tokens, and max_context_tokens into a new sub-agent profile.
An optional system_prompt_paths can specify a list of custom system prompt files as sandbox logical paths (e.g. ws:prompts/subagent.txt).
The profile is persisted to the workspace and used globally by tools such as run_subagent.

## Returns
```json
{"success": true, "name": "...", "base_url": "...", "model": "...", "max_output_tokens": 4096, "max_context_tokens": 8192, "message": "Subagent '...' registered using parent agent's LLM config."}
```

## When to Use
- Use this tool when the user wants the sub-agent to use the exact same LLM configuration as the parent agent.
- If the user wants a different endpoint, model, or other parameters, use register_subagent with manual configuration instead.

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