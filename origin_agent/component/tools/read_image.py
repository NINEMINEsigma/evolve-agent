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
except Exception:  # pragma: no cover — PIL is optional
    logger.debug("PIL not available; image size parsing disabled", exc_info=True)
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
        logger.warning("Failed to parse image dimensions", exc_info=True)
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
        # 读取图片文件并返回其内容和元数据。
        # 前置条件：图片存在于 agentspace（ws: 或 fork: 命名空间）。支持 PNG/JPEG/WebP/GIF/BMP/TIFF/SVG，最大 20MB。
        # 调用效果：只读操作，不修改任何文件。
        # 返回：{ path, mime_type, size, width, height, _image: { base64, mime_type }, _note }。width/height 通过 Pillow 解析（SVG 或解析失败时为 null）。
        # _image 载荷：AgentLoop 自动根据模型 vision 能力处理 — 支持时作为多模态 content block 送入 LLM，不支持时清理并以文本元数据形式提供。
        # 典型场景：查看用户上传的截图/图片；分析图片内容（需 vision 模型）。
        # 注意：path 必须包含命名空间前缀（如 'ws:uploads/screenshot.png'），否则沙箱无法解析。
        "description": """Read an image file and return its content and metadata.

## Prerequisites
Image must exist in agentspace (ws: or fork: namespace). Supported formats: PNG, JPEG, WebP, GIF, BMP, TIFF, SVG. Maximum file size: 20 MB.

## Effect
Read-only. Does not modify any files.

## Returns
```json
{
  "path": "<logical path>",
  "mime_type": "image/png",
  "size": 12345,
  "width": 800,
  "height": 600,
  "_image": { "base64": "...", "mime_type": "image/png" },
  "_note": "Image metadata returned. width/height are parsed via Pillow..."
}
```
`width`/`height` are parsed via Pillow; `null` for SVG or on parse failure.

## How `_image` Works
The AgentLoop automatically handles the `_image` payload based on model capability:
- **Vision-capable model**: the image is attached as a multimodal content block for direct visual analysis.
- **Non-vision model**: `_image` is stripped and only text metadata (path, mime_type, size, width, height) is provided.

The agent does not need to handle this distinction.

## When to Use
- Viewing user-uploaded screenshots or images.
- Analyzing image content (requires a vision-capable model).

## Side Effects / Notes
Path must include a namespace prefix (e.g. `ws:uploads/screenshot.png`); otherwise sandbox resolution fails. Uploaded files are located under `ws:uploads/`.""",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    # 图片文件的逻辑路径。必须包含命名空间前缀（ws:、fork: 或 fix:）。上传文件位于 'ws:uploads/'。
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