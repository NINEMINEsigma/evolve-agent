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
from typing import TYPE_CHECKING, Literal, TypeGuard
from collections.abc import Iterator
from contextlib import contextmanager

from framework import AsyncSystem
from system.runtime import RuntimeSystem
from system.llm_profile_store import LLMProfileStore
from system.lifecycle import (
    ApplicationStoppingError, LifecycleFailure, TaskOwner, requires_lifecycle_propagation,
)
from entity.constant import SYSTEM_QUIESCE_TIMEOUT_SECONDS

from easysave import load as es_load, save as es_save

from abstract.llm.loader import create_llm_client
from entity.constant import (
    FORWARDED_AUDIO_TAG,
    FORWARDED_VISION_TAG,
    FORWARDED_VIDEO_TAG,
    MODALITY_CAPABILITY_ES_FILENAME,
    MODALITY_CAPABILITY_ES_KEY,
)
from entity.puretype import Role, ModalityCapability, LLMProfile, LLMProfileData
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
from abstract.llm.client import BaseLLMClient, UnsupportedModalityError

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


def _load_dummy_mp4_b64() -> str:
    """从模板文件加载 dummy MP4 的 base64。

    使用 ffmpeg 生成的 2 秒 320x240 黑屏 MP4（2024 字节），
    经 API 验证可被接受。不能用更小的 MP4——部分 provider 对极短视频
    返回 400 "Invalid request parameters"。
    """
    from system.templates import read_template
    b64 = read_template("probe/dummy_video_mp4.txt")
    if not b64:
        raise ValueError("The video probe template is empty")
    return b64


# ---------------------------------------------------------------------------
# 多模态 content block 构造（供探针/转发与 tool result 转换共用）
# ---------------------------------------------------------------------------

def build_media_content_block(
    media_data: dict,
    media_type: str,
) -> MessageBlock | None:
    """构造单个多模态内容块，不附加文本提示词。

    调用方掌握音频 MIME 映射时应传入规范 ``format``；仅在缺少
    ``format`` 时从 ``mime_type`` 提取后缀作为兼容回退。
    """
    if media_type not in ("image", "audio", "video"):
        raise ValueError(f"Unsupported media_type: {media_type}")
    b64: str = str(media_data.get("base64", ""))
    if not b64:
        return None

    if media_type == "image":
        mime: str = str(media_data.get("mime_type", "image/png"))
        return ImageBlock(image_url=f"data:{mime};base64,{b64}")
    if media_type == "audio":
        fmt: str = str(media_data.get("format", ""))
        if not fmt:
            fmt = str(media_data.get("mime_type", "wav"))
            if "/" in fmt:
                fmt = fmt.rsplit("/", 1)[-1]
        return AudioBlock(data=b64, format=fmt)
    if media_type == "video":
        mime = str(media_data.get("mime_type", "video/mp4"))
        return VideoBlock(video_url=f"data:{mime};base64,{b64}")


def build_image_content_blocks(image: dict, text_payload: str) -> list[MessageBlock]:
    """构造 OpenAI 格式的 image_url + text content blocks。"""
    media_block = build_media_content_block(image, "image")
    if media_block is None:
        return [TextBlock(text=text_payload)]
    return [media_block, TextBlock(text=text_payload)]


def build_audio_content_blocks(audio: dict, text_payload: str) -> list[MessageBlock]:
    """构造 OpenAI 格式的 input_audio + text content blocks。"""
    media_block = build_media_content_block(audio, "audio")
    if media_block is None:
        return [TextBlock(text=text_payload)]
    return [media_block, TextBlock(text=text_payload)]


def build_video_content_blocks(video: dict, text_payload: str) -> list[MessageBlock]:
    """构造 OpenAI 格式的 video_url + text content blocks。"""
    media_block = build_media_content_block(video, "video")
    if media_block is None:
        return [TextBlock(text=text_payload)]
    return [media_block, TextBlock(text=text_payload)]


# ---------------------------------------------------------------------------
# 活跃模型解析 / 转发借用
# ---------------------------------------------------------------------------


def forwarded_tag_for_media(media_type: str) -> str | None:
    """按 media_type 返回对应的转发描述标签名；未知模态返回 None。"""
    return {
        "image": FORWARDED_VISION_TAG,
        "audio": FORWARDED_AUDIO_TAG,
        "video": FORWARDED_VIDEO_TAG,
        }.get(media_type)


