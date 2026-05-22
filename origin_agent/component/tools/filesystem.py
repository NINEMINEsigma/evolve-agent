"""File-system tools — all paths are logical (prefixed with namespace).

Registered at module-import time via ``registry.register()``.
Every tool handler resolves paths through the shared ``Sandbox`` instance
(set by ``set_sandbox()`` from ``main.py`` before the agent loop starts).

Path format: ``namespace:relative/path``
  - ``self:``  read-only  (own source code)
  - ``fork:``  write-only (evolved code destination)
  - ``ws:``    read+write (general workspace)
  - ``fix:``   write-only (repair target, fallback mode only)
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict

from abstract.tools.registry import registry, tool_error, tool_result
from system.sandbox import Access, Sandbox, SandboxError

logger = logging.getLogger(__name__)

# Populated by main.py before the agent loop starts.
_sandbox: Sandbox | None = None


def set_sandbox(s: Sandbox) -> None:
    global _sandbox
    _sandbox = s


def _s() -> Sandbox:
    if _sandbox is None:
        raise RuntimeError("Sandbox not initialized — call set_sandbox() first")
    return _sandbox


# ---------------------------------------------------------------------------
# Tool handlers
# ---------------------------------------------------------------------------


def _handle_read(args: Dict[str, Any]) -> str:
    path = str(args.get("path", "")).strip()
    if not path:
        return tool_error("path is required", path=path)
    try:
        content = _s().read(path)
        return tool_result(content=content, path=path)
    except SandboxError as exc:
        return tool_error(str(exc), path=path)


def _handle_write(args: Dict[str, Any]) -> str:
    path = str(args.get("path", "")).strip()
    content = str(args.get("content", ""))
    if not path:
        return tool_error("path is required", path=path)
    try:
        _s().write(path, content)
        return tool_result(success=True, path=path, bytes=len(content.encode("utf-8")))
    except SandboxError as exc:
        return tool_error(str(exc), path=path)


def _handle_list(args: Dict[str, Any]) -> str:
    path = str(args.get("path", "")).strip()
    if not path:
        return tool_error("path is required", path=path)
    try:
        entries = _s().list_dir(path)
        return tool_result(entries=entries, path=path, count=len(entries))
    except SandboxError as exc:
        return tool_error(str(exc), path=path)


def _handle_delete(args: Dict[str, Any]) -> str:
    path = str(args.get("path", "")).strip()
    if not path:
        return tool_error("path is required", path=path)
    try:
        _s().delete(path)
        return tool_result(success=True, path=path, deleted=True)
    except SandboxError as exc:
        return tool_error(str(exc), path=path)


def _handle_exists(args: Dict[str, Any]) -> str:
    path = str(args.get("path", "")).strip()
    if not path:
        return tool_error("path is required", path=path)
    exists = _s().exists(path)
    return tool_result(exists=exists, path=path)


# ---------------------------------------------------------------------------
# Registration (executes at module-import time)
# ---------------------------------------------------------------------------


def _param(path_desc: str, required: bool = True) -> Dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": f"Logical path ({path_desc}). "
                "Must use a namespace prefix: self:, fork:, ws:, or fix:.",
            },
        },
        "required": (["path"] if required else []),
    }


# -- read_file
registry.register(
    name="read_file",
    toolset="filesystem",
    schema={
        "description": (
            "Read the contents of a file.  The path must use a namespace "
            "prefix: 'self:' for own source code, 'ws:' for workspace data, "
            "'fork:' for evolved code, or 'fix:' for repair targets.  "
            "Examples: 'self:main.py', 'ws:logs/error.log'."
        ),
        "parameters": _param("file to read"),
    },
    handler=_handle_read,
    emoji="📖",
)


# -- write_file
registry.register(
    name="write_file",
    toolset="filesystem",
    schema={
        "description": (
            "Write content to a file.  The path must use a namespace prefix.  "
            "Use 'ws:' for workspace data or 'fork:' for evolved code.  "
            "'self:' is read-only — you cannot modify your own running code "
            "directly.  Directories are created automatically."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Logical path. Must use ws: or fork: prefix.",
                },
                "content": {
                    "type": "string",
                    "description": "Content to write to the file.",
                },
            },
            "required": ["path", "content"],
        },
    },
    handler=_handle_write,
    emoji="✏️",
)


# -- list_directory
registry.register(
    name="list_directory",
    toolset="filesystem",
    schema={
        "description": (
            "List the contents of a directory.  Returns entry names "
            "(not full paths).  Use any namespace prefix."
        ),
        "parameters": _param("directory to list"),
    },
    handler=_handle_list,
    emoji="📂",
)


# -- delete_file
registry.register(
    name="delete_file",
    toolset="filesystem",
    schema={
        "description": (
            "Delete a file or empty directory.  Only writable namespaces "
            "(ws:, fork:, fix:) are allowed."
        ),
        "parameters": _param("file or directory to delete"),
    },
    handler=_handle_delete,
    emoji="🗑️",
)


# -- file_exists
registry.register(
    name="file_exists",
    toolset="filesystem",
    schema={
        "description": "Check whether a file or directory exists (all namespaces).",
        "parameters": _param("file or directory to check", required=True),
    },
    handler=_handle_exists,
    emoji="🔍",
)