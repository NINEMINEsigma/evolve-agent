"""多模态消息工具 — 供 AgentLoop 使用。

包含 content block 拒绝检测、图片/音频剥离、vision/audio 缓存查询、
_image/_audio payload 构造，以及 tool result 到 content 的统一转换。
"""

from __future__ import annotations

import json
import logging
from typing import Any, TYPE_CHECKING, Callable

from entity.messages import AudioBlock, BaseMessage, CharacterConversationMessage, ImageBlock, MessageBlock, TextBlock, VideoBlock
from entity.puretype import MessageContent, Role, LLMProfile
from entity.constant import (
    FORWARDED_AUDIO_TAG,
    FORWARDED_VISION_TAG,
    FORWARDED_VIDEO_TAG,
    SYSTEM_CHARACTER_NAME,
)
from system.modality_capability import (
    ensure_modality_capability,
    forward_modality_to_ref_profile,
    resolve_active_model_base_url,
    wrap_forwarded_description,
)

if TYPE_CHECKING:
    from entry.base_agent_loop import ToolContext

logger = logging.getLogger(__name__)

# 存量 history.es 中 SP-3 之前持久化的 ToolResultMessage.content 为 str（JSON 序列化字典）。
# 加载时经 normalize_legacy_tool_results 调用本 helper 尝试解析回原生 dict；解析失败则
# 构造一条「历史解析失败的工具调用失败字典」（与 SP-1 {"error": ...} 同族），字段无 _ 前缀，前端可见。
LEGACY_CONTENT_PREVIEW_CHARS: int = 200


# NOTE: 兼容性代码
def legacy_tool_result_str_to_dict(content: str) -> dict[str, Any]:
    """将存量 str 形态的工具结果 content 归一化为原生 dict。

    - json.loads 成功且结果为 dict → 原样返回（解析成功的旧会话恢复为原生 dict，_meta 恢复可提取）。
    - 其他情况（非 JSON、解析结果非 dict）→ 返回失败字典，含截断原文预览保留可读性。

    本函数永不抛出异常。
    """
    try:
        parsed = json.loads(content)
        if isinstance(parsed, dict):
            return parsed
    except (json.JSONDecodeError, TypeError):
        pass
    return {
        "error": "Failed to parse legacy tool result content (stored before native-dict migration).",
        "legacy_content_preview": content[:LEGACY_CONTENT_PREVIEW_CHARS],
    }


def is_content_block_error(exc: Exception) -> bool:
    """检测异常是否由 unsupported content blocks（如图片/音频/视频）引起。"""
    import openai as _openai
    msg: str = str(exc).lower()
    if isinstance(exc, _openai.BadRequestError):
        keywords: list[str] = [
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
        ]
        return any(k in msg for k in keywords)
    if isinstance(exc, _openai.APIStatusError):
        if exc.status_code != 400:
            return False
        keywords400: list[str] = ["image", "audio", "video", "content", "unsupported"]
        return any(k in msg for k in keywords400)
    return False


def is_audio_block_error(exc: Exception) -> bool:
    """检测异常是否由 unsupported audio content blocks 引起。"""
    import openai as _openai
    msg: str = str(exc).lower()
    if isinstance(exc, _openai.BadRequestError):
        keywords: list[str] = [
            "input_audio",
            "audio",
            "content type",
            "content block",
            "unsupported",
            "invalid content",
            "multimodal",
        ]
        return any(k in msg for k in keywords)
    if isinstance(exc, _openai.APIStatusError):
        if exc.status_code != 400:
            return False
        return any(k in msg for k in ["audio", "content", "unsupported"])
    return False