def wrap_forwarded_description(description: str, tag: str | None) -> str:
    """用特殊标签包裹转发描述文本，供活跃模型识别转发来源。

    tag 为 None 或空串时原样返回（未知模态不包裹）。
    """
    if not tag:
        return description
    return f"<{tag}>\n{description}\n</{tag}>"


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
        return profile.model, profile.base_url, profile

    # 无 active profile — 探针返回不可用而非尝试建 client
    return "", "", None


def resolve_modality_reference_profile(
    active_profile: LLMProfile,
    media_type: Literal["image", "audio", "video"],
    profile_data: LLMProfileData,
) -> LLMProfile | None:
    """解析指定媒体的有效转发 Profile（纯函数，不访问 Application 单例）。

    活动 Profile 的显式引用优先；活动引用为空时从 ``LLMProfileData``
    按媒体类型取全局回退引用。``profile_data`` 由调用方注入，
    传入 ``LLMProfileData()`` 空实例即表示「无全局回退」。
    """
    if media_type == "image":
        active_reference = active_profile.vision_image_profile
        global_reference = profile_data.global_vision_image_profile
    elif media_type == "audio":
        active_reference = active_profile.audio_profile
        global_reference = profile_data.global_audio_profile
    else:
        active_reference = active_profile.vision_video_profile
        global_reference = profile_data.global_vision_video_profile
    return active_reference if active_reference is not None else global_reference


