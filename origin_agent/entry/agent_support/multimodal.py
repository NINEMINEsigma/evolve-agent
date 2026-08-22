"""多模态消息工具 — 供 AgentLoop 使用。

包含 content block 拒绝检测、图片/音频剥离、vision/audio 缓存查询、
_image/_audio payload 构造，以及 tool result 到 content 的统一转换。
"""

from __future__ import annotations

import json
import logging
from typing import Any, TYPE_CHECKING, Callable

from entity.messages import AudioBlock, BaseMessage, CharacterConversationMessage, ImageBlock, MessageBlock, TextBlock
from entity.puretype import MessageContent, Role, LLMProfile
from entity.constant import SYSTEM_CHARACTER_NAME

if TYPE_CHECKING:
    from entry.base_agent_loop import ToolContext

logger = logging.getLogger(__name__)


def is_content_block_error(exc: Exception) -> bool:
    """检测异常是否由 unsupported content blocks（如图片）引起。"""
    import openai as _openai
    msg: str = str(exc).lower()
    if isinstance(exc, _openai.BadRequestError):
        keywords: list[str] = [
            "image_url",
            "input_audio",
            "content type",
            "content block",
            "unsupported",
            "invalid content",
            "multimodal",
            "vision",
            "audio",
        ]
        return any(k in msg for k in keywords)
    if isinstance(exc, _openai.APIStatusError):
        if exc.status_code != 400:
            return False
        keywords400: list[str] = ["image", "audio", "content", "unsupported"]
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


# ── 转发描述特殊标签 ──
FORWARDED_VISION_TAG = "forwarded_vision"
FORWARDED_AUDIO_TAG = "forwarded_audio"


def wrap_forwarded_description(description: str, tag: str) -> str:
    """用特殊标签包裹转发描述文本，供活跃模型识别转发来源。"""
    return f"<{tag}>\n{description}\n</{tag}>"