def strip_image_blocks(messages: list[BaseMessage], session_id: str) -> int:
    """移除 BaseMessage 列表中所有含 image 的 content blocks，转为纯文本。

    返回被剥离的图片数量。
    """
    stripped: int = 0
    for msg in messages:
        content = msg.content
        if not isinstance(content, list):
            continue
        new_blocks: list[MessageBlock] = []
        has_image: bool = False
        for block in content:
            if isinstance(block, ImageBlock):
                has_image = True
                stripped += 1
                new_blocks.append(TextBlock(
                    text="[Image content removed — the provider rejected this image content block]",
                ))
            else:
                new_blocks.append(block)
        if has_image:
            msg.content = new_blocks
    if stripped:
        logger.info(
            "Stripped %d image block(s) from messages (session=%s)",
            stripped, session_id,
        )
    return stripped


def strip_audio_blocks(messages: list[BaseMessage], session_id: str) -> int:
    """移除 BaseMessage 列表中所有含 audio 的 content blocks，转为纯文本。

    返回被剥离的音频数量。
    """
    stripped: int = 0
    for msg in messages:
        content = msg.content
        if not isinstance(content, list):
            continue
        new_blocks: list[MessageBlock] = []
        has_audio: bool = False
        for block in content:
            if isinstance(block, AudioBlock):
                has_audio = True
                stripped += 1
                new_blocks.append(TextBlock(
                    text="[Audio content removed — the provider rejected this audio content block]",
                ))
            else:
                new_blocks.append(block)
        if has_audio:
            msg.content = new_blocks
    if stripped:
        logger.info(
            "Stripped %d audio block(s) from messages (session=%s)",
            stripped, session_id,
        )
    return stripped


async def _forward_unsupported_block(
    context: "ToolContext",
    profile: LLMProfile,
    block: ImageBlock | AudioBlock | VideoBlock,
    media_type: str,
    save_callback: "Callable[[str], None] | None" = None,
) -> str:
    """处理不支持的多模态块：优先用 forward_result_content，无则转发借用。

    转发成功后写入 block.forward_result_content（持久化），并调用 save_callback 立即固化。
    返回描述文本。
    """
    # 优先用已有的 forward_result_content
    if block.forward_result_content:
        logger.debug(
            "preprocess_multimodal | reusing existing forward_result_content for %s",
            media_type,
        )
        return block.forward_result_content

    # 无已有描述 → 转发借用。按模态显式检查引用实例。
    if media_type == "image":
        ref_profile = profile.vision_image_profile
    elif media_type == "audio":
        ref_profile = profile.audio_profile
    else:  # video
        ref_profile = profile.vision_video_profile
    if ref_profile is None:
        # 未配引用字段 → 报错
        raise ValueError(
            f"Active model does not support {media_type} in either tool or user messages, "
            f"and no {media_type} reference profile is configured. Please configure a reference profile "
            f"or switch to a model that supports {media_type}."
        )

    # 构造 media_data
    if isinstance(block, ImageBlock):
        # 解析 data URL 提取 base64 和 mime_type
        image_url = block.image_url
        if image_url.startswith("data:"):
            # data:image/png;base64,xxxx
            header, b64 = image_url.split(",", 1)
            mime_type = header.split(";")[0].split(":")[1]
            media_data = {"base64": b64, "mime_type": mime_type}
        else:
            # 非 data URL（HTTP URL），跳过转发，保留原块
            logger.warning(
                "preprocess_multimodal | skipping forward for non-data-URL image: %s",
                image_url[:50],
            )
            return ""
    elif isinstance(block, VideoBlock):
        # 解析 data URL 提取 base64 和 mime_type
        video_url = block.video_url
        if video_url.startswith("data:"):
            header, b64 = video_url.split(",", 1)
            mime_type = header.split(";")[0].split(":")[1]
            media_data = {"base64": b64, "mime_type": mime_type}
        else:
            # 非 data URL（HTTP URL），跳过转发，保留原块
            logger.warning(
                "preprocess_multimodal | skipping forward for non-data-URL video: %s",
                video_url[:50],
            )
            return ""
    else:
        # AudioBlock
        media_data = {"base64": block.data, "format": block.format}

    # 转发借用
    description = await forward_modality_to_ref_profile(
        context, profile, media_data, media_type,
    )

    # 写入 forward_result_content（持久化）
    block.forward_result_content = description
    if save_callback is not None:
        save_callback(context.session_id)

    return description