async def _forward_modality_to_ref_profile(
    system: ModalityCapabilitySystem,
    context: ToolContext | None,
    active_profile: LLMProfile,
    media_data: dict,
    media_type: Literal["image", "audio", "video"],
) -> str:
    """转发多模态内容到有效引用 Profile 对应的模型，返回描述文本。

    活动 Profile 的对应引用优先；活动引用为空时使用全局多模态回退引用。
    未配置有效引用属于调用方契约错误，调用方应在进入本函数前处理。

    Args:
        context: 工具执行上下文，用于获取 runtime_context 和全局 Profile 引用
        active_profile: 当前活跃的 LLMProfile
        media_data: 多模态数据 dict：
            - 图片: {"base64": str, "mime_type": str}
            - 音频: {"base64": str, "format": str}
            - 视频: {"base64": str, "mime_type": str}
        media_type: "image"、"audio" 或 "video"

    Returns:
        被引用模型返回的描述文本
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

    ref_profile = system.resolve_effective_modality_reference_profile(
        active_profile,
        media_type,
    )
    if ref_profile is None:
        raise ValueError(
            f"No active or global reference profile configured for {media_type}"
        )

    ctx = system.runtime.context
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

    # 建客户端；客户端创建异常属于配置/程序错误，不能伪装成转发结果。
    client = create_llm_client(ref_profile.llm_client_name, ctx, ref_profile)
    try:
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
    except UnsupportedModalityError as exc:
        logger.warning(
            "forward_modality unsupported | session=%s ref_profile=%s media_type=%s error=%s",
            context.session_id if context else "", ref_profile.name, media_type, exc,
        )
        raise
    except Exception as exc:
        if requires_lifecycle_propagation(exc):
            raise
        import openai as _openai
        if not isinstance(exc, _openai.BadRequestError) and not (
            isinstance(exc, _openai.APIStatusError)
            and exc.status_code == 400
        ):
            raise
        logger.warning(
            "forward_modality | session=%s ref_profile=%s media_type=%s error=%s",
            context.session_id if context else "", ref_profile.name, media_type, exc,
        )
        return _error_text(ref_profile.name, f"{type(exc).__name__}: {exc}")


# ---------------------------------------------------------------------------
# 能力缓存（easysave，类型保留）
# ---------------------------------------------------------------------------

def _cache_key(model: str, base_url: str) -> str:
    """缓存键按 模型名 + 服务商（base_url） 联合索引。

    同一模型在不同服务商上的 tool 消息多模态能力可能不同（图像 token 无"出身"概念，
    工具调用无法使用多模态大概率是提供商网关的问题），只按模型名索引会在不同
    服务商间互相污染缓存。
    """
    return f"{model.lower()}@{base_url}"


def _load_cache(path: Path) -> dict[str, ModalityCapability]:
    """加载 easysave 缓存（dict[cache_key, ModalityCapability]，类型保留）。

    easysave 直接重建 ModalityCapability 实例，无需再做 model_validate。
    文件缺失/无 key/损坏时返回空 dict（缓存可丢弃，缺失时重新探测）。
    """
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


def _save_cache(path: Path, data: dict[str, ModalityCapability]) -> None:
    """经 easysave 直接持久化 dict[cache_key, ModalityCapability]。

    直接传 ModalityCapability 实例，由 easysave 保留类型（type_token），
    不做 model_dump() 降级。easysave.save 需先读取既有文件，文件损坏时
    删除后重试一次（保持缓存自愈能力）。
    """
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        es_save(MODALITY_CAPABILITY_ES_KEY, str(path), data)
    except Exception:
        try:
            path.unlink(missing_ok=True)
            es_save(MODALITY_CAPABILITY_ES_KEY, str(path), data)
        except Exception as exc:
            logger.warning("Failed to save modality capability cache: %s", exc)


class ModalityCapabilitySystem(AsyncSystem):
    """多模态探测锁、探针媒体、缓存路径与请求的唯一所有者。"""

    def __init__(self) -> None:
        super().__init__(dependencies=(RuntimeSystem, LLMProfileStore))
        self._runtime: RuntimeSystem | None = None
        self._profiles: LLMProfileStore | None = None
        self._owner: TaskOwner | None = None
        self._cache_file: Path | None = None
        self._probe_locks: dict[str, asyncio.Lock] = {}
        self._wav = ""
        self._mp4 = ""
        self._closed = False

    async def virtual_awake(self) -> None:
        self._runtime = self.get_system(RuntimeSystem)
        self._profiles = self.get_system(LLMProfileStore)
        self._owner = TaskOwner("modality-capability", self.runtime.record_failure)
        self._cache_file = self.runtime.context.workspace / MODALITY_CAPABILITY_ES_FILENAME
        self._wav = _generate_dummy_wav_b64()
        self._mp4 = _load_dummy_mp4_b64()

    @property
    def runtime(self) -> RuntimeSystem:
        if self._runtime is None:
            raise LifecycleFailure("ModalityCapabilitySystem has not been awakened")
        return self._runtime

    @property
    def task_owner(self) -> TaskOwner:
        if self._owner is None:
            raise LifecycleFailure("ModalityCapabilitySystem has not been awakened")
        return self._owner

    @property
    def cache_path(self) -> Path:
        if self._cache_file is None:
            raise LifecycleFailure("Modality cache path has not been initialized")
        return self._cache_file

    @contextmanager
    def _admit(self) -> Iterator[None]:
        with self.runtime.admission():
            if self._closed:
                raise ApplicationStoppingError("Modality requests have closed")
            yield

    def close_admission(self) -> None:
        self._closed = True

    async def cancel_pending(self) -> None:
        self.close_admission()
        await self.task_owner.cancel_and_wait(timeout=SYSTEM_QUIESCE_TIMEOUT_SECONDS)

    async def virtual_shotdown(self) -> None:
        await self.cancel_pending()
        self._probe_locks.clear()
        self._wav = self._mp4 = ""

    def probe_lock(self, key: str) -> asyncio.Lock:
        lock = self._probe_locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            self._probe_locks[key] = lock
        return lock

    def modality_blocks(self, modality: str) -> list[MessageBlock]:
        return _build_modality_blocks(modality, self._wav, self._mp4)

    def resolve_effective_modality_reference_profile(
        self, active_profile: LLMProfile, media_type: Literal["image", "audio", "video"],
    ) -> LLMProfile | None:
        profiles = self._profiles
        if profiles is None:
            raise LifecycleFailure("Modality Profile store has not been initialized")
        with profiles.locked():
            return resolve_modality_reference_profile(active_profile, media_type, profiles.get_data())

    def _get_cached_capability(self, model: str, base_url: str) -> ModalityCapability | None:
        return _load_cache(self.cache_path).get(_cache_key(model, base_url))

    def get_cached_vision_support(self, model: str, base_url: str) -> bool | None:
        entry = self._get_cached_capability(model, base_url)
        return entry.vision if entry is not None else None

    def get_cached_audio_support(self, model: str, base_url: str) -> bool | None:
        entry = self._get_cached_capability(model, base_url)
        return entry.audio if entry is not None else None

    def get_cached_user_vision_support(self, model: str, base_url: str) -> bool | None:
        entry = self._get_cached_capability(model, base_url)
        return entry.user_vision if entry is not None else None

    def get_cached_user_audio_support(self, model: str, base_url: str) -> bool | None:
        entry = self._get_cached_capability(model, base_url)
        return entry.user_audio if entry is not None else None

    def get_cached_video_support(self, model: str, base_url: str) -> bool | None:
        entry = self._get_cached_capability(model, base_url)
        return entry.video if entry is not None else None

    def get_cached_user_video_support(self, model: str, base_url: str) -> bool | None:
        entry = self._get_cached_capability(model, base_url)
        return entry.user_video if entry is not None else None

    async def run_modality_probe(self, context: ToolContext | None) -> ModalityCapability:
        return await self.task_owner.run_request(
            lambda: _run_modality_probe(self, context), name="modality-probe", admission=self._admit,
        )

    async def ensure_modality_capability(self, context: ToolContext | None) -> ModalityCapability:
        return await self.run_modality_probe(context)

    async def forward_modality_to_ref_profile(
        self, context: ToolContext | None, active_profile: LLMProfile,
        media_data: dict, media_type: Literal["image", "audio", "video"],
    ) -> str:
        return await self.task_owner.run_request(
            lambda: _forward_modality_to_ref_profile(self, context, active_profile, media_data, media_type),
            name="modality-forward", admission=self._admit,
        )

    def build_modality_prompt_block(self, profile: LLMProfile, agentspace: Path | None = None) -> str:
        return _build_modality_prompt_block(self, profile, agentspace)


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


def _build_modality_blocks(modality: str, wav: str, mp4: str) -> list[MessageBlock]:
    """按模态构造探测用 content block 列表（dummy 载荷 + 伪 path 元数据）。"""
    if modality == "vision":
        return [
            ImageBlock(image_url=f"data:image/png;base64,{_DUMMY_PNG_B64}"),
            TextBlock(text='{"path": "probe://image.png", "width": 1, "height": 1}'),
        ]
    if modality == "audio":
        return [
            AudioBlock(data=wav, format="wav"),
            TextBlock(text='{"path": "probe://audio.wav"}'),
        ]
    # video
    return [
        VideoBlock(video_url=f"data:video/mp4;base64,{mp4}"),
        TextBlock(text='{"path": "probe://video.mp4"}'),
    ]


async def _probe_single_modality(
    system: ModalityCapabilitySystem,
    client: BaseLLMClient,
    model_name: str,
    session_id: str,
    modality: str,
) -> bool:
    """伪装成工具调用单独探测一种模态，返回该模态在工具消息中是否可用。"""
    probe_messages = _build_tool_probe_messages(system.modality_blocks(modality))

    try:
        system.runtime.require_running()
        await client.chat(probe_messages)
        logger.info(
            "probe_modality | session=%s model=%s %s=True source=single_probe(tool)",
            session_id, model_name, modality,
        )
        return True
    except Exception as exc:
        if requires_lifecycle_propagation(exc):
            raise
        if isinstance(exc, UnsupportedModalityError):
            logger.info(
                "probe_modality | session=%s model=%s %s=False source=single_probe(tool) reason=unsupported_modality",
                session_id, model_name, modality,
            )
            return False
        # TODO: 错误的提前依赖第三方库, 实际上根本就不一定使用openai库来使用openai协议
        import openai as _openai
        # 400 错误（无论是否匹配 modality 关键词）都判定为该模态在工具消息中不可用。
        # 某些 provider 返回通用的 "Invalid request parameters" / "Upstream request failed"
        # 而非明确的 "unsupported content" 消息，此时乐观默认 True 会导致能力误判。
        if isinstance(exc, _openai.APIStatusError) and exc.status_code == 400:
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
    system: ModalityCapabilitySystem,
    client: BaseLLMClient,
    model_name: str,
    session_id: str,
    modality: str,
) -> bool:
    """发送普通 user 消息单独探测一种模态，返回该模态在 user 消息中是否可用。"""
    probe_messages = _build_user_probe_messages(system.modality_blocks(modality))

    try:
        system.runtime.require_running()
        await client.chat(probe_messages)
        logger.info(
            "probe_modality | session=%s model=%s %s=True source=single_probe(user)",
            session_id, model_name, modality,
        )
        return True
    except Exception as exc:
        if requires_lifecycle_propagation(exc):
            raise
        if isinstance(exc, UnsupportedModalityError):
            logger.info(
                "probe_modality | session=%s model=%s %s=False source=single_probe(user) reason=unsupported_modality",
                session_id, model_name, modality,
            )
            return False
        import openai as _openai
        if isinstance(exc, _openai.APIStatusError) and exc.status_code == 400:
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

async def _run_modality_probe(
    system: ModalityCapabilitySystem,
    context: ToolContext | None,
) -> ModalityCapability:
    """执行一次完整的多模态能力探测，返回 ModalityCapability（六项全非 None）。

    缓存命中（六项完整）时直接返回；否则创建 client，按 模态 × 消息路径
    （tool/user）六路并发探测。客户端明确不支持该模态或 HTTP 模态拒绝返回 False；
    网络/认证/超时等错误向上抛出且不写缓存。按 cache_key 串行化（asyncio.Lock），防止多 session 重复探测。

    Raises:
        RuntimeError: 无 active profile 或无 llm_client_name。
        Exception: 探测过程中的非模态错误（网络、认证、超时等），向上抛出。
    """
    ctx = system.runtime.context
    session_id = context.session_id if context is not None else ""
    model_name, base_url, profile = resolve_active_model_base_url(context)

    key = _cache_key(model_name, base_url)

    # 缓存命中检查：如果六项都已探测，直接返回缓存值，跳过 API 请求
    cached = _load_cache(system.cache_path).get(key)
    if _is_complete(cached):
        logger.info(
            "probe_modality | session=%s model=%s cache_hit, skipping API probe",
            session_id, model_name,
        )
        return cached

    # 按 cache_key 串行化，防止多 session 同时探查同一 model+base_url
    async with system.probe_lock(key):
        system.runtime.require_running()
        # 双检缓存：等待期间可能已被其他请求写入
        cache = _load_cache(system.cache_path)
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
        # TaskGroup 持有并等待全部子探针；失败/取消时先完成子任务清理，
        # 再向完整请求传播异常组，不能留下仍调用模型的孤儿探针。
        async with asyncio.TaskGroup() as group:
            probes = [
                group.create_task(_probe_single_modality(system, client, model_name, session_id, "vision")),
                group.create_task(_probe_single_modality(system, client, model_name, session_id, "audio")),
                group.create_task(_probe_single_modality(system, client, model_name, session_id, "video")),
                group.create_task(_probe_single_user_modality(system, client, model_name, session_id, "vision")),
                group.create_task(_probe_single_user_modality(system, client, model_name, session_id, "audio")),
                group.create_task(_probe_single_user_modality(system, client, model_name, session_id, "video")),
            ]
        probed = [probe.result() for probe in probes]

        result = ModalityCapability(
            vision=probed[0],
            audio=probed[1],
            video=probed[2],
            user_vision=probed[3],
            user_audio=probed[4],
            user_video=probed[5],
        )
        # 不同模型键并发时重新读取最新根，避免覆盖另一路已保存能力。
        cache = _load_cache(system.cache_path)
        cache[key] = result
        _save_cache(system.cache_path, cache)
        logger.info(
            "probe_modality | session=%s model=%s vision=%s audio=%s video=%s "
            "user_vision=%s user_audio=%s user_video=%s source=concurrent_probe",
            session_id, model_name,
            probed[0], probed[1], probed[2], probed[3], probed[4], probed[5],
        )
        return result


# ---------------------------------------------------------------------------
# 系统提示词注入块
# ---------------------------------------------------------------------------

def _fmt_support(value: bool | None) -> str:
    """格式化单条能力探测结果，供系统提示词展示。"""
    if value is None:
        return "unknown (auto-probed on first use)"
    return "supported" if value else "NOT supported"


def _build_modality_prompt_block(
    system: ModalityCapabilitySystem,
    profile: LLMProfile,
    agentspace: Path | None = None,
) -> str:
    """构建系统提示词的多模态能力与转发配置块（每轮实时生成）。

    文案来自模板 ``templates/modality_capability.txt``，本函数只负责填值：
    - 能力部分只读探测缓存（不触发探测），未探测项显示 unknown。
      单次读取整个条目，避免 get_cached_* 逐字段重读缓存文件。
    - 转发部分按活动 Profile 引用优先、全局回退引用次之，显示三种媒体的有效目标。
      全局回退引用通过 :func:`resolve_effective_modality_reference_profile`
      从 Application 单例获取。

    profile 无 model 或模板缺失时返回空串（不注入）。
    """
    if not profile.model:
        return ""

    from system.templates import read_template
    template = read_template("modality_capability.txt")
    if not template:
        return ""

    # 能力值：单次读取整个条目，避免 get_cached_* 逐字段重读缓存文件
    entry = _load_cache(system.cache_path).get(_cache_key(profile.model, profile.base_url))
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

    image_ref = system.resolve_effective_modality_reference_profile(profile, "image")
    audio_ref = system.resolve_effective_modality_reference_profile(profile, "audio")
    video_ref = system.resolve_effective_modality_reference_profile(profile, "video")
    replacements = {
        "{{model}}": profile.model,
        "{{image_tool}}": image_tool,
        "{{image_user}}": image_user,
        "{{audio_tool}}": audio_tool,
        "{{audio_user}}": audio_user,
        "{{video_tool}}": video_tool,
        "{{video_user}}": video_user,
        "{{image_ref}}": _ref(image_ref),
        "{{audio_ref}}": _ref(audio_ref),
        "{{video_ref}}": _ref(video_ref),
    }
    for placeholder, value in replacements.items():
        template = template.replace(placeholder, value)
    return template