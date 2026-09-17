"""ReadForward 工具 — 将多个多模态文件转发给指定 LLM Profile。

按 ``paths`` 顺序读取图片、音频和视频文件，在每个媒体块前加入包含
1-based 序号、逻辑路径和 MIME 类型的文本标签，最后只附加一次 Agent 提供的
自定义 prompt。全部内容通过同一条 user 消息和一次 LLM 调用发送。

工具执行原子校验：任意文件无效时整体失败，不向目标 Profile 发送部分内容。
工具生成的内容块 JSON 载荷不得超过 45 MiB；具体 LLM 客户端必须完整发送
收到的多模态块，无法支持时自行抛出异常，本工具不假定客户端能力。

模块导入时通过 ``registry.register()`` 注册，由 AST 扫描自动发现。
路径解析通过 ``Application.current().sandbox`` 获取共享的 ``Sandbox`` 实例。
"""

from __future__ import annotations

import base64
import json
import logging
from typing import Any, TYPE_CHECKING

# ── 复用 filesystem 的 MIME 常量与探测函数 ──
from component.tools.filesystem import (
    _guess_mime,
    _SUPPORTED_MIMES,
    _SUPPORTED_AUDIO_MIMES,
    _SUPPORTED_VIDEO_MIMES,
    _MAX_IMAGE_SIZE,
    _MAX_AUDIO_SIZE,
    _MAX_VIDEO_SIZE,
    _AUDIO_FORMAT_MAP,
)

# ── 共享的单媒体 content block 构造 ──
from system.modality_capability import build_media_content_block

# ── LLM 客户端创建 ──
from abstract.llm.loader import create_llm_client

# ── 消息类型与载荷上限 ──
from entity.constant import READ_FORWARD_MAX_PAYLOAD_BYTES
from entity.messages import BaseMessage, MessageBlock, TextBlock
from entity.puretype import Role, ToolDangerLevel

# ── 工具注册 ──
from abstract.tools.registry import registry, tool_error, tool_result

# ── 沙箱与运行时上下文 ──
from system.sandbox import SandboxError
from system.context import get_runtime_context

if TYPE_CHECKING:
    from entry.base_agent_loop import ToolContext

logger = logging.getLogger(__name__)


def _s():
    """委托到 Application.sandbox property。"""
    from system.application import Application
    return Application.current().sandbox


def _classify_media(mime_type: str) -> tuple[str, int] | None:
    """把支持的 MIME 映射为媒体类型与对应的单文件字节上限。"""
    if mime_type in _SUPPORTED_MIMES:
        return "image", _MAX_IMAGE_SIZE
    if mime_type in _SUPPORTED_AUDIO_MIMES:
        return "audio", _MAX_AUDIO_SIZE
    if mime_type in _SUPPORTED_VIDEO_MIMES:
        return "video", _MAX_VIDEO_SIZE
    return None


