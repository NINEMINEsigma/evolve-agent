"""将 History 投影为前端全历史骨架、历史内容页与资源索引。"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
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
    SessionHistoryToolCard,
    SessionHistoryToolCardStatus,
)
from entry.agent_support.multimodal import (
    content_to_serializable,
    content_to_text,
    extract_tool_call_meta,
)

logger = logging.getLogger(__name__)
_MARKDOWN_IMAGE_RE = re.compile(r"!\[(.*?)\]\(([^)]+)\)")


@dataclass(frozen=True)
class _ToolCallOccurrence:
    history_index: int
    tool_index: int
    tool_call: Any


@dataclass(frozen=True)
class _ToolResultOccurrence:
    history_index: int
    message: ToolResultMessage


@dataclass(frozen=True)
class _ToolPair:
    request: _ToolCallOccurrence
    result: _ToolResultOccurrence | None


def history_row_id(
    history_index: int,
    row_kind: SessionHistoryRowKind,
    tool_index: int | None = None,
) -> str:
    """返回一个骨架代际内稳定的前端投影行 ID。"""
    if row_kind == SessionHistoryRowKind.tool_card:
        if tool_index is None or tool_index < 0:
            raise ValueError("tool_index is required for tool_card rows")
        return f"history:{history_index}:tool:{tool_index}"
    return f"history:{history_index}:message"


def _character_name(message: BaseMessage, fallback_character: str) -> str:
    if isinstance(message, CharacterMessage):
        return message.character_name
    return fallback_character


def has_visible_history_message_row(message: BaseMessage) -> bool:
    """判断带工具调用的 assistant 是否还应显示普通消息行。"""
    if not isinstance(message, CharacterConversationMessage) or not message.tool_calls:
        return True
    return bool(content_to_text(message.content).strip() or (message.reasoning or "").strip())


def _tool_args(arguments: str) -> tuple[dict[str, Any], str | None]:
    try:
        parsed = json.loads(arguments)
    except (json.JSONDecodeError, TypeError):
        return {}, arguments
    return (parsed if isinstance(parsed, dict) else {}), (
        None if isinstance(parsed, dict) else arguments
    )


def _build_tool_index(messages: list[BaseMessage]) -> tuple[dict[str, list[_ToolCallOccurrence]], dict[str, list[_ToolResultOccurrence]]]:
    requests: dict[str, list[_ToolCallOccurrence]] = {}
    results: dict[str, list[_ToolResultOccurrence]] = {}
    for history_index, message in enumerate(messages):
        if isinstance(message, CharacterConversationMessage) and message.tool_calls:
            for tool_index, tool_call in enumerate(message.tool_calls):
                requests.setdefault(tool_call.id, []).append(
                    _ToolCallOccurrence(history_index, tool_index, tool_call),
                )
        if isinstance(message, ToolResultMessage):
            results.setdefault(message.tool_call_id, []).append(
                _ToolResultOccurrence(history_index, message),
            )
    return requests, results


def _build_tool_pairs(messages: list[BaseMessage]) -> tuple[dict[str, _ToolPair], set[int]]:
    requests, results = _build_tool_index(messages)
    pairs: dict[str, _ToolPair] = {}
    consumed_results: set[int] = set()
    for tool_call_id, occurrences in requests.items():
        matching_results = results.get(tool_call_id, [])
        if len(occurrences) != 1 or len(matching_results) > 1:
            logger.warning(
                "Ambiguous tool call history projection | tool_call_id=%s requests=%d results=%d",
                tool_call_id, len(occurrences), len(matching_results),
            )
            if len(occurrences) == 1:
                pairs[tool_call_id] = _ToolPair(occurrences[0], None)
            continue
        request = occurrences[0]
        result = matching_results[0] if matching_results[0].history_index > request.history_index else None
        if result is None and matching_results:
            logger.warning(
                "Invalid tool result order in history projection | tool_call_id=%s",
                tool_call_id,
            )
        pairs[tool_call_id] = _ToolPair(request, result)
        if result is not None:
            consumed_results.add(result.history_index)
    return pairs, consumed_results


def _skeleton_for_message(
    message: BaseMessage,
    history_index: int,
    fallback_character: str,
    pairs: dict[str, _ToolPair],
) -> list[SessionHistorySkeletonRow]:
    character_name = _character_name(message, fallback_character)
    rows: list[SessionHistorySkeletonRow] = []
    if has_visible_history_message_row(message):
        rows.append(SessionHistorySkeletonRow(
            row_id=history_row_id(history_index, SessionHistoryRowKind.message),
            history_index=history_index,
            row_kind=SessionHistoryRowKind.message,
            role=message.role.value,
            character_name=character_name,
            is_system_status=isinstance(message, SystemStatusMessage),
        ))
    if isinstance(message, CharacterConversationMessage) and message.tool_calls:
        for tool_index, tool_call in enumerate(message.tool_calls):
            pair = pairs.get(tool_call.id)
            if pair is None:
                continue
            rows.append(SessionHistorySkeletonRow(
                row_id=history_row_id(history_index, SessionHistoryRowKind.tool_card, tool_index),
                history_index=history_index,
                row_kind=SessionHistoryRowKind.tool_card,
                role=Role.TOOL.value,
                character_name=character_name,
                tool_index=tool_index,
                tool_call_id=tool_call.id,
            ))
    return rows


def project_history_skeleton(
    messages: list[BaseMessage],
    fallback_character: str,
    *,
    start_index: int = 0,
) -> list[SessionHistorySkeletonRow]:
    """投影完整 History，并返回锚定索引不小于 start_index 的视觉行。"""
    pairs, consumed_results = _build_tool_pairs(messages)
    rows: list[SessionHistorySkeletonRow] = []
    for history_index, message in enumerate(messages):
        if history_index < start_index:
            continue
        if isinstance(message, ToolResultMessage):
            if history_index not in consumed_results:
                rows.append(SessionHistorySkeletonRow(
                    row_id=history_row_id(history_index, SessionHistoryRowKind.message),
                    history_index=history_index,
                    row_kind=SessionHistoryRowKind.message,
                    role=message.role.value,
                    character_name=_character_name(message, fallback_character),
                ))
            continue
        rows.extend(_skeleton_for_message(message, history_index, fallback_character, pairs))
    return rows


def _serialized_content(content: Any) -> str | list[dict[str, Any]]:
    serialized = content_to_serializable(content)
    if isinstance(serialized, dict):
        return content_to_text(serialized)
    return serialized


def _message_content_row(
    message: BaseMessage,
    history_index: int,
    fallback_character: str,
    metrics: MessageMetrics | None,
) -> SessionHistoryContentRow:
    character_name = _character_name(message, fallback_character)
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
    return SessionHistoryContentRow(
        row_id=history_row_id(history_index, SessionHistoryRowKind.message),
        history_index=history_index,
        row_kind=SessionHistoryRowKind.message,
        role=message.role.value,
        character_name=character_name,
        is_system_status=isinstance(message, SystemStatusMessage),
        content=_serialized_content(message.content),
        visible_characters=visible_characters,
        response_characters=response_characters,
        message_suffix=message_suffix,
        dynamic_message_suffix=dynamic_message_suffix,
        reasoning_content=reasoning_content,
        requires_response=True if message.role == Role.USER else None,
        tool_call_meta=extract_tool_call_meta(message.content) if isinstance(message, ToolResultMessage) else None,
        metrics=metrics,
    )


def _tool_card_content_row(
    pair: _ToolPair,
    fallback_character: str,
    metrics: MessageMetrics | None,
    character_name: str | None = None,
) -> SessionHistoryContentRow:
    request = pair.request
    tool_args, tool_args_raw = _tool_args(request.tool_call.function.arguments)
    character_name = character_name or fallback_character
    # The request occurrence is always from a CharacterConversationMessage; its character is
    # recovered by the caller when constructing the row and replaced there when needed.
    tool_name = request.tool_call.function.name
    result = pair.result
    status = SessionHistoryToolCardStatus.missing_result
    result_content: str | list[dict[str, Any]] | None = None
    result_history_index: int | None = None
    tool_call_meta: dict[str, Any] | None = None
    is_error = False
    if result is not None:
        result_content = _serialized_content(result.message.content)
        result_history_index = result.history_index
        tool_call_meta = extract_tool_call_meta(result.message.content)
        raw = result.message.content
        is_error = isinstance(raw, dict) and bool(raw.get("error"))
        status = SessionHistoryToolCardStatus.failed if is_error else SessionHistoryToolCardStatus.succeeded
    card = SessionHistoryToolCard(
        tool_call_id=request.tool_call.id,
        tool_name=tool_name,
        request_args=tool_args,
        request_args_raw=tool_args_raw,
        status=status,
        result_content=result_content,
        result_history_index=result_history_index,
        tool_call_meta=tool_call_meta,
        is_error=is_error,
    )
    text = f"{character_name} ⚡ {tool_name}"
    return SessionHistoryContentRow(
        row_id=history_row_id(request.history_index, SessionHistoryRowKind.tool_card, request.tool_index),
        history_index=request.history_index,
        row_kind=SessionHistoryRowKind.tool_card,
        role=Role.TOOL.value,
        character_name=character_name,
        tool_index=request.tool_index,
        tool_call_id=request.tool_call.id,
        content=text,
        tool_card=card,
        metrics=metrics,
    )


def project_history_content_rows(
    messages: list[BaseMessage],
    start_index: int,
    end_index: int,
    fallback_character: str,
    metrics_map: dict[int, MessageMetrics] | None = None,
) -> list[SessionHistoryContentRow]:
    """按完整 History 建立配对，并投影命中请求或结果范围的视觉行。"""
    pairs, consumed_results = _build_tool_pairs(messages)
    rows: list[SessionHistoryContentRow] = []
    metrics_map = metrics_map or {}
    for history_index, message in enumerate(messages):
        in_range = start_index <= history_index < end_index
        if isinstance(message, CharacterConversationMessage) and message.tool_calls:
            if in_range and has_visible_history_message_row(message):
                rows.append(_message_content_row(message, history_index, fallback_character, metrics_map.get(history_index)))
            for tool_call in message.tool_calls:
                pair = pairs.get(tool_call.id)
                if pair is None:
                    continue
                result_index = pair.result.history_index if pair.result is not None else None
                if not in_range and (result_index is None or not (start_index <= result_index < end_index)):
                    continue
                card_row = _tool_card_content_row(
                    pair,
                    fallback_character,
                    metrics_map.get(history_index),
                    _character_name(message, fallback_character),
                )
                rows.append(card_row)
            continue
        if isinstance(message, ToolResultMessage):
            if history_index in consumed_results or not in_range:
                continue
            rows.append(_message_content_row(message, history_index, fallback_character, metrics_map.get(history_index)))
            continue
        if in_range:
            rows.append(_message_content_row(message, history_index, fallback_character, metrics_map.get(history_index)))
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
    images.append(SessionHistoryImageResource(
        resource_id=f"history:{history_index}:image:{len(images)}", url=url, alt=alt,
    ))


def _scan_markdown_images(text: str, images: list[SessionHistoryImageResource], seen: set[str], history_index: int) -> None:
    for alt, url in _MARKDOWN_IMAGE_RE.findall(text):
        _append_image(images, seen, url, alt, history_index)


def project_history_resources(messages: list[BaseMessage], session_id: str) -> SessionHistoryResourcesResponse:
    """提取完整 History 中的图片与下载资源索引，不依赖前端已加载页。"""
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
                    _append_image(images, image_seen, block.image_url, "", history_index)
                elif isinstance(block, MessageBlock) and hasattr(block, "text"):
                    _scan_markdown_images(str(getattr(block, "text")), images, image_seen, history_index)
                elif isinstance(block, dict):
                    if block.get("type") == "image_url":
                        image_url = block.get("image_url")
                        url = str(image_url.get("url", "")) if isinstance(image_url, dict) else str(image_url or "")
                        _append_image(images, image_seen, url, "", history_index)
                    elif block.get("type") == "text":
                        _scan_markdown_images(str(block.get("text", "")), images, image_seen, history_index)
                elif isinstance(block, (AudioBlock, VideoBlock)):
                    continue
        elif isinstance(content, dict):
            markdown = content.get("markdown")
            if isinstance(markdown, str):
                _scan_markdown_images(markdown, images, image_seen, history_index)
            download_url = content.get("download_url")
            if isinstance(download_url, str) and download_url not in download_seen:
                download_seen.add(download_url)
                size = content.get("size")
                downloads.append(SessionHistoryDownloadResource(
                    resource_id=f"history:{history_index}:download:{len(downloads)}",
                    url=download_url,
                    filename=str(content.get("filename") or "download"),
                    size=size if isinstance(size, int) else None,
                ))
    return SessionHistoryResourcesResponse(
        session_id=session_id, history_count=len(messages), images=images, downloads=downloads,
    )
