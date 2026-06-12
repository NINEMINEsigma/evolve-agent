"""Vision 能力探测工具。

使用当前 agent 的 LLM 配置发送一个仅含 dummy 图片的独立请求，
检测模型是否接受 image_url content block。结果缓存到本地 JSON，
避免重复探测。
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict

from abstract.tools.registry import registry, tool_error, tool_result
from component.llm import LLMClient
from system.context import get_runtime_context

logger = logging.getLogger(__name__)

# 1x1 透明 PNG 的 base64（约 70 B）
_DUMMY_PNG_B64: str = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


def _cache_path() -> Path:
    return get_runtime_context().workspace / "logs" / "vision_capability_cache.json"


def _load_cache() -> Dict[str, bool]:
    try:
        path = _cache_path()
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def _save_cache(data: Dict[str, bool]) -> None:
    try:
        path = _cache_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception as exc:
        logger.warning("Failed to save vision capability cache: %s", exc)


def _is_vision_rejection(exc: Exception) -> bool:
    """判断异常是否为 API 拒绝 image content block。"""
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
        if getattr(exc, "status_code", 0) == 400:
            return any(k in msg for k in ["image", "content", "unsupported"])
    return False


async def _handle_probe_vision(args: Dict[str, Any]) -> dict:
    """探测当前配置的 LLM 模型是否支持 vision 输入。"""
    force: bool = bool(args.get("force", False))

    ctx = get_runtime_context()
    model: str = (ctx.llm_model or "").lower()
    if not model:
        return tool_error("No LLM model configured in RuntimeContext")

    cache = _load_cache()
    if not force and model in cache:
        capable: bool = cache[model]
        return tool_result(
            capable=capable,
            model=ctx.llm_model,
            source="cache",
            message=(
                f"Model {ctx.llm_model} {'supports' if capable else 'does not support'} "
                f"vision (cached)."
            ),
        )

    client = LLMClient(ctx)
    probe_messages: list[dict] = [
        {
            "role": "user",
            "content": [
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/png;base64,{_DUMMY_PNG_B64}",
                    },
                },
                {"type": "text", "text": "What is this?"},
            ],
        }
    ]

    try:
        resp = await client.chat(probe_messages)
        # API 接受了图片即视为支持（不关心回答内容）
        cache[model] = True
        _save_cache(cache)
        logger.info(
            "probe_vision | model=%s capable=True source=probe",
            ctx.llm_model,
        )
        return tool_result(
            capable=True,
            model=ctx.llm_model,
            source="probe",
            message=f"Model {ctx.llm_model} accepts image content blocks.",
        )
    except Exception as exc:
        if _is_vision_rejection(exc):
            cache[model] = False
            _save_cache(cache)
            logger.info(
                "probe_vision | model=%s capable=False source=probe reason=content_block_rejection",
                ctx.llm_model,
            )
            return tool_result(
                capable=False,
                model=ctx.llm_model,
                source="probe",
                message=f"Model {ctx.llm_model} rejected image content blocks: {exc}",
            )
        # 非 vision 相关错误（网络、认证、超时等）不写入缓存
        logger.warning("probe_vision | model=%s error=%s", ctx.llm_model, exc)
        return tool_error(
            f"Probe failed with non-vision error: {exc}",
            model=ctx.llm_model,
        )


# ---------------------------------------------------------------------------
# 注册
# ---------------------------------------------------------------------------

registry.register(
    name="probe_vision_capability",
    toolset="core",
    schema={
        "type": "function",
        "function": {
            "name": "probe_vision_capability",
            "description": (
                "Test whether the current LLM model supports image/vision input "
                "using a minimal dummy image probe (1x1 PNG). No conversation history "
                "is included. Results are cached in workspace/logs/vision_capability_cache.json. "
                "Call this when the model changes or when you need to confirm vision capability."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "force": {
                        "type": "boolean",
                        "default": False,
                        "description": "Force re-probe even if a cached result exists.",
                    },
                },
            },
        },
    },
    handler=_handle_probe_vision,
    is_async=True,
    emoji="👁️",
    danger_level="readonly",
)