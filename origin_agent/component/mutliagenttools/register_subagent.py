"""注册子 Agent 鉴权参数。

模块导入时通过 ``registry.register()`` 注册 ``register_subagent`` 工具。
以 name 为唯一标识，不允许覆盖已存在的注册项。
"""

from __future__ import annotations

import logging
from typing import Any

from abstract.tools.registry import registry, tool_error, tool_result

from ._store import _save_subagents, _subagent_registry

logger = logging.getLogger(__name__)


def _handle_register_subagent(args: dict[str, Any]) -> dict:
    """注册子 Agent 鉴权参数。"""
    name: str = str(args.get("name", "")).strip()
    base_url: str = str(args.get("base_url", "")).strip()
    model: str = str(args.get("model", "")).strip()
    api_key: str | None = args.get("api_key")
    system_prompt_path: str | None = args.get("system_prompt_path")
    max_output_tokens: int | None = args.get("max_output_tokens")
    max_context_tokens: int | None = args.get("max_context_tokens")

    if not name:
        return tool_error("'name' is required and must not be empty")
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

    if name in _subagent_registry:
        return tool_error(
            f"Subagent '{name}' already registered. "
            "Unregister it first if you need to replace.",
            registered=True,
        )

    _subagent_registry[name] = {
        "base_url": base_url,
        "model": model,
        "api_key": api_key if api_key is not None else None,
        "system_prompt_path": system_prompt_path if system_prompt_path else None,
        "max_output_tokens": max_output_tokens,
        "max_context_tokens": max_context_tokens,
    }
    _save_subagents()
    logger.info("Registered subagent: %s @ %s (%s)", name, base_url, model)
    return tool_result(
        success=True,
        name=name,
        message=f"Subagent '{name}' registered successfully.",
    )


registry.register(
    name="register_subagent",
    toolset="multiagent",
    schema={
        # 注册一个子 Agent 的完整配置（base_url、model、api_key、max_output_tokens、
        # max_context_tokens、system_prompt_path）。
        # 以 name 为唯一标识，不允许覆盖已存在的注册项。
        # max_output_tokens / max_context_tokens 为必填的 token 限制参数。
        # system_prompt_path 为可选字段，指向自定义系统提示词的文本文件绝对路径。
        # 注册信息为全局共享，其他多 Agent 工具可据此调用子 Agent。
        "description": (
            "Register a sub-agent profile (base_url, model, api_key, max_output_tokens, "
            "max_context_tokens, system_prompt_path). "
            "The 'name' field is the unique identifier; existing entries cannot be overwritten. "
            "max_output_tokens and max_context_tokens are required token limits. "
            "The optional 'system_prompt_path' points to a text file containing a custom system prompt. "
            "Registered profiles are global and may be used by other multi-agent tools."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    # 子 Agent 的唯一标识名称。
                    "description": "Unique identifier for the sub-agent.",
                },
                "base_url": {
                    "type": "string",
                    # 子 Agent 的 API 基础地址。
                    "description": "Base URL of the sub-agent API endpoint.",
                },
                "model": {
                    "type": "string",
                    # 子 Agent 使用的模型名称。
                    "description": "Model name used by the sub-agent.",
                },
                "api_key": {
                    "type": "string",
                    # 可选的 API 密钥。本地模型可能不需要。
                    "description": "Optional API key. May be omitted for local models.",
                },
                "system_prompt_path": {
                    "type": "string",
                    # 可选的自定义系统提示词文件绝对路径。若指定则启动时必须存在。
                    "description": "Optional absolute path to a custom system prompt text file. Must exist at sub-agent launch time if specified.",
                },
                "max_output_tokens": {
                    "type": "integer",
                    # 子 Agent 单次 LLM 输出的最大 token 数。
                    "description": "Maximum number of tokens the sub-agent can generate per LLM response.",
                },
                "max_context_tokens": {
                    "type": "integer",
                    # 子 Agent 上下文窗口的 token 上限，用于旋转控制。
                    "description": "Maximum context window size in tokens. Used for session rotation control.",
                },
            },
            "required": ["name", "base_url", "model", "max_output_tokens", "max_context_tokens"],
        },
    },
    handler=_handle_register_subagent,
    emoji="🤖",
    danger_level="write",
)