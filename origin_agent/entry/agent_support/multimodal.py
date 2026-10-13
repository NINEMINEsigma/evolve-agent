"""多模态消息工具 — 供 AgentLoop 使用。

包含 content block 拒绝检测、图片/音频剥离、vision/audio 缓存查询、
_image/_audio payload 构造，以及 tool result 到 content 的统一转换。
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections import defaultdict, deque
from pydantic import BaseModel
from typing import * # type: ignore

from entity.messages import AudioBlock, BaseMessage, CharacterConversationMessage, History, ImageBlock, MessageBlock, TextBlock, VideoBlock
from entity.puretype import MessageContent, Role, ModalityCapability, ModalityDescriptionResult
from entity.constant import (
    FORWARDED_AUDIO_TAG,
    FORWARDED_VISION_TAG,
    FORWARDED_VIDEO_TAG,
    SYSTEM_CHARACTER_NAME,
    SESSION_MEDIA_PLACEHOLDER_TEMPLATE,
)
from entry.history_media import HistoryMediaOccurrence, project_media_item
from system.runtime import RuntimeSystem
from system.templates import read_template
from system.modality_capability import (
    ModalityCapabilitySystem,
    resolve_active_model_base_url,
    wrap_forwarded_description,
)

if TYPE_CHECKING:
    from entry.base_agent_loop import ToolContext

logger = logging.getLogger(__name__)


class ModalityForwardUnavailableError(ValueError):
    """活动模型不支持该模态且未配置任何引用 Profile，无法转发。

    携带面向用户的配置指引（配置对应媒体引用 Profile 或切换到支持
    该模态的模型）。调用方捕获后应终止本轮回复并将指引作为持久化
    系统状态展示给前端。
    """


def is_content_block_error(exc: Exception) -> bool:
    """检测异常是否由 unsupported content blocks（如图片/音频/视频）引起。"""
    return any(k in str(exc).lower() for k in [
        "image_url",
        "input_audio",
        "video_url",
        "content type",
        "content block",
        "unsupported",
        "invalid content",
        "multimodal",
        "vision",
        "audio",
        "video",
    ])


class PreparedMultimodalRequest(BaseModel):
    """每请求固定的消息视图；原 History 和媒体载荷保持不变。"""

    messages: list[BaseMessage]
    last_user_message: CharacterConversationMessage | None
    source_history: History
    source_session_id: str

    @classmethod
    def capture(
        cls, messages: list[BaseMessage], history: History, session_id: str,
        last_user_message: CharacterConversationMessage | None, character_name: str,
    ) -> PreparedMultimodalRequest:
        copied: list[BaseMessage] = []
        last_user: CharacterConversationMessage | None = None
        for message in messages:
            if not message.is_visible_to(character_name):
                continue
            content = message.content
            if isinstance(content, list):
                content = [block.model_copy() for block in content]
            elif isinstance(content, dict):
                content = content.copy()
            snapshot = message.model_copy(update={"content": content})
            copied.append(snapshot)
            if message is last_user_message:
                if not isinstance(snapshot, CharacterConversationMessage):
                    raise TypeError("Last user message must be a conversation message")
                last_user = snapshot
        return cls(
            messages=copied, last_user_message=last_user,
            source_history=history, source_session_id=session_id,
        )


async def prepare_main_multimodal_request(
    messages: list[BaseMessage], context: ToolContext, *,
    last_user_message: CharacterConversationMessage | None,
) -> PreparedMultimodalRequest:
    """首个 await 前固定开关；关闭的媒体绝不在主请求中恢复直传。"""
    runtime = context.app.get_system(RuntimeSystem)
    runtime.require_running()
    if context.loop.is_interrupted():
        raise asyncio.CancelledError
    original_last_user = context.loop.history.last_user_message
    uses_history_last_user = last_user_message is not None and last_user_message is original_last_user
    original_history = list(context.loop.history.iter_messages())
    context.loop.ensure_media_identity()
    if uses_history_last_user:
        last_user_message = context.loop.history.last_user_message
    # 旧共享媒体引用拆分时，同步重连源视图，后续工具回环仍持有正式 History 对象。
    canonical: dict[int, deque[BaseMessage]] = defaultdict(deque)
    for previous, current in zip(original_history, context.loop.history.iter_messages()):
        canonical[id(previous)].append(current)
    for index, message in enumerate(messages):
        replacements = canonical.get(id(message))
        if replacements:
            replacement = replacements.popleft()
            messages[index] = replacement
            if message is last_user_message:
                if not isinstance(replacement, CharacterConversationMessage):
                    raise TypeError("Last user message must be a conversation message")
                last_user_message = replacement
    request = PreparedMultimodalRequest.capture(
        messages, context.loop.history, context.session_id,
        last_user_message, context.character_name,
    )
    model_name, _, profile = resolve_active_model_base_url(context)
    system = context.app.get_system(ModalityCapabilitySystem)
    has_enabled_media = any(
        isinstance(block, (ImageBlock, AudioBlock, VideoBlock)) and block.send_multimodal
        for message in request.messages if isinstance(message.content, list)
        for block in message.content
    )
    capability: ModalityCapability | None = None
    if has_enabled_media and profile is not None and model_name:
        capability = await system.ensure_modality_capability(context)
    placeholder: str | None = None
    for message_index, message in enumerate(request.messages):
        if not isinstance(message.content, list):
            continue
        blocks: list[MessageBlock] = []
        for block_index, block in enumerate(message.content):
            if not isinstance(block, (ImageBlock, AudioBlock, VideoBlock)):
                blocks.append(block)
                continue
            runtime.require_running()
            if context.loop.is_interrupted():
                raise asyncio.CancelledError
            tool_path = message.role == Role.TOOL
            if isinstance(block, ImageBlock):
                media_type = "image"
                tag = FORWARDED_VISION_TAG
                supported = capability.vision if tool_path and capability is not None else capability.user_vision if capability is not None else False
            elif isinstance(block, AudioBlock):
                media_type = "audio"
                tag = FORWARDED_AUDIO_TAG
                supported = capability.audio if tool_path and capability is not None else capability.user_audio if capability is not None else False
            else:
                media_type = "video"
                tag = FORWARDED_VIDEO_TAG
                supported = capability.video if tool_path and capability is not None else capability.user_video if capability is not None else False
            if block.send_multimodal and (supported or profile is None or not model_name):
                blocks.append(block)
                continue
            if block.forward_result_verified and block.forward_result_content and block.forward_result_content.strip():
                blocks.append(TextBlock(text=wrap_forwarded_description(block.forward_result_content, tag)))
                continue
            result = (
                await system.describe_media_block(context, profile, block)
                if profile is not None else ModalityDescriptionResult(status="unavailable", reason="no_reference")
            )
            runtime.require_running()
            if context.loop.is_interrupted():
                raise asyncio.CancelledError
            if result.status == "success":
                if result.description is None or not result.description.strip() or result.reason is not None:
                    raise RuntimeError("Invalid successful media description result")
                context.loop.commit_media_description(
                    request.source_session_id, request.source_history, block.media_id, result.description,
                )
                blocks.append(TextBlock(text=wrap_forwarded_description(result.description, tag)))
                continue
            if result.status != "unavailable" or result.reason is None or result.description is not None:
                raise RuntimeError("Invalid unavailable media description result")
            if block.send_multimodal:
                raise ModalityForwardUnavailableError(
                    f"Active model does not support {media_type} on this message path and forwarding is unavailable "
                    f"({result.reason}). Configure a usable reference Profile or switch to a supporting model."
                )
            if placeholder is None:
                placeholder = read_template(SESSION_MEDIA_PLACEHOLDER_TEMPLATE)
            source = project_media_item(HistoryMediaOccurrence(
                history_index=message_index, block_index=block_index, message=message, block=block,
            )).source_path
            text = (
                placeholder.replace("{{media_type}}", media_type)
                .replace("{{media_id}}", block.media_id)
                .replace("{{source_path}}", source or "unknown")
                .replace("{{reason}}", result.reason)
            )
            blocks.append(TextBlock(text=text))
        message.content = blocks
    runtime.require_running()
    if context.loop.is_interrupted():
        raise asyncio.CancelledError
    return request


def _attach_tool_media_source(
    blocks: list[MessageBlock], result: dict[str, Any], tool_call_id: str | None,
) -> None:
    """从正式工具结果附带逻辑来源；不采信物理 absolute_path。"""
    source = result.get("path")
    kind = result.get("type")
    for block in blocks:
        if not isinstance(block, (ImageBlock, AudioBlock, VideoBlock)):
            continue
        block.source_tool_call_id = tool_call_id
        matches = (
            (kind == "image" and isinstance(block, ImageBlock))
            or (kind == "audio" and isinstance(block, AudioBlock))
            or (kind == "video" and isinstance(block, VideoBlock))
        )
        if matches and isinstance(source, str):
            block.source_path = source


def tool_result_to_content(
    result: dict[str, Any], *, tool_call_id: str | None = None,
) -> dict[str, Any] | list[MessageBlock]:
    """把原生 dict 工具结果转换为 ToolResultMessage 可用的 content。

    - 含 _blocks 字段的 dict：pop _blocks 后经 blocks_from_dicts 转为有序 MessageBlock 列表；
      剩余 dict 非空时追加为末尾 TextBlock(json.dumps(remaining))。
    - 其他 dict：返回原生 dict。
    - 非 dict 输入：抛出 TypeError，不解析或包装旧格式结果。
    """
    # _blocks 优先：有序混合块列表，复用 blocks_from_dicts 格式
    blocks_data = result.pop("_blocks", None)
    assert blocks_data is None or isinstance(blocks_data, list), "_blocks must be a list"
    if blocks_data:
        blocks = blocks_from_dicts(blocks_data)
        _attach_tool_media_source(blocks, result, tool_call_id)
        if result:
            blocks.append(TextBlock(text=json.dumps(result, ensure_ascii=False)))
        return blocks
    return result


def tool_result_to_follow_up(
    result: dict,
    character_name: str,
    *,
    tool_call_id: str | None = None,
) -> tuple[list[BaseMessage] | None, dict[str, Any] | list[MessageBlock]]:
    """提取 _user_blocks，构造 follow_up 用户消息。

    从 result dict 中 pop _user_blocks（有序混合块列表），
    构造 CharacterConversationMessage(role=USER, character_name=system, content=[多模态块, 文本块])。
    剩余 dict 走 tool_result_to_content 生成 ToolResultMessage content。

    Returns:
        (follow_up_messages, remaining_content)
        - follow_up_messages: 延迟注入的 CharacterConversationMessage 列表，或 None
        - remaining_content: ToolResultMessage 的 content
    """
    user_blocks_data = result.pop("_user_blocks", None)

    if not (isinstance(user_blocks_data, list) and user_blocks_data):
        return None, tool_result_to_content(result, tool_call_id=tool_call_id)

    blocks: list[MessageBlock] = blocks_from_dicts(user_blocks_data)
    _attach_tool_media_source(blocks, result, tool_call_id)

    if not blocks:
        return None, tool_result_to_content(result, tool_call_id=tool_call_id)

    follow_up_msg = CharacterConversationMessage(
        role=Role.USER,
        character_name=SYSTEM_CHARACTER_NAME,
        content=blocks,
        visible_characters=[character_name],
    )

    remaining_content = tool_result_to_content(result, tool_call_id=tool_call_id)
    return [follow_up_msg], remaining_content


def _strip_internal_fields(text: str) -> str:
    """从 JSON 字符串中移除所有下划线前缀字段（_image、_meta、_note 等内部载荷）。

    解析失败时原样返回，不影响非 JSON 文本。
    """
    # NOTE: 此过滤仅作用于 content_to_text 产出的文本副本（用于前端展示/日志）。
    # _meta 等内部字段的权威传递路径是 emit_tool_result 的 tool_call_meta 关键字参数，
    # 不经过此函数，因此过滤不会影响前端接收 _meta。
    stripped = text.lstrip()
    if not stripped or stripped[0] != "{":
        return text
    try:
        parsed = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return text
    if not isinstance(parsed, dict):
        return text
    filtered = {
        k: v for k, v in parsed.items()
        if not k.startswith("_") and k != "queued_messages"
    }
    return json.dumps(filtered, ensure_ascii=False)


def content_to_text(content: MessageContent|dict[str, Any]|list[MessageBlock]|None) -> str:
    """把 content（字符串、dict 或 block 列表）转成适合日志/前端展示/事件推送的纯文本。

    同时接受内存态（list[MessageBlock]）与序列化态（MessageContent 的 list[dict]）内容，
    两种形态的 text 块都会被提取。SP-3 起也接受原生 dict 工具结果。

    自动过滤 JSON 文本中所有下划线前缀的内部字段（_image、_meta 等），
    避免 base64 等大体积载荷撑爆前端事件和日志。
    """
    if content is None:
        return ""
    if isinstance(content, str):
        return _strip_internal_fields(content)
    if isinstance(content, dict):
        # SP-3: 原生 dict 工具结果——json.dumps 后过滤 _ 前缀字段
        return _strip_internal_fields(json.dumps(content, ensure_ascii=False))
    else:
        parts: list[str] = []
        for block in content:
            if isinstance(block, TextBlock):
                parts.append(_strip_internal_fields(block.text))
            elif isinstance(block, ImageBlock):
                parts.append("[image]")
            elif isinstance(block, AudioBlock):
                parts.append("[audio]")
            elif isinstance(block, VideoBlock):
                parts.append("[video]")
            elif isinstance(block, dict):
                btype = block.get("type")
                if btype == "text":
                    parts.append(_strip_internal_fields(str(block.get("text", ""))))
                elif btype == "image_url":
                    parts.append("[image]")
                elif btype == "input_audio":
                    parts.append("[audio]")
                elif btype == "video_url":
                    parts.append("[video]")
        return "\n".join(parts)


def content_to_log_text(content: MessageContent | dict[str, Any] | list[MessageBlock] | None) -> str:
    """仅供日志使用的多模态文本视图；不改变前端或 LLM 的内容转换。"""
    if content is None or isinstance(content, str):
        return content_to_text(content)

    blocks = content if isinstance(content, list) else [content]
    parts: list[str] = []
    for block in blocks:
        if isinstance(block, (TextBlock, ImageBlock, AudioBlock, VideoBlock)):
            parts.append(content_to_text([block]))
        elif isinstance(block, dict):
            btype = block.get("type")
            if btype == "text":
                parts.append(_strip_internal_fields(str(block.get("text", ""))))
            elif btype == "image_url":
                parts.append("[image]")
            elif btype == "input_audio":
                parts.append("[audio]")
            elif btype == "video_url":
                parts.append("[video]")
            else:
                parts.append("[unknown block]")
        else:
            parts.append("[unknown block]")
    return "\n".join(parts)


def summarize_message_for_log(
    content: MessageContent | dict[str, Any] | list[MessageBlock] | None,
    max_text_len: int | None = 300,
) -> str:
    """以占位符记录多模态块；默认保留原有的 300 字符预览长度。

    max_text_len=None 供原本没有字符限制的日志入口使用。
    """
    summary = content_to_log_text(content)
    if max_text_len is None or len(summary) <= max_text_len:
        return summary
    return summary[:max_text_len] + "..."


_ALLOWED_BLOCK_TYPES: tuple[str, ...] = ("text", "image_url", "input_audio", "video_url")


def validate_content_blocks(blocks: list[Any]) -> str | None:
    """严格校验 content block 数组，供动态端点 HTTP 入口层使用。

    遍历 blocks，任一不合法立即返回英文错误描述字符串（含 block 索引），
    全部合法返回 None。与 ``blocks_from_dicts`` 共享 block 格式约定，
    但校验比解析更严格——解析器对缺字段做兜底，校验器要求必填字段齐全。

    对额外未知字段宽容（前向兼容），不做校验。
    """
    for i, block in enumerate(blocks):
        if not isinstance(block, dict):
            return f"block[{i}]: must be an object"
        btype = block.get("type")
        if btype not in _ALLOWED_BLOCK_TYPES:
            allowed = ", ".join(_ALLOWED_BLOCK_TYPES)
            return f"block[{i}]: unsupported type {btype!r}, allowed: {allowed}"
        if btype == "text":
            if "text" not in block or not isinstance(block["text"], str):
                return f"block[{i}]: 'text' field must be a string"
        elif btype == "image_url":
            url_block = block.get("image_url")
            if not isinstance(url_block, dict) or not str(url_block.get("url", "")):
                return f"block[{i}]: 'image_url.url' must be a non-empty string"
        elif btype == "input_audio":
            audio_block = block.get("input_audio")
            if not isinstance(audio_block, dict) or not str(audio_block.get("data", "")):
                return f"block[{i}]: 'input_audio.data' must be a non-empty string"
        elif btype == "video_url":
            url_block = block.get("video_url")
            if not isinstance(url_block, dict) or not str(url_block.get("url", "")):
                return f"block[{i}]: 'video_url.url' must be a non-empty string"
    return None


def blocks_from_dicts(blocks: list[dict[str, Any]]) -> list[MessageBlock]:
    """将 list[dict] 转换为 list[MessageBlock]，供 edit_session_message 和 _append 共用。"""
    result: list[MessageBlock] = []
    for block in blocks:
        if not isinstance(block, dict):
            continue
        btype = block.get("type")
        if btype == "text":
            result.append(TextBlock(text=str(block.get("text", ""))))
        elif btype == "image_url":
            image_url_block = block.get("image_url")
            if isinstance(image_url_block, dict):
                result.append(
                    ImageBlock(image_url=str(image_url_block.get("url", ""))),
                )
            else:
                result.append(ImageBlock(image_url=str(image_url_block or "")))
        elif btype == "input_audio":
            input_audio_block = block.get("input_audio")
            if isinstance(input_audio_block, dict):
                raw_data = str(input_audio_block.get("data", ""))
                # 兼容 data URL 格式：剥离 `data:audio/{format};base64,` 前缀，内部统一存裸 base64
                if raw_data.startswith("data:audio/") and ";base64," in raw_data:
                    raw_data = raw_data.split(";base64,", 1)[1]
                result.append(AudioBlock(
                    data=raw_data,
                    format=str(input_audio_block.get("format", "wav")),
                ))
        elif btype == "video_url":
            video_url_block = block.get("video_url")
            if isinstance(video_url_block, dict):
                result.append(
                    VideoBlock(video_url=str(video_url_block.get("url", ""))),
                )
            else:
                result.append(VideoBlock(video_url=str(video_url_block or "")))
    return result


def extract_tool_call_meta(
    content: str | dict[str, Any] | list[MessageBlock],
) -> dict[str, Any] | None:
    """读取工具结果内部 ``_meta``，不改变原始 content。"""
    if not isinstance(content, dict):
        return None
    meta = content.get("_meta")
    return dict(meta) if isinstance(meta, dict) else None


def extract_tool_embedded_messages(
    content: str | dict[str, Any] | list[MessageBlock],
) -> list[dict[str, Any]] | None:
    """读取工具结果内部的嵌入消息，不改变原始 content。

    新字段使用 ``_queued_messages``，避免进入普通工具结果 JSON；同时兼容
    旧 History 中已经持久化的 ``queued_messages`` 字段，并归一化旧版的
    ``{"queued_message": {...}}`` 包装结构。
    """
    if not isinstance(content, dict):
        return None
    raw = content.get("_queued_messages")
    if not isinstance(raw, list):
        raw = content.get("queued_messages")
    if not isinstance(raw, list):
        return None
    messages: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        nested = item.get("queued_message")
        message = nested if isinstance(nested, dict) else item
        if isinstance(message, dict) and "content" in message:
            messages.append(dict(message))
    return messages or None


def content_to_serializable(content: str | dict[str, Any] | list[MessageBlock]) -> str | dict[str, Any] | list[dict[str, Any]]:
    """将 content 序列化为前端可用的 str | dict | list[dict]，供编辑响应使用。"""
    if isinstance(content, str):
        return content
    if isinstance(content, dict):
        return content
    return [b.as_object() if isinstance(b, MessageBlock) else b for b in content]