"""多模态消息工具 — 供 AgentLoop 使用。

包含 content block 拒绝检测、图片剥离、vision 缓存查询、
_image payload 构造与脱敏，以及 tool result 到 content 的统一转换。
"""

from __future__ import annotations

import json
import logging
from typing import Any

from entity.messages import BaseMessage, ImageBlock, MessageBlock, TextBlock

logger = logging.getLogger(__name__)


def is_content_block_error(exc: Exception) -> bool:
    """检测异常是否由 unsupported content blocks（如图片）引起。"""
    import openai as _openai
    msg: str = str(exc).lower()
    if isinstance(exc, _openai.BadRequestError):
        keywords: list[str] = [
            "image_url",
            "content type",
            "content block",
            "unsupported",
            "invalid content",
            "multimodal",
            "vision",
        ]
        return any(k in msg for k in keywords)
    if isinstance(exc, _openai.APIStatusError):
        if exc.status_code != 400:
            return False
        keywords400: list[str] = ["image", "content", "unsupported"]
        return any(k in msg for k in keywords400)
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
                    text="[Image content stripped — current model does not support vision]",
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


def supports_vision(model: str) -> bool:
    """根据缓存判断模型是否支持 vision。

    缓存未命中时乐观默认返回 True，避免新模型被漏掉。
    """
    from component.tools.probe_vision import get_cached_vision_support
    cached = get_cached_vision_support(model)
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


def tool_result_to_content(result: Any) -> str | list[MessageBlock]:
    """把工具返回结果转换为 ToolResultMessage 可用的 content。

    - 字符串：原样返回。
    - 含 _image 字段的 dict：生成 [ImageBlock, TextBlock]。
    - 其他 dict：json.dumps 成字符串。
    - 其他：str(result)。
    """
    if isinstance(result, str):
        return result
    if isinstance(result, dict):
        image = result.get("_image")
        if isinstance(image, dict) and image.get("base64"):
            return build_image_content_blocks(image, json.dumps(result, ensure_ascii=False))
        return json.dumps(result, ensure_ascii=False)
    if isinstance(result, list):
        # 如果工具已经返回 MessageBlock 列表，直接透传
        if all(isinstance(b, MessageBlock) for b in result):
            return result  # type: ignore[return-value]
    return str(result)


def content_to_text(content: str | list[Any] | None) -> str:
    """把 content（字符串或 block 列表）转成适合日志/前端展示/事件推送的纯文本。"""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, TextBlock):
                parts.append(block.text)
            elif isinstance(block, ImageBlock):
                parts.append("[image_url]")
            elif isinstance(block, dict):
                btype = block.get("type")
                if btype == "text":
                    parts.append(str(block.get("text", "")))
                elif btype == "image_url":
                    parts.append("[image_url]")
                else:
                    parts.append(f"[{btype}]")
            else:
                parts.append(str(block))
        return "\n".join(parts)
    return str(content)


def sanitize_image_payload(result: dict, keep_metadata: bool = True) -> dict:
    """移除 tool result 中的 base64 数据，用于前端推送。"""
    pr_copy: dict = dict(result)
    raw_img_info = pr_copy.pop("_image", {})
    img_info: dict = dict(raw_img_info) if isinstance(raw_img_info, dict) else {}
    img_info.pop("base64", None)
    if keep_metadata and img_info:
        pr_copy["_image"] = img_info
    return pr_copy


def summarize_message_for_log(content: str | list[Any] | None, max_text_len: int = 30000) -> str:
    """将用户消息（纯文本或多模态 blocks）转为适合日志的短字符串。

    图片 block 会被替换为 [image_url] 占位符，避免 base64 撑爆日志。
    """
    summary = content_to_text(content)
    if len(summary) <= max_text_len:
        return summary
    return summary[:max_text_len] + "..."