def _base64_encoded_size(raw_size: int) -> int:
    """计算裸 Base64 字符数，仅作为最终 JSON 载荷的安全下界预检。"""
    return 4 * ((raw_size + 2) // 3)


def _measure_content_payload(blocks: list[MessageBlock]) -> int:
    """按紧凑 JSON 数组口径计算内容块载荷的 UTF-8 字节数。

    逐块调用 ``as_object()`` 计量，包含 data URL、标签、prompt、JSON 键名、
    转义、数组括号与块间逗号；不构造完整请求 JSON 副本。
    """
    payload_size = 2  # JSON 数组的 []
    for index, block in enumerate(blocks):
        if index:
            payload_size += 1  # 块间逗号
        serialized = json.dumps(
            block.as_object(),
            ensure_ascii=False,
            separators=(",", ":"),
        )
        payload_size += len(serialized.encode("utf-8"))
    return payload_size


# ---------------------------------------------------------------------------
# 工具 handler
# ---------------------------------------------------------------------------

async def _handle_read_forward(
    args: dict[str, Any],
    context: ToolContext | None = None,
) -> dict:
    # 读取多个图片/音频/视频文件，通过一条 user 消息转发给指定 LLM Profile。
    raw_paths = args.get("paths")
    profile_name: str = str(args.get("profile_name", "")).strip()
    prompt: str = str(args.get("prompt", "")).strip()

    # ── 步骤 a：参数校验 ──
    if not isinstance(raw_paths, list) or not raw_paths:
        return tool_error("paths must be a non-empty array of strings")

    paths: list[str] = []
    for index, raw_path in enumerate(raw_paths, start=1):
        if not isinstance(raw_path, str) or not raw_path.strip():
            return tool_error(
                "Each item in paths must be a non-empty string",
                index=index,
                path=raw_path if isinstance(raw_path, str) else "",
            )
        paths.append(raw_path.strip())

    if not profile_name:
        return tool_error("profile_name is required")
    if not prompt:
        return tool_error("prompt is required")

    # ── 步骤 b：原子元数据校验，不读取文件正文 ──
    # (index, logical_path, resolved_path, mime_type, media_type, file_size, max_size)
    validated_files: list[tuple[int, str, Any, str, str, int, int]] = []
    for index, path in enumerate(paths, start=1):
        try:
            resolved = _s().resolve_read(path)
        except SandboxError as exc:
            return tool_error(str(exc), index=index, path=path)

        try:
            if not resolved.real.exists():
                return tool_error("Path not found", index=index, path=path)
            if resolved.real.is_dir():
                return tool_error(
                    "ReadForward only supports image/audio/video files, not directories",
                    index=index,
                    path=path,
                )

            mime_type: str = _guess_mime(str(resolved.real))
            classification = _classify_media(mime_type)
            if classification is None:
                return tool_error(
                    "Unsupported file type: only image/audio/video files are supported",
                    index=index,
                    path=path,
                    mime_type=mime_type,
                )

            media_type, max_size = classification
            file_size: int = resolved.real.stat().st_size
        except Exception as exc:
            return tool_error(
                f"Failed to inspect file: {exc}",
                index=index,
                path=path,
            )

        if file_size <= 0:
            return tool_error(
                "Empty media file is not supported",
                index=index,
                path=path,
                size=file_size,
            )
        if file_size > max_size:
            return tool_error(
                f"File too large: {file_size} bytes (max {max_size})",
                index=index,
                path=path,
                mime_type=mime_type,
                size=file_size,
                max_size=max_size,
            )

        validated_files.append(
            (index, path, resolved, mime_type, media_type, file_size, max_size)
        )

    # ── 步骤 c：按 profile_name 从共享根对象取得 LLMProfile ──
    ctx = context.runtime_context if context is not None else get_runtime_context()
    from system.application import Application
    try:
        ref_profile = Application.current().llm_profile_store.get_profile(profile_name)
    except LookupError as exc:
        return tool_error(str(exc), profile_name=profile_name)

    if not ref_profile.llm_client_name:
        return tool_error(
            f"Profile '{profile_name}' has no llm_client_name configured",
            profile_name=profile_name,
        )

    # ── 步骤 d：裸 Base64 下界预检；通过后仍必须执行最终精确计量 ──
    minimum_payload_size = sum(
        _base64_encoded_size(file_size)
        for _, _, _, _, _, file_size, _ in validated_files
    )
    if minimum_payload_size > READ_FORWARD_MAX_PAYLOAD_BYTES:
        return tool_error(
            "ReadForward payload exceeds the 45 MiB limit",
            minimum_payload_size=minimum_payload_size,
            max_payload_size=READ_FORWARD_MAX_PAYLOAD_BYTES,
        )

    # ── 步骤 e：按原顺序读取、编码并构造“标签 + 媒体”块 ──
    blocks: list[MessageBlock] = []
    for index, path, resolved, mime_type, media_type, _, max_size in validated_files:
        try:
            raw_bytes: bytes = resolved.real.read_bytes()
        except Exception as exc:
            return tool_error(
                f"Failed to read file: {exc}",
                index=index,
                path=path,
            )

        if not raw_bytes:
            return tool_error(
                "Media file became empty while reading",
                index=index,
                path=path,
            )
        if len(raw_bytes) > max_size:
            return tool_error(
                f"File too large after reading: {len(raw_bytes)} bytes (max {max_size})",
                index=index,
                path=path,
                mime_type=mime_type,
                size=len(raw_bytes),
                max_size=max_size,
            )

        b64: str = base64.b64encode(raw_bytes).decode("ascii")
        label = f"File {index}: {path} ({mime_type})"
        blocks.append(TextBlock(text=label))

        if media_type == "audio":
            media_data = {
                "base64": b64,
                "format": _AUDIO_FORMAT_MAP.get(mime_type, "wav"),
            }
        else:
            media_data = {"base64": b64, "mime_type": mime_type}

        media_block = build_media_content_block(media_data, media_type)
        if media_block is None:
            return tool_error(
                "Failed to construct media content block",
                index=index,
                path=path,
                mime_type=mime_type,
            )
        blocks.append(media_block)

    blocks.append(TextBlock(text=prompt))

    # ── 步骤 f：最终实际内容块 JSON 载荷是唯一权威判定 ──
    payload_size = _measure_content_payload(blocks)
    if payload_size > READ_FORWARD_MAX_PAYLOAD_BYTES:
        return tool_error(
            "ReadForward payload exceeds the 45 MiB limit",
            payload_size=payload_size,
            max_payload_size=READ_FORWARD_MAX_PAYLOAD_BYTES,
        )

    logger.info(
        "read_forward | files=%d payload=%d profile=%s",
        len(validated_files), payload_size, profile_name,
    )

    # ── 步骤 g：构造唯一 user 消息并执行一次 LLM 调用 ──
    messages = [BaseMessage(role=Role.USER, content=blocks)]
    try:
        client = create_llm_client(ref_profile.llm_client_name, ctx, ref_profile)
        response = await client.chat(messages)
        content: str = response.content or ""
        if not content.strip():
            return tool_error(
                f"Profile '{profile_name}' returned an empty response",
                profile_name=profile_name,
            )
        logger.info(
            "read_forward | files=%d payload=%d profile=%s success",
            len(validated_files), payload_size, profile_name,
        )
        return tool_result(content=content)
    except Exception as exc:
        logger.warning(
            "read_forward | files=%d payload=%d profile=%s error=%s",
            len(validated_files), payload_size, profile_name, exc,
        )
        return tool_error(
            f"Forwarding failed: {type(exc).__name__}: {exc}",
            profile_name=profile_name,
        )


# ---------------------------------------------------------------------------
# 注册（模块导入时执行）
# ---------------------------------------------------------------------------

registry.register(
    name="ReadForward",
    toolset="read_forward",
    schema={
        # 按 paths 顺序读取多个图片/音频/视频文件，通过同一条 user 消息和一次
        # LLM 调用转发给指定 Profile。每个媒体块前会插入：
        # File <1-based index>: <logical path> (<MIME type>)
        # Agent 应在 prompt 中使用序号或逻辑路径准确引用文件。
        # 任意文件无效时整体失败，不发送部分内容。文件数量没有独立上限；
        # 最终工具生成内容块 JSON 总载荷不得超过 45 MiB。
        "description": """Read multiple image/audio/video files and forward them to a specified LLM profile in one user message and one LLM call, with one custom prompt appended after all media.

## Prerequisites
- `paths` must be a non-empty array of logical file paths. There is no separate file-count limit.
- Every path must exist, resolve to a file, and use a supported image/audio/video MIME type.
- Every individual file must satisfy its modality limit: images 20 MB, audio 25 MB, video 50 MB.
- The generated compact JSON content-block payload, including Base64 data, labels, and prompt, must not exceed 45 MiB.
- `profile_name` must identify an existing LLMProfile with `llm_client_name` configured.

## File Labels and Accurate References
Files preserve the exact `paths` order. Immediately before each media block, the target profile receives a text label in this format:
`File <1-based index>: <logical path> (<MIME type>)`
Use the file number or logical path in `prompt` when asking the target profile to compare or reference specific files.

## Effect
Validates every file before sending anything, reads and Base64-encodes all files in order, builds ordered `label + media` pairs, appends `prompt` exactly once, and sends all blocks in one user message through one `client.chat()` call. Images, audio, and video may be mixed in the same request. If any file is invalid, the entire call fails and no partial request is sent.

## Returns
```json
{"content": "AI response text"}
```
On error: `{"error": "..."}`. File-specific errors also identify the 1-based index and logical path.

## Side Effects / Notes
- Read-only file access plus one LLM call; no file-system writes.
- This tool does not probe modality support or assume any `custom_llm_client` implementation.
- A client must faithfully send every media block or raise an error; it must not silently drop or replace unsupported media.
- Mixed-modality support ultimately depends on the target client and provider, which may reject the request explicitly.""",
        "parameters": {
            "type": "object",
            "properties": {
                "paths": {
                    "type": "array",
                    "minItems": 1,
                    "items": {"type": "string"},
                    "description": "Ordered logical paths of image/audio/video files. Each file is labeled for the target profile as `File <1-based index>: <logical path> (<MIME type>)`; use these numbers or paths in `prompt` for accurate references. Namespace prefixes such as fork:, ws:, fix:, skills:, and available read-only namespaces are required.",
                },
                "profile_name": {
                    "type": "string",
                    "description": "Name of the target LLM profile to forward to (matched by LLMProfile.name).",
                },
                "prompt": {
                    "type": "string",
                    "description": "The single analysis instruction appended after all labeled media blocks. Refer to specific inputs by their `File N` label or logical path.",
                },
            },
            "required": ["paths", "profile_name", "prompt"],
        },
    },
    handler=_handle_read_forward,
    no_timeout=True,
    is_async=True,
    danger_level=ToolDangerLevel.safe,
)
