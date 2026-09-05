"""文件系统工具 — 所有路径均为逻辑路径（带命名空间前缀）。

模块导入时通过 ``registry.register()`` 注册。
每个工具 handler 通过 ``Application.current().sandbox`` 获取共享的 ``Sandbox`` 实例解析路径。

路径格式：``namespace:relative/path``
  - ``fork:``    读写（进化代码目标）
  - ``ws:``      读写（通用 agent 工作空间）
  - ``fix:``     读写（修复目标，仅 fallback 模式）
  - ``skills:``  读写（skill 文件目录）
  - ``third:``   只读（第三方子模块）
  - ``custom_hooks:``      只读（自定义钩子）
  - ``custom_llm_client:`` 只读（自定义 LLM 客户端）
  - ``custom_tools:``      只读（自定义工具）
"""
# TODO: _blocks构建应该具有一个公用的工厂
from __future__ import annotations

import base64
import io
import json
import logging
import mimetypes
import re
from datetime import datetime, timezone
from typing import Any, Dict, TYPE_CHECKING

from abstract.tools.registry import registry, tool_error, tool_result
from entity.puretype import ToolDangerLevel
from entity.constant import EDIT_FILE_MAX_CHARS, FILE_SNIFF_BYTES, READ_FILE_DEFAULT_LIMIT, READ_FILE_MAX_LINES, WRITE_FILE_MAX_CHARS, WRITE_FILE_TRUNCATION_TAIL
from system.sandbox import Access, Sandbox, SandboxError
from system.context import get_runtime_context
from pathlib import Path

if TYPE_CHECKING:
    from entry.base_agent_loop import ToolContext

try:
    from PIL import Image as PILImage
except Exception:  # pragma: no cover — PIL is optional
    logger = logging.getLogger(__name__)
    logger.debug("PIL not available; image size parsing disabled", exc_info=True)
    PILImage = None  # type: ignore

from system.modality_capability import get_cached_vision_support, get_cached_audio_support, get_cached_user_vision_support, get_cached_user_audio_support, get_cached_video_support, get_cached_user_video_support, resolve_active_model_base_url, forward_modality_to_ref_profile, ensure_modality_capability, wrap_forwarded_description, forwarded_tag_for_media

logger = logging.getLogger(__name__)


def _s() -> Sandbox:
    """委托到 Application.sandbox property。"""
    from system.application import Application
    return Application.current().sandbox


def _track_agentspace_access(
    context: ToolContext | None,
    paths: list[tuple[str, bool]],
) -> None:
    """登记明确的 ws: 路径；登记失败时让调用方返回工具错误。"""
    if context is None:
        return
    with context.agentspace_access(paths):
        pass


# ---------------------------------------------------------------------------
# 图片读取支持（从 read_image.py 合并）
# ---------------------------------------------------------------------------

_SUPPORTED_MIMES: set[str] = {
    "image/png",
    "image/jpeg",
    "image/webp",
    "image/gif",
    "image/bmp",
    "image/tiff",
    "image/svg+xml",
}

_MAX_IMAGE_SIZE: int = 20 * 1024 * 1024

# 音频读取支持（OpenAI input_audio 仅支持 wav 和 mp3）
_SUPPORTED_AUDIO_MIMES: set[str] = {
    "audio/wav",
    "audio/mpeg",
    "audio/mp3",
}

_MAX_AUDIO_SIZE: int = 25 * 1024 * 1024

_AUDIO_FORMAT_MAP: dict[str, str] = {
    "audio/wav": "wav",
    "audio/mpeg": "mp3",
    "audio/mp3": "mp3",
}

# 视频读取支持（OpenAI 兼容协议 video_url 扩展，Qwen-VL/vLLM 已验证）
_SUPPORTED_VIDEO_MIMES: set[str] = {
    "video/mp4",
}

_MAX_VIDEO_SIZE: int = 50 * 1024 * 1024


def _guess_mime(path: str) -> str:
    mime, _ = mimetypes.guess_type(path)
    return mime or "application/octet-stream"


def _parse_size(raw_bytes: bytes, mime_type: str) -> tuple[int | None, int | None]:
    """用 Pillow 解析图片宽高；SVG 返回 (None, None)。"""
    if mime_type == "image/svg+xml" or PILImage is None:
        return None, None
    try:
        with PILImage.open(io.BytesIO(raw_bytes)) as im:
            return im.width, im.height
    except Exception:
        logger.warning("Failed to parse image dimensions", exc_info=True)
        return None, None


# ---------------------------------------------------------------------------
# LSP diagnostics 附加（写入/编辑后自动附加）
# ---------------------------------------------------------------------------

# pyright 支持的代码文件扩展名
_LSP_CODE_EXTENSIONS: frozenset[str] = frozenset({".py"})

_LSP_DIAGNOSTICS_SETTLE_TIME: float = 0.8  # didChange 后等待 diagnostics 推送的短暂 sleep


def _try_attach_lsp_diagnostics(logical_path: str, content: str) -> list[dict] | None:
    """写入/编辑后尝试附加 LSP diagnostics。

    条件: LSP 已启动 + 文件在 LSP 根目录范围内 + 文件是 .py 代码文件。
    流程: notify_did_change → sleep → get_cached_diagnostics → 序列化。
    不满足条件或 LSP 未启动时返回 None（不附加字段）。
    """
    try:
        from system.lsp import get_lsp_manager
        manager = get_lsp_manager()
        if not manager.is_ready():
            return None
    except Exception:
        return None

    # 检查文件扩展名
    if Path(logical_path.split(":")[-1]).suffix.lower() not in _LSP_CODE_EXTENSIONS:
        return None

    # 检查文件是否在 LSP workspace 范围内
    try:
        resolved = _s().resolve_read(logical_path)
    except SandboxError:
        return None
    if not manager.is_in_workspace(resolved.real):
        return None

    # 发送 didChange 通知
    uri = resolved.real.as_uri()
    manager.notify_did_change(logical_path, content, _s())

    # 短暂等待 diagnostics 推送
    import time as _time
    _time.sleep(_LSP_DIAGNOSTICS_SETTLE_TIME)

    # 从缓存读取
    diags = manager.get_cached_diagnostics(uri)
    if not diags:
        return None
    return [d.model_dump() for d in diags]


# ---------------------------------------------------------------------------
# 工具 handler
# ---------------------------------------------------------------------------

