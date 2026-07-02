"""Vision 能力探测工具。

使用当前 agent 的 LLM 配置发送一个仅含 dummy 图片的独立请求，
检测模型是否接受 image_url content block。结果缓存到本地 JSON，
避免重复探测。
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, TYPE_CHECKING

from abstract.tools.registry import registry, tool_error, tool_result
from component.llm import LLMClient
from system.context import get_runtime_context
from entity.puretype import Role, ToolAvailability, ToolDangerLevel

if TYPE_CHECKING:
    from entry.base_agent_loop import ToolContext

logger = logging.getLogger(__name__)

# 1x1 透明 PNG 的 base64（约 70 B）
_DUMMY_PNG_B64: str = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


def _cache_path() -> Path:
    return get_runtime_context().workspace / "vision_capability_cache.json"


def _cache_key(model: str) -> str:
    """缓存键仅按模型名称索引，全局复用。"""
    return model.lower()


def _load_cache() -> dict[str, bool]:
    try:
        path = _cache_path()
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        logger.warning("Failed to load vision capability cache", exc_info=True)
    return {}


def get_cached_vision_support(model: str) -> bool | None:
    """读取模型 vision 能力缓存（全局，按 model 键）；未命中返回 None。"""
    normalized = model.lower()
    cache = _load_cache()
    if normalized in cache:
        return cache[normalized]
    return None


def _save_cache(data: dict[str, bool]) -> None:
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
        if exc.status_code == 400:
            return any(k in msg for k in ["image", "content", "unsupported"])
    return False


async def _handle_probe_vision(args: dict[str, Any], context: ToolContext | None = None) -> dict:
    """探测当前配置的 LLM 模型是否支持 vision 输入。"""
    force: bool = bool(args.get("force", False))

    ctx = context.runtime_context if context is not None else get_runtime_context()
    session_id = context.session_id if context is not None else ""
    model_name: str = ctx.llm_model or ""
    if not model_name:
        return tool_error("No LLM model configured in RuntimeContext")

    key = _cache_key(model_name)
    cache = _load_cache()
    if not force and key in cache:
        capable: bool = cache[key]
        return tool_result(
            capable=capable,
            model=model_name,
            source="cache",
            message=(
                f"Model {model_name} {'supports' if capable else 'does not support'} "
                f"vision (cached)."
            ),
        )

    client = LLMClient(ctx)
    probe_messages: list[dict] = [
        {
            "role": Role.USER,
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
        await client.chat(probe_messages)
        # API 接受了图片即视为支持（不关心回答内容）
        cache[key] = True
        _save_cache(cache)
        logger.info(
            "probe_vision | session=%s model=%s capable=True source=probe",
            session_id, model_name,
        )
        return tool_result(
            capable=True,
            model=model_name,
            source="probe",
            message=f"Model {model_name} accepts image content blocks.",
        )
    except Exception as exc:
        if _is_vision_rejection(exc):
            cache[key] = False
            _save_cache(cache)
            logger.info(
                "probe_vision | session=%s model=%s capable=False source=probe reason=content_block_rejection",
                session_id, model_name,
            )
            return tool_result(
                capable=False,
                model=model_name,
                source="probe",
                message=f"Model {model_name} rejected image content blocks: {exc}",
            )
        # 非 vision 相关错误（网络、认证、超时等）不写入缓存
        logger.warning("probe_vision | session=%s model=%s error=%s", session_id, model_name, exc)
        return tool_error(
            f"Probe failed with non-vision error: {exc}",
            model=model_name,
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
            # 通过发送一张最小 dummy 图片（1x1 透明 PNG）测试当前 LLM 模型是否支持图片/vision 输入。
            # 结果缓存到本地 JSON 文件，同一模型后续调用直接返回缓存结果，不消耗 API 请求。
            #
            # ## 前置条件
            # 必须已配置 LLM 模型（RuntimeContext.llm_model 非空）。
            #
            # ## 调用效果
            # 若缓存命中且 force=false，立即返回缓存结果。
            # 若缓存未命中或 force=true，发送一次含 1x1 透明 PNG 的 chat 请求探测。
            # - API 接受请求 → 模型支持 vision → 结果缓存为 capable=true。
            # - API 以 vision 相关关键词拒绝图片内容块 → 结果缓存为 capable=false。
            # - API 因非 vision 错误（网络、认证、超时）失败 → 不写缓存，工具返回错误。
            #
            # ## 返回
            # 成功时：
            # ```json
            # {"capable": true, "model": "gpt-4o", "source": "probe|cache", "message": "..."}
            # ```
            # vision 拒绝时：
            # ```json
            # {"capable": false, "model": "gpt-4o", "source": "probe", "message": "..."}
            # ```
            # 非 vision 错误时：
            # ```json
            # {"error": "...", "model": "gpt-4o"}
            # ```
            #
            # ## 何时使用
            # - 模型变更后确认 vision 能力。
            # - 调用图片相关工具（read_image 等）前验证模型不会拒绝图片内容。
            #
            # ## 副作用/注意
            # - 每次未缓存的探测消耗恰好一次 API 请求。
            # - 缓存持久化到本地 JSON 文件（vision_capability_cache.json），跨会话保留直到运行时工作空间重置。
            # - 非 vision 错误（网络、认证、超时）不写入缓存，agent 可重试。
            "description": """Test whether the current LLM model supports image/vision input by sending a minimal dummy image (1x1 transparent PNG).
Results are cached to a local JSON file; subsequent calls for the same model return the cached result immediately without consuming an API request.

## Prerequisites
An LLM model must be configured (RuntimeContext.llm_model must be non-empty).

## Effect
If a cached result exists and `force` is false, returns the cached result immediately.
If no cache exists or `force` is true, sends a single chat request with a 1x1 transparent PNG.
- API accepts the request → model supports vision → result cached as `capable=true`.
- API rejects the image content block with vision-related keywords → result cached as `capable=false`.
- API fails with a non-vision error (network, auth, timeout) → no cache written, tool returns error.

## Returns
On success:
```json
{"capable": true, "model": "gpt-4o", "source": "probe|cache", "message": "..."}
```
On vision rejection:
```json
{"capable": false, "model": "gpt-4o", "source": "probe", "message": "..."}
```
On non-vision error:
```json
{"error": "...", "model": "gpt-4o"}
```

## When to Use
- After the model changes, confirm vision capability.
- Before calling image-based tools (read_image, etc.), verify the model won't reject image content.

## Side Effects / Notes
- Each uncached probe consumes exactly one API request.
- Cache is persisted to a local JSON file (vision_capability_cache.json) and survives sessions until the runtime workspace is reset.
- Non-vision errors (network, auth, timeout) are NOT cached; the agent can retry.""",
            "parameters": {
                "type": "object",
                "properties": {
                    "force": {
                        "type": "boolean",
                        "default": False,
                        # 若为 true，即使缓存中已有结果也重新探测。默认 false。
                        "description": """If true, re-probe the model even when a cached result already exists. Default: false.""",
                    },
                },
            },
        },
    },
    handler=_handle_probe_vision,
    is_async=True,
    emoji="👁️",
    danger_level=ToolDangerLevel.readonly,
    no_timeout=True,
    availability=ToolAvailability.EVERY,
)