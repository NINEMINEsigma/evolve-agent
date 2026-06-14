"""多模态消息工具 — 供 AgentLoop 使用。

包含 content block 拒绝检测、图片剥离、vision 缓存查询、
_image payload 构造与脱敏。
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List

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
        if getattr(exc, "status_code", 0) != 400:
            return False
        keywords400: list[str] = ["image", "content", "unsupported"]
        return any(k in msg for k in keywords400)
    return False


def strip_image_blocks(messages: List[Dict[str, Any]], session_id: str) -> int:
    """移除消息列表中所有含 image_url 的 content blocks，转为纯文本。

    返回被剥离的图片数量。
    """
    stripped: int = 0
    for msg in messages:
        content = msg.get("content")
        if not isinstance(content, list):
            continue
        new_blocks: list[dict] = []
        has_image: bool = False
        for block in content:
            if isinstance(block, dict) and block.get("type") == "image_url":
                has_image = True
                stripped += 1
                new_blocks.append({
                    "type": "text",
                    "text": "[Image content stripped — current model does not support vision]",
                })
            else:
                new_blocks.append(block)
        if has_image:
            msg["content"] = new_blocks
    if stripped:
        logger.info(
            "Stripped %d image_url block(s) from messages (session=%s)",
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


def build_image_content_blocks(image: dict, text_payload: str) -> list[dict]:
    """构造 OpenAI 格式的 image_url + text content blocks。"""
    b64: str = str(image.get("base64", ""))
    mime: str = str(image.get("mime_type", "image/png"))
    if not b64:
        return []
    return [
        {
            "type": "image_url",
            "image_url": {"url": f"data:{mime};base64,{b64}"},
        },
        {"type": "text", "text": text_payload},
    ]


def sanitize_image_payload(result: dict, keep_metadata: bool = True) -> dict:
    """移除 tool result 中的 base64 数据，用于前端推送。"""
    pr_copy: dict = dict(result)
    raw_img_info = pr_copy.pop("_image", {})
    img_info: dict = dict(raw_img_info) if isinstance(raw_img_info, dict) else {}
    img_info.pop("base64", None)
    if keep_metadata and img_info:
        pr_copy["_image"] = img_info
    return pr_copy