async def _handle_read(args: dict[str, Any], context: ToolContext | None = None) -> dict:
    path: str = str(args.get("path", "")).strip()
    if not path:
        return tool_error("path is required", path=path)
    offset: int = int(args.get("offset", 0))
    limit: int = int(args.get("limit", READ_FILE_DEFAULT_LIMIT))
    if offset < 0:
        return tool_error("offset must be >= 0", path=path, offset=offset)
    if limit < 1:
        return tool_error("limit must be >= 1", path=path, limit=limit)
    if limit > READ_FILE_MAX_LINES:
        limit = READ_FILE_MAX_LINES

    # 类型探测 — resolve_read 可能抛 SandboxError，is_dir/is_file 不抛错
    try:
        resolved = _s().resolve_read(path)
    except SandboxError as exc:
        return tool_error(str(exc), path=path)

    if not resolved.real.exists():
        return tool_error("Path not found", path=path)

    # 目录分支
    if resolved.real.is_dir():
        try:
            raw: list[str] = _s().list_dir(path)
        except SandboxError as exc:
            return tool_error(str(exc), path=path)
        entries: list[str] = []
        for name in raw:
            fp = resolved.real / name
            entries.append(f"{name}/" if fp.is_dir() else name)
        return {
            "type": "directory",
            "path": path,
            "absolute_path": str(resolved.real),
            "total_lines": 0,
            "content": "",
            "remaining": 0,
            "offset": 0,
            "limit": 0,
            "entries": entries,
            "count": len(entries),
        }

    # 文件分支
    if resolved.real.is_file():
        try:
            _track_agentspace_access(context, [(path, False)])
        except Exception as exc:
            return tool_error(f"Agentspace access lock failed: {exc}", path=path)
        # --- 图片分支（MIME 自动检测，从 read_image.py 合并）---
        mime_type = _guess_mime(str(resolved.real))
        if mime_type in _SUPPORTED_MIMES:
            # vision 预检
            model_name, base_url, _profile = resolve_active_model_base_url(context)
            if not model_name:
                return tool_error(
                    "No LLM model configured; cannot determine vision capability.",
                    path=path,
                )
            tool_vision = get_cached_vision_support(model_name, base_url)
            if tool_vision is None:
                # 缓存未命中 → 自动探查
                capability = await ensure_modality_capability(context)
                tool_vision = capability.vision
            if tool_vision is False:
                # tool 消息不支持，检查 user 消息是否支持
                user_vision = get_cached_user_vision_support(model_name, base_url)
                if user_vision is None:
                    # 缓存未命中（ensure_modality_capability 已探查，但可能只写了部分）
                    capability = await ensure_modality_capability(context)
                    user_vision = capability.user_vision
                if user_vision is False:
                    # tool 和 user 都不支持 → 检查是否配置了引用字段
                    active_profile = _profile
                    if active_profile and active_profile.vision_image_profile:
                        # 读取文件 + base64
                        file_size = resolved.real.stat().st_size
                        if file_size > _MAX_IMAGE_SIZE:
                            return tool_error(
                                f"Image too large: {file_size} bytes (max {_MAX_IMAGE_SIZE})",
                                path=path, size=file_size,
                            )
                        try:
                            raw_bytes = resolved.real.read_bytes()
                            b64 = base64.b64encode(raw_bytes).decode("ascii")
                        except Exception as exc:
                            return tool_error(f"Failed to read image: {exc}", path=path)
                        width, height = _parse_size(raw_bytes, mime_type)
                        logger.info(
                            "read_image | path=%s mime=%s size=%d w=%s h=%s (forwarding to ref profile)",
                            path, mime_type, file_size, width, height,
                        )
                        description = await forward_modality_to_ref_profile(
                            context, active_profile,
                            {"base64": b64, "mime_type": mime_type}, "image",
                        )
                        description = wrap_forwarded_description(description, forwarded_tag_for_media("image"))
                        return {
                            "type": "image",
                            "path": path,
                            "absolute_path": str(resolved.real),
                            "mime_type": mime_type,
                            "size": file_size,
                            "width": width,
                            "height": height,
                            "description": description,
                            "_note": (
                                "Image content was forwarded to the referenced vision profile for description. "
                                "The description field contains the model's analysis of the image."
                            ),
                            "total_lines": 0,
                            "content": "",
                            "remaining": 0,
                            "offset": 0,
                            "limit": 0,
                            "entries": [],
                            "count": None,
                        }
                    return tool_error(
                        f"This provider does not support images inside either tool messages or user messages, "
                        f"so the Read tool cannot deliver image content to the model.",
                        path=path,
                        model=model_name,
                    )
                # user 消息支持 → 走 follow_up 路径
                # 大小检查
                file_size: int = resolved.real.stat().st_size
                if file_size > _MAX_IMAGE_SIZE:
                    return tool_error(
                        f"Image too large: {file_size} bytes (max {_MAX_IMAGE_SIZE})",
                        path=path,
                        size=file_size,
                    )
                try:
                    raw_bytes: bytes = resolved.real.read_bytes()
                    b64: str = base64.b64encode(raw_bytes).decode("ascii")
                except Exception as exc:
                    return tool_error(f"Failed to read image: {exc}", path=path)
                width, height = _parse_size(raw_bytes, mime_type)
                logger.info(
                    "read_image | path=%s mime=%s size=%d w=%s h=%s (user-message fallback)",
                    path, mime_type, file_size, width, height,
                )
                return {
                    "type": "image",
                    "path": path,
                    "absolute_path": str(resolved.real),
                    "mime_type": mime_type,
                    "size": file_size,
                    "width": width,
                    "height": height,
                    "_user_blocks": [{"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{b64}"}}],
                    "_note": (
                        "Image content will be delivered as a user message after this tool round. "
                        "Do NOT call any more tools — respond directly to receive the image. "
                        "width/height are parsed via Pillow (None for SVG or on failure)."
                    ),
                    "total_lines": 0,
                    "content": "",
                    "remaining": 0,
                    "offset": 0,
                    "limit": 0,
                    "entries": [],
                    "count": None,
                }
            # tool_vision is True → 现有行为
            # 大小检查
            file_size = resolved.real.stat().st_size
            if file_size > _MAX_IMAGE_SIZE:
                return tool_error(
                    f"Image too large: {file_size} bytes (max {_MAX_IMAGE_SIZE})",
                    path=path,
                    size=file_size,
                )
            # 读取 + base64
            try:
                raw_bytes = resolved.real.read_bytes()
                b64 = base64.b64encode(raw_bytes).decode("ascii")
            except Exception as exc:
                return tool_error(f"Failed to read image: {exc}", path=path)
            width, height = _parse_size(raw_bytes, mime_type)
            logger.info(
                "read_image | path=%s mime=%s size=%d w=%s h=%s",
                path, mime_type, file_size, width, height,
            )
            return {
                "type": "image",
                "path": path,
                "absolute_path": str(resolved.real),
                "mime_type": mime_type,
                "size": file_size,
                "width": width,
                "height": height,
                "_blocks": [{"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{b64}"}}],
                "_note": (
                    "Image metadata returned. width/height are parsed via Pillow "
                    "(None for SVG or on failure). The image content is attached "
                    "as a multimodal block for direct analysis."
                ),
                "total_lines": 0,
                "content": "",
                "remaining": 0,
                "offset": 0,
                "limit": 0,
                "entries": [],
                "count": None,
            }
        # --- 音频分支（MIME 自动检测）---
        if mime_type in _SUPPORTED_AUDIO_MIMES:
            model_name, base_url, _profile = resolve_active_model_base_url(context)
            if not model_name:
                return tool_error(
                    "No LLM model configured; cannot determine audio capability.",
                    path=path,
                )
            tool_audio = get_cached_audio_support(model_name, base_url)
            if tool_audio is None:
                # 缓存未命中 → 自动探查
                capability = await ensure_modality_capability(context)
                tool_audio = capability.audio
            if tool_audio is False:
                # tool 消息不支持，检查 user 消息是否支持
                user_audio = get_cached_user_audio_support(model_name, base_url)
                if user_audio is None:
                    # 缓存未命中（ensure_modality_capability 已探查，但可能只写了部分）
                    capability = await ensure_modality_capability(context)
                    user_audio = capability.user_audio
                if user_audio is False:
                    # tool 和 user 都不支持 → 检查是否配置了引用字段
                    active_profile = _profile
                    if active_profile and active_profile.audio_profile:
                        file_size = resolved.real.stat().st_size
                        if file_size > _MAX_AUDIO_SIZE:
                            return tool_error(
                                f"Audio too large: {file_size} bytes (max {_MAX_AUDIO_SIZE})",
                                path=path, size=file_size,
                            )
                        try:
                            raw_bytes = resolved.real.read_bytes()
                            b64 = base64.b64encode(raw_bytes).decode("ascii")
                        except Exception as exc:
                            return tool_error(f"Failed to read audio: {exc}", path=path)
                        audio_format = _AUDIO_FORMAT_MAP.get(mime_type, "wav")
                        logger.info(
                            "read_audio | path=%s mime=%s size=%d format=%s (forwarding to ref profile)",
                            path, mime_type, file_size, audio_format,
                        )
                        description = await forward_modality_to_ref_profile(
                            context, active_profile,
                            {"base64": b64, "format": audio_format}, "audio",
                        )
                        description = wrap_forwarded_description(description, forwarded_tag_for_media("audio"))
                        return {
                            "type": "audio",
                            "path": path,
                            "absolute_path": str(resolved.real),
                            "mime_type": mime_type,
                            "size": file_size,
                            "description": description,
                            "_note": (
                                "Audio content was forwarded to the referenced audio profile for description. "
                                "The description field contains the model's analysis of the audio."
                            ),
                            "total_lines": 0,
                            "content": "",
                            "remaining": 0,
                            "offset": 0,
                            "limit": 0,
                            "entries": [],
                            "count": None,
                        }
                    return tool_error(
                        f"This provider does not support audio inside either tool messages or user messages, "
                        f"so the Read tool cannot deliver audio content to the model.",
                        path=path,
                        model=model_name,
                    )
                # user 消息支持 → 走 follow_up 路径
                file_size = resolved.real.stat().st_size
                if file_size > _MAX_AUDIO_SIZE:
                    return tool_error(
                        f"Audio too large: {file_size} bytes (max {_MAX_AUDIO_SIZE})",
                        path=path,
                        size=file_size,
                    )
                try:
                    raw_bytes = resolved.real.read_bytes()
                    b64 = base64.b64encode(raw_bytes).decode("ascii")
                except Exception as exc:
                    return tool_error(f"Failed to read audio: {exc}", path=path)
                audio_format: str = _AUDIO_FORMAT_MAP.get(mime_type, "wav")
                logger.info(
                    "read_audio | path=%s mime=%s size=%d format=%s (user-message fallback)",
                    path, mime_type, file_size, audio_format,
                )
                return {
                    "type": "audio",
                    "path": path,
                    "absolute_path": str(resolved.real),
                    "mime_type": mime_type,
                    "size": file_size,
                    "_user_blocks": [{"type": "input_audio", "input_audio": {"data": b64, "format": audio_format}}],
                    "_note": (
                        "Audio content will be delivered as a user message after this tool round. "
                        "Do NOT call any more tools — respond directly to receive the audio."
                    ),
                    "total_lines": 0,
                    "content": "",
                    "remaining": 0,
                    "offset": 0,
                    "limit": 0,
                    "entries": [],
                    "count": None,
                }
            # tool_audio is True → 现有行为
            file_size = resolved.real.stat().st_size
            if file_size > _MAX_AUDIO_SIZE:
                return tool_error(
                    f"Audio too large: {file_size} bytes (max {_MAX_AUDIO_SIZE})",
                    path=path,
                    size=file_size,
                )
            try:
                raw_bytes = resolved.real.read_bytes()
                b64 = base64.b64encode(raw_bytes).decode("ascii")
            except Exception as exc:
                return tool_error(f"Failed to read audio: {exc}", path=path)
            audio_format = _AUDIO_FORMAT_MAP.get(mime_type, "wav")
            logger.info(
                "read_audio | path=%s mime=%s size=%d format=%s",
                path, mime_type, file_size, audio_format,
            )
            return {
                "type": "audio",
                "path": path,
                "absolute_path": str(resolved.real),
                "mime_type": mime_type,
                "size": file_size,
                "_blocks": [{"type": "input_audio", "input_audio": {"data": b64, "format": audio_format}}],
                "_note": (
                    "Audio content attached as a multimodal block for direct analysis."
                ),
                "total_lines": 0,
                "content": "",
                "remaining": 0,
                "offset": 0,
                "limit": 0,
                "entries": [],
                "count": None,
            }
        # --- 视频分支（MIME 自动检测）---
        if mime_type in _SUPPORTED_VIDEO_MIMES:
            model_name, base_url, _profile = resolve_active_model_base_url(context)
            if not model_name:
                return tool_error(
                    "No LLM model configured; cannot determine video capability.",
                    path=path,
                )
            tool_video = get_cached_video_support(model_name, base_url)
            if tool_video is None:
                # 缓存未命中 → 自动探查
                capability = await ensure_modality_capability(context)
                tool_video = capability.video
            if tool_video is False:
                # tool 消息不支持，检查 user 消息是否支持
                user_video = get_cached_user_video_support(model_name, base_url)
                if user_video is None:
                    capability = await ensure_modality_capability(context)
                    user_video = capability.user_video
                if user_video is False:
                    # tool 和 user 都不支持 → 检查是否配置了引用字段
                    active_profile = _profile
                    if active_profile and active_profile.vision_video_profile:
                        file_size = resolved.real.stat().st_size
                        if file_size > _MAX_VIDEO_SIZE:
                            return tool_error(
                                f"Video too large: {file_size} bytes (max {_MAX_VIDEO_SIZE})",
                                path=path, size=file_size,
                            )
                        try:
                            raw_bytes = resolved.real.read_bytes()
                            b64 = base64.b64encode(raw_bytes).decode("ascii")
                        except Exception as exc:
                            return tool_error(f"Failed to read video: {exc}", path=path)
                        logger.info(
                            "read_video | path=%s mime=%s size=%d (forwarding to ref profile)",
                            path, mime_type, file_size,
                        )
                        description = await forward_modality_to_ref_profile(
                            context, active_profile,
                            {"base64": b64, "mime_type": mime_type}, "video",
                        )
                        description = wrap_forwarded_description(description, forwarded_tag_for_media("video"))
                        return {
                            "type": "video",
                            "path": path,
                            "absolute_path": str(resolved.real),
                            "mime_type": mime_type,
                            "size": file_size,
                            "description": description,
                            "_note": "Video content forwarded to the referenced profile for analysis.",
                            "total_lines": 0,
                            "content": "",
                            "remaining": 0,
                            "offset": 0,
                            "limit": 0,
                            "entries": [],
                            "count": None,
                        }
                    return tool_error(
                        f"Video not supported by model '{model_name}' in either tool or user messages, "
                        f"and no vision_video_profile is configured.",
                        path=path, model=model_name,
                    )
                if user_video is True:
                    # 仅 user 消息支持 → _user_blocks 载荷
                    file_size = resolved.real.stat().st_size
                    if file_size > _MAX_VIDEO_SIZE:
                        return tool_error(
                            f"Video too large: {file_size} bytes (max {_MAX_VIDEO_SIZE})",
                            path=path, size=file_size,
                        )
                    try:
                        raw_bytes = resolved.real.read_bytes()
                        b64 = base64.b64encode(raw_bytes).decode("ascii")
                    except Exception as exc:
                        return tool_error(f"Failed to read video: {exc}", path=path)
                    logger.info(
                        "read_video | path=%s mime=%s size=%d (user-message fallback)",
                        path, mime_type, file_size,
                    )
                    return {
                        "type": "video",
                        "path": path,
                        "absolute_path": str(resolved.real),
                        "mime_type": mime_type,
                        "size": file_size,
                        "_user_blocks": [{"type": "video_url", "video_url": {"url": f"data:{mime_type};base64,{b64}"}}],
                        "_note": (
                            "Video content will be delivered as a user message after this tool round. "
                            "Do NOT call any more tools — respond directly to receive the video."
                        ),
                        "total_lines": 0,
                        "content": "",
                        "remaining": 0,
                        "offset": 0,
                        "limit": 0,
                        "entries": [],
                        "count": None,
                    }
            # tool_video is True → 直接返回 _blocks 载荷
            file_size = resolved.real.stat().st_size
            if file_size > _MAX_VIDEO_SIZE:
                return tool_error(
                    f"Video too large: {file_size} bytes (max {_MAX_VIDEO_SIZE})",
                    path=path, size=file_size,
                )
            try:
                raw_bytes = resolved.real.read_bytes()
                b64 = base64.b64encode(raw_bytes).decode("ascii")
            except Exception as exc:
                return tool_error(f"Failed to read video: {exc}", path=path)
            logger.info(
                "read_video | path=%s mime=%s size=%d",
                path, mime_type, file_size,
            )
            return {
                "type": "video",
                "path": path,
                "absolute_path": str(resolved.real),
                "mime_type": mime_type,
                "size": file_size,
                "_blocks": [{"type": "video_url", "video_url": {"url": f"data:{mime_type};base64,{b64}"}}],
                "_note": "Video content attached as a multimodal block for direct analysis.",
                "total_lines": 0,
                "content": "",
                "remaining": 0,
                "offset": 0,
                "limit": 0,
                "entries": [],
                "count": None,
            }
        # --- 文本分支（原有逻辑，无修改）---
        try:
            content: str = _s().read(path, offset=offset, limit=limit)
        except SandboxError as exc:
            return tool_error(str(exc), path=path)
        lines: list[str] = content.splitlines()
        numbered: str = "\n".join(
            f"{offset + i + 1}: {line}" for i, line in enumerate(lines)
        )
        try:
            total: int = _s().count_lines(path)
        except SandboxError as exc:
            return tool_error(str(exc), path=path)
        last_line: int = offset + len(lines)
        remaining: int = max(0, total - last_line)
        return {
            "type": "file",
            "path": path,
            "absolute_path": str(resolved.real),
            "total_lines": total,
            "content": numbered,
            "remaining": remaining,
            "offset": offset,
            "limit": limit,
            "entries": [],
            "count": None,
        }

    return tool_error("Unsupported path type — must be a file or directory", path=path)


