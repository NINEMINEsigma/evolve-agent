"""多模态能力探测（系统内部自动调用）。

伪装成 Read 工具调用（assistant tool_calls → tool 消息携带多模态 content block），
检测 provider 是否支持在**工具消息**和**用户消息**中读取图片/音频。

探针已从工具内化为系统自动行为：当需要给当前模型传递多模态块时，
系统自动查找探针缓存（modality_capability_cache.json），没有缓存时自动探查。
非模态错误（网络/认证/超时）向上抛出异常，不静默吞没。

缓存按 model+base_url 联合索引，切换 LLM 配置时新组合未探查则自动触发探查，
已探查则命中缓存。同一 model+base_url 的并发探查请求通过 asyncio.Lock 串行化。
"""
# TODO: 没有使用easysave进行缓存, 依然在使用裸字典
# TODO: 应该迁移到system中
from __future__ import annotations

import asyncio
import base64
import io
import json
import logging
import wave
from pathlib import Path
from typing import Any, TYPE_CHECKING

from abstract.tools.registry import registry, tool_error, tool_result
from abstract.llm.loader import create_llm_client
from system.context import get_runtime_context
from entity.constant import MODALITY_CAPABILITY_CACHE_FILENAME
from entity.puretype import Role, ToolAvailability, ToolDangerLevel, ModalityCapability, LLMProfile
from entity.messages import (
    BaseMessage,
    ImageBlock,
    AudioBlock,
    TextBlock,
    MessageBlock,
    CharacterConversationMessage,
    ToolResultMessage,
    ToolCall,
    FunctionCall,
)
from abstract.llm.client import BaseLLMClient
from system.llm_profile_store import load_profiles
from entry.agent_support.multimodal import build_image_content_blocks, build_audio_content_blocks

if TYPE_CHECKING:
    from entry.base_agent_loop import ToolContext

logger = logging.getLogger(__name__)

# 1x1 透明 PNG 的 base64（约 70 B）
_DUMMY_PNG_B64: str = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


def _generate_dummy_wav_b64() -> str:
    """运行时生成 1 秒 8kHz 16bit 单声道静音 WAV 的 base64。

    过短/异常的音频会被部分 provider 拒绝（如 token-plan 对 45 字节最小 WAV 返回 400），
    必须保证音频数据合法。
    """
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(8000)
        w.writeframes(b"\x00\x00" * 8000)
    return base64.b64encode(buf.getvalue()).decode("ascii")


_DUMMY_WAV_B64: str = _generate_dummy_wav_b64()

# 按 cache_key 串行化探查请求，防止多 session 同时探查同一 model+base_url
_probe_locks: dict[str, asyncio.Lock] = {}


def _cache_path() -> Path:
    return get_runtime_context().workspace / MODALITY_CAPABILITY_CACHE_FILENAME


def _resolve_base_url(base_url: str | None) -> str:
    """解析 base_url：显式传入优先，否则从 active profile 取。"""
    if base_url:
        return base_url
    # ctx.llm_base_url 已删除；调用方应通过 resolve_active_model_base_url 传入 profile
    return ""



def resolve_active_model_base_url(
    context: ToolContext | None = None,
) -> tuple[str, str, LLMProfile | None]:
    """解析当前活跃的 model 和 base_url，供探针和 Read 工具共用。

    优先从 context.loop.active_llm_profile 获取（前端切换后的配置），
    fallback 到 runtime_context（启动配置）。

    Returns:
        (model_name, base_url, profile_or_None)
        - profile 非空时包含活跃配置，可直接传给 create_llm_client
        - profile 为 None 表示使用启动配置
    """
    profile: LLMProfile | None = None
    if context is not None:
        profile = context.loop.active_llm_profile

    if profile:
        return profile.model or "", profile.base_url or "", profile

    # 无 active profile — 探针返回不可用而非尝试建 client
    return "", "", None


