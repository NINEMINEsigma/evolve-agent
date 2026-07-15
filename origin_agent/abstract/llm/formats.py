"""LLM wire format converters — default tool functions for building OpenAI protocol dicts.

``to_openai_message()`` is the single entry point. It dispatches by message type
to one of three private converters. Callers inside ``origin_agent/`` import from
``abstract.llm.formats``; dynamically loaded LLM clients (``custom_llm_client/``)
do the same since ``origin_agent`` is on ``sys.path``.

Anthropic 转换器 ``messages_to_anthropic_list()`` 直接从 ``list[BaseMessage]``
构建 Anthropic Messages API 格式，无需经过 OpenAI 中间层。
"""

from __future__ import annotations

import re
from typing import Any

from entity.messages import (
    BaseMessage,
    CharacterConversationMessage,
    CharacterSystemMessage,
    TextBlock,
    ToolCall as MsgToolCall,
    ToolResultMessage,
)
from entity.puretype import Role


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def to_openai_message(
    message: BaseMessage,
    current_character_agent: str,
    is_last_user_message: bool = False,
    **kwargs: Any,
) -> dict[str, Any] | None:
    """Convert a ``BaseMessage`` to an OpenAI protocol dict.

    Dispatches by ``isinstance``:

    - ``ToolResultMessage``          → ``_toolresult_to_openai_dict``
    - ``CharacterConversationMessage`` → ``_charconv_to_openai_dict``
    - others (``BaseMessage``,        → ``_base_to_openai_dict``
              ``CharacterMessage``,
              ``CharacterSystemMessage``)

    Returns ``None`` when the message is invisible to the current agent
    (the underlying ``as_content()`` returned ``None``).
    """
    if isinstance(message, ToolResultMessage):
        return _toolresult_to_openai_dict(
            message, current_character_agent,
            is_last_user_message=is_last_user_message,
            **kwargs,
        )
    if isinstance(message, CharacterConversationMessage):
        return _charconv_to_openai_dict(
            message, current_character_agent,
            is_last_user_message=is_last_user_message,
            **kwargs,
        )
    return _base_to_openai_dict(
        message, current_character_agent,
        is_last_user_message=is_last_user_message,
        **kwargs,
    )


def messages_to_openai_list(
    messages: list[BaseMessage],
    current_character_agent: str,
    **kwargs: Any,
) -> list[dict[str, Any]]:
    """Convert a list of ``BaseMessage`` to a list of OpenAI protocol dicts.

    This is the batch equivalent of ``to_openai_message()``, intended for
    LLM client implementors that need to prepare the full message array
    in one call.
    """
    return [
        d for m in messages
        if (d := to_openai_message(m, current_character_agent, **kwargs)) is not None
    ]


# ---------------------------------------------------------------------------
# Summary dict — minimal role+content for prompt templates
# ---------------------------------------------------------------------------


def to_summary_dict(
    message: BaseMessage,
    current_character_agent: str,
) -> dict[str, Any] | None:
    """Convert a ``BaseMessage`` to a minimal dict for LLM prompt templates.

    Returns only ``{"role": ..., "content": raw_text}``.

    Strips tool_calls, reasoning, ``message_suffix``, ``dynamic_message_suffix``,
    role-prefix and identity-prefix decorations — none of which are useful
    for auto-title / auto-tag / history-summary contexts.

    Messages not visible to *current_character_agent* are filtered out
    (returns ``None``), using the same visibility rule as the full converter.
    """
    # Visibility gate: borrow as_content() which returns None when invisible
    if message.as_content(current_character_agent) is None:
        return None

    # Extract raw text directly from .content field, skipping non-text blocks
    raw = message.content
    if isinstance(raw, str):
        text = raw
    elif isinstance(raw, list):
        parts: list[str] = []
        for block in raw:
            if isinstance(block, TextBlock):
                parts.append(block.text)
        text = "[Resources Block]".join(parts)
    else:
        raise ValueError(f"Invalid content type: {type(raw)}")

    return {"role": message.role.value, "content": text}


# ---------------------------------------------------------------------------
# Private converters
# ---------------------------------------------------------------------------