def _handle_write(
    args: dict[str, Any],
    context: ToolContext | None = None,
) -> dict:
    path: str = str(args.get("path", "")).strip()
    has_content = "content" in args and args["content"] is not None
    content: str = str(args["content"]) if has_content else ""
    mode: str = str(args.get("mode", "overwrite")).strip()
    if not path:
        return tool_error("path is required", path=path)
    try:
        _track_agentspace_access(context, [(path, False)])
    except Exception as exc:
        return tool_error(f"Agentspace access lock failed: {exc}", path=path)

    # -- 目录创建分支：content 缺失或为 None --
    if not has_content:
        try:
            already_exists = _s().is_dir(path)
            if not already_exists:
                if _s().exists(path):
                    return tool_error(f"Path already exists as a file: {path}", path=path)
                _s().create_folder(path, parents=True)
            return tool_result(
                success=True, path=path,
                type="directory", already_exists=already_exists,
            )
        except SandboxError as exc:
            return tool_error(str(exc), path=path)

    # -- 文件写入分支 --
    if mode not in ("overwrite", "append"):
        return tool_error(
            f"Invalid mode '{mode}'. Valid values: overwrite, append.",
            path=path,
        )
    truncated: bool = False
    tail: str = ""
    if len(content) > WRITE_FILE_MAX_CHARS:
        tail = content[WRITE_FILE_MAX_CHARS:WRITE_FILE_MAX_CHARS + WRITE_FILE_TRUNCATION_TAIL]
        content = content[:WRITE_FILE_MAX_CHARS]
        truncated = True
        logger.warning(
            "Write | content truncated from %d to %d chars | path=%s | tail=%s",
            len(args.get("content", "")), WRITE_FILE_MAX_CHARS, path, repr(tail),
        )
    try:
        if mode == "append":
            if not _s().exists(path):
                return tool_error("File not found — use Write with mode='overwrite' to create it first", path=path)
            _s().append(path, content)
        else:
            _s().write(path, content)
        _lsp_diags = _try_attach_lsp_diagnostics(path, content)
        if truncated:
            result = tool_result(
                success=True, path=path,
                bytes=len(content.encode("utf-8")),
                truncated=True,
                tail=tail,
                type="file",
            )
        else:
            result = tool_result(
                success=True, path=path,
                bytes=len(content.encode("utf-8")),
                type="file",
            )
        if _lsp_diags is not None:
            result["diagnostics"] = _lsp_diags
        return result
    except SandboxError as exc:
        return tool_error(str(exc), path=path)


def _handle_delete(
    args: dict[str, Any],
    context: ToolContext | None = None,
) -> dict:
    paths_raw = args.get("paths", [])
    if not isinstance(paths_raw, list) or not paths_raw:
        return tool_error("paths is required as a non-empty array of strings")
    results: list[dict] = []
    succeeded = 0
    failed = 0
    for p in paths_raw:
        path = str(p).strip()
        if not path:
            results.append({"path": str(p), "success": False, "error": "path is empty"})
            failed += 1
            continue
        try:
            is_directory = _s().is_dir(path)
            _track_agentspace_access(context, [(path, is_directory)])
            if is_directory:
                _s().delete_folder(path)
            else:
                _s().delete(path)
            results.append({"path": path, "success": True, "deleted": True})
            succeeded += 1
        except Exception as exc:
            results.append({"path": path, "success": False, "error": str(exc)})
            failed += 1
    return tool_result(results=results, summary={"total": len(results), "succeeded": succeeded, "failed": failed})



# ---------------------------------------------------------------------------
# 注册（模块导入时执行）
# ---------------------------------------------------------------------------


def _param(path_desc: str, required: bool = True) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                # 逻辑路径（{path_desc}）。必须使用命名空间前缀：fork:、ws:、fix: 或 skills:。
                "description": f"Logical path ({path_desc}). "
                "Must use a namespace prefix: fork:, ws:, fix:, or skills:.",
            },
        },
        "required": (["path"] if required else []),
    }


def _param_paths(paths_desc: str) -> dict[str, Any]:
    """生成 paths: array of strings 的 parameters schema 片段。"""
    return {
        "type": "object",
        "properties": {
            "paths": {
                "type": "array",
                "items": {"type": "string"},
                # 逻辑路径列表（{paths_desc}）。每个路径必须使用命名空间前缀：fork:、ws:、fix: 或 skills:。
                "description": f"Logical paths ({paths_desc}). "
                "Each must use a namespace prefix: fork:, ws:, fix:, or skills:.",
            },
        },
        "required": ["paths"],
    }


