"""YAML frontmatter parser — pure Python stdlib, no PyYAML dependency.

Parses the ``---``-delimited YAML frontmatter block at the top of Markdown
files (like SKILL.md).  Supports the subset of YAML that skills actually use:

- Scalars: strings, integers, booleans, null
- Quoted strings (single and double)
- Lists: inline ``[a, b]`` and block ``- item``
- Nested dicts via indentation
- Multi-line strings (``|`` literal, ``>`` folded)
- Comments (``# ...``)

Usage::

    >>> from hermes_skills.frontmatter import parse_frontmatter
    >>> fm, body = parse_frontmatter(content)
    >>> fm["name"]
    'my-skill'
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_DELIMITER = re.compile(r"^---\s*$", re.MULTILINE)

# Match a top-level key   key: value
_KEY_VAL = re.compile(r"^([a-zA-Z_][a-zA-Z0-9_\-]*)\s*:(?:\s+(.*))?$")

# Match a list item   - value
_LIST_ITEM = re.compile(r"^(\s*)-\s+(.*)$")

# Indentation for continuation lines
_CONTINUATION = re.compile(r"^(\s+)(.+)$")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def parse_frontmatter(content: str) -> Tuple[Dict[str, Any], str]:
    """Parse YAML frontmatter from *content*.

    Args:
        content: Raw file content (Markdown with optional frontmatter).

    Returns:
        ``(frontmatter_dict, body_string)``.
        If no frontmatter is found, returns ``({}, content)``.
    """
    if not content or not content.startswith("---"):
        return {}, content

    # Split on the --- delimiter — we want exactly two delimiters.
    parts = _DELIMITER.split(content, maxsplit=2)
    if len(parts) < 3:
        # Only one --- found — treat whole file as body
        return {}, content

    _before, raw_fm, body = parts  # _before is empty string
    # If there were leading characters before the first ---, no frontmatter
    if _before.strip():
        return {}, content

    parsed = _parse_yaml_block(raw_fm.strip())
    return parsed, body.lstrip()


def load_frontmatter_only(content: str) -> Dict[str, Any]:
    """Parse and return *only* the frontmatter dict (discard body).

    Convenience wrapper when you only need the metadata.
    """
    fm, _ = parse_frontmatter(content)
    return fm


# ---------------------------------------------------------------------------
# Internal YAML parser
# ---------------------------------------------------------------------------


def _parse_yaml_block(text: str) -> Dict[str, Any]:
    """Parse a raw YAML string block into a dict.

    Handles:
      - Scalars (str, int, bool, None)
      - Inline lists ``[a, b]``
      - Block lists ``- item``
      - Nested dicts via indentation
      - Multi-line strings (``|`` and ``>``)
      - Comments
    """
    if not text:
        return {}

    lines = text.split("\n")
    result: Dict[str, Any] = {}
    _parse_dict_body(lines, 0, len(lines), result, 0)
    return result


def _parse_dict_body(
    lines: List[str],
    start: int,
    end: int,
    target: Dict[str, Any],
    base_indent: int,
) -> int:
    """Parse lines[start:end] as key-value pairs into *target*.

    Returns the index of the first line not consumed.
    """
    i = start
    while i < end:
        line = lines[i]
        stripped = line.strip()

        # Skip blank lines and comments
        if not stripped or stripped.startswith("#"):
            i += 1
            continue

        # Detect indent level for this block
        indent = len(line) - len(line.lstrip())

        # If we've dedented past base_indent, we're done
        if indent < base_indent and stripped:
            break

        # List items shouldn't appear at dict level — we handle them elsewhere
        if stripped.startswith("- ") or stripped == "-":
            i = _parse_list_block(
                lines, i, end, target.setdefault("_list_", []), base_indent
            )
            continue

        # Key-value line
        m = _KEY_VAL.match(line)
        if not m:
            i += 1
            continue

        key = m.group(1)
        val_raw = (m.group(2) or "").strip()

        # Peek ahead for continuation / multiline
        if val_raw == "" or val_raw == "|" or val_raw == ">":
            i = _parse_multiline_value(lines, i, end, target, key, val_raw)
        elif val_raw.startswith("["):
            target[key] = _parse_inline_list(val_raw)
            i += 1
        elif val_raw.startswith('"') or val_raw.startswith("'"):
            target[key] = _unquote(val_raw)
            i += 1
        else:
            target[key] = _coerce_scalar(val_raw)
            i += 1

    return i


def _parse_list_block(
    lines: List[str],
    start: int,
    end: int,
    target: List[Any],
    base_indent: int,
) -> int:
    """Parse a block list starting at *start* into *target*.

    Supports:
      - item
      - key: value  (list of dicts)
      - | multiline
    """
    i = start
    list_indent: Optional[int] = None

    while i < end:
        line = lines[i]
        stripped = line.strip()

        if not stripped or stripped.startswith("#"):
            i += 1
            continue

        indent = len(line) - len(line.lstrip())

        if list_indent is None:
            list_indent = indent

        if indent < list_indent:
            break

        m = _LIST_ITEM.match(line)
        if not m:
            break

        item_indent = len(m.group(1))
        item_raw = m.group(2).strip()

        # Check if item is a dict key (contains ": " or ends with ":")
        kv = _KEY_VAL.match("x: " + item_raw)
        is_kv = ":" in item_raw

        if is_kv:
            # Parse as inline or multi-line sub-dict
            sub: Dict[str, Any] = {}
            _parse_dict_body([item_raw], 0, 1, sub, 0)
            if sub:
                target.append(sub)
            else:
                target.append(item_raw)
            i += 1
        elif item_raw == "|" or item_raw == ">":
            # Multi-line string as list item
            collected = _collect_multiline_body(lines, i + 1, end, item_indent + 2)
            val = "\n".join(collected) if item_raw == "|" else " ".join(collected)
            target.append(val)
            i += 1 + len(collected)
        else:
            target.append(_coerce_scalar(item_raw))
            i += 1

    return i


def _parse_multiline_value(
    lines: List[str],
    start: int,
    end: int,
    target: Dict[str, Any],
    key: str,
    indicator: str,
) -> int:
    """Parse a multi-line string value starting at *start*.

    ``indicator`` is ``""`` (indented block), ``"|"`` (literal), or ``">"`` (folded).
    """
    i = start + 1
    key_indent = len(lines[start]) - len(lines[start].lstrip())

    if indicator in ("|", ">"):
        body_indent: Optional[int] = None
        collected: List[str] = []
        while i < end:
            line = lines[i]
            if not line.strip():
                collected.append("")
                i += 1
                continue
            indent = len(line) - len(line.lstrip())
            if body_indent is None:
                body_indent = indent
            if indent < body_indent:
                break
            collected.append(line.strip())
            i += 1
        if indicator == ">":
            target[key] = " ".join(collected)
        else:
            target[key] = "\n".join(collected)
    else:
        # Indented continuation block — could be text or a block list
        collected = _collect_multiline_body(lines, i, end, key_indent + 1)
        # Detect block list: lines starting with "- "
        if collected and all(line.startswith("- ") for line in collected if line.strip()):
            items = []
            for line in collected:
                stripped = line.strip()
                if stripped.startswith("- "):
                    items.append(_coerce_scalar(stripped[2:].strip()))
            target[key] = items
        else:
            target[key] = "\n".join(collected)
        i += len(collected)

    return i


def _collect_multiline_body(
    lines: List[str], start: int, end: int, min_indent: int
) -> List[str]:
    """Collect continuation lines indented at least *min_indent*."""
    collected: List[str] = []
    i = start
    while i < end:
        line = lines[i]
        if not line.strip():
            collected.append("")
            i += 1
            continue
        indent = len(line) - len(line.lstrip())
        if indent < min_indent:
            break
        collected.append(line.strip())
        i += 1
    return collected


def _parse_inline_list(text: str) -> List[Any]:
    """Parse an inline YAML list: ``[a, b, c]``"""
    inner = text.strip()
    if inner.startswith("[") and inner.endswith("]"):
        inner = inner[1:-1]
    items = []
    for item in inner.split(","):
        item = item.strip()
        if item:
            items.append(_coerce_scalar(_unquote(item)))
    return items


# ---------------------------------------------------------------------------
# Scalar coercion
# ---------------------------------------------------------------------------

_BOOL_TRUE = frozenset({"true", "yes", "on"})
_BOOL_FALSE = frozenset({"false", "no", "off"})
_NULL = frozenset({"null", "~", ""})


def _coerce_scalar(raw: str) -> Any:
    """Coerce a string to int/bool/None/str as appropriate."""
    if not raw:
        return None
    if raw.lower() in _NULL:
        return None
    if raw.lower() in _BOOL_TRUE:
        return True
    if raw.lower() in _BOOL_FALSE:
        return False
    try:
        return int(raw)
    except ValueError:
        pass
    try:
        return float(raw)
    except ValueError:
        pass
    return raw


def _unquote(text: str) -> str:
    """Remove matching surrounding quotes from *text*."""
    text = text.strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in ('"', "'"):
        return text[1:-1]
    return text
