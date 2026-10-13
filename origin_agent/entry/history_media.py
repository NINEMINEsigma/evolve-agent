"""History 媒体实例的纯定位、身份归一化、候选提交与轻量投影。"""

from __future__ import annotations

import base64
import binascii
import re
import uuid
from collections.abc import Iterator
from urllib.parse import urlsplit

from pydantic import BaseModel

from entity.constant import (
    AUDIO_FORMAT_MIME_SUBTYPE,
    SESSION_MEDIA_ID_PATTERN,
    SESSION_MEDIA_LABEL_MAX_CHARS,
    SESSION_MEDIA_PREVIEW_MIME_TYPES,
)
from entity.messages import (
    AudioBlock, BaseMessage, CharacterMessage, History, ImageBlock,
    MediaBlock, MessageBlock, ToolResultMessage, VideoBlock,
)
from entity.puretype import ModalityType, SessionMediaItem, SessionMediaListResponse


class HistoryMediaNotFoundError(LookupError):
    """媒体实例已不存在，不能按原历史位置猜测另一个实例。"""


class HistoryMediaConflictError(ValueError):
    """客户端所见开关与服务端当前值发生并发冲突。"""


class HistoryMediaPreviewError(ValueError):
    def __init__(self, message: str, status_code: int) -> None:
        if status_code not in (400, 415):
            raise ValueError("Invalid media preview error status")
        super().__init__(message)
        self.status_code = status_code


class HistoryMediaOccurrence(BaseModel):
    history_index: int
    block_index: int
    message: BaseMessage
    block: MediaBlock

    @property
    def media_type(self) -> ModalityType:
        if isinstance(self.block, ImageBlock):
            return "image"
        if isinstance(self.block, AudioBlock):
            return "audio"
        if isinstance(self.block, VideoBlock):
            return "video"
        raise TypeError("Unknown History media block")


def iter_history_media(history: History) -> Iterator[HistoryMediaOccurrence]:
    for history_index, message in enumerate(history.iter_messages()):
        if not isinstance(message.content, list):
            continue
        for block_index, block in enumerate(message.content):
            if isinstance(block, (ImageBlock, AudioBlock, VideoBlock)):
                yield HistoryMediaOccurrence(
                    history_index=history_index, block_index=block_index,
                    message=message, block=block,
                )


def ensure_history_media_identity(history: History) -> bool:
    """先验证现有身份，再补齐空身份；旧共享引用定向拆为独立实例。"""
    occurrences = list(iter_history_media(history))
    registered: set[str] = set()
    unregistered_objects: set[int] = set()
    for occurrence in occurrences:
        block = occurrence.block
        if type(block.send_multimodal) is not bool or type(block.forward_result_verified) is not bool:
            raise TypeError("Invalid History media control fields")
        if not isinstance(block.media_id, str):
            raise TypeError("Invalid History media identity type")
        if not block.media_id:
            unregistered_objects.add(id(block))
            continue
        if re.fullmatch(SESSION_MEDIA_ID_PATTERN, block.media_id) is None:
            raise ValueError("Invalid persisted History media identity")
        if block.media_id in registered:
            raise ValueError("Duplicate persisted History media identity")
        registered.add(block.media_id)

    changed = False
    seen_objects: set[int] = set()
    for history_index, message in enumerate(history.iter_messages()):
        if not isinstance(message.content, list):
            continue
        content = list(message.content)
        replaced = False
        for index, block in enumerate(content):
            if not isinstance(block, (ImageBlock, AudioBlock, VideoBlock)):
                continue
            identity = id(block)
            if identity not in unregistered_objects:
                continue
            if identity in seen_objects:
                block = block.model_copy()
                content[index] = block
                replaced = True
            seen_objects.add(identity)
            block.media_id = uuid.uuid4().hex
            changed = True
        if replaced:
            history.set_message(history_index, message.model_copy(update={"content": content}))
    return changed


def find_history_media(history: History, media_id: str) -> HistoryMediaOccurrence:
    found: HistoryMediaOccurrence | None = None
    for occurrence in iter_history_media(history):
        if occurrence.block.media_id == media_id:
            if found is not None:
                raise ValueError("Duplicate persisted History media identity")
            found = occurrence
    if found is None:
        raise HistoryMediaNotFoundError("History media instance not found")
    return found


def _safe_source_path(source: str | None) -> str | None:
    if not source or re.match(r"^[A-Za-z][A-Za-z0-9_-]*:", source) is None:
        return None
    if re.match(r"^[A-Za-z]:[\\/]", source) or source.lower().startswith(("http:", "https:", "data:")):
        return None
    return source[:SESSION_MEDIA_LABEL_MAX_CHARS]


