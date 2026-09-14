"""文本文件编码探测与解码工具。

文件没有可靠的通用编码元数据，因此这里采用“严格尝试候选编码”的策略：
优先保留 BOM/UTF-8，随后使用系统和 Windows 常见编码，最后使用 latin-1
保证日志类文本不会因为单个非法字节导致整个 Read 失败。
"""

from __future__ import annotations

import locale
import sys


def preferred_text_encodings() -> list[str]:
    """返回按可靠性排序且去重的文本编码候选。"""
    candidates = ["utf-8-sig", "utf-8", "utf-16", "utf-32"]
    for encoding in (
        locale.getpreferredencoding(False),
        sys.getfilesystemencoding(),
    ):
        if encoding:
            candidates.append(encoding)
    if sys.platform == "win32":
        candidates.extend(["gb18030", "gbk", "cp936", "mbcs"])
    candidates.extend(["cp1252", "latin-1"])

    result: list[str] = []
    seen: set[str] = set()
    for encoding in candidates:
        key = encoding.lower().replace("_", "-")
        if key not in seen:
            seen.add(key)
            result.append(encoding)
    return result


def split_lf_lines(text: str) -> list[str]:
    """只按 LF 分行，保留每行内原有的 CR；末尾 LF 不额外计行。"""
    if not text:
        return []
    lines = text.split("\n")
    if text.endswith("\n"):
        lines.pop()
    return lines


def strip_lf_line_ending(text: str) -> str:
    """仅移除行尾 LF 及其配对的 CR，保留其余 CR。"""
    if text.endswith("\n"):
        text = text[:-1]
        if text.endswith("\r"):
            text = text[:-1]
    return text


def decode_text(raw: bytes, *, strict_utf8: bool = False) -> tuple[str, str, bool]:
    """解码文本并返回 ``(content, encoding, fallback_used)``。

    ``strict_utf8=True`` 供编辑路径使用，防止非 UTF-8 文件被读取后又以
    UTF-8 写回而发生静默转码。普通查看路径允许使用候选编码自动降级。
    """
    if strict_utf8:
        return raw.decode("utf-8", errors="strict"), "utf-8", False

    for encoding in preferred_text_encodings():
        try:
            return raw.decode(encoding, errors="strict"), encoding, encoding not in {
                "utf-8", "utf-8-sig",
            }
        except (LookupError, UnicodeDecodeError):
            continue

    # latin-1 理论上可以解码任意字节；保留此分支作为最后保险。
    return raw.decode("latin-1", errors="replace"), "latin-1", True
