"""将 History 投影为前端全历史骨架、历史内容页与资源索引。"""

from __future__ import annotations

import json
import re
from typing import Any

from entity.messages import (
    AudioBlock,
    BaseMessage,
    CharacterConversationMessage,
    CharacterMessage,
    ImageBlock,
    MessageBlock,
    SystemStatusMessage,
    ToolResultMessage,
    VideoBlock,
)
from entity.puretype import (
    MessageMetrics,
    Role,
    SessionHistoryContentRow,
    SessionHistoryDownloadResource,
    SessionHistoryImageResource,
    SessionHistoryResourcesResponse,
    SessionHistoryRowKind,
    SessionHistorySkeletonRow,
)
from entry.agent_support.multimodal import (
    content_to_serializable,
    content_to_text,
    extract_tool_call_meta,
)

_MARKDOWN_IMAGE_RE = re.compile(r"!\[(.*?)\]\(([^)]+)\)")


def history_row_id(
    history_index: int,
    row_kind: SessionHistoryRowKind,
    tool_index: int | None = None,
) -> str:
    """返回一个骨架代际内稳定的前端投影行 ID。"""
    if row_kind == SessionHistoryRowKind.tool_call:
        if tool_index is None or tool_index < 0:
            raise ValueError("tool_index is required for tool_call rows")
        return f"history:{history_index}:tool:{tool_index}"
    return f"history:{history_index}:message"


def _character_name(message: BaseMessage, fallback_character: str) -> str:
    if isinstance(message, CharacterMessage):
        return message.character_name
    return fallback_character


def _skeleton_for_message(
    message: BaseMessage,
    history_index: int,
    fallback_character: str,
) -> list[SessionHistorySkeletonRow]:
    character_name = _character_name(message, fallback_character)
    rows = [
        SessionHistorySkeletonRow(
            row_id=history_row_id(history_index, SessionHistoryRowKind.message),
            history_index=history_index,
            row_kind=SessionHistoryRowKind.message,
            role=message.role.value,
            character_name=character_name,
            is_system_status=isinstance(message, SystemStatusMessage),
        )
    ]
    if isinstance(message, CharacterConversationMessage) and message.tool_calls:
        rows.extend(
            SessionHistorySkeletonRow(
                row_id=history_row_id(
                    history_index, SessionHistoryRowKind.tool_call, tool_index,
                ),
                history_index=history_index,
                row_kind=SessionHistoryRowKind.tool_call,
                role=Role.TOOL.value,
                character_name=character_name,
                tool_index=tool_index,
            )
            for tool_index, _tool_call in enumerate(message.tool_calls)
        )
    return rows


def project_history_skeleton(
    messages: list[BaseMessage],
    fallback_character: str,
    *,
    start_index: int = 0,
) -> list[SessionHistorySkeletonRow]:
    """投影 ``messages``，其首条消息的 History 索引为 ``start_index``。"""
    rows: list[SessionHistorySkeletonRow] = []
    for offset, message in enumerate(messages):
        rows.extend(
            _skeleton_for_message(message, start_index + offset, fallback_character)
        )
    return rows


def _tool_args(arguments: str) -> tuple[dict[str, Any], str | None]:
    try:
        parsed = json.loads(arguments)
    except (json.JSONDecodeError, TypeError):
        return {}, arguments
    return (parsed if isinstance(parsed, dict) else {}), (
        None if isinstance(parsed, dict) else arguments
    )