# -- Read 工具（统一文件/目录/图片读取）
registry.register(
    name="Read",
    toolset="filesystem",
    schema={
        # 读取文件内容（带行号前缀、总行数、绝对路径）、列出目录条目、或读取图片/音频/视频文件（按 MIME 自动检测）。
        # 支持命名空间前缀：ws:、fork:、fix:、skills: 及其他只读命名空间。
        # 目录分支忽略 offset/limit，文件分支使用 offset/limit 分页，图片/音频/视频分支忽略 offset/limit。
        #
        # ## 图片/音频/视频分支（MIME 自动检测）
        # 当文件 MIME 类型命中图片白名单（PNG/JPEG/WebP/GIF/BMP/TIFF/SVG）、音频白名单（WAV/MP3）或视频白名单（MP4）时自动走对应分支。
        # 多模态能力自动探测：首次读图/音频/视频时自动探测并缓存，无需手动探查。探测结果分三态：
        # - tool 消息支持 → 直接返回 _blocks（多模态块在 tool 消息中传递）
        # - 仅 user 消息支持 → 返回 _user_blocks，多模态内容在当前轮工具调用完成后
        #   通过 follow_up 用户消息注入上下文，返回文本提醒模型不要再调用工具
        # - 都不支持但配了引用字段 → 返回 description（转发给被引用模型取描述文本）
        # - 都不支持且未配引用字段 → 返回错误，不读取文件
        # 支持最大图片 20MB、音频 25MB、视频 50MB。
        # _blocks 载荷由 tool_result_to_content 提取并构造为 ImageBlock/AudioBlock/VideoBlock + TextBlock（元数据）。
        # _user_blocks 载荷由 tool_result_to_follow_up 提取并构造为 CharacterConversationMessage
        # （role=USER, character_name=system, visible_characters=[当前角色]）。
        # offset/limit 在图片/音频/视频分支中被忽略（固定填充为 0）。
        #
        # ## 前置条件
        # - 路径必须存在（文件或目录均可）。
        # - 路径必须使用命名空间前缀。
        # - 图片/音频/视频分支：多模态能力自动探测（首次访问时自动探查并缓存），
        #   至少 tool 或 user 消息之一支持该模态时才读取文件。
        #
        # ## 调用效果
        # **文件分支**：返回文件内容，每行前缀为 1-indexed 行号。
        # 支持 offset（0-indexed 起始行）和 limit（最大行数）分页。
        # **目录分支**：返回条目名称列表，目录条目以 "/" 后缀标识。
        # offset/limit 在目录分支中被忽略（固定填充为 0）。
        # **图片分支**：按 MIME 自动检测。若 tool 消息支持 → 返回 _blocks（多模态块在 tool 消息中传递）；
        # 若仅 user 消息支持 → 返回 _user_blocks，多模态内容在当前轮工具调用完成后通过用户消息注入，
        # 返回文本提醒模型不要再调用工具；都不支持但配了引用字段 → 转发取描述文本；都不支持且未配 → 返回错误。
        # **音频分支**：与图片分支对称。
        # **视频分支**：与图片分支对称，使用 _blocks/_user_blocks/vision_video_profile。
        # offset/limit 在图片/音频/视频分支中被忽略（固定填充为 0）。
        #
        # ## 返回
        # ```json
        # {{"path": "ws:example.txt", "content": "1|first line\n2|second line", "total_lines": 100, "remaining": 98, "offset": 0, "limit": 100}}
        # ```
        # `total_lines` 为文件总行数。`remaining` 为当前读取的最后一行到文件末尾还剩多少行（0 表示已读至文件末尾）。
        #
        # ## 何时使用
        # - 编辑前查看文件内容。
        # - 分页浏览大文件。
        # - 通过行号引用具体位置。
        # - 利用 `remaining` 判断是否需要继续分页读取。
        # - 读取图片/音频/视频文件（多模态能力自动探测，无需手动探查）。
        # - 即使 provider 不支持 tool 消息多模态，只要支持 user 消息多模态，Read 仍可通过
        #   follow_up 用户消息回退路径传递图片/音频/视频内容。
        #
        # ## 副作用/注意
        # - 无副作用，纯查询。
        # - offset < 0 或 limit < 1 返回错误。
        # - 文件不存在或沙箱拒绝访问返回描述性错误。
        # - 图片/音频/视频分支：未探测或 tool/user 消息都不支持且未配引用字段时返回错误，不读取文件。
        # - tool/user 消息都不支持但配了引用字段时，转发给被引用模型取描述文本，返回 description 字段。
        # - 仅 user 消息支持时，返回 _user_blocks 而非 _blocks，
        #   多模态内容将在当前轮工具调用完成后通过用户消息注入，返回文本提醒不要再调用工具。
        "description": """Read file content (with line numbers, total lines, absolute path), list directory entries, or read an image/audio file (auto-detected by MIME type). Supports namespace prefixes: ws:, fork:, fix:, skills:, and read-only namespaces.

## Prerequisites
- The path must exist (file or directory).
- The path must use a namespace prefix.
- Image/audio branches automatically probe multimodal capability on first access and cache the result. No manual probe needed.

## Effect
**File branch**: Returns file content prefixed with 1-indexed line numbers. Supports pagination via offset (0-indexed start) and limit (max lines).
**Directory branch**: Returns entry names; directory entries suffixed with '/'. offset and limit are ignored for directories (filled as 0).
**Image branch**: Auto-detected by MIME type (PNG, JPEG, WebP, GIF, BMP, TIFF, SVG; max 20 MB). Delivery path depends on probe results:
- `vision_capable=true` → image is delivered directly in the tool message as a `_blocks` payload (multimodal content block).
- `vision_capable=false` but `user_vision_capable=true` → image is delivered via a follow-up user message after the current tool round completes. The tool result contains `_user_blocks` and a text note advising you NOT to call any more tools — respond directly to receive the image.
- Both false but `vision_image_profile` is set → image is forwarded to the referenced profile's model, which returns a detailed text description. The tool result contains a `description` field (no multimodal blocks) with the forwarded analysis.
- Both false and no reference configured → error, file is not read.
offset and limit are ignored for images (filled as 0).

**Audio branch**: Auto-detected by MIME type (WAV, MP3; max 25 MB). Same four-state delivery as the image branch, using `_blocks` / `_user_blocks` / `description` (forwarded) / error. offset and limit are ignored for audio (filled as 0).

**Video branch**: Auto-detected by MIME type (MP4; max 50 MB). Same four-state delivery as the image branch, using `_blocks` / `_user_blocks` / `description` (forwarded, via `vision_video_profile`) / error. offset and limit are ignored for video (filled as 0).

All branches return absolute_path (resolved absolute path), total_lines (line count; 0 for directories/images/audio/video), entries (directory entries; empty array for files/images/audio/video), and a type discriminant ("file", "directory", "image", "audio", or "video").

## Returns
File branch:
```json
{"type": "file", "path": "ws:a.py", "absolute_path": "...", "total_lines": 100, "content": "1|...", "remaining": 98, "offset": 0, "limit": 100, "entries": [], "count": null}
```
Directory branch:
```json
{"type": "directory", "path": "ws:src", "absolute_path": "...", "total_lines": 0, "content": "", "remaining": 0, "offset": 0, "limit": 0, "entries": ["a.py", "sub/"], "count": 2}
```
Image branch (tool-message path):
```json
{"type": "image", "path": "ws:uploads/screenshot.png", "absolute_path": "...", "mime_type": "image/png", "size": 12345, "width": 800, "height": 600, "_blocks": [{"type": "image_url", "image_url": {"url": "data:image/png;base64,..."}}], "_note": "Image metadata returned...", "total_lines": 0, "content": "", "remaining": 0, "offset": 0, "limit": 0, "entries": [], "count": null}
```
Image branch (user-message fallback path):
```json
{"type": "image", "path": "ws:uploads/screenshot.png", "absolute_path": "...", "mime_type": "image/png", "size": 12345, "width": 800, "height": 600, "_user_blocks": [{"type": "image_url", "image_url": {"url": "data:image/png;base64,..."}}], "_note": "Image content will be delivered as a user message after this tool round. Do NOT call any more tools...", "total_lines": 0, "content": "", "remaining": 0, "offset": 0, "limit": 0, "entries": [], "count": null}
```
`width`/`height` are parsed via Pillow; `null` for SVG or on parse failure.

Video branch (tool-message path):
```json
{"type": "video", "path": "ws:uploads/demo.mp4", "absolute_path": "...", "mime_type": "video/mp4", "size": 123456, "_blocks": [{"type": "video_url", "video_url": {"url": "data:video/mp4;base64,..."}}], "_note": "Video content attached as a multimodal block for direct analysis.", "total_lines": 0, "content": "", "remaining": 0, "offset": 0, "limit": 0, "entries": [], "count": null}
```
Video branch (user-message fallback path):
```json
{"type": "video", "path": "ws:uploads/demo.mp4", "absolute_path": "...", "mime_type": "video/mp4", "size": 123456, "_user_blocks": [{"type": "video_url", "video_url": {"url": "data:video/mp4;base64,..."}}], "_note": "Video content will be delivered as a user message after this tool round. Do NOT call any more tools...", "total_lines": 0, "content": "", "remaining": 0, "offset": 0, "limit": 0, "entries": [], "count": null}
```

## When to Use
- Targets a file → file branch; targets a directory → directory branch; image/audio/video files → image/audio/video branch (auto-detected).
- Use skills: prefix to replace the old read_skill_file tool (e.g. Read(path="skills:my-skill/scripts/hello.py")).
- Use absolute_path to resolve paths when you have a readable target.
- Read image/audio/video files: multimodal capability is automatically probed on first access. Even if the provider rejects multimodal in tool messages, Read can still deliver images/audio/video via a follow-up user message when the provider accepts multimodal in user messages.

## Side Effects / Notes
- No file system side effects, read-only query.
- offset < 0 or limit out of range returns an error.
- Non-existent or unsupported paths return a descriptive error.
- For directories, images, and audio, offset/limit are ignored and filled as 0.
- Image/audio branch: returns an error if support has not been probed or both tool and user messages are unsupported; the file is not read in this case.
- User-message fallback: when only user-message multimodal is supported, the tool result text includes a note advising you to stop calling tools and respond directly — the image/audio will arrive as a user message after the current tool round.""",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    # 文件逻辑路径。必须使用命名空间前缀：fork:、ws: 或 fix:。
                    "description": "File logical path. "
                    "Must use a namespace prefix: fork:, ws:, fix:, or skills:.",
                },
                "offset": {
                    "type": "integer",
                    # 起始行号（0-indexed，默认 0）。输出使用 1-indexed 行号前缀。
                    "description": "Starting line number, 0-indexed (default 0). "
                    "Output uses 1-indexed line number prefixes for display.",
                    "default": 0,
                    "minimum": 0,
                },
                "limit": {
                    "type": "integer",
                    # 最大返回行数（默认 100，硬上限见 READ_FILE_MAX_LINES）。
                    "description": "Maximum number of lines to return (default 100, hard cap defined by READ_FILE_MAX_LINES).",
                    "default": 100,
                    "minimum": 1,
                    "maximum": READ_FILE_MAX_LINES,
                },
            },
            "required": ["path"],
        },
    },
    handler=_handle_read,
    no_timeout=True,
    is_async=True,
)


