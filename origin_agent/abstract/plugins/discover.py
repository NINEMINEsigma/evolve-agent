"""
Directory-based plugin discovery system.

Pure Python stdlib — no external dependencies.

Scans directories for plugin subdirectories, detects plugin types by
heuristic source analysis, reads plugin.yaml metadata, and handles
name deduplication (first directory wins on collision).

Usage::

    from hermes_plugins.discover import scan_plugins, is_plugin_dir, \
        detect_plugin_type, read_plugin_metadata

    plugins = scan_plugins("/path/to/plugins", "/other/plugin/dir")
    for p in plugins:
        print(p["name"], p["type"], p["metadata"])
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Dict, List, Optional


# ---------------------------------------------------------------------------
# Core functions
# ---------------------------------------------------------------------------


def scan_plugins(*scan_dirs: str) -> List[Dict]:
    """Scan one or more directories for plugin subdirectories.

    Each subdirectory containing ``__init__.py`` is considered a candidate.
    On name collisions (same directory name in multiple scan directories),
    the first occurrence wins.

    Returns
    -------
    list of dict
        Each dict has keys ``name``, ``path``, ``type``, ``metadata``.
    """
    seen: Dict[str, Dict] = {}

    for scan_dir in scan_dirs:
        scan_path = Path(scan_dir)
        if not scan_path.is_dir():
            continue

        for child in sorted(scan_path.iterdir()):
            if not child.is_dir():
                continue
            name = child.name

            # Skip hidden directories and Python package directories
            if name.startswith("__") or name.startswith("."):
                continue

            if not is_plugin_dir(str(child)):
                continue

            # First directory wins on name collision
            if name in seen:
                continue

            plugin_type = detect_plugin_type(str(child))
            metadata = read_plugin_metadata(str(child))

            seen[name] = {
                "name": name,
                "path": str(child.resolve()),
                "type": plugin_type,
                "metadata": metadata,
            }

    return list(seen.values())


def is_plugin_dir(plugin_dir: str) -> bool:
    """Check if a directory looks like a plugin.

    A valid plugin directory must contain ``__init__.py`` with non-trivial
    content (not just a docstring or blank).

    Parameters
    ----------
    plugin_dir : str
        Path to the candidate plugin directory.

    Returns
    -------
    bool
        ``True`` if the directory has ``__init__.py`` with real code.
    """
    init_file = Path(plugin_dir) / "__init__.py"
    if not init_file.is_file():
        return False

    # Require at least one line of non-comment, non-blank, non-docstring code
    try:
        text = init_file.read_text(encoding="utf-8", errors="replace")
    except (OSError, UnicodeDecodeError):
        return False

    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        # Skip comment-only lines
        if stripped.startswith("#"):
            continue
        # Skip triple-quoted docstrings (opening or closing)
        if stripped.startswith('"""') or stripped.startswith("'''"):
            continue
        # Skip the ``from __future__`` import (boilerplate)
        if stripped.startswith("from __future__"):
            continue
        return True

    return False


def detect_plugin_type(plugin_dir: str) -> str:
    """Heuristically determine the plugin type by scanning source code.

    Reads ``__init__.py`` in the given directory and looks for class
    definition patterns.  Types are returned in priority order:

    * ``"memory"`` — if source references ``MemoryProvider``
    * ``"context_engine"`` — if source references ``ContextEngine``
    * ``"model_provider"`` — if source references ``ModelProvider``
    * ``"tool_provider"`` — if source references ``ToolProvider``
    * ``"plugin"`` — if source references ``Plugin``
    * ``"register"`` — if source defines a ``register()`` function
    * ``"image_gen"`` — if source references ``ImageGenProvider``
    * ``"unknown"`` — none of the above matched

    Parameters
    ----------
    plugin_dir : str
        Path to the plugin directory containing ``__init__.py``.

    Returns
    -------
    str
        One of the type strings listed above.
    """
    init_file = Path(plugin_dir) / "__init__.py"
    if not init_file.is_file():
        return "unknown"

    try:
        source = init_file.read_text(encoding="utf-8", errors="replace")
    except (OSError, UnicodeDecodeError):
        return "unknown"

    # Ordered by specificity — check more specific before general "Plugin"
    patterns = [
        (r"\bMemoryProvider\b", "memory"),
        (r"\bContextEngine\b", "context_engine"),
        (r"\bModelProvider\b", "model_provider"),
        (r"\bToolProvider\b", "tool_provider"),
        (r"\bImageGenProvider\b", "image_gen"),
        (r"\bAudioGenProvider\b", "audio_gen"),
        (r"\bProvider\b", "provider"),
        (r"\bclass\s+\w*Plugin\w*", "plugin"),
        (r"\bdef\s+register\s*\(", "register"),
    ]

    for pattern, plugin_type in patterns:
        if re.search(pattern, source):
            return plugin_type

    return "unknown"


