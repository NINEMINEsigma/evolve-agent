"""读取图片工具 — 从 agentspace 读取图片，返回 base64 编码数据。

模块导入时通过 ``registry.register()`` 注册。

始终返回 ``_image`` 键。agent 循环检测到此键后，
会将 ToolMessage 的 content 格式化为 OpenAI content blocks
（包含 ``image_url`` 块）。如果模型不支持 vision 导致 API 拒绝，
entry/agent.py 中的 ``_strip_image_blocks`` 会捕获错误、
剥离图片 block、用 text-only 消息重试，agent 会收到明确的错误提示。
"""

from __future__ import annotations

import base64
import json
import logging
import mimetypes
from typing import Any, Dict

from abstract.tools.registry import registry, tool_error
from system.sandbox import Sandbox, SandboxError

logger = logging.getLogger(__name__)

_sandbox: Sandbox | None = None


def set_sandbox(s: Sandbox) -> None:
    global _sandbox
    _sandbox = s


def _s() -> Sandbox:
    if _sandbox is None:
        raise RuntimeError("Sandbox not initialized — call set_sandbox() first")
    return _sandbox


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


def _guess_mime(path: str) -> str:
    mime, _ = mimetypes.guess_type(path)
    return mime or "application/octet-stream"


def _handle_read_image(args: Dict[str, Any]) -> str:
    path: str = str(args.get("path", "")).strip()
    if not path:
        return tool_error("path is required", path=path)

    try:
        resolved = _s().resolve_read(path)
    except SandboxError as exc:
        return tool_error(str(exc), path=path)

    if not resolved.real.is_file():
        return tool_error("File not found", path=path)

    file_size: int = resolved.real.stat().st_size
    mime_type: str = _guess_mime(str(resolved.real))

    if mime_type not in _SUPPORTED_MIMES:
        return tool_error(
            f"Unsupported image type: {mime_type}. "
            f"Supported: {', '.join(sorted(_SUPPORTED_MIMES))}",
            path=path,
            mime_type=mime_type,
        )

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

    logger.info("read_image | path=%s mime=%s size=%d", path, mime_type, file_size)

    return json.dumps({
        "path": path,
        "mime_type": mime_type,
        "size": file_size,
        "width": None,
        "height": None,
        "_image": {
            "base64": b64,
            "mime_type": mime_type,
        },
        "_note": (
            "图片已以 base64 编码返回。如果模型支持 vision，你可以直接查看并分析图片内容。"
            "如果 API 返回内容类型错误，系统会自动剥离图片并用纯文本重试，"
            "届时你会收到明确的错误提示。"
        ),
    }, ensure_ascii=False)


# ---------------------------------------------------------------------------
# 注册
# ---------------------------------------------------------------------------

registry.register(
    name="read_image",
    toolset="filesystem",
    schema={
        "description": (
            "读取图片文件并返回其内容。图片以 base64 编码返回。\n\n"
            "如果模型支持 vision，你可以直接查看图片内容进行视觉分析。\n"
            "如果模型不支持 vision，系统会自动处理错误并告知你。\n\n"
            "路径必须使用命名空间前缀，通常为 'ws:'（agent workspace）。"
            "示例：'ws:uploads/screenshot.png'。\n\n"
            "支持的格式：PNG、JPEG、WebP、GIF、BMP、TIFF、SVG。"
            "最大文件大小：20MB。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": (
                        "图片文件的逻辑路径。必须使用命名空间前缀（ws:、fork: 或 fix:）。"
                        "上传的文件位于 'ws:uploads/' 目录下。"
                    ),
                },
            },
            "required": ["path"],
        },
    },
    handler=_handle_read_image,
    emoji="🖼️",
)