# -- Write
registry.register(
    name="Write",
    toolset="filesystem",
    schema={
        # 将内容写入文件（覆写或追加），或在省略 content 时创建目录。路径必须使用命名空间前缀。
        #
        # ## 前置条件
        # - mode="overwrite"（默认）：确定文件不存在需要新建文件，或确定文件内容已完全无效需要覆写。
        # - mode="append"：文件必须已存在。
        # - 小范围修改应使用 PatchEdit。
        #
        # ## 目录创建模式
        # 当 `content` 省略或为 null 时，`path` 被视为目录路径，递归创建该目录（含所有父目录）。
        # 目录已存在时返回 `already_exists: true`，不报错。
        # 此模式下 `mode` 参数无意义，被忽略。
        #
        # ## 调用效果
        # 以 `content` 写入目标文件。每次调用最多 {WRITE_FILE_MAX_CHARS} 个字符。
        # mode="overwrite"（默认）：完整覆盖，若文件已存在则被覆盖，若不存在则创建。
        # mode="append"：追加到文件末尾，不影响已有内容；文件不存在时返回错误。
        # 超出限制时自动截断至 {WRITE_FILE_MAX_CHARS}，返回结果中 `truncated=true` 提示内容不完整。
        # 同时返回 `tail` 字段（被截断内容的前 {WRITE_FILE_TRUNCATION_TAIL} 个字符），可作为 PatchEdit 的 old_string 继续写入，剩余内容也可用 Write(mode="append") 追加。
        # 不得使用 run_python 替代此工具写文件。
        # 使用 `skills:` 前缀可写入 skill 包内文件（如 skills:my-skill/scripts/hello.py）。
        #
        # ## 返回
        # 文件写入（未截断）：
        # ```json
        # {{"success": true, "path": "ws:example.txt", "bytes": 42, "type": "file"}}
        # ```
        # 文件写入（截断时额外包含 `truncated=true` 和 `tail` 字段）：
        # ```json
        # {{"success": true, "path": "ws:example.txt", "bytes": {WRITE_FILE_MAX_CHARS}, "truncated": true, "tail": "...", "type": "file"}}
        # ```
        # `tail` 为被截断部分的前 {WRITE_FILE_TRUNCATION_TAIL} 个字符，用作 PatchEdit 的 old_string。
        # 目录创建：
        # ```json
        # {{"success": true, "path": "ws:src/subdir", "type": "directory", "already_exists": false}}
        # ```
        #
        # ## 何时使用
        # - 创建目录（省略 content，path 被视为目录路径）。
        # - 创建新文件。
        # - 完整覆写小文件（不超过 {WRITE_FILE_MAX_CHARS} 字符）。
        # - 向已有文件末尾追加新内容（mode="append"）。
        # - 写入 skill 附属文件（skills: 前缀，替代原 write_skill_file）。
        #
        # ## 副作用/注意
        # - 写入文件系统，mode="overwrite" 覆盖已有文件。
        # - 超出 {WRITE_FILE_MAX_CHARS} 限制时自动截断，应继续用 `tail` 作为 old_string 调用 PatchEdit，或用 Write(mode="append") 追加剩余内容。
        # - 路径使用命名空间前缀：'ws:' 用于 workspace 数据，'fork:' 用于进化代码，'skills:' 用于 skill 文件。
        "description": f"""Write content to a file (overwrite or append), or create a directory when content is omitted. Path must use a namespace prefix.

## Prerequisites
- mode="overwrite" (default): The file does not exist yet (new file creation), or the file content is confirmed to be completely invalid and needs overwriting.
- mode="append": The file must already exist.
- For small edits, use PatchEdit instead.

## Effect
If `content` is omitted or null, `path` is treated as a directory path — creates it recursively (including all parent directories). If the directory already exists, returns `already_exists: true` (no error). In this mode, the `mode` parameter is ignored.
When `content` is provided, writes it to the target file. Max {WRITE_FILE_MAX_CHARS} characters per call.
mode="overwrite" (default): Overwrites the target file entirely, creating it if it doesn't exist.
mode="append": Appends to the end of the target file without affecting existing content; errors if the file doesn't exist.
Content exceeding the limit is automatically truncated to {WRITE_FILE_MAX_CHARS}; the result includes `truncated=true` to indicate incomplete content.
When truncated, a `tail` field is also returned containing the first {WRITE_FILE_TRUNCATION_TAIL} characters of the truncated portion — use it as the `old_string` for a follow-up PatchEdit call, and append the remaining content with Write(mode="append").
Do NOT use run_python as a substitute for this tool.
Use the `skills:` prefix to write files inside a skill package (e.g. skills:my-skill/scripts/hello.py) — replaces the old write_skill_file tool.

## Returns
File write (without truncation):
```json
{{"success": true, "path": "ws:example.txt", "bytes": 42, "type": "file"}}
```
File write (truncated, additionally includes `truncated=true` and `tail`):
```json
{{"success": true, "path": "ws:example.txt", "bytes": {WRITE_FILE_MAX_CHARS}, "truncated": true, "tail": "...", "type": "file"}}
```
`tail` contains the first {WRITE_FILE_TRUNCATION_TAIL} characters of the truncated portion to use as old_string for PatchEdit.
Directory creation (content omitted):
```json
{{"success": true, "path": "ws:src/subdir", "type": "directory", "already_exists": false}}
```

## When to Use
- Create directories (omit `content`; path is treated as a directory path).
- Create new files.
- Completely overwrite small files (within {WRITE_FILE_MAX_CHARS} characters).
- Append new content to the end of an existing file (mode="append").
- Write skill ancillary files (skills: prefix, replaces the old write_skill_file).

## Side Effects / Notes
- Writes to the file system; mode="overwrite" overwrites existing files.
- Content exceeding {WRITE_FILE_MAX_CHARS} is auto-truncated; continue with PatchEdit using `tail` as old_string, or use Write(mode="append") to add the remaining content.
- Use namespace prefixes: 'ws:' for workspace data, 'fork:' for evolution code, 'skills:' for skill files.""",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    # 逻辑路径。必须使用 ws:、fork: 或 skills: 前缀。
                    "description": "Logical path. Must use ws:, fork:, or skills: prefix.",
                },
                "content": {
                    "type": "string",
                    # 要写入文件的内容。最多 WRITE_FILE_MAX_CHARS 个字符。省略或为 null 时，path 被视为目录路径创建目录。
                    "description": f"Content to write to the file. Max {WRITE_FILE_MAX_CHARS} characters. Omit or set to null to create a directory at `path` instead of writing a file.",
                },
                "mode": {
                    "type": "string",
                    # 写入模式：overwrite（默认，覆写或创建）、append（追加，文件必须存在）。
                    "enum": ["overwrite", "append"],
                    "description": "Write mode: 'overwrite' (default, overwrite or create) or 'append' (append to end, file must exist).",
                    "default": "overwrite",
                },
            },
            "required": ["path"],
        },
    },
    handler=_handle_write,
    danger_level=ToolDangerLevel.write,
)


# -- Delete
# 删除多个文件或目录。仅允许可写命名空间（ws:、fork:、fix:、skills:）。
# 根据路径类型自动分流：文件 → 直接删除；目录 → 递归删除整个目录树。
#
# ## 前置条件
# - 路径必须存在。
# - 路径必须使用可写命名空间前缀。
#
# ## 调用效果
# 逐个删除指定路径。文件分支删除单个文件；目录分支递归删除目录及其所有内容。
# 部分路径失败不影响其他路径的删除。
#
# ## 返回
# ```json
# {"results": [{"path": "ws:a.txt", "success": true, "deleted": true}, {"path": "ws:b.txt", "success": false, "error": "File not found"}], "summary": {"total": 2, "succeeded": 1, "failed": 1}}
# ```
#
# ## 何时使用
# - 删除不再需要的文件或目录。
# - 清理 workspace 中的临时文件/目录。
#
# ## 副作用/注意
# - ⚠️ 危险操作：删除后无法恢复（沙箱无回收站）；目录分支为递归删除。
# - 只读命名空间返回访问错误。
registry.register(
    name="Delete",
    toolset="filesystem",
    schema={
        "description": """Delete multiple files or directories. Only writable namespaces are allowed (ws:, fork:, fix:, skills:). The branch is auto-detected from the path type: files are deleted directly; directories are deleted recursively with all their contents. Best-effort: all paths are attempted, each result reports success or failure.

## Prerequisites
- The paths must exist.
- Paths must use a writable namespace prefix.

## Effect
Deletes each specified path. File branch deletes a single file; directory branch recursively deletes the directory and all its contents. Failures for individual paths do not affect others.

## Returns
```json
{"results": [{"path": "ws:a.txt", "success": true, "deleted": true}, {"path": "ws:b.txt", "success": false, "error": "File not found"}], "summary": {"total": 2, "succeeded": 1, "failed": 1}}
```

## When to Use
- Remove files or directories that are no longer needed.
- Clean up temporary files/directories in the workspace.

## Side Effects / Notes
- DANGEROUS: Deletion is irreversible (no trash/recycle bin in the sandbox); directory branch is recursive.
- Read-only namespaces return an access error.
- **Prefer ``Move`` over ``Delete``**: move the file/directory to a trash directory (e.g. ``ws:.trash/``)
  or a temporary directory (e.g. ``ws:tmp/``) first, so the content remains recoverable. Only use
  ``Delete`` for confirmed cleanup of trash/temp directories or when the content is certain to be unneeded.""",
        "parameters": _param_paths("files or directories to delete"),
    },
    handler=_handle_delete,
    danger_level=ToolDangerLevel.write,
)


def _find_ranges(
    content: str, start_marker: str, end_marker: str,
) -> list[tuple[int, int]]:
    """扫描 content 中所有 start_marker..end_marker 区间（含标记本身）。

    返回 [(start_idx, end_idx), ...]，其中 start_idx 是 start_marker 的起始位置，
    end_idx 是 end_marker 结束后的位置（即区间为 content[start_idx:end_idx]）。
    找到 start_marker 后从其后搜索最近的 end_marker；未配对的 start_marker 跳过。
    """
    ranges: list[tuple[int, int]] = []
    search_from = 0
    while True:
        s_idx = content.find(start_marker, search_from)
        if s_idx == -1:
            break
        e_start = s_idx + len(start_marker)
        e_idx = content.find(end_marker, e_start)
        if e_idx == -1:
            break
        e_end = e_idx + len(end_marker)
        ranges.append((s_idx, e_end))
        search_from = e_end
    return ranges


