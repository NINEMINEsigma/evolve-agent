"""
Context sanitization utilities for memory provider output.

Strips fence tags, injected context blocks, and system notes that memory
providers may embed in their responses.  Provides both a one-shot
``sanitize_context`` function (suitable for buffered text) and a
``StreamingContextScrubber`` class that can handle text split across
arbitrary chunk boundaries.

All functions use only the Python stdlib (``re``).
"""

import re

# ---------------------------------------------------------------------------
# Regex patterns
# ---------------------------------------------------------------------------

_FENCE_TAG_RE = re.compile(r"</?\s*memory-context\s*>", re.IGNORECASE)

_INTERNAL_CONTEXT_RE = re.compile(
    r"<\s*memory-context\s*>[\s\S]*?</\s*memory-context\s*>",
    re.IGNORECASE,
)

_INTERNAL_NOTE_RE = re.compile(
    r"\[System note:\s*The following is recalled memory context,"
    r"\s*NOT new user input\.\s*Treat as "
    r"(?:informational background data|authoritative reference data[^\]]*)"
    r"\.\]\s*",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# One-shot sanitize
# ---------------------------------------------------------------------------


def sanitize_context(text: str) -> str:
    """Strip fence tags, injected context blocks, and system notes from
    memory provider output.

    This is a one-shot regex-based scrubber suitable for **buffered**
    (fully received) text.  For streaming responses where a ``<memory-context>``
    span may be split across chunks, use :class:`StreamingContextScrubber`
    instead.

    Parameters
    ----------
    text : str
        The raw text from a memory provider response.

    Returns
    -------
    str
        Cleaned text with all memory-context markup removed.
    """
    text = _INTERNAL_CONTEXT_RE.sub("", text)
    text = _INTERNAL_NOTE_RE.sub("", text)
    text = _FENCE_TAG_RE.sub("", text)
    return text


# ---------------------------------------------------------------------------
# Partial-tag detection helper
# ---------------------------------------------------------------------------


def _max_partial_suffix(buf: str, tag: str) -> int:
    """Return the length of the longest *buf* suffix that is a prefix of *tag*.

    Case-insensitive.  Returns ``0`` if no suffix of *buf* could start *tag*.

    This is used internally by :class:`StreamingContextScrubber` to decide
    how much trailing text to hold back when no complete tag is visible —
    the held-back text *could* be the beginning of ``<memory-context>`` or
    ``</memory-context>`` arriving in a future chunk.

    Parameters
    ----------
    buf : str
        Text buffer to inspect.
    tag : str
        The full tag string to match against (e.g. ``"<memory-context>"``).

    Returns
    -------
    int
        The length of the longest matching suffix (``0`` if none).
    """
    tag_lower = tag.lower()
    buf_lower = buf.lower()
    max_check = min(len(buf_lower), len(tag_lower) - 1)
    for i in range(max_check, 0, -1):
        if tag_lower.startswith(buf_lower[-i:]):
            return i
    return 0


# ---------------------------------------------------------------------------
# Streaming scrubber
# ---------------------------------------------------------------------------


class StreamingContextScrubber:
    """Stateful scrubber for streaming text that may contain split
    memory-context spans across chunks.

    The one-shot :func:`sanitize_context` regex cannot survive chunk
    boundaries: a ``<memory-context>`` opened in one delta and closed in a
    later delta leaks its payload to the UI because the non-greedy block
    regex needs both tags in one string.  This scrubber runs a small state
    machine across deltas, holding back partial-tag tails and discarding
    everything inside a span (including the system-note line).

    Usage::

        scrubber = StreamingContextScrubber()
        for delta in stream:
            visible = scrubber.feed(delta)
            if visible:
                emit(visible)
        trailing = scrubber.flush()  # at end of stream
        if trailing:
            emit(trailing)

    The scrubber is re-entrant per agent instance.  Callers building new
    top-level responses (new turn) should create a fresh scrubber or call
    :meth:`reset`.
    """

    _OPEN_TAG = "<memory-context>"
    _CLOSE_TAG = "</memory-context>"

    def __init__(self) -> None:
        self._in_span: bool = False
        self._buf: str = ""

    def reset(self) -> None:
        """Reset the internal state machine back to initial conditions.

        Use this when starting a new top-level response to avoid
        cross-turn contamination.
        """
        self._in_span = False
        self._buf = ""

    def feed(self, text: str) -> str:
        """Return the visible portion of *text* after scrubbing.

        Any trailing fragment that could be the start of an open or close
        tag is held back in the internal buffer and surfaced on the next
        ``feed()`` call or discarded/emitted by :meth:`flush`.

        Parameters
        ----------
        text : str
            A single chunk of streaming text.

        Returns
        -------
        str
            The visible (non-context) portion of the chunk.  May be empty.
        """
        if not text:
            return ""
        buf = self._buf + text
        self._buf = ""
        out: list[str] = []

        while buf:
            if self._in_span:
                idx = buf.lower().find(self._CLOSE_TAG)
                if idx == -1:
                    # Hold back a potential partial close tag; drop the rest
                    held = _max_partial_suffix(buf, self._CLOSE_TAG)
                    self._buf = buf[-held:] if held else ""
                    return "".join(out)
                # Found close — skip span content + tag, continue
                buf = buf[idx + len(self._CLOSE_TAG) :]
                self._in_span = False
            else:
                idx = buf.lower().find(self._OPEN_TAG)
                if idx == -1:
                    # No open tag — hold back a potential partial open tag
                    held = _max_partial_suffix(buf, self._OPEN_TAG)
                    if held:
                        out.append(buf[:-held])
                        self._buf = buf[-held:]
                    else:
                        out.append(buf)
                    return "".join(out)
                # Emit text before the tag, enter span
                if idx > 0:
                    out.append(buf[:idx])
                buf = buf[idx + len(self._OPEN_TAG) :]
                self._in_span = True

        return "".join(out)

    def flush(self) -> str:
        """Emit any held-back buffer at end-of-stream.

        If we're still inside an unterminated span the remaining content is
        discarded (safer: leaking partial memory context is worse than a
        truncated answer).  Otherwise the held-back partial-tag tail is
        emitted verbatim (it turned out not to be a real tag).

        Returns
        -------
        str
            The flushed content, or empty string if still in a span.
        """
        if self._in_span:
            self._buf = ""
            self._in_span = False
            return ""
        tail = self._buf
        self._buf = ""
        return tail
