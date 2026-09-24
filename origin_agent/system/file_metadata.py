"""Read 使用的同级元数据文件解析。"""

from __future__ import annotations

import re
from collections.abc import Iterator


class MetaFormatError(ValueError):
    """元数据文本不符合 [key] 分段格式。"""

    def __init__(self, line_number: int, reason: str) -> None:
        self.line_number = line_number
        self.reason = reason
        super().__init__(f"line {line_number}: {reason}")


def _lines_with_endings(content: str) -> Iterator[str]:
    """按 LF 分行，同时保留每一行的原始行结束符。"""
    if not content:
        return
    parts = content.split("\n")
    for index, part in enumerate(parts):
        if index < len(parts) - 1:
            yield part + "\n"
        elif part:
            yield part


def _key_line_body(line: str) -> str:
    """移除用于匹配的 LF 和配对 CR，不改变值文本。"""
    body = line[:-1] if line.endswith("\n") else line
    if line.endswith("\n") and body.endswith("\r"):
        body = body[:-1]
    return body


def parse_meta_content(content: str) -> dict[str, str]:
    """解析元数据文本为一层 ``dict[str, str]``。

    键名必须独立成行并使用 ``[key]`` 包裹；键名之后直到下一个键名的
    所有字符都保留在对应值中。空白前导行允许存在，但首个键前的非空
    文本、空键和重复键都会抛出带行号的 ``MetaFormatError``。
    """
    values: dict[str, str] = {}
    current_key: str | None = None
    current_value: list[str] = []

    for line_number, line in enumerate(_lines_with_endings(content), start=1):
        body = _key_line_body(line)
        match = re.fullmatch(r"\[([^\[\]\r\n]+)\]", body)
        if match is not None:
            key = match.group(1)
            if not key.strip():
                raise MetaFormatError(line_number, "metadata key must not be empty")
            if key in values or key == current_key:
                raise MetaFormatError(line_number, f"duplicate metadata key: {key}")
            if current_key is not None:
                values[current_key] = "".join(current_value)
            current_key = key
            current_value = []
            continue

        if body == "[]" or (body.startswith("[") and body.endswith("]")):
            raise MetaFormatError(line_number, "invalid metadata key line")

        if current_key is None:
            if body.strip():
                raise MetaFormatError(
                    line_number,
                    "non-empty text before the first metadata key",
                )
            continue

        current_value.append(line)

    if current_key is not None:
        values[current_key] = "".join(current_value)
    return values