def _url_metadata(url: str) -> tuple[str | None, int | None, bool]:
    if not url.startswith("data:"):
        parsed = urlsplit(url)
        return None, None, parsed.scheme in ("http", "https") and bool(parsed.netloc)
    comma = url.find(",")
    if comma < 0 or comma > SESSION_MEDIA_LABEL_MAX_CHARS:
        return None, None, False
    header = url[5:comma]
    mime_type = header.split(";", 1)[0].lower()
    encoded = header.endswith(";base64")
    return (
        mime_type or None,
        len(url) - comma - 1 if encoded else None,
        encoded and mime_type in SESSION_MEDIA_PREVIEW_MIME_TYPES,
    )


def project_media_item(occurrence: HistoryMediaOccurrence) -> SessionMediaItem:
    block = occurrence.block
    if isinstance(block, AudioBlock):
        mime_type = f"audio/{AUDIO_FORMAT_MIME_SUBTYPE.get(block.format, block.format)}"
        payload_chars: int | None = len(block.data)
        preview = mime_type in SESSION_MEDIA_PREVIEW_MIME_TYPES
    elif isinstance(block, ImageBlock):
        mime_type, payload_chars, preview = _url_metadata(block.image_url)
    elif isinstance(block, VideoBlock):
        mime_type, payload_chars, preview = _url_metadata(block.video_url)
    else:
        raise TypeError("Unknown History media block")
    message = occurrence.message
    return SessionMediaItem(
        media_id=block.media_id,
        history_index=occurrence.history_index,
        block_index=occurrence.block_index,
        media_type=occurrence.media_type,
        role=message.role,
        character_name=message.character_name if isinstance(message, CharacterMessage) else None,
        source_path=_safe_source_path(block.source_path),
        tool_call_id=message.tool_call_id if isinstance(message, ToolResultMessage) else block.source_tool_call_id,
        send_multimodal=block.send_multimodal,
        has_forward_description=bool(block.forward_result_verified and block.forward_result_content and block.forward_result_content.strip()),
        mime_type=mime_type,
        inline_payload_chars=payload_chars,
        preview_available=preview,
    )


def project_history_media(
    history: History, session_id: str, *, offset: int, limit: int, editable: bool,
) -> SessionMediaListResponse:
    if offset < 0 or limit < 1:
        raise ValueError("Invalid History media page")
    items: list[SessionMediaItem] = []
    total = 0
    for occurrence in iter_history_media(history):
        if offset <= total < offset + limit:
            items.append(project_media_item(occurrence))
        total += 1
    return SessionMediaListResponse(
        session_id=session_id, history_count=history.count, total_count=total,
        offset=offset, limit=limit, editable=editable, items=items,
    )


def build_media_history_candidate(
    history: History, occurrence: HistoryMediaOccurrence, replacement: MediaBlock,
) -> History:
    content = occurrence.message.content
    if not isinstance(content, list):
        raise TypeError("History media message must have block content")
    blocks = list(content)
    blocks[occurrence.block_index] = replacement
    message = occurrence.message.model_copy(update={"content": blocks})
    messages = list(history.iter_messages())
    messages[occurrence.history_index] = message
    last_user = message if history.last_user_message is occurrence.message else history.last_user_message
    return history.model_copy(update={"messages": messages, "last_user_message": last_user})


def reuse_unchanged_media_blocks(
    existing: list[MessageBlock], replacement: list[MessageBlock],
) -> list[MessageBlock]:
    result = list(replacement)
    for index, new in enumerate(result):
        if index >= len(existing):
            break
        old = existing[index]
        same = False
        if isinstance(old, ImageBlock) and isinstance(new, ImageBlock):
            same = old.image_url == new.image_url
        elif isinstance(old, VideoBlock) and isinstance(new, VideoBlock):
            same = old.video_url == new.video_url
        elif isinstance(old, AudioBlock) and isinstance(new, AudioBlock):
            same = old.data == new.data and old.format == new.format
        if same:
            result[index] = old
    return result


def decode_media_preview(block: MediaBlock) -> tuple[bytes, str]:
    if isinstance(block, AudioBlock):
        mime_type = f"audio/{AUDIO_FORMAT_MIME_SUBTYPE.get(block.format, block.format)}"
        data = block.data
    else:
        if isinstance(block, ImageBlock):
            url = block.image_url
        elif isinstance(block, VideoBlock):
            url = block.video_url
        else:
            raise TypeError("Unknown History media block")
        mime_type, _, available = _url_metadata(url)
        if not url.startswith("data:") or not available or mime_type is None:
            raise HistoryMediaPreviewError("Media preview format is not supported", 415)
        data = url[url.find(",") + 1:]
    if mime_type not in SESSION_MEDIA_PREVIEW_MIME_TYPES:
        raise HistoryMediaPreviewError("Media preview format is not supported", 415)
    try:
        return base64.b64decode(data, validate=True), mime_type
    except (binascii.Error, ValueError) as exc:
        raise HistoryMediaPreviewError("Invalid encoded media content", 400) from exc
