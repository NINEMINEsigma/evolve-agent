"""LMStudio 等本地 GGUF 后端专用的 OpenAI 兼容 LLM 客户端。

与标准 :class:`OpenAILLMClient` 的区别：
  - 在发送前将所有 ``role: "system"`` 消息合并到列表开头。

部分 OpenAI 兼容后端（如 LMStudio 加载的 GGUF 模型）使用 Jinja chat
template，要求 system 消息只能出现在对话开头；穿插在 user/assistant 之间的
system 消息会触发 ``raise_exception('System message must be at the
beginning')``。本客户端在请求构造阶段自动合并 system 消息，其余行为与
:class:`OpenAILLMClient` 完全一致。
"""

from __future__ import annotations

import os
from typing import Any, Optional

from entity.puretype import LLMProfile
from system.context import RuntimeContext

from custom_llm_client.openai_client import OpenAILLMClient


# ---------------------------------------------------------------------------
# 消息整理
# ---------------------------------------------------------------------------


def _merge_leading_system(
    messages: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """将分散的 system 消息合并到列表开头。

    按出现顺序将所有 ``role: "system"`` 消息的文本内容合并为一条，放置在
    列表最前面，其余消息保持原序。非文本 content（图片等）的 system 消息
    会被跳过——system 消息按约定只携带全局文本指令。
    """
    system_parts: list[str] = []
    others: list[dict[str, Any]] = []
    for m in messages:
        if m.get("role") != "system":
            others.append(m)
            continue
        content = m.get("content")
        if isinstance(content, str):
            if content.strip():
                system_parts.append(content)
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    text = block.get("text", "")
                    if text:
                        system_parts.append(text)
    if not system_parts:
        return others
    return [{"role": "system", "content": "\n\n".join(system_parts)}] + others


# ---------------------------------------------------------------------------
# 客户端
# ---------------------------------------------------------------------------


class LMStudioLLMClient(OpenAILLMClient):
    """LMStudio 等本地 GGUF 后端专用的 OpenAI 兼容客户端。

    继承 :class:`OpenAILLMClient` 的全部公开接口（``chat`` / ``chat_stream``）
    与重试 / 流式续传 / 工具解析逻辑，仅覆写 :meth:`_build_kwargs` 以在
    请求构造阶段合并 system 消息。
    """

    def _build_kwargs(
        self,
        messages: list[dict[str, Any]],
        tools: Optional[list[dict[str, Any]]] = None,
        stream: bool = False,
        response_format: Optional[dict[str, str]] = None,
    ) -> dict[str, Any]:
        """在父类参数基础上合并 system 消息到开头。"""
        merged = _merge_leading_system(messages)
        return super()._build_kwargs(
            merged, tools, stream, response_format,
        )


# ---------------------------------------------------------------------------
# 模块工厂
# ---------------------------------------------------------------------------


def create_llm_client(
    runtime_context: RuntimeContext,
    profile: LLMProfile | None = None,
) -> LMStudioLLMClient:
    """按 profile 构造 LMStudio LLM 客户端。
    """
    if profile is None:
        raise ValueError("create_llm_client requires a non-None profile for the main model path ")

    return LMStudioLLMClient(
        api_key=profile.api_key or os.environ.get("OPENAI_API_KEY", ""),
        base_url=profile.base_url,
        model=profile.model,
        temperature=profile.temperature,
        max_output_tokens=profile.max_output_tokens,
        reasoning_effort=profile.reasoning_effort,
    )