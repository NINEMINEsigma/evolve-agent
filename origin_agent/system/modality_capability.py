"""多模态能力探测（系统内部自动调用）。

伪装成 Read 工具调用（assistant tool_calls → tool 消息携带多模态 content block），
检测 provider 是否支持在**工具消息**和**用户消息**中读取图片/音频/视频。

探针已从工具内化为系统自动行为：当需要给当前模型传递多模态块时，
系统自动查找探针缓存（modality_capability_cache.es），没有缓存时自动探查。
非模态错误（网络/认证/超时）向上抛出异常，不静默吞没。

首次探查直接按 模态 × 消息路径（tool/user）六路并发探测，不做组合探测——
全模态（三模态全支持）的模型+厂商极少，组合探测几乎必然失败、白白浪费一次请求。

缓存按 model+base_url 联合索引（easysave 序列化，类型保留），切换 LLM 配置时
新组合未探查则自动触发探查，已探查则命中缓存。同一 model+base_url 的并发探查
请求通过 asyncio.Lock 串行化。缓存文件缺失或损坏时直接重新探测。
"""
from __future__ import annotations

import asyncio
import base64
import io
import logging
import wave
from pathlib import Path
from typing import TYPE_CHECKING, TypeGuard

from easysave import load as es_load, save as es_save

from abstract.llm.loader import create_llm_client
from system.context import get_runtime_context
from entity.constant import (
    FORWARDED_AUDIO_TAG,
    FORWARDED_VISION_TAG,
    FORWARDED_VIDEO_TAG,
    MODALITY_CAPABILITY_ES_FILENAME,
    MODALITY_CAPABILITY_ES_KEY,
)
from entity.puretype import Role, ModalityCapability, LLMProfile
from entity.messages import (
    BaseMessage,
    ImageBlock,
    AudioBlock,
    VideoBlock,
    TextBlock,
    MessageBlock,
    CharacterConversationMessage,
    ToolResultMessage,
    ToolCall,
    FunctionCall,
)
from abstract.llm.client import BaseLLMClient

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


def _load_dummy_mp4_b64() -> str:
    """从模板文件加载 dummy MP4 的 base64。

    使用 ffmpeg 生成的 2 秒 320x240 黑屏 MP4（2024 字节），
    经 API 验证可被接受。不能用更小的 MP4——部分 provider 对极短视频
    返回 400 "Invalid request parameters"。
    """
    from system.templates import read_template
    b64 = read_template("probe/dummy_video_mp4.txt")
    if not b64:
        logger.warning("Failed to load dummy_video_mp4.txt template — video probe will not work")
    return b64


_DUMMY_MP4_B64: str = _load_dummy_mp4_b64()

# 按 cache_key 串行化探查请求，防止多 session 同时探查同一 model+base_url
_probe_locks: dict[str, asyncio.Lock] = {}


# ---------------------------------------------------------------------------
# 多模态 content block 构造（供探针/转发与 tool result 转换共用）
# ---------------------------------------------------------------------------

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


def build_video_content_blocks(video: dict, text_payload: str) -> list[MessageBlock]:
    """构造 OpenAI 格式的 video_url + text content blocks。"""
    b64: str = str(video.get("base64", ""))
    mime: str = str(video.get("mime_type", "video/mp4"))
    if not b64:
        return [TextBlock(text=text_payload)]
    return [
        VideoBlock(video_url=f"data:{mime};base64,{b64}"),
        TextBlock(text=text_payload),
    ]


# ---------------------------------------------------------------------------
# 活跃模型解析 / 转发借用
# ---------------------------------------------------------------------------

# ── 转发描述特殊标签 ──
# 标签常量定义于 entity/constant.py，此处提供按 media_type 查找标签的映射与包裹函数，
# 供 preprocess（entry 层）与 Read 工具（component 层）共用，保证两条转发路径产出的
# 描述都以同一种标签包裹。
_FORWARDED_TAG_BY_MEDIA: dict[str, str] = {
    "image": FORWARDED_VISION_TAG,
    "audio": FORWARDED_AUDIO_TAG,
    "video": FORWARDED_VIDEO_TAG,
}


def forwarded_tag_for_media(media_type: str) -> str | None:
    """按 media_type 返回对应的转发描述标签名；未知模态返回 None。"""
    return _FORWARDED_TAG_BY_MEDIA.get(media_type)


