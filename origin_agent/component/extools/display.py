"""Display image tool — publish a ws: image file to the frontend.

Call this after generating an image file (via run_python, Pillow, etc.)
so the user can see it inline in the web UI.
Also provides publish_file for downloading any ws: file.

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
_AUDIO_EXTS = {".mp3", ".wav", ".ogg", ".flac", ".aac", ".m4a"}

_MIME_MAP = {
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".gif": "image/gif", ".webp": "image/webp",
    ".pdf": "application/pdf",
    ".json": "application/json",
    ".csv": "text/csv",
    ".txt": "text/plain",
    ".md": "text/markdown",
    ".zip": "application/zip",
    ".tar": "application/x-tar",
    ".gz": "application/gzip",
    ".mp3": "audio/mpeg", ".wav": "audio/wav", ".ogg": "audio/ogg",
    ".flac": "audio/flac", ".aac": "audio/aac", ".m4a": "audio/mp4",
}


def _get_sandbox():
    global _fs_sandbox
    if _fs_sandbox is None:
        from component.tools.filesystem import _sandbox
        _fs_sandbox = _sandbox
    return _fs_sandbox


def _resolve_common(path: str) -> tuple[Path, Path] | str:
    """Resolve a ws: path. Returns (real_path, agentspace_root) or error string."""
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

    return real, sb._ctx.agentspace


def _resolve_image(path: str) -> tuple[Path, str, str] | str:
    """Resolve a ws: image path. Returns (real_path, mime_type, http_url) or error.
    Only accepts image extensions.
    """
    result = _resolve_common(path)
    if isinstance(result, str):
        return result
    real, agentspace = result

    ext = real.suffix.lower()
    if ext not in _IMAGE_EXTS:
        return f"不支持的文件类型: {ext}（支持: {', '.join(sorted(_IMAGE_EXTS))}）"

    mime = _MIME_MAP.get(ext, "application/octet-stream")
    try:
        rel = real.relative_to(agentspace)
        http_url = f"/uploads/{rel.as_posix()}"
    except ValueError:
        http_url = f"/uploads/{real.name}"

    return real, mime, http_url


def _resolve_download(path: str) -> tuple[Path, str, str] | str:
    """Resolve any ws: path for download. Returns (real_path, mime_type, download_url) or error.
    Accepts any file type and generates a /downloads/ URL that triggers attachment download.
    """
    result = _resolve_common(path)
    if isinstance(result, str):
        return result
    real, agentspace = result

    ext = real.suffix.lower()
    mime = _MIME_MAP.get(ext, "application/octet-stream")

    try:
        rel = real.relative_to(agentspace)
        download_url = f"/downloads/{rel.as_posix()}"
    except ValueError:
        download_url = f"/downloads/{real.name}"

    return real, mime, download_url


def _handle_display_image(args: Dict[str, Any]) -> str:
    """Publish a ws: image file to the frontend for inline display."""
    path: str = str(args.get("path", "")).strip()
    description: str = str(args.get("description", "")).strip() or "image"

    if not path:
        return tool_error("path is required — image file under ws: path")

    result = _resolve_image(path)
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
        return tool_error("path is required — file under ws: path")

    result = _resolve_download(path)
    if isinstance(result, str):
        return tool_error(result)

    real_path, mime, download_url = result
    file_size = real_path.stat().st_size
    display_name = filename or real_path.name

    return tool_result(
        path=path,
        mime=mime,
        size=file_size,
        filename=display_name,
        description=description,
        download_url=download_url,
        message=f"📄 {display_name} ({file_size / 1024:.1f} KB)",
    )


def _handle_play_audio(args: Dict[str, Any]) -> str:
    """Play audio in the frontend. Accepts a ws: file path or an external URL."""
    path: str = str(args.get("path", "")).strip()
    url: str = str(args.get("url", "")).strip()
    autoplay: bool = bool(args.get("autoplay", True))

    if not path and not url:
        return tool_error("Must provide 'path' (ws: audio file) or 'url' (external audio URL)")
    if path and url:
        return tool_error("Provide only one of 'path' or 'url', not both.")

    audio_url: str = ""
    mime: str = "audio/mpeg"
    size: int = 0

    if path:
        result = _resolve_common(path)
        if isinstance(result, str):
            return tool_error(result)
        real, agentspace = result

        ext = real.suffix.lower()
        if ext not in _AUDIO_EXTS:
            return tool_error(
                f"Unsupported audio format '{ext}'. "
                f"Supported: {', '.join(sorted(_AUDIO_EXTS))}"
            )

        mime = _MIME_MAP.get(ext, "audio/mpeg")
        size = real.stat().st_size
        try:
            rel = real.relative_to(agentspace)
            audio_url = f"/uploads/{rel.as_posix()}"
        except ValueError:
            audio_url = f"/uploads/{real.name}"

    if url:
        audio_url = url
        # infer MIME from extension if possible
        ext = Path(url.split("?")[0]).suffix.lower()
        mime = _MIME_MAP.get(ext, "audio/mpeg")

    label = path or url
    size_str = f" ({size / 1024:.1f} KB)" if size else ""
    autoplay_str = " (autoplay)" if autoplay else ""

    return tool_result(
        path=path or None,
        url=url or None,
        audio_url=audio_url,
        mime=mime,
        size=size,
        autoplay=autoplay,
        message=f"🔊 {label}{size_str}{autoplay_str}",
    )


def _resolve_audio_item(raw: Any, agentspace: Path) -> dict[str, Any] | str:
    """Resolve a single audio item (dict with path or url) into playlist entry."""
    if not isinstance(raw, dict):
        return f"Invalid playlist item: expected dict, got {type(raw).__name__}"

    path: str = str(raw.get("path", "")).strip()
    url: str = str(raw.get("url", "")).strip()
    title: str = str(raw.get("title", "")).strip()

    if not path and not url:
        return "Each item must provide 'path' or 'url'"
    if path and url:
        return "Each item must provide only one of 'path' or 'url'"

    audio_url: str = ""
    mime: str = "audio/mpeg"
    size: int = 0

    if path:
        result = _resolve_common(path)
        if isinstance(result, str):
            return result
        real, _ = result

        ext = real.suffix.lower()
        if ext not in _AUDIO_EXTS:
            return (
                f"Unsupported audio format '{ext}' for '{path}'. "
                f"Supported: {', '.join(sorted(_AUDIO_EXTS))}"
            )

        mime = _MIME_MAP.get(ext, "audio/mpeg")
        size = real.stat().st_size
        try:
            rel = real.relative_to(agentspace)
            audio_url = f"/uploads/{rel.as_posix()}"
        except ValueError:
            audio_url = f"/uploads/{real.name}"
        if not title:
            title = real.stem

    if url:
        audio_url = url
        ext = Path(url.split("?")[0]).suffix.lower()
        mime = _MIME_MAP.get(ext, "audio/mpeg")
        if not title:
            title = Path(url.split("?")[0]).stem or "Untitled"

    return {
        "audio_url": audio_url,
        "mime": mime,
        "size": size,
        "title": title,
        "path": path or None,
        "url": url or None,
    }


def _handle_play_audio_list(args: Dict[str, Any]) -> str:
    """Play a list of audio tracks sequentially in the frontend."""
    items: Any = args.get("items", [])
    autoplay: bool = bool(args.get("autoplay", True))

    if not isinstance(items, list):
        return tool_error("'items' must be a list of audio entries")
    if not items:
        return tool_error("'items' list is empty — provide at least one audio entry")

    sb = _get_sandbox()
    agentspace: Path = sb._ctx.agentspace if sb else Path()

    playlist: list[dict[str, Any]] = []
    for idx, raw in enumerate(items):
        entry = _resolve_audio_item(raw, agentspace)
        if isinstance(entry, str):
            return tool_error(f"Item {idx + 1}: {entry}")
        playlist.append(entry)

    total_size = sum(t.get("size", 0) for t in playlist)
    track_labels = ", ".join(t["title"] for t in playlist)
    size_str = f" ({total_size / 1024:.1f} KB)" if total_size else ""
    autoplay_str = " (autoplay)" if autoplay else ""

    return tool_result(
        playlist=playlist,
        autoplay=autoplay,
        current_index=0,
        total_tracks=len(playlist),
        total_size=total_size,
        message=f"📻 Playlist: {track_labels}{size_str}{autoplay_str}",
    )


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

registry.register(
    name="display_image",
    toolset="display",
    schema={
        # 将 ws: 路径下的图片发布到前端，使用户能在聊天界面中直接看到。
        # 使用步骤:
        #   1. 生成或获取图片并保存到 ws: 路径
        #   2. 调用 display_image(path="ws:path/to/image.png", description="xxx")
        #   3. 工具会验证图片文件是否存在并返回 Markdown 图片链接
        #   4. **你必须把返回的 Markdown 图片链接放入你的回复文本中**，
        #      用户才能在前端看到图片。不要只发超链接 [text](url)，
        #      要用 ![](/uploads/xxx.png) 语法。
        # 路径规则:
        #   - ws: 是逻辑路径前缀，不是真实文件系统目录。
        #     用 write_file(path="ws:output/img.png", ...) 保存文件。
        #   - 在 Python 代码中用绝对路径保存：agentspace 目录是服务器能访问的。
        #   - 可用 run_python 查询 agentspace 目录路径。
        "description": (
            'Publish an image under ws: path to the frontend so the user '
            'can see it directly in the chat interface.\n\n'
            'Steps:\n'
            '  1. Generate or obtain an image and save it to a ws: path\n'
            '  2. Call display_image(path="ws:path/to/image.png", description="xxx")\n'
            '  3. The tool verifies the image file exists and returns a Markdown image link\n'
            '  4. **You MUST include the returned Markdown image link in your reply text** '
            'for the user to see the image in the frontend. '
            'Do NOT just send a hyperlink [text](url), '
            'use the ![](/uploads/xxx.png) syntax.\n\n'
            'Path rules:\n'
            '  - ws: is a logical path prefix, not a real filesystem directory.\n'
            '    Use write_file(path="ws:output/img.png", ...) to save files.\n'
            '  - In Python code, save with absolute paths: the agentspace directory '
            'is accessible by the server.\n'
            '  - Use run_python to query the agentspace directory path.\n\n'
            'Example:\n'
            '  display_image(path="ws:output/mindmap.png", description="Mind map of ancient Chinese history")\n'
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    # ws: 前缀下的图片文件路径，如 ws:output/diagram.png
                    "description": "Image file path under ws: prefix, e.g. ws:output/diagram.png",
                },
                "description": {
                    "type": "string",
                    # 图片描述（alt 文本），用于无障碍和图片加载失败时的替代文字。
                    "description": "Image description (alt text), for accessibility and fallback when image fails to load.",
                },
            },
            "required": ["path"],
        },
    },
    handler=_handle_display_image,
    emoji="🖼️",
)

registry.register(
    name="publish_file",
    toolset="display",
    schema={
        # 将 ws: 路径下的任意文件发布为前端可下载的链接。
        # 前端会显示一个下载按钮，用户点击即可下载文件。
        # 注意：图片文件如需展示请使用 display_image，
        # publish_file 是用于下载的（包括图片）。
        "description": (
            'Publish any file under ws: path as a frontend-downloadable link.\n'
            'The frontend shows a download button; clicking it downloads the file.\n'
            'Note: for displaying images, use display_image instead;\n'
            'publish_file is for downloading (including images).\n\n'
            'Examples:\n'
            '  publish_file(path="ws:output/report.pdf", filename="report.pdf", description="Data analysis report")\n'
            '  publish_file(path="ws:output/archive.zip", description="Dataset archive")\n'
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    # ws: 前缀下的文件路径
                    "description": "File path under ws: prefix",
                },
                "filename": {
                    "type": "string",
                    # 可选的下载文件名（覆盖原文件名）
                    "description": "Optional download filename (overrides original filename)",
                },
                "description": {
                    "type": "string",
                    # 文件描述
                    "description": "File description",
                },
            },
            "required": ["path"],
        },
    },
    handler=_handle_publish_file,
    emoji="📤",
)

registry.register(
    name="play_audio",
    toolset="display",
    schema={
        # 将音频发送到前端，可选择立即播放。
        # 使用步骤:
        #   1. 生成或获取音频文件并保存到 ws: 路径，或准备一个外部 URL
        #   2. 调用 play_audio(path="ws:output/speech.mp3", autoplay=true)
        #   3. 前端会显示一个音频播放器，如果 autoplay=true 则自动播放
        # 输入模式（二选一）:
        #   - path: ws: 前缀下的本地音频文件路径
        #   - url:  外部音频 URL
        # 支持的音频格式:
        #   mp3, wav, ogg, flac, aac, m4a
        "description": (
            "Send audio to the frontend and optionally play it immediately.\\n\\n"
            "Two input modes (mutually exclusive):\\n"
            "  - path: ws: path to a local audio file\\n"
            "  - url:  external audio URL\\n\\n"
            "If autoplay=true (default), the frontend <audio> element has the "
            "autoPlay attribute, which starts playback as soon as the "
            "tool result is received.\\n\\n"
            "Supported audio formats (for ws: path): "
            "mp3, wav, ogg, flac, aac, m4a\\n\\n"
            "Returns:\\n"
            "  - audio_url: resolved URL for playback\\n"
            "  - autoplay: whether autoplay is enabled\\n"
            "  - mime: MIME type\\n"
            "  - size: file size in bytes (path mode only)\\n"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    # ws: 前缀下的音频文件路径，如 ws:output/speech.mp3。与 url 互斥。
                    "description": (
                        "Path to an audio file under ws: prefix, "
                        "e.g. ws:output/speech.mp3. "
                        "Mutually exclusive with 'url'."
                    ),
                },
                "url": {
                    "type": "string",
                    # 外部音频 URL，如 https://example.com/audio.mp3。与 path 互斥。
                    "description": (
                        "External URL of an audio file, "
                        "e.g. https://example.com/audio.mp3. "
                        "Mutually exclusive with 'path'."
                    ),
                },
                "autoplay": {
                    "type": "boolean",
                    # 是否立即播放。开启后前端收到结果自动播放，默认为 true。
                    "description": (
                        "If true, the frontend starts playback immediately "
                        "when the tool result arrives. Default: true."
                    ),
                    "default": True,
                },
            },
        },
    },
    handler=_handle_play_audio,
    emoji="🔊",
)

registry.register(
    name="play_audio_list",
    toolset="display",
    schema={
        "description": (
            "Send a playlist of audio tracks to the frontend and play them sequentially.\n\n"
            "Each track plays to completion, then the next track starts automatically.\n\n"
            "Input: a list of items, each item is an object with:\n"
            "  - path: ws: path to a local audio file (mutually exclusive with url)\n"
            "  - url:  external audio URL (mutually exclusive with path)\n"
            "  - title: optional track title\n\n"
            "Supported audio formats (for ws: path): "
            "mp3, wav, ogg, flac, aac, m4a\n\n"
            "Returns:\n"
            "  - playlist: list of resolved tracks with audio_url, mime, title, size\n"
            "  - autoplay: whether playback starts immediately\n"
            "  - current_index: starting track index (always 0)\n"
            "  - total_tracks: number of tracks\n\n"
            "Example:\n"
            '  play_audio_list(items=[\n'
            '    {"path": "ws:output/chapter1.mp3", "title": "Chapter 1"},\n'
            '    {"path": "ws:output/chapter2.mp3", "title": "Chapter 2"},\n'
            '    {"url": "https://example.com/outro.mp3", "title": "Outro"}\n'
            '  ], autoplay=true)\n'
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "items": {
                    "type": "array",
                    "description": (
                        "List of audio entries. Each entry is an object with "
                        "'path' (ws: file) or 'url' (external), and optional 'title'."
                    ),
                    "items": {
                        "type": "object",
                        "properties": {
                            "path": {
                                "type": "string",
                                "description": (
                                    "Path to an audio file under ws: prefix, "
                                    "e.g. ws:output/speech.mp3. "
                                    "Mutually exclusive with 'url'."
                                ),
                            },
                            "url": {
                                "type": "string",
                                "description": (
                                    "External URL of an audio file, "
                                    "e.g. https://example.com/audio.mp3. "
                                    "Mutually exclusive with 'path'."
                                ),
                            },
                            "title": {
                                "type": "string",
                                "description": "Optional track title displayed in the playlist.",
                            },
                        },
                    },
                },
                "autoplay": {
                    "type": "boolean",
                    "description": (
                        "If true, the frontend starts playback immediately "
                        "when the tool result arrives. Default: true."
                    ),
                    "default": True,
                },
            },
            "required": ["items"],
        },
    },
    handler=_handle_play_audio_list,
    emoji="📻",
)