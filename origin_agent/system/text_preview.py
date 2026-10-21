"""无 I/O 的文本展示辅助函数，不改变原文读取和编辑契约。"""

from system.text_codec import split_lf_lines, strip_lf_line_ending


def truncate_lf_lines(
    text: str,
    *,
    max_line_chars: int,
    marker: str
    ) -> tuple[str, list[int]]:
    """按 Unicode 码点截断各行正文，返回展示文本及相对 0-indexed 截断行索引。

    仅 LF 分行；保留 LF/CRLF 和末尾换行，孤立 CR 仍按正文计数。
    marker 与真实行尾不占正文额度；标识符由调用方提供，不绑定具体工具。
    非法上限或空/含 CR/LF 的标识符抛 ValueError，不回退为未截断原文。
    """
    if max_line_chars < 1:
        raise ValueError("max_line_chars must be a positive integer")
    if not marker or "\r" in marker or "\n" in marker:
        raise ValueError("marker must be a non-empty string without CR or LF")

    lines = split_lf_lines(text)
    trailing_lf = text.endswith("\n")
    rendered_lines: list[str] = []
    truncated_lines: list[int] = []
    for index, line in enumerate(lines):
        has_lf = index < len(lines) - 1 or trailing_lf
        original_line = line + "\n" if has_lf else line
        body = strip_lf_line_ending(original_line)
        if len(body) > max_line_chars:
            line_ending = original_line[len(body):]
            rendered_lines.append(body[:max_line_chars] + marker + line_ending)
            truncated_lines.append(index)
        else:
            rendered_lines.append(original_line)

    if not truncated_lines:
        return text, []
    return "".join(rendered_lines), truncated_lines
