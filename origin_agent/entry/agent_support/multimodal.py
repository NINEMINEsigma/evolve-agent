"""多模态消息工具 — 供 AgentLoop 使用。

包含 content block 拒绝检测、图片/音频剥离、vision/audio 缓存查询、
_image/_audio payload 构造，以及 tool result 到 content 的统一转换。
"""

from __future__ import annotations

import json
import logging
from typing import Any

from entity.messages import AudioBlock, BaseMessage, CharacterConversationMessage, ImageBlock, MessageBlock, TextBlock
from entity.puretype import MessageContent, Role
from entity.constant import SYSTEM_CHARACTER_NAME

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


def supports_vision(model: str) -> bool:
    """根据缓存判断 Read 工具（tool 消息）读取图片是否被当前 provider 接受。

    缓存未命中时乐观默认返回 True，避免新 provider 被漏掉。
    """
    from component.tools.modality_capability import get_cached_vision_support
    cached = get_cached_vision_support(model)
    if cached is not None:
        return cached
    return True


def supports_audio(model: str) -> bool:
    """根据缓存判断 Read 工具（tool 消息）读取音频是否被当前 provider 接受。

    缓存未命中时乐观默认返回 True，避免新 provider 被漏掉。
    """
    from component.tools.modality_capability import get_cached_audio_support
    cached = get_cached_audio_support(model)
    if cached is not None:
        return cached
    return True


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