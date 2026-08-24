"""ReadForward 工具 — 拟态 Read，转发多模态文件给指定 LLM 配置。

读取图片/音频/视频文件，将内容 base64 编码后连同 agent 提供的自定义 prompt
转发给指定名称的 LLM 配置（按 LLMProfile.name 查找），返回该 AI 的响应文本。

弥补现有 ``forward_modality_to_ref_profile`` 使用固定模板 prompt、
无法让 agent 表达具体分析需求的缺陷。

模块导入时通过 ``registry.register()`` 注册，由 AST 扫描自动发现。
路径解析通过 ``Application.current().sandbox`` 获取共享的 ``Sandbox`` 实例。
"""

from __future__ import annotations

import base64
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

# ── 多模态 content block 构造（与 Read 工具多模态分支共用） ──
from system.modality_capability import (
    build_image_content_blocks,
    build_audio_content_blocks,
    build_video_content_blocks,
)

# ── LLM Profile 加载与客户端创建 ──
from system.llm_profile_store import load_profiles
from abstract.llm.loader import create_llm_client

# ── 消息类型 ──
from entity.messages import BaseMessage
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


# ---------------------------------------------------------------------------
# 工具 handler
# ---------------------------------------------------------------------------

async def _handle_read_forward(
    args: dict[str, Any],
    context: ToolContext | None = None,
) -> dict:
    # 读取图片/音频/视频文件，转发给指定 LLM 配置并附加自定义 prompt，返回 AI 响应文本。
    path: str = str(args.get("path", "")).strip()
    profile_name: str = str(args.get("profile_name", "")).strip()
    prompt: str = str(args.get("prompt", "")).strip()

    # ── 步骤 a：参数校验 ──
    if not path:
        return tool_error("path is required")
    if not profile_name:
        return tool_error("profile_name is required")
    if not prompt:
        return tool_error("prompt is required")

    # ── 步骤 b：路径解析 ──
    try:
        resolved = _s().resolve_read(path)
    except SandboxError as exc:
        return tool_error(str(exc), path=path)

    if not resolved.real.exists():
        return tool_error("Path not found", path=path)

    if resolved.real.is_dir():
        return tool_error(
            "ReadForward only supports image/audio/video files, not directories",
            path=path,
        )

    # ── 步骤 c：MIME 探测与分流 ──
    mime_type: str = _guess_mime(str(resolved.real))

    if mime_type in _SUPPORTED_MIMES:
        max_size = _MAX_IMAGE_SIZE
        media_type = "image"
    elif mime_type in _SUPPORTED_AUDIO_MIMES:
        max_size = _MAX_AUDIO_SIZE
        media_type = "audio"
    elif mime_type in _SUPPORTED_VIDEO_MIMES:
        max_size = _MAX_VIDEO_SIZE
        media_type = "video"
    else:
        return tool_error(
            "Unsupported file type: only image/audio/video files are supported",
            path=path,
            mime_type=mime_type,
        )

    # ── 步骤 d：读取文件 + 大小检查 + base64 编码 ──
    file_size: int = resolved.real.stat().st_size
    if file_size > max_size:
        return tool_error(
            f"File too large: {file_size} bytes (max {max_size})",
            path=path,
            size=file_size,
        )

    try:
        raw_bytes: bytes = resolved.real.read_bytes()
    except Exception as exc:
        return tool_error(f"Failed to read file: {exc}", path=path)

    b64: str = base64.b64encode(raw_bytes).decode("ascii")
    logger.info(
        "read_forward | path=%s mime=%s size=%d profile=%s",
        path, mime_type, file_size, profile_name,
    )

    # ── 步骤 e：按 profile_name 查找 LLMProfile ──
    ctx = context.runtime_context if context is not None else get_runtime_context()
    profiles = load_profiles(ctx.agentspace)
    ref_profile = next((p for p in profiles if p.name == profile_name), None)

    if ref_profile is None:
        available: str = ", ".join(p.name for p in profiles) or "(none)"
        return tool_error(
            f"LLM profile '{profile_name}' not found. Available profiles: {available}",
            profile_name=profile_name,
        )

    if not ref_profile.llm_client_name:
        return tool_error(
            f"Profile '{profile_name}' has no llm_client_name configured",
            profile_name=profile_name,
        )

    # ── 步骤 f：构造多模态 content blocks ──
    if media_type == "image":
        blocks = build_image_content_blocks(
            {"base64": b64, "mime_type": mime_type}, prompt,
        )
    elif media_type == "audio":
        audio_format: str = _AUDIO_FORMAT_MAP.get(mime_type, "wav")
        blocks = build_audio_content_blocks(
            {"base64": b64, "format": audio_format}, prompt,
        )
    else:  # video
        blocks = build_video_content_blocks(
            {"base64": b64, "mime_type": mime_type}, prompt,
        )

    # ── 步骤 g：构造消息 ──
    messages = [BaseMessage(role=Role.USER, content=blocks)]

    # ── 步骤 h：发送给指定 LLM 配置 ──
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
            "read_forward | path=%s profile=%s success",
            path, profile_name,
        )
        # ── 步骤 i：返回 AI 响应文本 ──
        return tool_result(content=content)
    except Exception as exc:
        logger.warning(
            "read_forward | path=%s profile=%s error=%s",
            path, profile_name, exc,
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
        # 读取图片/音频/视频文件，将内容连同自定义 prompt 转发给指定名称的 LLM 配置，
        # 返回该 AI 的响应文本。
        # 与 Read 工具的多模态分支类似，但区别在于：
        # - 按 profile_name（而非 uid）查找转发目标
        # - agent 传入自定义 prompt（而非固定模板 prompt）
        # - 直接返回 AI 响应文本（不包装转发标签、不做能力探测）
        # 仅支持图片/音频/视频文件，不支持文本文件和目录。
        # 支持命名空间前缀：ws:、fork:、fix:、skills: 及其他只读命名空间。
        #
        # ## 前置条件
        # - 路径必须存在且为文件（非目录）。
        # - 文件 MIME 必须在图片/音频/视频白名单内。
        # - profile_name 必须对应一个已存在的 LLMProfile。
        # - 该 profile 必须配置了 llm_client_name。
        #
        # ## 调用效果
        # 读取文件 → base64 编码 → 构造多模态 content blocks（媒体块 + TextBlock(prompt)）→
        # 按 profile_name 查找 LLMProfile → create_llm_client → client.chat → 返回响应文本。
        # 图片白名单：PNG/JPEG/WebP/GIF/BMP/TIFF/SVG（最大 20MB）。
        # 音频白名单：WAV/MP3（最大 25MB）。
        # 视频白名单：MP4（最大 50MB）。
        #
        # ## 返回
        # ```json
        # {"content": "AI response text"}
        # ```
        # 错误时返回 {"error": "..."}。
        #
        # ## 何时使用
        # - 需要让另一个 AI 配置分析图片/音频/视频内容，且需要自定义分析指令时。
        # - 弥补 Read 工具多模态转发使用固定模板 prompt 的限制。
        #
        # ## 副作用/注意
        # - 无文件系统副作用，纯查询 + LLM 调用。
        # - 转发目标 profile 的多模态能力由其自身决定，本工具不做事前探测。
        # - LLM 调用可能因网络、认证或模态不支持而失败。
        "description": """Read an image/audio/video file and forward it to a specified LLM profile with a custom prompt, returning the AI's response text. Unlike Read's multimodal forwarding (which uses a fixed template prompt), this tool lets you provide a custom analysis instruction.

## Prerequisites
- The path must exist and be a file (not a directory).
- The file MIME must be in the image/audio/video whitelist.
- profile_name must correspond to an existing LLMProfile.
- The profile must have an llm_client_name configured.

## Effect
Reads the file, base64-encodes the content, constructs multimodal content blocks (media block + TextBlock with your prompt), looks up the LLMProfile by name, creates an LLM client, sends the message, and returns the AI's response text.
Image whitelist: PNG, JPEG, WebP, GIF, BMP, TIFF, SVG (max 20 MB).
Audio whitelist: WAV, MP3 (max 25 MB).
Video whitelist: MP4 (max 50 MB).

## Returns
```json
{"content": "AI response text"}
```
On error: {"error": "..."}.

## When to Use
- When you need another AI profile to analyze image/audio/video content with a specific analysis instruction.
- To overcome Read's multimodal forwarding limitation of using a fixed template prompt.

## Side Effects / Notes
- No file system side effects; read-only query + LLM call.
- The target profile's multimodal capability is determined by itself; this tool does not probe beforehand.
- LLM calls may fail due to network, authentication, or unsupported modality.""",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    # 文件逻辑路径。必须使用命名空间前缀：fork:、ws:、fix: 或 skills:。
                    "description": "File logical path. "
                    "Must use a namespace prefix: fork:, ws:, fix:, or skills:.",
                },
                "profile_name": {
                    "type": "string",
                    # 转发目标 LLM 配置名（按 LLMProfile.name 查找）。
                    "description": "Name of the target LLM profile to forward to "
                    "(matched by LLMProfile.name).",
                },
                "prompt": {
                    "type": "string",
                    # 传给目标 AI 的分析指令文本。
                    "description": "The analysis instruction to send to the target AI "
                    "along with the file content.",
                },
            },
            "required": ["path", "profile_name", "prompt"],
        },
    },
    handler=_handle_read_forward,
    emoji="🔄",
    no_timeout=True,
    is_async=True,
    danger_level=ToolDangerLevel.safe,
)