def _handle_edit(
    args: dict[str, Any],
    context: ToolContext | None = None,
) -> dict:
    """文本替换 — 支持 exact / regex / range 三种匹配模式。"""
    path: str = str(args.get("path", "")).strip()
    old_string: str = str(args.get("old_string", ""))
    new_string: str = str(args.get("new_string", ""))
    replace_all: bool = bool(args.get("replace_all", False))
    match_mode: str = str(args.get("match_mode", "exact")).strip()
    start_marker: str = str(args.get("start_marker", ""))
    end_marker: str = str(args.get("end_marker", ""))

    if not path:
        return tool_error("path is required")

    # --- 通用长度校验 ---
    if len(new_string) > EDIT_FILE_MAX_CHARS:
        return tool_error(
            f"new_string exceeds {EDIT_FILE_MAX_CHARS} characters (got {len(new_string)}). "
            "Split the change into multiple sequential PatchEdit calls.",
            path=path,
        )

    if match_mode == "range":
        # range 模式：start_marker + end_marker + new_string 必填，old_string 忽略
        if not start_marker:
            return tool_error("start_marker is required when match_mode='range'", path=path)
        if not end_marker:
            return tool_error("end_marker is required when match_mode='range'", path=path)
        if len(start_marker) > EDIT_FILE_MAX_CHARS:
            return tool_error(
                f"start_marker exceeds {EDIT_FILE_MAX_CHARS} characters (got {len(start_marker)}).",
                path=path,
            )
        if len(end_marker) > EDIT_FILE_MAX_CHARS:
            return tool_error(
                f"end_marker exceeds {EDIT_FILE_MAX_CHARS} characters (got {len(end_marker)}).",
                path=path,
            )
    else:
        # exact / regex 模式：old_string + new_string 必填
        if not old_string:
            return tool_error("old_string is required")
        if len(old_string) > EDIT_FILE_MAX_CHARS:
            return tool_error(
                f"old_string exceeds {EDIT_FILE_MAX_CHARS} characters (got {len(old_string)}). "
                "Use a smaller, unique snippet with surrounding context instead.",
                path=path,
            )

    if not _s().exists(path):
        return tool_error("File not found — use Write to create it first", path=path)

    try:
        _track_agentspace_access(context, [(path, False)])
        content: str = _s().read(path, limit=0)
    except Exception as exc:
        return tool_error(str(exc), path=path)

    # --- exact 模式（默认，向后兼容） ---
    if match_mode == "exact":
        if old_string == new_string:
            return tool_error("old_string and new_string are identical — nothing to change", path=path)
        if old_string not in content:
            return tool_error("old_string not found in file", path=path)
        if replace_all:
            new_content = content.replace(old_string, new_string)
            diffs = []
            search_from = 0
            while True:
                pos = content.find(old_string, search_from)
                if pos == -1:
                    break
                start_line = content[:pos].count("\n") + 1
                diffs.append([old_string, new_string, start_line])
                search_from = pos + len(old_string)
        else:
            count = content.count(old_string)
            if count > 1:
                return tool_error(
                    f"old_string matches {count} locations. Use more surrounding "
                    f"context to make it unique, or set replace_all=true.",
                    path=path, matches=count,
                )
            new_content = content.replace(old_string, new_string, 1)
            start_pos = content.find(old_string)
            start_line = content[:start_pos].count("\n") + 1
            diffs = [[old_string, new_string, start_line]]

    # --- regex 模式 ---
    elif match_mode == "regex":
        if old_string == new_string:
            return tool_error("old_string and new_string are identical — nothing to change", path=path)
        try:
            pattern = re.compile(old_string)
        except re.error as exc:
            return tool_error(f"Invalid regex pattern: {exc}", path=path)
        iter_matches = list(pattern.finditer(content))
        if not iter_matches:
            return tool_error("regex pattern did not match anything in file", path=path)
        if replace_all:
            new_content = pattern.sub(new_string, content)
            diffs = [[m.group(0), m.expand(new_string), content[:m.start()].count("\n") + 1] for m in iter_matches]
        else:
            if len(iter_matches) > 1:
                return tool_error(
                    f"regex matches {len(iter_matches)} locations. "
                    f"Use replace_all=true or make the pattern more specific.",
                    path=path, matches=len(iter_matches),
                )
            new_content = pattern.sub(new_string, content, count=1)
            m = iter_matches[0]
            diffs = [[m.group(0), m.expand(new_string), content[:m.start()].count("\n") + 1]]

    # --- range 模式 ---
    elif match_mode == "range":
        ranges = _find_ranges(content, start_marker, end_marker)
        if not ranges:
            if start_marker not in content:
                return tool_error("start_marker not found in file", path=path)
            return tool_error("end_marker not found after start_marker", path=path)
        if not replace_all and len(ranges) > 1:
            return tool_error(
                f"range matches {len(ranges)} locations. "
                f"Use replace_all=true or use more specific markers.",
                path=path, matches=len(ranges),
            )
        target_ranges = ranges if replace_all else ranges[:1]
        diffs = [[content[s:e], new_string, content[:s].count("\n") + 1] for s, e in target_ranges]
        # 逆序替换以避免偏移
        new_content = content
        for s_idx, e_end in reversed(target_ranges):
            new_content = new_content[:s_idx] + new_string + new_content[e_end:]

    else:
        return tool_error(
            f"Invalid match_mode '{match_mode}'. Valid values: exact, regex, range.",
            path=path,
        )

    try:
        _s().write(path, new_content)
    except SandboxError as exc:
        return tool_error(str(exc), path=path)

    _lsp_diags = _try_attach_lsp_diagnostics(path, new_content)
    result = tool_result(success=True, path=path, replaced=True, diffs=diffs)
    if _lsp_diags is not None:
        result["diagnostics"] = _lsp_diags
    return result


registry.register(
    name="PatchEdit",
    toolset="filesystem",
    schema={
        # 通过替换匹配文本为 new_string 来编辑文件。支持三种匹配模式：
        #   - exact（默认）：old_string 精确匹配，必须唯一出现或设置 replace_all=true。
        #   - regex：old_string 作为正则 pattern，new_string 支持 Python re.sub 替换语法：
        #     \1~\99（编号组）、\g<1>（显式编号组，推荐）、\g<name>（命名组）、\g<0>（整个匹配）、\\（字面反斜杠）。
        #     注意：$1、$& 等 JS/Perl 语法不被支持，会被当作字面文本。
        #   - range：通过 start_marker 和 end_marker 定位整个区间（含标记），替换为 new_string。
        #
        # exact / regex 模式下 old_string 必填，range 模式下 start_marker + end_marker 必填。
        # old_string / start_marker / end_marker / new_string 各自不能超过 {EDIT_FILE_MAX_CHARS} 字符。
        # 仅需修改几行时使用此工具替代 Write — 避免重新发送整个文件内容。
        # 如需更大更改，请多次顺序调用 PatchEdit。
        #
        # 使用方式：
        # - 必须先使用 Read 查看当前内容及行号。
        # - exact 模式：从 Read 输出中选取 old_string，保留行号前缀之后的精确缩进。
        # - exact 模式：包含 2-3 行周围上下文以确保唯一匹配。
        # - regex 模式：old_string 为 Python 正则表达式，new_string 用 \1 或 \g<1> 引用捕获组（不支持 $1）。
        # - range 模式：start_marker 到其后最近 end_marker（含两端）的整个区间被替换。
        # - 设置 replace_all=true 可替换所有匹配项（跳过唯一性检查），所有模式通用。
        # - 修改少量行时始终优先使用此工具替代 Write。
        #
        # 参数：
        #   path:         带命名空间前缀的逻辑路径（ws:/fork:/fix:/skills:）（必需）
        #   new_string:   替换文本，使用 '' 表示删除，最多 {EDIT_FILE_MAX_CHARS} 字符（必需）
        #   match_mode:   匹配模式：exact | regex | range（默认 exact）
        #   old_string:   exact/regex 模式下要查找的文本或正则，最多 {EDIT_FILE_MAX_CHARS} 字符
        #   start_marker: range 模式下区间起始标记（必需）
        #   end_marker:   range 模式下区间结束标记（必需）
        #   replace_all:  替换所有匹配项而非仅第一处（默认 false）
        #
        # 错误：
        #   - exact: 文件中未找到 old_string → 编辑失败
        #   - exact: old_string 匹配到 2+ 处（replace_all=false）→ 提示设 replace_all=true 或加上下文
        #   - regex: 正则编译失败 → 返回 re.error 详情
        #   - regex: 正则未匹配 → 编辑失败
        #   - regex: 正则匹配 2+ 处（replace_all=false）→ 提示设 replace_all=true 或收窄 pattern
        #   - range: start_marker 未找到 → 编辑失败
        #   - range: start_marker 后无 end_marker → 编辑失败
        #   - range: 匹配 2+ 个区间（replace_all=false）→ 提示设 replace_all=true 或用更具体标记
        #   - 文件不存在 → 提示先使用 Write 创建
        #   - 字符串相同（exact/regex）→ 无变更，报错
        "description": f"""Edit a file by replacing matched text with new_string. Supports three matching modes via `match_mode`:

- **exact** (default): `old_string` must match exactly once (or set `replace_all=true`). Classic find-and-replace.
- **regex**: `old_string` is a Python regex pattern. In `new_string`, use Python `re.sub` replacement syntax: `\\1`-`\\99` (numbered group), `\\g<1>` (explicit numbered, recommended), `\\g<name>` (named group via `(?P<name>...)`), `\\g<0>` (full match), `\\\\` (literal backslash). Do NOT use `$1` or `$&` — these are JS/Perl syntax and will be inserted as literal text.
- **range**: Replace the entire region from `start_marker` to the nearest `end_marker` (both markers included) with `new_string`.

All modes share `replace_all` (default false): when false, multiple matches return an error; when true, all matches are replaced.

Both `old_string` and `new_string` are limited to {EDIT_FILE_MAX_CHARS} characters each. Use this instead of Write when only a few lines need changing — avoids resending the entire file content. For larger changes, make multiple sequential PatchEdit calls.

Usage:
- You must use Read first to inspect current content with line numbers.
- exact: pick old_string from Read output, preserve exact indentation after the line number prefix. Include 2-3 lines of surrounding context for uniqueness.
- regex: old_string is a Python regex. new_string uses Python replacement syntax: \\1, \\g<1>, \\g<name>, \\g<0>. Do NOT use $1 (JS/Perl) — it will be literal text.
- range: provide start_marker and end_marker. The entire span from start_marker to the nearest end_marker (inclusive) is replaced by new_string.
- Set replace_all=true to replace all matches (skips uniqueness check).
- ALWAYS prefer editing existing files over Write for small changes.

Parameters:
  path:         Logical path with namespace prefix (ws:/fork:/fix:/skills:) (required)
  new_string:   Replacement text, use '' to delete, max {EDIT_FILE_MAX_CHARS} chars (required)
  match_mode:   Matching mode: exact | regex | range (default exact)
  old_string:   Text to find (exact) or regex pattern (regex mode), max {EDIT_FILE_MAX_CHARS} chars. Required for exact/regex, ignored for range.
  start_marker: Range start marker. Required for range mode, ignored otherwise.
  end_marker:   Range end marker. Required for range mode, ignored otherwise.
  replace_all:  Replace all matches instead of just the first one (default false, all modes)

Errors:
  - exact: old_string not found in file → edit fails
  - exact: old_string matches 2+ locations (replace_all=false) → set replace_all=true or add context
  - regex: invalid regex pattern → returns re.error detail
  - regex: pattern did not match → edit fails
  - regex: pattern matches 2+ locations (replace_all=false) → set replace_all=true or narrow the pattern
  - range: start_marker not found → edit fails
  - range: end_marker not found after start_marker → edit fails
  - range: 2+ ranges matched (replace_all=false) → set replace_all=true or use more specific markers
  - File does not exist → error telling caller to use Write first
  - Strings identical (exact/regex) → error, nothing to change""",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    # 逻辑路径（ws:/fork:/fix:/skills: 前缀）。
                    "description": "Logical path (ws:/fork:/fix:/skills: prefix).",
                },
                "new_string": {
                    "type": "string",
                    # 替换文本（使用 '' 表示删除）。
                    "description": "Replacement text (use '' to delete).",
                },
                "match_mode": {
                    "type": "string",
                    # 匹配模式：exact（精确匹配，默认）、regex（正则匹配）、range（首尾标记区间）。
                    "enum": ["exact", "regex", "range"],
                    "description": "Matching mode: 'exact' (default, precise string match), 'regex' (old_string as Python regex), 'range' (replace from start_marker to nearest end_marker, inclusive).",
                    "default": "exact",
                },
                "old_string": {
                    "type": "string",
                    # exact 模式下为要查找的精确文本；regex 模式下为正则 pattern。range 模式下忽略。
                    "description": "Text to find (exact mode) or regex pattern (regex mode). Ignored in range mode.",
                },
                "start_marker": {
                    "type": "string",
                    # range 模式下区间起始标记。exact/regex 模式下忽略。
                    "description": "Range start marker. The region from this marker to the nearest end_marker (inclusive) is replaced. Only used when match_mode='range'.",
                },
                "end_marker": {
                    "type": "string",
                    # range 模式下区间结束标记。exact/regex 模式下忽略。
                    "description": "Range end marker. Only used when match_mode='range'. The region from start_marker to the nearest end_marker (inclusive) is replaced.",
                },
                "replace_all": {
                    "type": "boolean",
                    # 如为 true，替换所有匹配项而非仅替换第一处（默认 false，所有模式通用）。
                    "description": "If true, replace ALL matches instead of just the first one (default false, applies to all modes).",
                    "default": False,
                },
            },
            "required": ["path", "new_string"],
        },
    },
    handler=_handle_edit,
    danger_level=ToolDangerLevel.write,
)