def _base_to_openai_dict(
    message: BaseMessage,
    current_character_agent: str,
    **kwargs: Any,
) -> dict[str, Any] | None:
    """Convert a plain ``BaseMessage`` (or ``CharacterMessage`` /
    ``CharacterSystemMessage``) to an OpenAI protocol dict.
    """
    content = message.as_content(current_character_agent, **kwargs)
    if content is None:
        return None
    return {
        "role": message.role.value,
        "content": content,
    }


def _charconv_to_openai_dict(
    message: CharacterConversationMessage,
    current_character_agent: str,
    **kwargs: Any,
) -> dict[str, Any] | None:
    """Convert a ``CharacterConversationMessage`` to an OpenAI protocol dict.

    Handles:
    - visibility filtering (delegated to ``_base_to_openai_dict``)
    - role override (non-self → ``"user"``)
    - reasoning field injection
    - ``tool_calls`` dict array construction
    """
    raw = _base_to_openai_dict(message, current_character_agent, **kwargs)
    if raw is None:
        return None

    # Non-self messages are delivered as user messages to the target agent
    if current_character_agent != message.character_name:
        raw["role"] = Role.USER.value
        return raw

    # Self: inject reasoning + tool_calls
    if message.character_name == current_character_agent:
        if message.reasoning_field_name and message.reasoning:
            raw[message.reasoning_field_name] = message.reasoning
        if message.tool_calls:
            raw["tool_calls"] = [tc.as_object() for tc in message.tool_calls]

    return raw


def _toolresult_to_openai_dict(
    message: ToolResultMessage,
    current_character_agent: str,
    **kwargs: Any,
) -> dict[str, Any] | None:
    """Convert a ``ToolResultMessage`` to an OpenAI protocol dict.

    Injects the ``tool_call_id`` field (OpenAI-specific).
    """
    if current_character_agent != message.character_name:
        return None
    raw = _base_to_openai_dict(message, current_character_agent, **kwargs)
    if raw is None:
        return None
    raw["tool_call_id"] = message.tool_call_id
    return raw


# ---------------------------------------------------------------------------
# Anthropic 转换器
# ---------------------------------------------------------------------------


def _content_to_anthropic_blocks(content: Any) -> list[dict[str, Any]]:
    """将 ``as_content()`` 的输出转为 Anthropic content blocks。

    ``as_content()`` 可能返回：
      - ``str``：纯文本
      - ``list[dict]``：OpenAI 格式内容块（text / image_url）
      - ``None``：空
    """
    if content is None:
        return []
    if isinstance(content, str):
        return [{"type": "text", "text": content}] if content else []

    if isinstance(content, list):
        blocks: list[dict[str, Any]] = []
        for block in content:
            if not isinstance(block, dict):
                continue
            block_type = block.get("type")
            if block_type == "text":
                text = block.get("text", "")
                if text:
                    blocks.append({"type": "text", "text": text})
            elif block_type == "image_url":
                image_url = block.get("image_url", {})
                url = image_url.get("url", "") if isinstance(image_url, dict) else ""
                image_block = _image_url_to_anthropic_image(url)
                if image_block is not None:
                    blocks.append(image_block)
        return blocks

    return []


def _image_url_to_anthropic_image(url: str) -> dict[str, Any] | None:
    """将 OpenAI image_url 格式转换为 Anthropic image block。

    支持 base64 data URL（``data:image/png;base64,...``）和普通 URL。
    """
    if not url:
        return None

    if url.startswith("data:"):
        match = re.match(r"data:([^;]+);base64,(.+)", url)
        if match:
            media_type = match.group(1)
            data = match.group(2)
            return {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": media_type,
                    "data": data,
                },
            }
        return None

    return {
        "type": "image",
        "source": {"type": "url", "url": url},
    }


def _tool_call_to_anthropic_tool_use(tc: MsgToolCall) -> dict[str, Any]:
    """将 entity 的 ``ToolCall`` 转为 Anthropic ``tool_use`` block。"""
    import json
    import dirtyjson

    tc_id = tc.id
    name = tc.function.name
    arguments_raw = tc.function.arguments
    # arguments 是 JSON 字符串，解析为 dict
    if isinstance(arguments_raw, str) and arguments_raw.strip():
        try:
            arguments = dirtyjson.loads(arguments_raw)
            if not isinstance(arguments, dict):
                arguments = {}
        except Exception:
            arguments = {"_raw": arguments_raw}
    else:
        arguments = {}
    return {
        "type": "tool_use",
        "id": tc_id,
        "name": name,
        "input": arguments,
    }