async def preprocess_multimodal_blocks(
    messages: list[BaseMessage],
    context: "ToolContext",
    save_callback: "Callable[[str], None] | None" = None,
) -> list[BaseMessage]:
    """预检多模态块：自动探查能力，不支持时转发借用替换。

    遍历 messages 中的 ImageBlock/AudioBlock/VideoBlock：
    - 查缓存 → 有缓存直接判断
    - 无缓存 → 自动探查（ensure_modality_capability）
    - tool 或 user 支持 → 原样发送
    - 都不支持 → 优先用 forward_result_content；无则转发借用并写入 forward_result_content
      用特殊标签包裹描述后替换该块为 TextBlock（临时 messages 列表，不改持久化历史）

    遇到探查非模态错误时向上抛出异常，由调用方的 except 分支处理。

    Args:
        messages: 发给 LLM 的消息列表（临时列表，不修改持久化历史中的多模态块）
        context: 工具执行上下文
        save_callback: 接收 session_id 的回调，用于转发后持久化 forward_result_content。
                       传入 None 时不持久化。
    """
    model_name, base_url, profile = resolve_active_model_base_url(context)

    # 无 profile 或 model_name → 无需预检
    if not profile or not model_name:
        return messages

    # 快速检查 messages 中是否有 ImageBlock 或 AudioBlock 或 VideoBlock
    has_multimodal = False
    for msg in messages:
        if isinstance(msg.content, list):
            for block in msg.content:
                if isinstance(block, (ImageBlock, AudioBlock, VideoBlock)):
                    has_multimodal = True
                    break
        if has_multimodal:
            break
    if not has_multimodal:
        return messages

    # 自动探查能力
    capability = await ensure_modality_capability(context)

    # 遍历处理每条消息
    result_messages: list[BaseMessage] = []
    any_replaced = False
    for msg in messages:
        content = msg.content
        if not isinstance(content, list):
            result_messages.append(msg)
            continue

        new_blocks: list[MessageBlock] = []
        blocks_replaced = False
        for block in content:
            if isinstance(block, ImageBlock):
                if capability.vision or capability.user_vision:
                    # 支持 → 原样保留
                    new_blocks.append(block)
                else:
                    # 都不支持
                    description = await _forward_unsupported_block(
                        context, profile, block,
                        "image",
                        save_callback,
                    )
                    if description:
                        new_blocks.append(TextBlock(text=wrap_forwarded_description(description, FORWARDED_VISION_TAG)))
                        blocks_replaced = True
                        any_replaced = True
                    else:
                        # 非 data URL 跳过转发，保留原块
                        new_blocks.append(block)
            elif isinstance(block, AudioBlock):
                if capability.audio or capability.user_audio:
                    # 支持 → 原样保留
                    new_blocks.append(block)
                else:
                    # 都不支持
                    description = await _forward_unsupported_block(
                        context, profile, block,
                        "audio",
                        save_callback,
                    )
                    if description:
                        new_blocks.append(TextBlock(text=wrap_forwarded_description(description, FORWARDED_AUDIO_TAG)))
                        blocks_replaced = True
                        any_replaced = True
                    else:
                        # 非 data URL 跳过转发，保留原块
                        new_blocks.append(block)
            elif isinstance(block, VideoBlock):
                if capability.video or capability.user_video:
                    # 支持 → 原样保留
                    new_blocks.append(block)
                else:
                    # 都不支持
                    description = await _forward_unsupported_block(
                        context, profile, block,
                        "video",
                        save_callback,
                    )
                    if description:
                        new_blocks.append(TextBlock(text=wrap_forwarded_description(description, FORWARDED_VIDEO_TAG)))
                        blocks_replaced = True
                        any_replaced = True
                    else:
                        # 非 data URL 跳过转发，保留原块
                        new_blocks.append(block)
            else:
                new_blocks.append(block)

        if blocks_replaced:
            # 创建消息副本，避免修改持久化历史
            result_messages.append(msg.model_copy(update={"content": new_blocks}))
        else:
            result_messages.append(msg)

    if any_replaced:
        logger.debug(
            "preprocess_multimodal | session=%s model=%s replaced unsupported blocks with forwarded descriptions",
            context.session_id, model_name,
        )

    return result_messages


