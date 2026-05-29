"""Display image tool — publish a ws: image file to the frontend.

Call this after generating an image file (via run_python, Pillow, etc.)
so the user can see it inline in the web UI.

Module-import-time registration via ``registry.register()``.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict

from abstract.tools.registry import registry, tool_error, tool_result

logger = logging.getLogger(__name__)

# Lazy import of Sandbox
_fs_sandbox: Any | None = None

_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp"}


def _get_sandbox():
    global _fs_sandbox
    if _fs_sandbox is None:
        from component.tools.filesystem import _sandbox
        _fs_sandbox = _sandbox
    return _fs_sandbox


def _resolve_and_validate(path: str) -> tuple[Path, str, str] | str:
    """Resolve a ws: path. On success returns (real_path, mime_type, http_url).
    On error returns an error string.
    """
    if not path.startswith("ws:"):
        return '路径必须以 "ws:" 开头，例如 ws:output/diagram.png'

    sb = _get_sandbox()
    if sb is None:
        return "Sandbox 未初始化，无法解析路径"

    try:
        resolved = sb.resolve_read(path)
    except Exception as exc:
        return f"路径解析失败: {exc}"

    real = resolved.real
    if not real.exists():
        return f"文件不存在: {path}"
    if not real.is_file():
        return f"不是文件: {path}"

    ext = real.suffix.lower()
    if ext not in _IMAGE_EXTS:
        return f"不支持的文件类型: {ext}（支持: {', '.join(sorted(_IMAGE_EXTS))})"

    # MIME type
    mime = {
        ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".gif": "image/gif", ".webp": "image/webp",
    }.get(ext, "application/octet-stream")

    # Compute HTTP URL relative to agentspace
    agentspace = sb._ctx.agentspace
    try:
        rel = real.relative_to(agentspace)
        http_url = f"/uploads/{rel.as_posix()}"
    except ValueError:
        http_url = f"/uploads/{real.name}"

    return real, mime, http_url


def _handle_display_image(args: Dict[str, Any]) -> str:
    """Publish a ws: image file to the frontend for inline display."""
    path: str = str(args.get("path", "")).strip()
    description: str = str(args.get("description", "")).strip() or "image"

    if not path:
        return tool_error("path 是必填的 — ws: 路径下的图片文件")

    result = _resolve_and_validate(path)
    if isinstance(result, str):
        return tool_error(result)

    real_path, mime, http_url = result

    file_size = real_path.stat().st_size
    markdown = f"![{description}]({http_url})"
    return tool_result(
        path=path,
        mime=mime,
        size=file_size,
        markdown=markdown,
        message=f"![{description}]({http_url})",
    )


def _handle_publish_file(args: Dict[str, Any]) -> str:
    """Publish any file from ws: and return a download link for the frontend."""
    path: str = str(args.get("path", "")).strip()
    filename: str = str(args.get("filename", "")).strip()
    description: str = str(args.get("description", "")).strip() or "file"

    if not path:
        return tool_error("path 是必填的 — ws: 路径下的文件")

    result = _resolve_and_validate(path)
    if isinstance(result, str):
        return tool_error(result)

    real_path, mime, http_url = result
    file_size = real_path.stat().st_size
    display_name = filename or real_path.name

    link = f"[{description}]({http_url})" if mime.startswith("image/") else f"[{display_name}]({http_url})"
    return tool_result(
        path=path,
        mime=mime,
        size=file_size,
        filename=display_name,
        download_url=http_url,
        message=f"[{display_name}]({http_url})",
    )


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

registry.register(
    name="display_image",
    toolset="display",
    schema={
        "description": (
            "将 ws: 路径下的图片发布到前端，使用户能在聊天界面中直接看到。\n\n"
            "使用步骤:\n"
            "  1. 生成或获取图片并保存到 ws: 路径\n"
            "  2. 调用 display_image(path=\"ws:path/to/image.png\", description=\"xxx\")\n"
            "  3. 工具会验证图片文件是否存在并返回 Markdown 图片链接\n"
            "  4. **你必须把返回的 Markdown 图片链接放入你的回复文本中**，\n"
            "     用户才能在前端看到图片。不要只发超链接 [text](url)，\n"
            "     要用 ![](/uploads/xxx.png) 语法。\n\n"
            "路径规则:\n"
            "  - ws: 是逻辑路径前缀，不是真实文件系统目录。\n"
            "    用 write_file(path=\"ws:output/img.png\", ...) 保存文件。\n"
            "  - 在 Python 代码中用绝对路径保存：agentspace 目录是服务器能访问的。\n"
            "  - 可用 run_python 查询 agentspace 目录路径。\n\n"
            "示例:\n"
            "  display_image(path=\"ws:output/mindmap.png\", description=\"中国古代史思维导图\")\n"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "ws: 前缀下的图片文件路径，如 ws:output/diagram.png",
                },
                "description": {
                    "type": "string",
                    "description": "图片描述（alt 文本），用于无障碍和图片加载失败时的替代文字。",
                },
            },
            "required": ["path"],
        },
    },
    handler=_handle_display_image,
    emoji="\U0001f5bc\U0000fe0f",
)

registry.register(
    name="publish_file",
    toolset="display",
    schema={
        "description": (
            "将 ws: 路径下的任意文件发布为前端可下载的链接。\n"
            "图片文件会自动使用 display_image 的显示方式。\n"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "ws: 前缀下的文件路径",
                },
                "filename": {
                    "type": "string",
                    "description": "可选的下载文件名（覆盖原文件名）",
                },
                "description": {
                    "type": "string",
                    "description": "文件描述",
                },
            },
            "required": ["path"],
        },
    },
    handler=_handle_publish_file,
    emoji="\U0001f4e4",
)