# -- Copy
def _handle_copy(
    args: dict[str, Any],
    context: ToolContext | None = None,
) -> dict:
    source: str = str(args.get("source", "")).strip()
    destination: str = str(args.get("destination", "")).strip()
    if not source:
        return tool_error("source is required")
    if not destination:
        return tool_error("destination is required")
    try:
        resolved = _s().resolve_read(source)
        if not resolved.real.exists():
            return tool_error("Source not found", source=source)
        is_directory = resolved.real.is_dir()
        _track_agentspace_access(
            context,
            [(source, is_directory), (destination, is_directory)],
        )
        if resolved.real.is_file():
            _s().copy(source, destination)
        elif resolved.real.is_dir():
            _s().copy_folder(source, destination)
        else:
            return tool_error("Source must be a file or directory", source=source)
        return tool_result(success=True, source=source, destination=destination)
    except Exception as exc:
        return tool_error(str(exc), source=source, destination=destination)


# -- copy_file
# 复制文件或目录。源路径和目标路径均需使用命名空间前缀（ws:、fork:、fix:、skills:）。
# 支持跨命名空间复制（如从 fork: 复制到 ws:）。
# 根据源路径类型自动分流：
#   - 文件分支：目标已存在则被覆盖。
#   - 目录分支：递归复制整个目录树，目标路径必须**不存在**（shutil.copytree 限制），需先 Delete 再 Copy。
#
# ## 前置条件
# - 源文件或目录必须存在。
# - 目标路径不能与源路径相同。
# - 目标路径所在命名空间必须是可写的。
#
# ## 调用效果
# 将源文件/目录复制到目标路径。文件分支目标已存在则覆盖；目录分支目标必须不存在。
# 返回 source 和 destination 确认路径。
#
# ## 返回
# ```json
# {"success": true, "source": "fork:src/a.py", "destination": "ws:a.py"}
# ```
#
# ## 何时使用
# - 在不同命名空间之间复制文件/目录（如从 fork: 复制到 ws:）。
# - 备份文件/目录到同一命名空间下的不同路径。
#
# ## 副作用/注意
# - 写入文件系统。文件分支目标已存在则被覆盖。
# - 目录分支目标路径必须**不存在**（与文件分支不同，copytree 不覆盖）。
# - 跨命名空间复制时，目标命名空间必须可写。
registry.register(
    name="Copy",
    toolset="filesystem",
    schema={
        "description": """Copy a file or directory. Both source and destination must use a namespace prefix (ws:, fork:, fix:, skills:). Supports cross-namespace copying (e.g. from fork: to ws:). The branch is auto-detected from the source type:
- **File branch**: copies a single file; the destination is overwritten if it already exists.
- **Directory branch**: recursively copies the whole directory tree; the destination must **not** already exist (shutil.copytree limitation) — delete it first with Delete if needed.

## Prerequisites
- The source file or directory must exist.
- The destination must not be the same path as the source.
- The destination namespace must be writable.

## Effect
Copies the source file/directory to the destination path. File branch overwrites an existing destination; directory branch requires the destination to not exist. Returns both source and destination paths for confirmation.

## Returns
```json
{"success": true, "source": "fork:src/a.py", "destination": "ws:a.py"}
```

## When to Use
- Copy files/directories between different namespaces (e.g. from fork: to ws:).
- Back up files/directories to a different path within the same namespace.

## Side Effects / Notes
- Writes to the file system. File branch overwrites the destination if it already exists.
- Directory branch requires the destination to **not** exist (unlike the file branch, copytree does not overwrite).
- Cross-namespace copy requires a writable destination namespace.""",
        "parameters": {
            "type": "object",
            "properties": {
                "source": {
                    "type": "string",
                    # 要复制的源文件/目录逻辑路径（命名空间前缀 + 路径）。
                    "description": "Source file/directory logical path (namespace prefix + path).",
                },
                "destination": {
                    "type": "string",
                    # 目标文件/目录逻辑路径（命名空间前缀 + 路径）。目录分支时目标必须不存在。
                    "description": "Destination file/directory logical path (namespace prefix + path). Must not exist for the directory branch.",
                },
            },
            "required": ["source", "destination"],
        },
    },
    handler=_handle_copy,
    danger_level=ToolDangerLevel.write,
)




# -- move_file
def _handle_move(
    args: dict[str, Any],
    context: ToolContext | None = None,
) -> dict:
    source: str = str(args.get("source", "")).strip()
    destination: str = str(args.get("destination", "")).strip()
    if not source:
        return tool_error("source is required")
    if not destination:
        return tool_error("destination is required")
    try:
        resolved = _s().resolve_read(source)
        if not resolved.real.exists():
            return tool_error("Source not found", source=source)
        is_directory = resolved.real.is_dir()
        _track_agentspace_access(
            context,
            [(source, is_directory), (destination, is_directory)],
        )
        _s().move(source, destination)
        return tool_result(success=True, source=source, destination=destination)
    except Exception as exc:
        return tool_error(str(exc), source=source, destination=destination)


# -- Move
# 移动或重命名文件/目录。目标路径可包含新名称，从而实现重命名。
# 源和目标路径均需使用命名空间前缀（ws:、fork:、fix:、skills:）。
# 支持跨命名空间移动（实现为复制+删除，非原子操作）。
#
# ## 前置条件
# - 源文件或目录必须存在。
# - 目标路径所在命名空间必须是可写的。
#
# ## 调用效果
# 将源文件或目录移动到目标路径。如果目标路径包含不同的文件名，同时完成重命名。
# 如果目标已存在且为文件，会被覆盖。
#
# ## 返回
# ```json
# {"success": true, "source": "ws:src/old.py", "destination": "ws:src/new.py"}
# ```
#
# ## 何时使用
# - 将文件/目录移动到不同路径。
# - 同时移动并重命名文件。
# - 整理目录结构。
#
# ## 副作用/注意
# - 写入文件系统。目标已存在则被覆盖。
# - 源路径在移动后不再存在。
# - 跨命名空间移动使用 shutil.move（内部复制后删除），不是原子操作。
registry.register(
    name="Move",
    toolset="filesystem",
    schema={
        "description": """Move or rename a file/directory. The destination can include a new name, effectively renaming. Both source and destination must use a namespace prefix (ws:, fork:, fix:, skills:). Supports cross-namespace moving (implemented as copy + delete, not atomic).

## Prerequisites
- The source file or directory must exist.
- The destination namespace must be writable.

## Effect
Moves a file or directory to the destination path. If the destination includes a different filename, the move also acts as a rename. If the destination already exists and is a file, it will be overwritten.

## Returns
```json
{"success": true, "source": "ws:src/old.py", "destination": "ws:src/new.py"}
```

## When to Use
- Move files/directories to a different path.
- Move and rename a file in one operation.
- Reorganize directory structure.

## Side Effects / Notes
- Writes to the file system. Overwrites destination if it already exists.
- The source path no longer exists after the move.
- Cross-namespace moves use shutil.move (copy + delete internally), not atomic.""",
        "parameters": {
            "type": "object",
            "properties": {
                "source": {
                    "type": "string",
                    # 要移动的源文件/目录逻辑路径。
                    "description": "Source file/directory logical path.",
                },
                "destination": {
                    "type": "string",
                    # 目标路径（可包含新文件名）。
                    "description": "Destination path (can include a new filename).",
                },
            },
            "required": ["source", "destination"],
        },
    },
    handler=_handle_move,
    danger_level=ToolDangerLevel.write,
)




# -- search_files
def _handle_search_files(args: dict[str, Any]) -> dict:
    path: str = str(args.get("path", "")).strip()
    pattern: str = str(args.get("pattern", "")).strip()
    limit: int = int(args.get("limit", 100))

    if not path:
        return tool_error("path is required")
    if not pattern:
        return tool_error("pattern is required")

    try:
        resolved = _s().resolve_read(path)
    except SandboxError as exc:
        return tool_error(str(exc), path=path)

    if not resolved.real.is_dir():
        return tool_error(f"Not a directory: {path}")

    matches: list[str] = []
    for p in resolved.real.rglob(pattern):
        if p.is_file():
            rel = p.relative_to(resolved.real).as_posix()
            matches.append(f"{resolved.namespace}:{rel}")

    count = len(matches)
    if count > limit:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        log_name = f"ws:logs/search_files_{timestamp}.log"
        log_content = (
            f"# search_files results for {path} pattern={pattern}\n"
            f"Total: {count} matches\n\n"
            + "\n".join(matches)
        )
        try:
            _s().write(log_name, log_content)
        except SandboxError as exc:
            return tool_error(str(exc))
        return tool_result(
            count=count,
            log_path=log_name,
            _note=f"Results exceeded {limit} matches. Full list written to log file.",
        )

    return tool_result(matches=matches, count=count)