async def forward_modality_to_ref_profile(
    context: ToolContext | None,
    active_profile: LLMProfile,
    ref_field: str,
    media_data: dict,
    media_type: str,
) -> str:
    """转发多模态内容到被引用 profile 对应的模型，返回描述文本。

    成功返回被引用模型的描述文本；失败返回错误信息+提示词模板包装。
    供 Read 工具在活跃模型 tool+user 都不支持该模态时调用。

    Args:
        context: 工具执行上下文，用于获取 runtime_context.agentspace
        active_profile: 当前活跃的 LLMProfile（含 vision_image_profile/audio_profile 引用字段）
        ref_field: 引用字段名，"vision_image_profile" 或 "audio_profile"
        media_data: 多模态数据 dict：
            - 图片: {"base64": str, "mime_type": str}
            - 音频: {"base64": str, "format": str}
        media_type: "image" 或 "audio"

    Returns:
        描述文本字符串（成功=模型描述，失败=错误信息+提示词模板）
    """
    from system.templates import read_template

    def _error_text(ref_uid: str, error_message: str) -> str:
        """构造转发错误文本（从模板加载并填充占位符）。"""
        return (
            read_template("forwarded/forwarded_error_template.txt")
            .replace("{{media_type}}", media_type)
            .replace("{{ref_uid}}", ref_uid)
            .replace("{{error_message}}", error_message)
        )

    ref_uid: str = getattr(active_profile, ref_field, "")
    if not ref_uid:
        return _error_text("(empty)", f"Active profile has no {ref_field} configured")

    # 加载全部 profiles 按 uid 查找被引用 profile
    ctx = context.runtime_context if context is not None else get_runtime_context()
    profiles = load_profiles(ctx.agentspace)
    ref_profile: LLMProfile | None = next(
        (p for p in profiles if p.uid == ref_uid), None
    )
    if ref_profile is None:
        return _error_text(ref_uid, "Referenced profile not found in profile list (dangling reference)")

    if not ref_profile.llm_client_name:
        return _error_text(ref_uid, f"Referenced profile '{ref_profile.name}' has no llm_client_name")

    # 构造提示词（从模板加载）
    prompt: str = read_template(
        "forwarded/forwarded_image_prompt.txt" if media_type == "image"
        else "forwarded/forwarded_audio_prompt.txt"
    )

    # 构造多模态块
    if media_type == "image":
        blocks = build_image_content_blocks(media_data, prompt)
    else:
        blocks = build_audio_content_blocks(media_data, prompt)

    # 构造单条 user 消息
    messages = [BaseMessage(role=Role.USER, content=blocks)]

    # 建客户端并发送
    try:
        client = create_llm_client(ref_profile.llm_client_name, ctx, ref_profile)
        response = await client.chat(messages)
        description: str = response.content or ""
        if not description.strip():
            return _error_text(ref_uid, f"Referenced profile '{ref_profile.name}' returned an empty description")
        logger.info(
            "forward_modality | session=%s ref_profile=%s media_type=%s ref_field=%s success",
            context.session_id if context else "", ref_profile.name, media_type, ref_field,
        )
        return description
    except Exception as exc:
        logger.warning(
            "forward_modality | session=%s ref_profile=%s media_type=%s ref_field=%s error=%s",
            context.session_id if context else "", ref_profile.name, media_type, ref_field, exc,
        )
        return _error_text(ref_uid, f"{type(exc).__name__}: {exc}")


def _cache_key(model: str, base_url: str | None = None) -> str:
    """缓存键按 模型名 + 服务商（base_url） 联合索引。

    同一模型在不同服务商上的 tool 消息多模态能力可能不同（图像 token 无"出身"概念，
    工具调用无法使用多模态大概率是提供商网关的问题），只按模型名索引会在不同
    服务商间互相污染缓存。
    """
    return f"{model.lower()}@{_resolve_base_url(base_url)}"


def _load_cache() -> dict[str, dict[str, Any]]:
    try:
        path = _cache_path()
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        logger.warning("Failed to load modality capability cache", exc_info=True)
    return {}


def _normalize_entry(raw: Any) -> ModalityCapability | None:
    """将缓存条目反序列化为 ModalityCapability；格式不匹配时返回 None。"""
    if not isinstance(raw, dict):
        return None
    try:
        return ModalityCapability.model_validate(raw)
    except Exception:
        return None


def get_cached_vision_support(model: str, base_url: str | None = None) -> bool | None:
    """读取模型在指定服务商下的 vision（tool 消息图片）能力缓存；未命中返回 None。"""
    cache = _load_cache()
    entry = _normalize_entry(cache.get(_cache_key(model, base_url)))
    if entry is not None and entry.vision is not None:
        return entry.vision
    return None


def get_cached_audio_support(model: str, base_url: str | None = None) -> bool | None:
    """读取模型在指定服务商下的 audio（tool 消息音频）能力缓存；未命中返回 None。"""
    cache = _load_cache()
    entry = _normalize_entry(cache.get(_cache_key(model, base_url)))
    if entry is not None and entry.audio is not None:
        return entry.audio
    return None


def get_cached_user_vision_support(model: str, base_url: str | None = None) -> bool | None:
    """读取模型在指定服务商下的 user 消息 vision 能力缓存；未命中返回 None。"""
    cache = _load_cache()
    entry = _normalize_entry(cache.get(_cache_key(model, base_url)))
    if entry is not None and entry.user_vision is not None:
        return entry.user_vision
    return None


def get_cached_user_audio_support(model: str, base_url: str | None = None) -> bool | None:
    """读取模型在指定服务商下的 user 消息 audio 能力缓存；未命中返回 None。"""
    cache = _load_cache()
    entry = _normalize_entry(cache.get(_cache_key(model, base_url)))
    if entry is not None and entry.user_audio is not None:
        return entry.user_audio
    return None