def project_history_content_rows(
    message: BaseMessage,
    history_index: int,
    fallback_character: str,
    metrics: MessageMetrics | None = None,
) -> list[SessionHistoryContentRow]:
    """把一条 History 消息投影为一个正文行及其工具调用子行。"""
    character_name = _character_name(message, fallback_character)
    serialized = content_to_serializable(message.content)
    content: str | list[dict[str, Any]]
    if isinstance(serialized, dict):
        content = content_to_text(serialized)
    else:
        content = serialized

    visible_characters: list[str] | None = None
    response_characters: list[str] | None = None
    message_suffix: str | None = None
    dynamic_message_suffix: str | None = None
    reasoning_content: str | None = None
    if isinstance(message, CharacterConversationMessage):
        visible_characters = message.visible_characters or None
        response_characters = message.response_characters or None
        message_suffix = message.message_suffix or None
        dynamic_message_suffix = message.dynamic_message_suffix or None
        reasoning_content = message.reasoning or None

    rows = [
        SessionHistoryContentRow(
            row_id=history_row_id(history_index, SessionHistoryRowKind.message),
            history_index=history_index,
            row_kind=SessionHistoryRowKind.message,
            role=message.role.value,
            character_name=character_name,
            is_system_status=isinstance(message, SystemStatusMessage),
            content=content,
            visible_characters=visible_characters,
            response_characters=response_characters,
            message_suffix=message_suffix,
            dynamic_message_suffix=dynamic_message_suffix,
            reasoning_content=reasoning_content,
            requires_response=True if message.role == Role.USER else None,
            tool_call_meta=(
                extract_tool_call_meta(message.content)
                if isinstance(message, ToolResultMessage)
                else None
            ),
            metrics=metrics,
        )
    ]

    if isinstance(message, CharacterConversationMessage) and message.tool_calls:
        for tool_index, tool_call in enumerate(message.tool_calls):
            tool_args, tool_args_raw = _tool_args(tool_call.function.arguments)
            tool_content = f"{character_name} ⚡ {tool_call.function.name}"
            if tool_args_raw:
                tool_content = f"{tool_content} ({tool_args_raw})"
            rows.append(
                SessionHistoryContentRow(
                    row_id=history_row_id(
                        history_index, SessionHistoryRowKind.tool_call, tool_index,
                    ),
                    history_index=history_index,
                    row_kind=SessionHistoryRowKind.tool_call,
                    role=Role.TOOL.value,
                    character_name=character_name,
                    tool_index=tool_index,
                    content=tool_content,
                    tool_name=tool_call.function.name,
                    tool_args=tool_args,
                    tool_args_raw=tool_args_raw,
                )
            )
    return rows


def _append_image(
    images: list[SessionHistoryImageResource],
    seen: set[str],
    url: str,
    alt: str,
    history_index: int,
) -> None:
    if not url or url in seen:
        return
    seen.add(url)
    images.append(
        SessionHistoryImageResource(
            resource_id=f"history:{history_index}:image:{len(images)}",
            url=url,
            alt=alt,
        )
    )


def _scan_markdown_images(
    text: str,
    images: list[SessionHistoryImageResource],
    seen: set[str],
    history_index: int,
) -> None:
    for alt, url in _MARKDOWN_IMAGE_RE.findall(text):
        _append_image(images, seen, url, alt, history_index)


def project_history_resources(
    messages: list[BaseMessage],
    session_id: str,
) -> SessionHistoryResourcesResponse:
    """提取完整 History 中的图片与下载资源，不依赖前端已加载页。"""
    images: list[SessionHistoryImageResource] = []
    downloads: list[SessionHistoryDownloadResource] = []
    image_seen: set[str] = set()
    download_seen: set[str] = set()

    for history_index, message in enumerate(messages):
        content = message.content
        if isinstance(content, str):
            _scan_markdown_images(content, images, image_seen, history_index)
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, ImageBlock):
                    _append_image(
                        images, image_seen, block.image_url, "", history_index,
                    )
                elif isinstance(block, MessageBlock):
                    if hasattr(block, "text"):
                        _scan_markdown_images(
                            str(getattr(block, "text")), images, image_seen,
                            history_index,
                        )
                elif isinstance(block, dict):
                    if block.get("type") == "image_url":
                        image_url = block.get("image_url")
                        url = (
                            str(image_url.get("url", ""))
                            if isinstance(image_url, dict)
                            else str(image_url or "")
                        )
                        _append_image(images, image_seen, url, "", history_index)
                    elif block.get("type") == "text":
                        _scan_markdown_images(
                            str(block.get("text", "")), images, image_seen,
                            history_index,
                        )
                elif isinstance(block, (AudioBlock, VideoBlock)):
                    continue
        elif isinstance(content, dict):
            markdown = content.get("markdown")
            if isinstance(markdown, str):
                _scan_markdown_images(
                    markdown, images, image_seen, history_index,
                )
            download_url = content.get("download_url")
            if isinstance(download_url, str) and download_url not in download_seen:
                download_seen.add(download_url)
                size = content.get("size")
                downloads.append(
                    SessionHistoryDownloadResource(
                        resource_id=f"history:{history_index}:download:{len(downloads)}",
                        url=download_url,
                        filename=str(content.get("filename") or "download"),
                        size=size if isinstance(size, int) else None,
                    )
                )

    return SessionHistoryResourcesResponse(
        session_id=session_id,
        history_count=len(messages),
        images=images,
        downloads=downloads,
    )