def messages_to_anthropic_list(
    messages: list[BaseMessage],
    current_character_agent: str,
    **kwargs: Any,
) -> tuple[list[dict[str, Any]], str]:
    """将 ``list[BaseMessage]`` 直接转换为 Anthropic Messages API 格式。

    返回 ``(anthropic_messages, system_text)``。

    Anthropic 要求：
      - system 提示只能作为顶层 ``system`` 参数，不能穿插在 messages 中。
      - 工具调用结果（tool_result）必须放在 user 消息的 content 列表里。
      - 助手消息的 tool_calls 需要转换为 ``tool_use`` content block。
      - reasoning 内容转换为 ``thinking`` content block。
    """
    system_parts: list[str] = []
    anthropic_messages: list[dict[str, Any]] = []
    pending_tool_results: list[dict[str, Any]] = []

    def _flush_tool_results() -> None:
        nonlocal pending_tool_results
        if pending_tool_results:
            anthropic_messages.append({
                "role": "user",
                "content": pending_tool_results,
            })
            pending_tool_results = []

    for msg in messages:
        # system 消息提取到顶层
        if isinstance(msg, CharacterSystemMessage):
            content = msg.as_content(current_character_agent, **kwargs)
            if content is None:
                continue
            if isinstance(content, str):
                if content.strip():
                    system_parts.append(content)
            elif isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        text = block.get("text", "")
                        if text:
                            system_parts.append(text)
            continue

        if msg.role == Role.SYSTEM:
            content = msg.as_content(current_character_agent, **kwargs)
            if content is None:
                continue
            if isinstance(content, str) and content.strip():
                system_parts.append(content)
            elif isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        text = block.get("text", "")
                        if text:
                            system_parts.append(text)
            continue

        # tool result 消息缓冲到 pending_tool_results
        if isinstance(msg, ToolResultMessage):
            if msg.character_name != current_character_agent:
                continue
            content = msg.as_content(current_character_agent, **kwargs)
            anthropic_content = _content_to_anthropic_blocks(content)
            if not anthropic_content:
                anthropic_content = [{"type": "text", "text": ""}]
            pending_tool_results.append({
                "type": "tool_result",
                "tool_use_id": msg.tool_call_id,
                "content": anthropic_content,
            })
            continue

        _flush_tool_results()

        # 角色对话消息
        if isinstance(msg, CharacterConversationMessage):
            content = msg.as_content(current_character_agent, **kwargs)
            if content is None:
                continue

            is_self = msg.character_name == current_character_agent
            anthropic_content = _content_to_anthropic_blocks(content)

            if is_self:
                # 自己的消息：assistant 角色
                # 注入 thinking block（若有 reasoning）
                if msg.reasoning:
                    anthropic_content.append({
                        "type": "thinking",
                        "thinking": msg.reasoning,
                        "signature": "",
                    })
                # 注入 tool_use blocks（若有 tool_calls）
                if msg.tool_calls:
                    for tc in msg.tool_calls:
                        anthropic_content.append(_tool_call_to_anthropic_tool_use(tc))

                if not anthropic_content:
                    continue
                anthropic_messages.append({
                    "role": "assistant",
                    "content": anthropic_content,
                })
            else:
                # 非自己的消息：user 角色
                if not anthropic_content:
                    continue
                anthropic_messages.append({
                    "role": "user",
                    "content": anthropic_content,
                })
            continue

        # 普通 BaseMessage
        content = msg.as_content(current_character_agent, **kwargs)
        if content is None:
            continue
        anthropic_content = _content_to_anthropic_blocks(content)
        if not anthropic_content:
            continue
        anthropic_messages.append({
            "role": msg.role.value,
            "content": anthropic_content,
        })

    _flush_tool_results()

    system = "\n\n".join(system_parts) if system_parts else ""
    return anthropic_messages, system