def tool_result_to_content(result: Any) -> str | dict[str, Any] | list[MessageBlock]:
    """把工具返回结果转换为 ToolResultMessage 可用的 content。

    - str（防御性，实际不可达——SP-1 后 handler 返回 dict）：经 legacy_tool_result_str_to_dict 解析为 dict 后落入 dict 处理。
    - 含 _blocks 字段的 dict：pop _blocks 后经 blocks_from_dicts 转为有序 MessageBlock 列表；
      剩余 dict 非空时追加为末尾 TextBlock(json.dumps(remaining))。
    - 其他 dict：返回原生 dict（不再 json.dumps）。
    - 非以上类型：raise TypeError（SP-1 后 handler 必须返回 dict，响亮失败优先于静默兜底）。
    """
    if isinstance(result, str):
        # 防御性：SP-1 后 dispatch 层保证 handler 返回 dict，str 理论不可达。
        # 存量 str（旧 history.es）已在加载缝经 normalize_legacy_tool_results 归一化。
        result = legacy_tool_result_str_to_dict(result)
    if isinstance(result, dict):
        # _blocks 优先：有序混合块列表，复用 blocks_from_dicts 格式
        blocks_data = result.pop("_blocks", None)
        if isinstance(blocks_data, list) and blocks_data:
            blocks = blocks_from_dicts(blocks_data)
            # 剩余 dict（去掉 _blocks）非空时追加为末尾 TextBlock
            if result:
                blocks.append(TextBlock(text=json.dumps(result, ensure_ascii=False)))
            return blocks
        # 无媒体键：返回原生 dict（不再 json.dumps）
        return result
    raise TypeError(f"tool_result_to_content expects dict, got {type(result).__name__}")


def tool_result_to_follow_up(
    result: dict,
    character_name: str,
) -> tuple[list[BaseMessage] | None, str | dict[str, Any] | list[MessageBlock]]:
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
        return None, tool_result_to_content(result)

    metadata_json = json.dumps(result, ensure_ascii=False)
    blocks: list[MessageBlock] = blocks_from_dicts(user_blocks_data)

    if not blocks:
        return None, tool_result_to_content(result)

    follow_up_msg = CharacterConversationMessage(
        role=Role.USER,
        character_name=SYSTEM_CHARACTER_NAME,
        content=blocks,
        visible_characters=[character_name],
    )

    remaining_content = tool_result_to_content(result)
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
    filtered = {k: v for k, v in parsed.items() if not k.startswith("_")}
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


def summarize_message_for_log(content: MessageContent|list[MessageBlock]|None, max_text_len: int = 300) -> str:
    """将消息（纯文本或多模态 blocks）转为适合日志的短字符串。

    同时接受内存态（list[MessageBlock]）与序列化态（MessageContent 的 list[dict]）内容。
    图片 block 会被替换为 [image_url] 占位符，避免 base64 撑爆日志。
    """
    summary = content_to_text(content)
    if len(summary) <= max_text_len:
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


def content_to_serializable(content: str | dict[str, Any] | list[MessageBlock]) -> str | dict[str, Any] | list[dict[str, Any]]:
    """将 content 序列化为前端可用的 str | dict | list[dict]，供编辑响应使用。"""
    if isinstance(content, str):
        return content
    if isinstance(content, dict):
        return content
    return [b.as_object() if isinstance(b, MessageBlock) else b for b in content]