def _save_cache(data: dict[str, dict[str, Any]]) -> None:
    try:
        path = _cache_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception as exc:
        logger.warning("Failed to save modality capability cache: %s", exc)


def _is_modality_rejection(exc: Exception) -> bool:
    """判断异常是否为 API 拒绝 multimodal content block。"""
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
        if exc.status_code == 400:
            return any(k in msg for k in ["image", "audio", "content", "unsupported"])
    return False


def _build_tool_probe_messages(blocks: list[MessageBlock]) -> list[BaseMessage]:
    """构造伪装成 Read 工具调用的探测消息序列。

    结构：user → assistant(tool_calls=[Read]) → tool(多模态 content block)。
    与真实 Read 工具读图/读音频的请求结构完全一致，只有这样才能测出
    "工具消息中读多模态"的真实能力。
    """
    return [
        BaseMessage(role=Role.USER, content="请读取并描述这个文件的内容"),
        CharacterConversationMessage(
            role=Role.ASSISTANT,
            character_name="",
            content="好的，我来读取",
            tool_calls=[
                ToolCall(
                    id="probe_tool_1",
                    type="function",
                    function=FunctionCall(name="Read", arguments='{"path": "probe://media"}'),
                ),
            ],
        ),
        ToolResultMessage(
            role=Role.TOOL,
            character_name="",
            tool_call_id="probe_tool_1",
            content=blocks,
        ),
    ]


async def _probe_single_modality(
    client: BaseLLMClient,
    model_name: str,
    session_id: str,
    modality: str,
) -> bool:
    """伪装成工具调用单独探测一种模态，返回该模态在工具消息中是否可用。"""
    if modality == "vision":
        blocks: list[MessageBlock] = [
            ImageBlock(image_url=f"data:image/png;base64,{_DUMMY_PNG_B64}"),
            TextBlock(text='{"path": "probe://image.png", "width": 1, "height": 1}'),
        ] # type: ignore
    else:
        blocks = [
            AudioBlock(data=_DUMMY_WAV_B64, format="wav"),
            TextBlock(text='{"path": "probe://audio.wav"}'),
        ] # type: ignore
    probe_messages = _build_tool_probe_messages(blocks)

    try:
        await client.chat(probe_messages)
        logger.info(
            "probe_modality | session=%s model=%s %s=True source=single_probe(tool)",
            session_id, model_name, modality,
        )
        return True
    except Exception as exc:
        import openai as _openai
        # 400 错误（无论是否匹配 modality 关键词）都判定为该模态在工具消息中不可用。
        # 某些 provider 返回通用的 "Invalid request parameters" / "Upstream request failed"
        # 而非明确的 "unsupported content" 消息，此时乐观默认 True 会导致能力误判。
        if isinstance(exc, (_openai.BadRequestError, _openai.APIStatusError)):
            logger.info(
                "probe_modality | session=%s model=%s %s=False source=single_probe reason=http_400",
                session_id, model_name, modality,
            )
            return False
        # 真正的非模态错误（网络、认证、超时等），向上抛出
        raise exc


def _build_user_probe_messages(blocks: list[MessageBlock]) -> list[BaseMessage]:
    """构造普通 user 消息探测序列（不伪装工具调用）。

    与 _build_tool_probe_messages 不同，这里只发送一条 user 消息，
    消息 content 为多模态 content block 列表，测试 provider 是否接受
    user 消息中的多模态内容。
    """
    return [
        BaseMessage(role=Role.USER, content=blocks),
    ]


async def _probe_single_user_modality(
    client: Any,
    model_name: str,
    session_id: str,
    modality: str,
) -> bool:
    """发送普通 user 消息单独探测一种模态，返回该模态在 user 消息中是否可用。"""
    if modality == "vision":
        blocks: list[MessageBlock] = [
            ImageBlock(image_url=f"data:image/png;base64,{_DUMMY_PNG_B64}"),
            TextBlock(text='{"path": "probe://image.png", "width": 1, "height": 1}'),
        ]
    else:
        blocks = [
            AudioBlock(data=_DUMMY_WAV_B64, format="wav"),
            TextBlock(text='{"path": "probe://audio.wav"}'),
        ]
    probe_messages = _build_user_probe_messages(blocks)

    try:
        await client.chat(probe_messages)
        logger.info(
            "probe_modality | session=%s model=%s %s=True source=single_probe(user)",
            session_id, model_name, modality,
        )
        return True
    except Exception as exc:
        import openai as _openai
        if isinstance(exc, (_openai.BadRequestError, _openai.APIStatusError)):
            logger.info(
                "probe_modality | session=%s model=%s %s=False source=single_probe(user) reason=http_400",
                session_id, model_name, modality,
            )
            return False
        # 真正的非模态错误（网络、认证、超时等），向上抛出
        raise exc


