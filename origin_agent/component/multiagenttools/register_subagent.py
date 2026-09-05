"""注册子 Agent 的 LLM 配置参数。
以 name 为唯一标识，不允许覆盖已存在的注册项。
所有 LLM 配置参数由调用方显式传入，不再从父 Agent 继承。
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, Any

from abstract.tools.registry import registry, tool_error, tool_result
from entity.constant import SUBAGENT_NAME_PATTERN
from entity.puretype import ToolAvailability, ToolDangerLevel, AgentConfig

if TYPE_CHECKING:
    from entry.base_agent_loop import ToolContext

from ._store import SubagentStore
from system.context import get_runtime_context

logger = logging.getLogger(__name__)


def _handle_register_subagent(args: dict[str, Any], context: ToolContext | None = None) -> dict:
    """以显式传入的全套 LLM 配置参数注册子 Agent。"""
    name: str = str(args.get("name", "")).strip()
    base_url: str = str(args.get("base_url", "")).strip()
    model: str = str(args.get("model", "")).strip()
    api_key_raw: Any = args.get("api_key")
    max_output_tokens_raw: Any = args.get("max_output_tokens")
    max_context_tokens_raw: Any = args.get("max_context_tokens")
    client_type: str = str(args.get("client_type", "")).strip()
    system_prompt_paths: list[str] = args.get("system_prompt_paths") or []

    # ── 参数校验 ──
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
    if not client_type:
        return tool_error("'client_type' is required and must not be empty")

    # api_key: 允许 None 或字符串（含空串）
    if api_key_raw is not None and not isinstance(api_key_raw, str):
        return tool_error("'api_key' must be a string or null")
    api_key: str = api_key_raw if isinstance(api_key_raw, str) else ""

    # max_output_tokens / max_context_tokens: 要求 > 0 的整数
    if not isinstance(max_output_tokens_raw, int) or isinstance(max_output_tokens_raw, bool):
        return tool_error("'max_output_tokens' must be a positive integer")
    if max_output_tokens_raw <= 0:
        return tool_error("'max_output_tokens' must be greater than 0")
    if not isinstance(max_context_tokens_raw, int) or isinstance(max_context_tokens_raw, bool):
        return tool_error("'max_context_tokens' must be a positive integer")
    if max_context_tokens_raw <= 0:
        return tool_error("'max_context_tokens' must be greater than 0")

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

    profile = AgentConfig(
        base_url=base_url,
        model=model,
        api_key=api_key or None,
        system_prompt_paths=system_prompt_paths,
        max_output_tokens=max_output_tokens_raw,
        max_context_tokens=max_context_tokens_raw,
        client_type=client_type,
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
        "Registered subagent '%s': %s @ %s (client=%s)",
        name, model, base_url, client_type,
    )
    return tool_result(
        success=True,
        name=name,
        base_url=base_url,
        model=model,
        max_output_tokens=max_output_tokens_raw,
        max_context_tokens=max_context_tokens_raw,
        client_type=client_type,
        message=f"Subagent '{name}' registered.",
    )


registry.register(
    name="RegisterSubAgent",
    toolset="multiagent",
    schema={
        # 以显式传入的全套 LLM 配置参数注册一个子 Agent。
        #
        # ## 前置条件
        # name 不能与其他已注册子 Agent 重复；如需更新，请先注销。
        # 所有 LLM 配置参数（base_url/model/api_key/max_output_tokens/max_context_tokens/client_type）
        # 均由调用方显式提供，不再从父 Agent 继承。
        # 参数取值参考：系统提示词 Runtime configuration 区的 LLM 行包含当前活跃配置；
        # 其他 profile 的完整配置可通过 Read ws:llm_profiles.es 获取（见系统提示词中的
        # LLM Profiles Registry 与 easysave Serialized Format 小节）。
        # client_type 对应 custom_llm_client/<name>.py 模块名。
        #
        # ## 调用效果
        # 将传入的 base_url/model/api_key/max_output_tokens/max_context_tokens/client_type
        # 写入新的子 Agent 配置中。
        # 可选的 system_prompt_paths 可指定自定义系统提示词文件列表。
        # 配置持久化到工作空间，供 run_subagent 等工具全局使用。
        #
        # ## 返回
        # { "success": true, "name": "...", "base_url": "...", "model": "...",
        #   "max_output_tokens": ..., "max_context_tokens": ...,
        #   "client_type": "...", "message": "..." }
        #
        # ## 何时使用
        # - 当用户希望注册一个使用指定 LLM 配置的子 Agent 时使用本工具。
        # - 子 Agent 可使用与主 Agent 相同或不同的 LLM 后端/模型。
        #
        # ## 副作用/注意
        # - 注册信息持久化到磁盘。
        # - 同名已存在时会返回错误，不会覆盖。
        # - api_key 以明文形式持久化。
        "description": """Register a sub-agent with explicit LLM configuration parameters.

