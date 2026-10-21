"""本地字体文件的共享校验；在线路由与导出读取复用同一规则。"""

from __future__ import annotations

import os
import stat
from pathlib import Path

from entity.constant import (
    LOCAL_FONT_ALLOWED_EXTENSIONS, LOCAL_FONT_MAX_BYTES, LOCAL_FONT_MIME_TYPES,
)


class LocalFontAccessError(ValueError):
    """已识别的字体读取拒绝；携带稳定 code 与 HTTP status，不含物理路径。"""

    def __init__(self, code: str, message: str, status: int) -> None:
        super().__init__(message)
        self.code = code
        self.status = status


def reject_reparse_components(path: Path) -> None:
    """逐层拒绝符号链接与其他 reparse point，避免经由联接点越界读取。

    仅用于导出更严格的读取层；在线字体路由保持既有行为，不调用本函数。
    """
    if not path.is_absolute():
        raise LocalFontAccessError("font_reparse", "Font path must be absolute", 400)
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current = current / part
        try:
            info = os.lstat(current)
        except FileNotFoundError:
            return
        if stat.S_ISLNK(info.st_mode):
            raise LocalFontAccessError("font_reparse", "Font path contains a link", 403)
        if os.name == "nt" and info.st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT:
            raise LocalFontAccessError("font_reparse", "Font path contains a link", 403)


def local_font_mime_type(path: Path) -> str:
    """按扩展名返回本地字体 MIME；未知扩展名回退二进制流。"""
    return LOCAL_FONT_MIME_TYPES.get(path.suffix.lower(), "application/octet-stream")


def resolve_local_font(font_path: str, *, strict_reparse: bool = False) -> Path:
    """校验并返回可读取的本地字体物理路径。

    ``strict_reparse`` 为真时额外拒绝目录组件中的符号链接/reparse，并强制绝对路径；
    在线路由以假值保持原有语义（含相对路径按当前工作目录解析）。
    """
    if not isinstance(font_path, str) or not font_path or "\x00" in font_path:
        raise LocalFontAccessError("invalid_font_path", "Invalid font path", 400)
    if ".." in font_path:
        raise LocalFontAccessError("font_traversal", "Path traversal not allowed", 403)

    candidate = Path(font_path)
    if strict_reparse and not candidate.is_absolute():
        raise LocalFontAccessError("invalid_font_path", "Font path must be absolute", 400)

    ext = candidate.suffix.lower()
    if ext not in LOCAL_FONT_ALLOWED_EXTENSIONS:
        raise LocalFontAccessError(
            "font_type",
            f"Font type '{ext}' not allowed. Allowed: {', '.join(LOCAL_FONT_ALLOWED_EXTENSIONS)}",
            404,
        )

    if strict_reparse:
        reject_reparse_components(candidate)

    font_file = candidate.resolve()
    if not font_file.exists() or not font_file.is_file():
        raise LocalFontAccessError("font_not_found", "Font file not found", 404)

    if font_file.stat().st_size > LOCAL_FONT_MAX_BYTES:
        raise LocalFontAccessError(
            "font_too_large",
            f"Font file exceeds {LOCAL_FONT_MAX_BYTES} byte limit",
            403,
        )
    return font_file