async def _forward_unsupported_block(
    context: "ToolContext",
    profile: LLMProfile,
    block: ImageBlock | AudioBlock,
    ref_field: str,
    media_type: str,
    save_callback: "Callable[[str], None] | None" = None,
) -> str:
    """处理不支持的多模态块：优先用 forward_result_content，无则转发借用。

    转发成功后写入 block.forward_result_content（持久化），并调用 save_callback 立即固化。
    返回描述文本。
    """
    # 优先用已有的 forward_result_content
    if block.forward_result_content:
        logger.info(
            "preprocess_multimodal | reusing existing forward_result_content for %s",
            media_type,
        )
        return block.forward_result_content

    # 无已有描述 → 转发借用
    from component.tools.modality_capability import forward_modality_to_ref_profile

    ref_uid: str = getattr(profile, ref_field, "")
    if not ref_uid:
        # 未配引用字段 → 报错
        raise ValueError(
            f"Active model does not support {media_type} in either tool or user messages, "
            f"and no {ref_field} is configured. Please configure a reference profile "
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
    else:
        # AudioBlock
        media_data = {"base64": block.data, "format": block.format}

    # 转发借用
    description = await forward_modality_to_ref_profile(
        context, profile, ref_field, media_data, media_type,
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

    遍历 messages 中的 ImageBlock/AudioBlock：
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
    from component.tools.modality_capability import (
        ensure_modality_capability,
        resolve_active_model_base_url,
    )

    model_name, base_url, profile = resolve_active_model_base_url(context)

    # 无 profile 或 model_name → 无需预检
    if not profile or not model_name:
        return messages

    # 快速检查 messages 中是否有 ImageBlock 或 AudioBlock
    has_multimodal = False
    for msg in messages:
        if isinstance(msg.content, list):
            for block in msg.content:
                if isinstance(block, (ImageBlock, AudioBlock)):
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
                        "vision_image_profile", "image",
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
                        "audio_profile", "audio",
                        save_callback,
                    )
                    if description:
                        new_blocks.append(TextBlock(text=wrap_forwarded_description(description, FORWARDED_AUDIO_TAG)))
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
        logger.info(
            "preprocess_multimodal | session=%s model=%s replaced unsupported blocks with forwarded descriptions",
            context.session_id, model_name,
        )

    return result_messages


def build_image_content_blocks(image: dict, text_payload: str) -> list[MessageBlock]:
    """构造 OpenAI 格式的 image_url + text content blocks。"""
    b64: str = str(image.get("base64", ""))
    mime: str = str(image.get("mime_type", "image/png"))
    if not b64:
        return [TextBlock(text=text_payload)]
    return [
        ImageBlock(image_url=f"data:{mime};base64,{b64}"),
        TextBlock(text=text_payload),
    ]


def build_audio_content_blocks(audio: dict, text_payload: str) -> list[MessageBlock]:
    """构造 OpenAI 格式的 input_audio + text content blocks。"""
    b64: str = str(audio.get("base64", ""))
    fmt: str = str(audio.get("format", audio.get("mime_type", "wav")))
    # 如果 format 是 MIME 类型，提取后缀
    if "/" in fmt:
        fmt = fmt.rsplit("/", 1)[-1]
    if not b64:
        return [TextBlock(text=text_payload)]
    return [
        AudioBlock(data=b64, format=fmt),
        TextBlock(text=text_payload),
    ]


def tool_result_to_content(result: Any) -> str | list[MessageBlock]:
    """把工具返回结果转换为 ToolResultMessage 可用的 content。

    - 字符串：原样返回。
    - 含 _image 字段的 dict：pop _image 后生成 [ImageBlock, TextBlock（元数据，不含 base64）]。
    - 含 _audio 字段的 dict：pop _audio 后生成 [AudioBlock, TextBlock（元数据，不含 base64）]。
    - 其他 dict：json.dumps 成字符串。
    - 其他：str(result)。
    """
    if isinstance(result, str):
        return result
    if isinstance(result, dict):
        image = result.pop("_image", None)
        if isinstance(image, dict) and image.get("base64"):
            return build_image_content_blocks(image, json.dumps(result, ensure_ascii=False))
        audio = result.pop("_audio", None)
        if isinstance(audio, dict) and audio.get("base64"):
            return build_audio_content_blocks(audio, json.dumps(result, ensure_ascii=False))
        return json.dumps(result, ensure_ascii=False)
    if isinstance(result, list):
        # 如果工具已经返回 MessageBlock 列表，直接透传
        if all(isinstance(b, MessageBlock) for b in result):
            return result  # type: ignore[return-value]
    return str(result)


def tool_result_to_follow_up(
    result: dict,
    character_name: str,
) -> tuple[list[BaseMessage] | None, str | list[MessageBlock]]:
    """提取 _user_image/_user_audio，构造 follow_up 用户消息。

    从 result dict 中 pop _user_image/_user_audio，构造
    CharacterConversationMessage(role=USER, character_name=system, content=[多模态块, 文本块])。
    剩余 dict 走 tool_result_to_content 生成纯文本 ToolResultMessage content。

    Returns:
        (follow_up_messages, remaining_content)
        - follow_up_messages: 延迟注入的 CharacterConversationMessage 列表，或 None
        - remaining_content: ToolResultMessage 的 content（纯文本 JSON）
    """
    user_image = result.pop("_user_image", None)
    user_audio = result.pop("_user_audio", None)

    if user_image is None and user_audio is None:
        return None, tool_result_to_content(result)

    metadata_json = json.dumps(result, ensure_ascii=False)
    blocks: list[MessageBlock] = []

    if isinstance(user_image, dict) and user_image.get("base64"):
        blocks.extend(build_image_content_blocks(user_image, metadata_json))
    if isinstance(user_audio, dict) and user_audio.get("base64"):
        blocks.extend(build_audio_content_blocks(user_audio, metadata_json))

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


def content_to_text(content: str|list[MessageBlock]|None) -> str:
    """把 content（字符串或 block 列表）转成适合日志/前端展示/事件推送的纯文本。

    自动过滤 JSON 文本中所有下划线前缀的内部字段（_image、_meta 等），
    避免 base64 等大体积载荷撑爆前端事件和日志。
    """
    if content is None:
        return ""
    if isinstance(content, str):
        return _strip_internal_fields(content)
    else:
        parts: list[str] = []
        for block in content:
            # 跳过多模态块（ImageBlock、AudioBlock 等），避免输出非JSON的占位符
            if isinstance(block, TextBlock):
                parts.append(_strip_internal_fields(block.text))
            elif isinstance(block, dict):
                btype = block.get("type")
                if btype == "text":
                    parts.append(_strip_internal_fields(str(block.get("text", ""))))
        return "\n".join(parts)


def sanitize_image_payload(result: dict, keep_metadata: bool = True) -> dict:
    """移除 tool result 中的 base64 数据，用于前端推送。"""
    pr_copy: dict = dict(result)
    raw_img_info = pr_copy.pop("_image", {})
    img_info: dict = dict(raw_img_info) if isinstance(raw_img_info, dict) else {}
    img_info.pop("base64", None)
    if keep_metadata and img_info:
        pr_copy["_image"] = img_info
    return pr_copy


def summarize_message_for_log(content: str|list[MessageBlock]|None, max_text_len: int = 300) -> str:
    """将消息（纯文本或多模态 blocks）转为适合日志的短字符串。

    图片 block 会被替换为 [image_url] 占位符，避免 base64 撑爆日志。
    """
    summary = content_to_text(content)
    if len(summary) <= max_text_len:
        return summary
    return summary[:max_text_len] + "..."


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
    return result


def content_to_serializable(content: str | list[MessageBlock]) -> str | list[dict[str, Any]]:
    """将 content 序列化为前端可用的 str | list[dict]，供编辑响应使用。"""
    if isinstance(content, str):
        return content
    return [b.as_object() if isinstance(b, MessageBlock) else b for b in content]