# -- search_files
# 按文件名 glob 模式递归搜索目录中的文件。返回匹配文件的逻辑路径列表。
# 使用 glob 模式（如 *.py、**/test_*.py），不是正则表达式。
# 结果超过 limit 时自动写入 ws:logs/ 下的日志文件，仅返回数量和日志路径。
#
# ## 前置条件
# - 搜索路径必须是一个存在的目录。
# - 路径必须使用命名空间前缀。
#
# ## 调用效果
# 递归遍历目录，查找文件名匹配 glob pattern 的文件。
# 返回匹配文件的逻辑路径列表（如 ws:src/main.py）。
# 结果超过 limit 条时，完整列表写入 ws:logs/search_files_<timestamp>.log。
#
# ## 返回
# 结果未超限时：
# ```json
# {"matches": ["ws:src/a.py", "ws:src/b.py"], "count": 2}
# ```
# 结果超限时：
# ```json
# {"count": 150, "log_path": "ws:logs/search_files_20250314_120000.log", "_note": "..."}
# ```
#
# ## 何时使用
# - 查找特定文件名的文件。
# - 确定目录结构中有哪些文件。
#
# ## 副作用/注意
# - 无副作用，只读查询。
# - 使用 glob 模式（如 *.py），不是正则表达式。
# - 结果超过 limit（默认 100）时写入日志文件，不直接返回完整列表。
# - 不搜索文件内容（使用 Grep）。
registry.register(
    name="SearchFiles",
    toolset="filesystem",
    schema={
        "description": """Recursively search for files matching a filename glob pattern in a directory. Uses glob patterns (e.g. *.py, **/test_*.py), NOT regex. Returns a list of matching logical file paths. If results exceed the limit, the full list is written to a log file under ws:logs/ and only the count and log path are returned.

## Prerequisites
- The search path must be an existing directory.
- The path must use a namespace prefix.

## Effect
Recursively traverses the directory looking for files whose names match the glob pattern. Returns logical paths of matching files (e.g. ws:src/main.py). When results exceed the limit, the full list is written to ws:logs/search_files_<timestamp>.log.

## Returns
When results fit within the limit:
```json
{"matches": ["ws:src/a.py", "ws:src/b.py"], "count": 2}
```
When results exceed the limit:
```json
{"count": 150, "log_path": "ws:logs/search_files_20250314_120000.log", "_note": "..."}
```

## When to Use
- Find files by name pattern.
- Discover what files exist in a directory tree.

## Side Effects / Notes
- No side effects, read-only query.
- Uses glob patterns (e.g. *.py), NOT regex.
- Results exceeding the limit (default 100) are written to a log file instead of returned inline.
- For searching file contents, use Grep.""",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    # 要搜索的目录逻辑路径（如 'ws:'、'fork:src'）。必须使用命名空间前缀。
                    "description": "Directory logical path to search in (e.g. 'ws:', 'fork:src'). Must use a namespace prefix.",
                },
                "pattern": {
                    "type": "string",
                    # 文件名 glob 模式（如 '*.py'、'**/test_*.py'）。不是正则表达式。
                    "description": "Filename glob pattern (e.g. '*.py', '**/test_*.py'). NOT regex.",
                },
                "limit": {
                    "type": "integer",
                    # 内联返回的最大结果数（默认 100）。超出时写入日志文件。
                    "description": "Maximum number of results to return inline (default 100). Excess results are written to a log file.",
                    "default": 100,
                },
            },
            "required": ["path", "pattern"],
        },
    },
    handler=_handle_search_files,
)


# -- grep
_TEXT_EXTENSIONS: frozenset[str] = frozenset(
    {
        ".py", ".txt", ".md", ".json", ".yaml", ".yml", ".toml", ".csv",
        ".ini", ".cfg", ".conf", ".js", ".ts", ".jsx", ".tsx", ".css",
        ".html", ".htm", ".xml", ".sh", ".bat", ".ps1", ".rs", ".go",
        ".java", ".c", ".cpp", ".h", ".hpp", ".rb", ".php", ".swift",
        ".kt", ".scala", ".sql", ".rst", ".log",
    }
)


def _is_text_file(path: Any) -> bool:
    """通过扩展名和空字节探测判断是否为文本文件。"""
    if path.suffix.lower() in _TEXT_EXTENSIONS:
        return True
    try:
        sample: bytes = path.read_bytes()[:FILE_SNIFF_BYTES]
        return b"\x00" not in sample
    except Exception:
        logger.warning("Failed to sniff file type: %s", path, exc_info=True)
        return False


def _handle_grep(
    args: dict[str, Any],
    context: ToolContext | None = None,
) -> dict:
    path: str = str(args.get("path", "")).strip()
    pattern: str = str(args.get("pattern", "")).strip()
    limit: int = int(args.get("limit", 100))
    max_file_size: int = int(args.get("max_file_size", 524_288_000))
    context_lines: int = int(args.get("context_lines", 2))

    if not path:
        return tool_error("path is required")
    if not pattern:
        return tool_error("pattern is required")

    try:
        resolved = _s().resolve_read(path)
    except SandboxError as exc:
        return tool_error(str(exc), path=path)

    # 收集待搜索文件列表：文件直接搜索，目录递归搜索
    files: list[Path] = []
    if resolved.real.is_file():
        try:
            _track_agentspace_access(context, [(path, False)])
        except Exception as exc:
            return tool_error(f"Agentspace access lock failed: {exc}", path=path)
        files = [resolved.real]
    elif resolved.real.is_dir():
        files = [p for p in resolved.real.rglob("*") if p.is_file()]
    else:
        return tool_error(f"Not a file or directory: {path}")

    try:
        regex = re.compile(pattern)
    except re.error as exc:
        return tool_error(f"Invalid regex pattern: {exc}")

    matches: list[dict[str, Any]] = []
    for p in files:
        if p.stat().st_size > max_file_size:
            continue
        if not _is_text_file(p):
            continue

        try:
            content = p.read_text(encoding="utf-8", errors="replace")
        except Exception:
            logger.warning("Failed to read file for search: %s", p, exc_info=True)
            continue

        lines = content.splitlines()
        for i, line in enumerate(lines):
            if regex.search(line):
                if resolved.real.is_file():
                    file_path = path
                else:
                    rel = p.relative_to(resolved.real).as_posix()
                    file_path = f"{resolved.namespace}:{rel}"
                matches.append(
                    {
                        "file": file_path,
                        "line": i + 1,
                        "match": line,
                        "context_before": lines[max(0, i - context_lines) : i],
                        "context_after": lines[i + 1 : i + 1 + context_lines],
                    }
                )

    count = len(matches)
    if count > limit:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        log_name = f"ws:logs/grep_{timestamp}.log"
        out_lines = [
            f"# grep results for {path} pattern={pattern}",
            f"Total: {count} matches",
            "",
        ]
        for m in matches:
            out_lines.append(f"{m['file']}:{m['line']}:{m['match']}")
            if m["context_before"]:
                for cb in m["context_before"]:
                    out_lines.append(f"  - {cb}")
            if m["context_after"]:
                for ca in m["context_after"]:
                    out_lines.append(f"  + {ca}")
            out_lines.append("")
        try:
            _s().write(log_name, "\n".join(out_lines))
        except SandboxError as exc:
            return tool_error(str(exc))
        return tool_result(
            count=count,
            log_path=log_name,
            _note=f"Results exceeded {limit} matches. Full list written to log file.",
        )

    return tool_result(matches=matches, count=count)


# -- grep
# 在目录或单个文件中按正则表达式递归搜索文本文件的内容。
# 自动跳过二进制文件（通过扩展名 + 空字节探测）和超大文件。
# 返回匹配项的文件路径、行号、匹配文本及周围上下文行。
# 结果超过 limit 时自动写入 ws:logs/ 下的日志文件。
#
# ## 前置条件
# - 搜索路径必须是一个存在的目录或文件。
# - 路径必须使用命名空间前缀。
# - pattern 必须是有效的 Python 正则表达式。
#
# ## 调用效果
# 当路径为目录时递归遍历其中的文本文件，当路径为文件时只搜索该文件。
# 用正则表达式搜索内容。自动跳过二进制文件（通过白名单扩展名 + 前 {FILE_SNIFF_BYTES} 字节的空字节探测）、
# 超过 max_file_size 字节的文件、以及无法以 UTF-8 解码的文件。
# 每条匹配返回文件路径、行号、匹配行文本、前后上下文行。
# 结果超过 limit 条时，完整列表写入 ws:logs/grep_<timestamp>.log。
#
# ## 返回
# 结果未超限时：
# ```json
# {"matches": [{"file": "ws:src/main.py", "line": 42, "match": "def foo():", "context_before": [...], "context_after": [...]}], "count": 2}
# ```
# 结果超限时：
# ```json
# {"count": 150, "log_path": "ws:logs/grep_20250314_120000.log", "_note": "..."}
# ```
#
# ## 何时使用
# - 在代码库中搜索特定函数、变量、错误信息等。
# - 配合 Read 使用，根据 grep 结果的行号读取文件。
#
# ## 副作用/注意
# - 无副作用，只读查询。
# - pattern 是 Python 正则表达式，不是 glob 模式。
# - 自动跳过二进制文件和超大文件。
# - 结果超过 limit（默认 100）时写入日志文件。
# - 按文件名搜索使用 SearchFiles。
registry.register(
    name="Grep",
    toolset="filesystem",
    schema={
        "description": f"""Recursively search text file contents using a regex pattern in a directory or a single file. Automatically skips binary files (by extension + null-byte sniffing) and oversized files. Returns matches with file path, line number, matched text, and surrounding context lines. If results exceed the limit, the full list is written to a log file under ws:logs/.

## Prerequisites
- The search path must be an existing directory or file.
- The path must use a namespace prefix.
- The pattern must be a valid Python regex.

## Effect
When the path is a directory, recursively traverses text files in it; when it is a single file, searches only that file. Searches contents with a regex pattern. Automatically skips binary files (via allowlist extension + null-byte probe on first {FILE_SNIFF_BYTES} bytes), files larger than max_file_size, and files that cannot be decoded as UTF-8. Each match returns file path, line number, matched line text, and surrounding context lines. When results exceed the limit, the full list is written to ws:logs/grep_<timestamp>.log.

## Returns
When results fit within the limit:
```json
{{"matches": [{{"file": "ws:src/main.py", "line": 42, "match": "def foo():", "context_before": [...], "context_after": [...]}}], "count": 2}}
```
When results exceed the limit:
```json
{{"count": 150, "log_path": "ws:logs/grep_20250314_120000.log", "_note": "..."}}
```

## When to Use
- Search for specific functions, variables, error messages, etc. in a codebase.
- Use with Read by line number from grep results.

## Side Effects / Notes
- No side effects, read-only query.
- Pattern is a Python regex, NOT a glob pattern.
- Automatically skips binary files and oversized files.
- Results exceeding the limit (default 100) are written to a log file.
- For searching by filename, use SearchFiles.""",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    # 要搜索的目录或文件逻辑路径（如 'ws:'、'fork:src'、'ws:eve-site.html'）。必须使用命名空间前缀。
                    "description": "Directory or file logical path to search in (e.g. 'ws:', 'fork:src', 'ws:eve-site.html'). Must use a namespace prefix.",
                },
                "pattern": {
                    "type": "string",
                    # 用于匹配文件内容的正则表达式。
                    "description": "Regex pattern to search for in file contents.",
                },
                "limit": {
                    "type": "integer",
                    # 内联返回的最大结果数（默认 100）。超出时写入日志文件。
                    "description": "Maximum number of results to return inline (default 100). Excess results are written to a log file.",
                    "default": 100,
                },
                "max_file_size": {
                    "type": "integer",
                    # 跳过大于此字节数的文件（默认 524288000 = 500MB）。
                    "description": "Skip files larger than this many bytes (default 524288000 = 500MB).",
                    "default": 524288000,
                },
                "context_lines": {
                    "type": "integer",
                    # 每条匹配结果前后包含的上下文行数（默认 2）。
                    "description": "Number of context lines to include before and after each match (default 2).",
                    "default": 2,
                },
            },
            "required": ["path", "pattern"],
        },
    },
    handler=_handle_grep,
)