async def run_modality_probe(
    context: ToolContext | None,
) -> ModalityCapability:
    """执行一次完整的多模态能力探测，返回 ModalityCapability（四项全非 None）。

    缓存命中（四项完整）时直接返回；否则创建 client 发送探测请求。
    非 400 错误（网络/认证/超时）向上抛出异常，不写缓存。
    按 cache_key 串行化（asyncio.Lock），防止多 session 重复探测。

    Raises:
        RuntimeError: 无 active profile 或无 llm_client_name。
        Exception: 探测过程中的非模态错误（网络、认证、超时等），向上抛出。
    """
    ctx = context.runtime_context if context is not None else get_runtime_context()
    session_id = context.session_id if context is not None else ""
    model_name, base_url, profile = resolve_active_model_base_url(context)

    key = _cache_key(model_name, base_url)

    # 缓存命中检查：如果四项都已探测，直接返回缓存值，跳过 API 请求
    cache = _load_cache()
    entry = _normalize_entry(cache.get(key))
    if (
        entry is not None
        and entry.vision is not None
        and entry.audio is not None
        and entry.user_vision is not None
        and entry.user_audio is not None
    ):
        logger.info(
            "probe_modality | session=%s model=%s cache_hit, skipping API probe",
            session_id, model_name,
        )
        return entry

    # 按 cache_key 串行化，防止多 session 同时探查同一 model+base_url
    lock = _probe_locks.get(key)
    if lock is None:
        lock = asyncio.Lock()
        _probe_locks[key] = lock
    async with lock:
        # 双检缓存：等待期间可能已被其他请求写入
        cache = _load_cache()
        entry = _normalize_entry(cache.get(key))
        if (
            entry is not None
            and entry.vision is not None
            and entry.audio is not None
            and entry.user_vision is not None
            and entry.user_audio is not None
        ):
            logger.info(
                "probe_modality | session=%s model=%s cache_hit (after lock), skipping API probe",
                session_id, model_name,
            )
            return entry

        client_name = profile.llm_client_name if profile else ""
        if not client_name:
            raise RuntimeError(
                f"No active LLM profile or llm_client_name — cannot probe modality capability "
                f"(model={model_name})."
            )
        client = create_llm_client(client_name, ctx, profile)

        # 先发送伪装成 Read 工具的图片+音频组合请求
        combined_blocks: list[MessageBlock] = [
            ImageBlock(image_url=f"data:image/png;base64,{_DUMMY_PNG_B64}"),
            AudioBlock(data=_DUMMY_WAV_B64, format="wav"),
            TextBlock(text='{"path": "probe://media"}'),
        ]
        combined_messages = _build_tool_probe_messages(combined_blocks)

        try:
            await client.chat(combined_messages)
            # API 接受了两者
            result = ModalityCapability(vision=True, audio=True, user_vision=True, user_audio=True)
            cache[key] = result.model_dump()
            _save_cache(cache)
            logger.info(
                "probe_modality | session=%s model=%s vision=True audio=True user_vision=True user_audio=True source=combined_probe",
                session_id, model_name,
            )
            return result
        except Exception as exc:
            if not _is_modality_rejection(exc):
                import openai as _openai
                if not isinstance(exc, (_openai.BadRequestError, _openai.APIStatusError)):
                    # 非模态错误（网络、认证、超时等）不写入缓存，向上抛出
                    logger.warning(
                        "probe_modality | session=%s model=%s error=%s",
                        session_id, model_name, exc,
                    )
                    raise

            # 模态被拒绝，需分别探测
            logger.info(
                "probe_modality | session=%s model=%s combined_rejected, probing individually",
                session_id, model_name,
            )

            vision_capable = await _probe_single_modality(client, model_name, session_id, "vision")
            audio_capable = await _probe_single_modality(client, model_name, session_id, "audio")

            # 仅在 tool 消息不支持该模态时才探测 user 消息，避免不必要的 API 调用
            user_vision_capable = True if vision_capable else await _probe_single_user_modality(client, model_name, session_id, "vision")
            user_audio_capable = True if audio_capable else await _probe_single_user_modality(client, model_name, session_id, "audio")

            result = ModalityCapability(
                vision=vision_capable,
                audio=audio_capable,
                user_vision=user_vision_capable,
                user_audio=user_audio_capable,
            )
            cache[key] = result.model_dump()
            _save_cache(cache)
            return result


async def ensure_modality_capability(
    context: ToolContext | None,
) -> ModalityCapability:
    """确保当前活跃模型的多模态能力已探测。有缓存读缓存，无缓存自动探查。

    Returns:
        ModalityCapability（四项全非 None）

    Raises:
        Exception: 探测过程中的非模态错误（网络/认证/超时），向上抛出。
    """
    return await run_modality_probe(context)