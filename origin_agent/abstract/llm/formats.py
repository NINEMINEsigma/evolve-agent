"""LLM wire format converters — default tool functions for building OpenAI protocol dicts.

``to_openai_message()`` is the single entry point. It dispatches by message type
to one of three private converters. Callers inside ``origin_agent/`` import from
``abstract.llm.formats``; dynamically loaded LLM clients (``custom_llm_client/``)
do the same since ``origin_agent`` is on ``sys.path``.
"""

from typing import Any

from entity.messages import (
    BaseMessage,
    CharacterConversationMessage,
    CharacterSystemMessage,
    TextBlock,
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