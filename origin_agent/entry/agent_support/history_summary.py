"""会话历史摘要工具 — 供 session_manager.py / parent_agent_loop.py 复用。

提供：
- History 实例到纯文本的安全转换（处理多模态 block，剥离 base64）
- LLM 摘要生成（使用 compress.txt / compress_input.txt 模板）
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from system.templates import read_template
from entity.constant import SUMMARY_INPUT_MAX_CHARS

if TYPE_CHECKING:
    from component.llm import LLMClient
    from entity.messages import BaseMessage, History, MessageBlock

logger = logging.getLogger(__name__)


def history_to_summary_text(history: History) -> str:
    """把 History 实例转换为适合 LLM 阅读的纯文本。

    直接遍历 ``history.messages`` 中类型化的消息对象，而非裸 dict，
    因此更稳定且无需处理任意 JSON 结构。

    处理规则：
    - TextBlock → 提取文本。
    - ImageBlock / VideoBlock / AudioBlock → 输出 ``[image: ...]`` 等，剥离 base64。
    - 工具调用链（tool_calls / tool_result）已忽略，只保留消息自身的文本内容。
    """
    from entity.messages import BaseMessage

    lines: list[str] = []

    for msg in history.messages:
        role_str = _role_display(msg)
        if role_str is None:
            continue

        content_text = _content_to_text(msg.content)

        if content_text:
            lines.append(f"## {role_str}")
            if content_text.strip():
                lines.append(content_text)

        lines.append("")

    result = "\n".join(lines)
    if len(result) > SUMMARY_INPUT_MAX_CHARS:
        result = result[:SUMMARY_INPUT_MAX_CHARS] + "\n\n... [truncated]"
    return result


def _role_display(msg: BaseMessage) -> str | None:
    """返回消息角色的显示名称。跳过 system 角色。"""
    from entity.messages import CharacterSystemMessage
    if isinstance(msg, CharacterSystemMessage):
        return None
    try:
        return str(msg.role.value).upper()
    except Exception:
        return "?"


def _content_to_text(content: str | list[MessageBlock] | None) -> str:
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


async def summarize_history(history: History, llm: LLMClient) -> str:
    """用 LLM 对 History 实例做压缩生成摘要。

    组合 history_to_summary_text() 与 compress / compress_input 模板。
    """
    text: str = history_to_summary_text(history)
    system_prompt: str = read_template("compress.txt")
    user_prompt: str = read_template("compress_input.txt").replace("{{old_text}}", text)

    try:
        resp = await llm.chat([
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ])
        result = resp.content or ""
        result = result.strip()
        prefix = "Summary:"
        if result.lower().startswith(prefix.lower()):
            result = result[len(prefix):].strip()
        return result
    except Exception as exc:
        logger.exception("Failed to generate session summary: %s", exc)
        return ""