def wrap_forwarded_description(description: str, tag: str | None) -> str:
    """用特殊标签包裹转发描述文本，供活跃模型识别转发来源。

    tag 为 None 或空串时原样返回（未知模态不包裹）。
    """
    if not tag:
        return description
    return f"<{tag}>\n{description}\n</{tag}>"


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

    从 context.llm_profile 获取当前 agent 的 LLM 配置（由 ToolExecutor 注入）。
    若为 None 则表示使用启动配置。

    Returns:
        (model_name, base_url, profile_or_None)
        - profile 非空时包含活跃配置，可直接传给 create_llm_client
        - profile 为 None 表示使用启动配置
    """
    profile: LLMProfile | None = None
    if context is not None:
        profile = context.llm_profile

    if profile:
        return profile.model or "", profile.base_url or "", profile

    # 无 active profile — 探针返回不可用而非尝试建 client
    return "", "", None


async def forward_modality_to_ref_profile(
    context: ToolContext | None,
    active_profile: LLMProfile,
    media_data: dict,
    media_type: str,
) -> str:
    """转发多模态内容到被引用 profile 对应的模型，返回描述文本。

    成功返回被引用模型的描述文本；失败返回错误信息+提示词模板包装。
    供 Read 工具在活跃模型 tool+user 都不支持该模态时调用。

    Args:
        context: 工具执行上下文，用于获取 runtime_context.agentspace
        active_profile: 当前活跃的 LLMProfile（含 vision_image_profile/audio_profile/vision_video_profile 引用字段）
        media_data: 多模态数据 dict：
            - 图片: {"base64": str, "mime_type": str}
            - 音频: {"base64": str, "format": str}
            - 视频: {"base64": str, "mime_type": str}
        media_type: "image" 或 "audio" 或 "video"

    Returns:
        描述文本字符串（成功=模型描述，失败=错误信息+提示词模板）
    """
    from system.templates import read_template

    def _error_text(ref_profile_name: str, error_message: str) -> str:
        """构造转发错误文本（从模板加载并填充占位符）。"""
        return (
            read_template("forwarded/forwarded_error_template.txt")
            .replace("{{media_type}}", media_type)
            .replace("{{ref_profile_name}}", ref_profile_name)
            .replace("{{error_message}}", error_message)
        )

    # 按 media_type 显式取得根对象中的引用实例，不使用反射。
    if media_type == "image":
        ref_profile = active_profile.vision_image_profile
    elif media_type == "audio":
        ref_profile = active_profile.audio_profile
    else:  # video
        ref_profile = active_profile.vision_video_profile
    if ref_profile is None:
        return _error_text(
            "(not configured)",
            f"Active profile has no {media_type} reference profile configured",
        )

    ctx = context.runtime_context if context is not None else get_runtime_context()
    if not ref_profile.llm_client_name:
        return _error_text(
            ref_profile.name,
            f"Referenced profile '{ref_profile.name}' has no llm_client_name",
        )

    # 构造提示词（从模板加载）
    if media_type == "image":
        prompt: str = read_template("forwarded/forwarded_image_prompt.txt")
    elif media_type == "audio":
        prompt = read_template("forwarded/forwarded_audio_prompt.txt")
    else:
        prompt = read_template("forwarded/forwarded_video_prompt.txt")

    # 构造多模态块
    if media_type == "image":
        blocks = build_image_content_blocks(media_data, prompt)
    elif media_type == "audio":
        blocks = build_audio_content_blocks(media_data, prompt)
    else:
        blocks = build_video_content_blocks(media_data, prompt)

    # 构造单条 user 消息
    messages = [BaseMessage(role=Role.USER, content=blocks)]

    # 建客户端并发送
    try:
        client = create_llm_client(ref_profile.llm_client_name, ctx, ref_profile)
        response = await client.chat(messages)
        description: str = response.content or ""
        if not description.strip():
            return _error_text(
                ref_profile.name,
                f"Referenced profile '{ref_profile.name}' returned an empty description",
            )
        logger.info(
            "forward_modality | session=%s ref_profile=%s media_type=%s success",
            context.session_id if context else "", ref_profile.name, media_type,
        )
        return description
    except Exception as exc:
        logger.warning(
            "forward_modality | session=%s ref_profile=%s media_type=%s error=%s",
            context.session_id if context else "", ref_profile.name, media_type, exc,
        )
        return _error_text(ref_profile.name, f"{type(exc).__name__}: {exc}")


# ---------------------------------------------------------------------------
# 能力缓存（easysave，类型保留）
# ---------------------------------------------------------------------------

def _cache_key(model: str, base_url: str | None = None) -> str:
    """缓存键按 模型名 + 服务商（base_url） 联合索引。

    同一模型在不同服务商上的 tool 消息多模态能力可能不同（图像 token 无"出身"概念，
    工具调用无法使用多模态大概率是提供商网关的问题），只按模型名索引会在不同
    服务商间互相污染缓存。
    """
    return f"{model.lower()}@{_resolve_base_url(base_url)}"


def _cache_path() -> Path:
    return get_runtime_context().workspace / MODALITY_CAPABILITY_ES_FILENAME


def _load_cache() -> dict[str, ModalityCapability]:
    """加载 easysave 缓存（dict[cache_key, ModalityCapability]，类型保留）。

    easysave 直接重建 ModalityCapability 实例，无需再做 model_validate。
    文件缺失/无 key/损坏时返回空 dict（缓存可丢弃，缺失时重新探测）。
    """
    path = _cache_path()
    try:
        raw = es_load(MODALITY_CAPABILITY_ES_KEY, str(path))
    except (FileNotFoundError, KeyError):
        return {}
    except Exception:
        logger.warning("Failed to load modality capability cache", exc_info=True)
        return {}
    if not isinstance(raw, dict):
        logger.warning("Modality capability cache in %s is not a dict: %s", path, type(raw))
        return {}
    return raw


def _save_cache(data: dict[str, ModalityCapability]) -> None:
    """经 easysave 直接持久化 dict[cache_key, ModalityCapability]。

    直接传 ModalityCapability 实例，由 easysave 保留类型（type_token），
    不做 model_dump() 降级。easysave.save 需先读取既有文件，文件损坏时
    删除后重试一次（保持缓存自愈能力）。
    """
    path = _cache_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        es_save(MODALITY_CAPABILITY_ES_KEY, str(path), data)
    except Exception:
        try:
            path.unlink(missing_ok=True)
            es_save(MODALITY_CAPABILITY_ES_KEY, str(path), data)
        except Exception as exc:
            logger.warning("Failed to save modality capability cache: %s", exc)


def _get_cached_field(model: str, base_url: str | None, field: str) -> bool | None:
    """读取指定 model+base_url 条目的单个能力字段；未命中/未探测返回 None。"""
    entry = _load_cache().get(_cache_key(model, base_url))
    if entry is None:
        return None
    return getattr(entry, field)


def get_cached_vision_support(model: str, base_url: str | None = None) -> bool | None:
    """读取模型在指定服务商下的 vision（tool 消息图片）能力缓存；未命中返回 None。"""
    return _get_cached_field(model, base_url, "vision")


def get_cached_audio_support(model: str, base_url: str | None = None) -> bool | None:
    """读取模型在指定服务商下的 audio（tool 消息音频）能力缓存；未命中返回 None。"""
    return _get_cached_field(model, base_url, "audio")


def get_cached_user_vision_support(model: str, base_url: str | None = None) -> bool | None:
    """读取模型在指定服务商下的 user 消息 vision 能力缓存；未命中返回 None。"""
    return _get_cached_field(model, base_url, "user_vision")


def get_cached_user_audio_support(model: str, base_url: str | None = None) -> bool | None:
    """读取模型在指定服务商下的 user 消息 audio 能力缓存；未命中返回 None。"""
    return _get_cached_field(model, base_url, "user_audio")


def get_cached_video_support(model: str, base_url: str | None = None) -> bool | None:
    """读取模型在指定服务商下的 video（tool 消息视频）能力缓存；未命中返回 None。"""
    return _get_cached_field(model, base_url, "video")


def get_cached_user_video_support(model: str, base_url: str | None = None) -> bool | None:
    """读取模型在指定服务商下的 user 消息 video 能力缓存；未命中返回 None。"""
    return _get_cached_field(model, base_url, "user_video")


def _is_complete(entry: ModalityCapability | None) -> TypeGuard[ModalityCapability]:
    """六项能力是否全部探测完成（可安全命中缓存，跳过 API 请求）。"""
    return (
        entry is not None
        and entry.vision is not None
        and entry.audio is not None
        and entry.user_vision is not None
        and entry.user_audio is not None
        and entry.video is not None
        and entry.user_video is not None
    )


# ---------------------------------------------------------------------------
# 探测消息构造与单路探测
# ---------------------------------------------------------------------------

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


def _build_modality_blocks(modality: str) -> list[MessageBlock]:
    """按模态构造探测用 content block 列表（dummy 载荷 + 伪 path 元数据）。"""
    if modality == "vision":
        return [
            ImageBlock(image_url=f"data:image/png;base64,{_DUMMY_PNG_B64}"),
            TextBlock(text='{"path": "probe://image.png", "width": 1, "height": 1}'),
        ]
    if modality == "audio":
        return [
            AudioBlock(data=_DUMMY_WAV_B64, format="wav"),
            TextBlock(text='{"path": "probe://audio.wav"}'),
        ]
    # video
    return [
        VideoBlock(video_url=f"data:video/mp4;base64,{_DUMMY_MP4_B64}"),
        TextBlock(text='{"path": "probe://video.mp4"}'),
    ]


async def _probe_single_modality(
    client: BaseLLMClient,
    model_name: str,
    session_id: str,
    modality: str,
) -> bool:
    """伪装成工具调用单独探测一种模态，返回该模态在工具消息中是否可用。"""
    probe_messages = _build_tool_probe_messages(_build_modality_blocks(modality))

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
    client: BaseLLMClient,
    model_name: str,
    session_id: str,
    modality: str,
) -> bool:
    """发送普通 user 消息单独探测一种模态，返回该模态在 user 消息中是否可用。"""
    probe_messages = _build_user_probe_messages(_build_modality_blocks(modality))

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


# ---------------------------------------------------------------------------
# 探测入口
# ---------------------------------------------------------------------------

async def run_modality_probe(
    context: ToolContext | None,
) -> ModalityCapability:
    """执行一次完整的多模态能力探测，返回 ModalityCapability（六项全非 None）。

    缓存命中（六项完整）时直接返回；否则创建 client，按 模态 × 消息路径
    （tool/user）六路并发探测。非 400 错误（网络/认证/超时）向上抛出异常，
    不写缓存。按 cache_key 串行化（asyncio.Lock），防止多 session 重复探测。

    Raises:
        RuntimeError: 无 active profile 或无 llm_client_name。
        Exception: 探测过程中的非模态错误（网络、认证、超时等），向上抛出。
    """
    ctx = context.runtime_context if context is not None else get_runtime_context()
    session_id = context.session_id if context is not None else ""
    model_name, base_url, profile = resolve_active_model_base_url(context)

    key = _cache_key(model_name, base_url)

    # 缓存命中检查：如果六项都已探测，直接返回缓存值，跳过 API 请求
    cached = _load_cache().get(key)
    if _is_complete(cached):
        logger.info(
            "probe_modality | session=%s model=%s cache_hit, skipping API probe",
            session_id, model_name,
        )
        return cached

    # 按 cache_key 串行化，防止多 session 同时探查同一 model+base_url
    lock = _probe_locks.get(key)
    if lock is None:
        lock = asyncio.Lock()
        _probe_locks[key] = lock
    async with lock:
        # 双检缓存：等待期间可能已被其他请求写入
        cache = _load_cache()
        cached = cache.get(key)
        if _is_complete(cached):
            logger.info(
                "probe_modality | session=%s model=%s cache_hit (after lock), skipping API probe",
                session_id, model_name,
            )
            return cached

        client_name = profile.llm_client_name if profile else ""
        if not client_name:
            raise RuntimeError(
                f"No active LLM profile or llm_client_name — cannot probe modality capability "
                f"(model={model_name})."
            )
        client = create_llm_client(client_name, ctx, profile)

        # 直接按 模态 × 消息路径（tool/user）六路并发探测，不做组合探测：
        # 全模态（三模态全支持）的模型+厂商极少，组合探测几乎必然失败、
        # 白白多一次请求后才回退分别探测，因此首次即分别并发探测。
        results = await asyncio.gather(
            _probe_single_modality(client, model_name, session_id, "vision"),
            _probe_single_modality(client, model_name, session_id, "audio"),
            _probe_single_modality(client, model_name, session_id, "video"),
            _probe_single_user_modality(client, model_name, session_id, "vision"),
            _probe_single_user_modality(client, model_name, session_id, "audio"),
            _probe_single_user_modality(client, model_name, session_id, "video"),
            return_exceptions=True,
        )
        # 单路探针仅对 400/模态拒绝返回 False；此处出现的异常必为非模态错误
        # （网络/认证/超时等），不写缓存，向上抛出
        probed: list[bool] = []
        for item in results:
            if isinstance(item, BaseException):
                raise item
            probed.append(item)

        result = ModalityCapability(
            vision=probed[0],
            audio=probed[1],
            video=probed[2],
            user_vision=probed[3],
            user_audio=probed[4],
            user_video=probed[5],
        )
        cache[key] = result
        _save_cache(cache)
        logger.info(
            "probe_modality | session=%s model=%s vision=%s audio=%s video=%s "
            "user_vision=%s user_audio=%s user_video=%s source=concurrent_probe",
            session_id, model_name,
            probed[0], probed[1], probed[2], probed[3], probed[4], probed[5],
        )
        return result


async def ensure_modality_capability(
    context: ToolContext | None,
) -> ModalityCapability:
    """确保当前活跃模型的多模态能力已探测。有缓存读缓存，无缓存自动探查。

    Returns:
        ModalityCapability（六项全非 None）

    Raises:
        Exception: 探测过程中的非模态错误（网络/认证/超时），向上抛出。
    """
    return await run_modality_probe(context)


# ---------------------------------------------------------------------------
# 系统提示词注入块
# ---------------------------------------------------------------------------

def _fmt_support(value: bool | None) -> str:
    """格式化单条能力探测结果，供系统提示词展示。"""
    if value is None:
        return "unknown (auto-probed on first use)"
    return "supported" if value else "NOT supported"


def build_modality_prompt_block(
    profile: LLMProfile,
    agentspace: Path | None = None,
) -> str:
    """构建系统提示词的多模态能力与转发配置块（每轮实时生成）。

    文案来自模板 ``templates/modality_capability.txt``，本函数只负责填值：
    - 能力部分只读探测缓存（不触发探测），未探测项显示 unknown。
      单次读取整个条目，避免 get_cached_* 逐字段重读缓存文件。
    - 转发部分直接读取三个引用实例的名称与模型。

    profile 无 model 或模板缺失时返回空串（不注入）。
    """
    if not profile.model:
        return ""

    from system.templates import read_template
    template = read_template("modality_capability.txt")
    if not template:
        return ""

    # 能力值：单次读取整个条目，避免 get_cached_* 逐字段重读缓存文件
    entry = _load_cache().get(_cache_key(profile.model, profile.base_url))
    if entry is None:
        image_tool = image_user = _fmt_support(None)
        audio_tool = audio_user = _fmt_support(None)
        video_tool = video_user = _fmt_support(None)
    else:
        image_tool, image_user = _fmt_support(entry.vision), _fmt_support(entry.user_vision)
        audio_tool, audio_user = _fmt_support(entry.audio), _fmt_support(entry.user_audio)
        video_tool, video_user = _fmt_support(entry.video), _fmt_support(entry.user_video)

    def _ref(reference: LLMProfile | None) -> str:
        if reference is None:
            return "not configured"
        return f'"{reference.name}" (model ``{reference.model}``)'

    replacements = {
        "{{model}}": profile.model,
        "{{image_tool}}": image_tool,
        "{{image_user}}": image_user,
        "{{audio_tool}}": audio_tool,
        "{{audio_user}}": audio_user,
        "{{video_tool}}": video_tool,
        "{{video_user}}": video_user,
        "{{image_ref}}": _ref(profile.vision_image_profile),
        "{{audio_ref}}": _ref(profile.audio_profile),
        "{{video_ref}}": _ref(profile.vision_video_profile),
    }
    for placeholder, value in replacements.items():
        template = template.replace(placeholder, value)
    return template