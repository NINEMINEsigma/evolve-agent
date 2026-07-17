"""会话历史摘要工具 — 供 session_manager.py / parent_agent_loop.py 复用。

提供：
- History 实例到纯文本的安全转换（处理多模态 block，剥离 base64；包含 tool call/result）
- 任意消息列表到纯文本的转换（``messages_to_text``）
- 提取最后 N 轮消息的原始对象（``extract_last_rounds``）
- LLM 摘要生成（使用 compress.txt / compress_input.txt 模板）
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from entity.puretype import Role
from entity.messages import BaseMessage
from system.templates import read_template
from entity.constant import SUMMARY_INPUT_MAX_CHARS, INHERIT_LAST_ROUNDS, TOOL_RESULT_PREVIEW_CHARS, META_EXTRACTOR_CHARACTER

if TYPE_CHECKING:
    from abstract.llm.client import BaseLLMClient
    from entity.messages import BaseMessage, History, MessageBlock

logger = logging.getLogger(__name__)


def messages_to_text(messages: list) -> str:
    """把一系列 ``BaseMessage`` 转换为适合 LLM 阅读的纯文本。

    格式：每条消息以 ``## ROLE`` 开头，按需输出 tool_call/tool_result 行。
    全局截断由调用方自行处理（``SUMMARY_INPUT_MAX_CHARS``）。
    """
    from entity.messages import (
        CharacterConversationMessage,
        ToolResultMessage,
    )

    lines: list[str] = []

    for msg in messages:
        role_str = _role_display(msg)
        if role_str is None:
            continue

        # 工具结果消息：紧凑输出 + 截断
        if isinstance(msg, ToolResultMessage):
            text = _content_to_text(msg.content)
            lines.append(f"## {role_str} ({msg.tool_call_id})")
            if len(text) > TOOL_RESULT_PREVIEW_CHARS:
                lines.append(text[:TOOL_RESULT_PREVIEW_CHARS] + "...")
            else:
                lines.append(text)
            lines.append("")
            continue

        # 含 tool_calls 的助手消息：先输出文本，再逐条输出工具调用摘要
        if isinstance(msg, CharacterConversationMessage) and msg.tool_calls:
            content_text = _content_to_text(msg.content)
            if content_text:
                lines.append(f"## {role_str}")
                lines.append(content_text)
            for tc in msg.tool_calls:
                args_excerpt = tc.function.arguments[:200]
                lines.append(f"[tool_call: {tc.function.name}({args_excerpt})]")
            lines.append("")
            continue

        # 普通 user / assistant
        content_text = _content_to_text(msg.content)
        if content_text:
            lines.append(f"## {role_str}")
            lines.append(content_text)
            lines.append("")

    return "\n".join(lines)


def history_to_summary_text(history: History) -> str:
    """把 History 实例转换为适合 LLM 阅读的纯文本。

    委托给 ``messages_to_text``，应用 ``SUMMARY_INPUT_MAX_CHARS`` 截断。
    """
    result = messages_to_text(list(history.iter_messages()))
    if len(result) > SUMMARY_INPUT_MAX_CHARS:
        result = result[:SUMMARY_INPUT_MAX_CHARS] + "\n\n... [truncated]"
    return result


def extract_last_rounds(
    history: History,
    rounds: int = INHERIT_LAST_ROUNDS,
    include_tool_messages: bool = False,
) -> list:
    """从 History 中提取倒数 ``rounds`` 个用户/助手消息轮次。

    返回的列表包含纯 ``CharacterConversationMessage`` 原始引用（只读）。
    不含 ``ToolResultMessage``，除非 ``include_tool_messages=True``。

    轮次定义：从倒数第 ``rounds`` 条用户消息到末尾的所有 ``Role.USER``
    和 ``Role.ASSISTANT`` 消息。
    """
    from entity.messages import (
        CharacterConversationMessage,
        ToolResultMessage,
        CharacterSystemMessage,
    )

    idx = history.find_last_user_message_index(count=rounds)
    if idx is None:
        idx = 0

    tail = list(history.iter_messages())
    tail = tail[idx:] if idx < len(tail) else []

    result = []
    for msg in tail:
        if isinstance(msg, CharacterSystemMessage):
            continue
        if isinstance(msg, ToolResultMessage):
            if not include_tool_messages:
                continue
            result.append(msg)
            continue
        if isinstance(msg, CharacterConversationMessage):
            if msg.role not in (Role.USER, Role.ASSISTANT):
                continue
            result.append(msg)
    return result


def _role_display(msg) -> str | None:
    """返回消息角色的显示名称。跳过 system 角色。"""
    from entity.messages import CharacterSystemMessage
    if isinstance(msg, CharacterSystemMessage):
        return None
    try:
        return str(msg.role.value).upper()
    except Exception:
        return "?"


def _content_to_text(content: str | list | None) -> str:
    """把 content（str / list[MessageBlock] / None）转为纯文本。

    核心目标：剥离 base64，保留可读媒体引用。
    """
    from entity.messages import (
        TextBlock,
        ImageBlock,
        VideoBlock,
        AudioBlock,
    )

    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, TextBlock):
                parts.append(block.text)
            elif isinstance(block, ImageBlock):
                parts.append(_safe_media_ref("image", block.image_url))
            elif isinstance(block, VideoBlock):
                parts.append(_safe_media_ref("video", block.video_url))
            elif isinstance(block, AudioBlock):
                parts.append(_safe_media_ref("audio", block.audio_url))
            else:
                parts.append(str(block))
        return "\n".join(parts)
    return str(content)


def _safe_media_ref(kind: str, url: str) -> str:
    """生成安全的媒体引用，剥离 base64 数据。"""
    if not url:
        return f"[{kind}: (empty)]"
    if url.startswith("data:"):
        if len(url) > 100:
            prefix = url[:80].rstrip(",").rstrip(";")
            return f"[{kind}: {prefix};... (base64 stripped)]"
        return f"[{kind}: data:... (base64 stripped)]"
    short = url[:80]
    if len(url) > 80:
        short += "..."
    return f"[{kind}: {short}]"


async def summarize_history(
    history: History,
    llm: BaseLLMClient,
    character: str = META_EXTRACTOR_CHARACTER,
) -> str:
    """用 LLM 对 History 实例做压缩生成摘要。

    组合 history_to_summary_text() 与 compress / compress_input 模板。
    *character* 声明元数据提取器身份，与 agent 角色隔离。
    """
    text: str = history_to_summary_text(history)
    system_prompt: str = read_template("compress.txt")
    user_prompt: str = read_template("compress_input.txt").replace("{{old_text}}", text)

    try:
        resp = await llm.chat([
            BaseMessage(role=Role.SYSTEM, content=system_prompt),
            BaseMessage(role=Role.USER, content=user_prompt),
        ], character=character)
        result = resp.content or ""
        result = result.strip()
        # 兼容旧版模板输出的 "Summary:" 前缀
        prefix = "Summary:"
        if result.lower().startswith(prefix.lower()):
            result = result[len(prefix):].strip()
        return result
    except Exception as exc:
        logger.exception("Failed to generate session summary: %s", exc)
        return ""