"""Context 清洗工具 — 用于 memory provider 输出。

剥离 memory provider 可能在响应中嵌入的围栏标签、
注入的上下文块和系统注释。同时提供一次性
``sanitize_context`` 函数（适用于缓冲文本）和
``StreamingContextScrubber`` 类（可处理跨任意 chunk
边界分割的文本）。

所有函数仅使用 Python stdlib（``re``）。
"""

import re

# ---------------------------------------------------------------------------
# Regex 模式
# ---------------------------------------------------------------------------

_FENCE_TAG_RE: re.Pattern = re.compile(r"</?\s*memory-context\s*>", re.IGNORECASE)

_INTERNAL_CONTEXT_RE: re.Pattern = re.compile(
    r"<\s*memory-context\s*>[\s\S]*?</\s*memory-context\s*>",
    re.IGNORECASE,
)

_INTERNAL_NOTE_RE: re.Pattern = re.compile(
    r"\[System note:\s*The following is recalled memory context,"
    r"\s*NOT new user input\.\s*Treat as "
    r"(?:informational background data|authoritative reference data[^\]]*)"
    r"\.\]\s*",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# 一次性清洗
# ---------------------------------------------------------------------------


def sanitize_context(text: str) -> str:
    """从 memory provider 输出中剥离围栏标签、注入的上下文块和系统注释。

    这是一次性基于 regex 的清洗器，适用于**缓冲完成**的文本。
    对于流式响应（``<memory-context>`` 区间可能跨 chunk 分割），
    请使用 :class:`StreamingContextScrubber`。

    参数
    ----------
    text : str
        memory provider 响应的原始文本。

    返回
    -------
    str
        移除所有 memory-context 标记后的清洗文本。
    """
    text = _INTERNAL_CONTEXT_RE.sub("", text)
    text = _INTERNAL_NOTE_RE.sub("", text)
    text = _FENCE_TAG_RE.sub("", text)
    return text


# ---------------------------------------------------------------------------
# 部分标签检测辅助函数
# ---------------------------------------------------------------------------


def _max_partial_suffix(buf: str, tag: str) -> int:
    """返回 *buf* 最长后缀中作为 *tag* 前缀的长度。

    大小写不敏感。如果 *buf* 无后缀可开始 *tag* 则返回 ``0``。

    此函数由 :class:`StreamingContextScrubber` 内部使用，
    用于决定在无完整标签可见时应保留多少尾部文本 —
    保留的文本*可能*是 ``<memory-context>`` 或
    ``</memory-context>`` 的开头片段，在未来的 chunk 中到达。

    参数
    ----------
    buf : str
        要检查的文本缓冲区。
    tag : str
        要匹配的完整标签字符串（例如 ``"<memory-context>"``）。

    返回
    -------
    int
        最长匹配后缀的长度（无匹配时为 ``0``）。
    """
    tag_lower: str = tag.lower()
    buf_lower: str = buf.lower()
    max_check: int = min(len(buf_lower), len(tag_lower) - 1)
    for i in range(max_check, 0, -1):
        if tag_lower.startswith(buf_lower[-i:]):
            return i
    return 0


# ---------------------------------------------------------------------------
# 流式清洗器
# ---------------------------------------------------------------------------


class StreamingContextScrubber:
    """有状态清洗器，处理可能跨 chunk 分割的 memory-context 区间。

    一次性 :func:`sanitize_context` regex 无法跨越 chunk 边界：
    一个 delta 中打开的 ``<memory-context>`` 在后续 delta 中关闭时
    会将其负载泄露到 UI，因为非贪心块 regex 需要两个标签
    在同一字符串中。此清洗器跨 delta 运行一个小状态机，
    保留部分标签尾部，丢弃区间内的所有内容（包括系统注释行）。

    用法::

        scrubber = StreamingContextScrubber()
        for delta in stream:
            visible = scrubber.feed(delta)
            if visible:
                emit(visible)
        trailing = scrubber.flush()  # 流结束时
        if trailing:
            emit(trailing)

    清洗器在每个 agent 实例内可重入。构建新顶级响应的调用方
    应创建新清洗器或调用 :meth:`reset`。
    """

    _OPEN_TAG: str = "<memory-context>"
    _CLOSE_TAG: str = "</memory-context>"

    def __init__(self) -> None:
        self._in_span: bool = False
        self._buf: str = ""

    def reset(self) -> None:
        """将内部状态机重置到初始条件。

        在开始新的顶级响应时使用此方法，
        避免跨回合污染。
        """
        self._in_span = False
        self._buf = ""

    def feed(self, text: str) -> str:
        """返回清洗后 *text* 的可见部分。

        任何可能是开标签或闭标签起始的尾部片段
        被保留在内部缓冲区中，在下次 ``feed()`` 调用时释放，
        或由 :meth:`flush` 丢弃/发出。

        参数
        ----------
        text : str
            流式文本的单个 chunk。

        返回
        -------
        str
            该 chunk 的可见（非上下文）部分。可能为空。
        """
        if not text:
            return ""
        buf: str = self._buf + text
        self._buf = ""
        out: list[str] = []

        while buf:
            if self._in_span:
                idx: int = buf.lower().find(self._CLOSE_TAG)
                if idx == -1:
                    # 保留可能的部分闭标签；丢弃其余内容
                    held: int = _max_partial_suffix(buf, self._CLOSE_TAG)
                    self._buf = buf[-held:] if held else ""
                    return "".join(out)
                # 找到闭标签 — 跳过区间内容 + 标签，继续
                buf = buf[idx + len(self._CLOSE_TAG):]
                self._in_span = False
            else:
                idx = buf.lower().find(self._OPEN_TAG)
                if idx == -1:
                    # 无开标签 — 保留可能的部分开标签
                    held = _max_partial_suffix(buf, self._OPEN_TAG)
                    if held:
                        out.append(buf[:-held])
                        self._buf = buf[-held:]
                    else:
                        out.append(buf)
                    return "".join(out)
                # 发出标签前的文本，进入区间
                if idx > 0:
                    out.append(buf[:idx])
                buf = buf[idx + len(self._OPEN_TAG):]
                self._in_span = True

        return "".join(out)

    def flush(self) -> str:
        """在流结束时发出任何保留的缓冲区内容。

        如果仍在未终止的区间内，剩余内容被丢弃
        （更安全：泄露部分 memory 上下文比截断回答更糟糕）。
        否则保留的部分标签尾部按原样发出（它实际不是真实标签）。

        返回
        -------
        str
            刷新的内容，仍在区间内时为空字符串。
        """
        if self._in_span:
            self._buf = ""
            self._in_span = False
            return ""
        tail: str = self._buf
        self._buf = ""
        return tail