def read_plugin_metadata(plugin_dir: str) -> dict:
    """Read ``plugin.yaml`` metadata from a plugin directory.

    Since this module uses only the Python stdlib (no PyYAML dependency),
    ``plugin.yaml`` is parsed with a simple line-based reader that handles
    the key ``: value`` format commonly used in plugin manifests.  Nested
    YAML structures (lists, dicts) are **not** parsed — they are stored as
    raw text strings.

    Returns an empty dict if the file does not exist or cannot be parsed.

    Parameters
    ----------
    plugin_dir : str
        Path to the plugin directory.

    Returns
    -------
    dict
        Parsed metadata or ``{}``.
    """
    yaml_file = Path(plugin_dir) / "plugin.yaml"
    if not yaml_file.is_file():
        return {}

    try:
        text = yaml_file.read_text(encoding="utf-8-sig", errors="replace")
    except (OSError, UnicodeDecodeError):
        return {}

    metadata: Dict = {}
    lines = text.splitlines()
    i = 0
    n = len(lines)

    while i < n:
        line = lines[i]
        stripped = line.strip()

        # Skip blank and comment lines
        if not stripped or stripped.startswith("#"):
            i += 1
            continue

        # Match key: value or key:
        match = re.match(r"^(\S[^:]*?):\s*(.*)", stripped)
        if not match:
            i += 1
            continue

        key = match.group(1).strip()
        value = match.group(2).strip()

        # If the value is empty, it might be the start of a multi-line
        # block (list item with leading dash or plain continuation).
        if value == "":
            # Collect continuation lines (indented relative to this key)
            continuation: List[str] = []
            j = i + 1
            base_indent = len(line) - len(line.lstrip())
            while j < n:
                next_line = lines[j]
                if not next_line.strip():
                    j += 1
                    continue
                next_indent = len(next_line) - len(next_line.lstrip())
                if next_indent <= base_indent:
                    break
                continuation.append(next_line)
                j += 1
            if continuation:
                value = "\n".join(line.rstrip() for line in continuation)
            i = j
        else:
            # Try to collect continuation for values that start a list
            if value == "-" and i + 1 < n:
                continuation = []
                j = i + 1
                base_indent = len(line) - len(line.lstrip())
                while j < n:
                    next_line = lines[j]
                    if not next_line.strip():
                        j += 1
                        continue
                    next_indent = len(next_line) - len(next_line.lstrip())
                    if next_indent <= base_indent:
                        break
                    continuation.append(next_line)
                    j += 1
                if continuation:
                    value = "\n".join(line.rstrip() for line in continuation)
                i = j
            else:
                i += 1

        # Store simple scalar values
        metadata[key] = _coerce_yaml_scalar(value)

    return metadata


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _coerce_yaml_scalar(value: str):
    """Coerce a YAML scalar string to the proper Python type.

    * Quoted strings are returned as-is (quotes stripped).
    * ``true``/``false`` (case-insensitive) → ``True``/``False``.
    * Numeric strings → ``int`` or ``float``.
    * ``null``/``~`` → ``None``.
    * Everything else returned as a stripped string.
    """
    v = value.strip()

    # Handle quoted strings
    if (v.startswith('"') and v.endswith('"')) or (
        v.startswith("'") and v.endswith("'")
    ):
        return v[1:-1]

    # Handle null
    if v.lower() in ("null", "~"):
        return None

    # Handle booleans
    if v.lower() == "true":
        return True
    if v.lower() == "false":
        return False

    # Handle numbers
    try:
        if "." in v or "e" in v.lower():
            return float(v)
        return int(v)
    except (ValueError, TypeError):
        pass

    return v