## Prerequisites
The name must be unique among registered sub-agents; to update an existing profile, call unregister_subagent first.
All LLM configuration parameters (base_url, model, api_key, max_output_tokens, max_context_tokens, client_type) must be provided explicitly by the caller; they are no longer inherited from the parent agent.

## Parameter Value Sources
- The current active LLM configuration is available in the system prompt's Runtime configuration section (LLM line).
- Other profiles' full configurations can be obtained via ``Read ws:llm_profiles.es`` (see the LLM Profiles Registry and easysave Serialized Format sections in the system prompt).
- ``client_type`` corresponds to a ``custom_llm_client/<name>.py`` module name.

## Effect
Writes the provided base_url, model, api_key, max_output_tokens, max_context_tokens, and client_type into a new sub-agent profile.
An optional system_prompt_paths can specify a list of custom system prompt files as sandbox logical paths.
The profile is persisted to the workspace and used globally by tools such as run_subagent.

## Returns
{ "success": true, "name": "...", "base_url": "...", "model": "...", "max_output_tokens": ..., "max_context_tokens": ..., "client_type": "...", "message": "..." }

## When to Use
- Use this tool when the user wants to register a sub-agent with a specific LLM configuration.
- Sub-agents can use the same or a different LLM backend/model as the parent agent.

## Side Effects / Notes
- Registration data is persisted to disk.
- If the name already exists, the call returns an error and does not overwrite.
- The api_key is persisted in plaintext.""",
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
                    # LLM API 端点地址。
                    "description": "LLM API endpoint URL for the sub-agent.",
                },
                "model": {
                    "type": "string",
                    # 模型名称。
                    "description": "Model name for the sub-agent.",
                },
                "api_key": {
                    "type": "string",
                    # API 密钥。本地端点（如 llama.cpp / Ollama）可传空字符串。
                    "description": "API key for the endpoint. Pass an empty string for local backends (e.g. llama.cpp, Ollama).",
                },
                "max_output_tokens": {
                    "type": "integer",
                    # 单次 LLM 输出的最大 token 数，必须 > 0。
                    "description": "Maximum output tokens per LLM request. Must be greater than 0.",
                },
                "max_context_tokens": {
                    "type": "integer",
                    # 上下文窗口 token 上限，必须 > 0。
                    "description": "Context window token limit for rotation control. Must be greater than 0.",
                },
                "client_type": {
                    "type": "string",
                    # LLM 客户端模块名，对应 custom_llm_client/<name>.py。
                    "description": "LLM client module name, corresponding to custom_llm_client/<name>.py.",
                },
                "system_prompt_paths": {
                    "type": "array",
                    "items": {"type": "string"},
                    # 可选的自定义系统提示词文件路径列表（沙箱逻辑路径，如 ws:prompts/subagent.txt）。若指定，启动时所有文件必须存在。
                    "description": "Optional list of sandbox logical paths to custom system prompt text files (e.g. ws:prompts/subagent.txt). All files must exist at sub-agent launch time if specified.",
                },
            },
            "required": ["name", "base_url", "model", "api_key", "max_output_tokens", "max_context_tokens", "client_type"],
        },
    },
    handler=_handle_register_subagent,
    danger_level=ToolDangerLevel.safe,
    availability=ToolAvailability.MAIN,
)