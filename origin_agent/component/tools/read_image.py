"""读取图片工具 — 从 agentspace 读取图片。

模块导入时通过 ``registry.register()`` 注册。

返回图片元数据（path、mime_type、size、width、height）以及内部的
``_image`` 载荷。AgentLoop 会根据当前模型是否支持 vision，将 ``_image``
自动转换为多模态 content block 送入 LLM，或在模型不支持时清理 ``_image``
并以文本形式提供图片元数据。agent 侧无需关心底层传输格式。
"""

from __future__ import annotations

import base64
import io
import logging
import mimetypes
from typing import Any, Dict, Optional, Tuple

from abstract.tools.registry import registry, tool_error
from system.sandbox import SandboxError
from .filesystem import _s

try:
    from PIL import Image as PILImage
except Exception:  # pragma: no cover
    PILImage = None  # type: ignore

logger = logging.getLogger(__name__)


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


def _parse_size(raw_bytes: bytes, mime_type: str) -> Tuple[Optional[int], Optional[int]]:
    """用 Pillow 解析图片宽高；SVG 返回 (None, None)。"""
    if mime_type == "image/svg+xml" or PILImage is None:
        return None, None
    try:
        with PILImage.open(io.BytesIO(raw_bytes)) as im:
            return im.width, im.height
    except Exception:
        return None, None


def _handle_read_image(args: dict[str, Any]) -> dict:
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

    width, height = _parse_size(raw_bytes, mime_type)
    logger.info("read_image | path=%s mime=%s size=%d w=%s h=%s", path, mime_type, file_size, width, height)

    return {
        "path": path,
        "mime_type": mime_type,
        "size": file_size,
        "width": width,
        "height": height,
        "_image": {
            "base64": b64,
            "mime_type": mime_type,
        },
        "_note": (
            # 返回图片元数据。width/height 通过 Pillow 解析；SVG 或解析失败时为 None。
            # 若当前模型支持 vision，图片内容会作为多模态 content block 直接送入 LLM，
            # 你可以直接查看并分析图片；若不支持 vision，你将只收到图片元数据文本，
            # 不会收到图片内容本身。
            "Image metadata returned. width/height are parsed via Pillow "
            "(None for SVG or on failure). If the model supports vision, "
            "the image content is attached as a multimodal block for direct analysis; "
            "otherwise you will receive only the text metadata without the image content."
        ),
    }


# ---------------------------------------------------------------------------
# 注册
# ---------------------------------------------------------------------------

registry.register(
    name="read_image",
    toolset="filesystem",
    schema={
        # Read an image file and return its contents.
        # If the model supports vision, the image is attached as a multimodal block for direct visual analysis.
        # If the model does not support vision, you will receive only the image metadata (path, format, size, width, height).
        # Path must use a namespace prefix, typically 'ws:' (agent workspace).
        # Example: 'ws:uploads/screenshot.png'.
        # Supported formats: PNG, JPEG, WebP, GIF, BMP, TIFF, SVG.
        # Maximum file size: 20MB.
        "description": """Read an image file and return its contents.

If the model supports vision, the image is attached as a multimodal block for direct visual analysis.
If the model does not support vision, you will receive only the image metadata (path, format, size, width, height).

Path must use a namespace prefix, typically 'ws:' (agent workspace). Example: 'ws:uploads/screenshot.png'.

Supported formats: PNG, JPEG, WebP, GIF, BMP, TIFF, SVG. Maximum file size: 20MB.""",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    # Logical path of the image file. Must include a namespace prefix (ws:, fork:, or fix:).
                    # Uploaded files are located under 'ws:uploads/'.
                    "description": """Logical path of the image file. Must include a namespace prefix (ws:, fork:, or fix:). Uploaded files are located under 'ws:uploads/'.""",
                },
            },
            "required": ["path"],
        },
    },
    handler=_handle_read_image,
    emoji="🖼️",
    no_timeout=True,
)