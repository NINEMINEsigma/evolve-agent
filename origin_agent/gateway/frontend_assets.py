"""Frontend artifact location and file metadata without runtime caches."""

import hashlib
import mimetypes
from pathlib import Path

from entity.constant import HTTP_TEXT_MIME_EXTENSIONS, HTTP_TEXT_MIME_PREFIXES


def frontend_dist() -> Path:
    return Path(__file__).resolve().parent.parent / "frontend" / "dist"


def compute_build_hash() -> str:
    index = frontend_dist() / "index.html"
    if not index.exists():
        return ""
    return hashlib.md5(index.read_bytes()).hexdigest()[:12]


def guess_media_type_with_charset(path: Path) -> str:
    mime, _ = mimetypes.guess_type(str(path))
    if mime is None:
        mime = "application/octet-stream"
    if mime.startswith(HTTP_TEXT_MIME_PREFIXES) or path.suffix.lower() in HTTP_TEXT_MIME_EXTENSIONS:
        if "charset" not in mime:
            mime = f"{mime}; charset=utf-8"
    return mime
