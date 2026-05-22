"""Code introspection and evolution tools.

All paths are logical (prefixed with namespace), resolved through
the shared Sandbox.  These tools let the agent read its own source,
write evolved code, and validate changes.
"""

from __future__ import annotations

import ast
import json
import logging
import subprocess  # nosec
from typing import Any, Dict, List

from abstract.tools.registry import registry, tool_error, tool_result
from system.sandbox import SandboxError

logger = logging.getLogger(__name__)

# Import the sandbox reference from the filesystem module's setter
# (it's the same singleton — main.py sets it once for all tools).
from .filesystem import _s as _get_sandbox


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _s():
    return _get_sandbox()


def _resolve_sandboxed_path(path: str, mode: str) -> str:
    """Resolve a logical path to an absolute path via the sandbox.

    Special case: bare filenames without namespace prefix are treated
    as relative to ``self:`` (for read_own_source / write_fork).
    """
    if ":" not in path:
        # Bare filename — resolve relative to self: for read, fork: for write
        return str(_s().resolve(f"{'fork' if mode == 'write' else 'self'}:{path}",
                                "write" if mode == "write" else "read").real)
    raise SandboxError("Use bare filenames (e.g. 'main.py') for code tools")


# ---------------------------------------------------------------------------
# Tool handlers
# ---------------------------------------------------------------------------


def _handle_read_own_source(args: Dict[str, Any]) -> str:
    """Read a file from the agent's own source directory (self: namespace).

    Accepts bare filenames (e.g. 'main.py') which resolve to self:, or
    full logical paths.  Only readable namespaces are allowed.
    """
    path = str(args.get("file", args.get("path", ""))).strip()
    if not path:
        # Return a directory listing so the agent can discover what's available
        try:
            entries = _s().list_dir("self:")
            return tool_result(entries=entries, tip="Use read_own_source with file=<name>")
        except SandboxError as exc:
            return tool_error(str(exc))

    try:
        if ":" in path:
            # Explicit logical path — must be readable
            resolved = _s().resolve(path, "read")
        else:
            # Bare filename — resolve relative to self:
            resolved = _s().resolve(f"self:{path}", "read")
        content = resolved.real.read_text(encoding="utf-8")
        return tool_result(content=content, path=path)
    except (SandboxError, FileNotFoundError) as exc:
        return tool_error(str(exc), path=path)


def _handle_write_fork(args: Dict[str, Any]) -> str:
    """Write a file to the evolution target directory (fork: namespace).

    Only allowed in 'fast' mode.  Accepts bare filenames or logical paths.
    """
    path = str(args.get("file", args.get("path", ""))).strip()
    content = str(args.get("content", ""))
    if not path or not content:
        return tool_error("file and content are required")

    try:
        if ":" in path:
            resolved = _s().resolve(path, "write")
        else:
            resolved = _s().resolve(f"fork:{path}", "write")
        resolved.real.parent.mkdir(parents=True, exist_ok=True)
        resolved.real.write_text(content, encoding="utf-8")
        return tool_result(success=True, path=path, bytes=len(content.encode("utf-8")))
    except SandboxError as exc:
        return tool_error(str(exc), path=path)


def _handle_validate_code(args: Dict[str, Any]) -> str:
    """Validate Python code for syntax errors.

    *file* — bare filename or logical path to validate.
    If no file specified, validates all .py files in the fork: namespace.
    """
    path = str(args.get("file", "")).strip()
    results: List[Dict[str, Any]] = []

    if path:
        # Validate single file
        try:
            if ":" in path:
                resolved = _s().resolve(path, "read")
            else:
                resolved = _s().resolve(f"fork:{path}", "read")
            source = resolved.real.read_text(encoding="utf-8")
            ast.parse(source, filename=str(resolved.real))
            results.append({"file": path, "status": "ok"})
        except SyntaxError as exc:
            results.append({
                "file": path,
                "status": "syntax_error",
                "line": exc.lineno,
                "offset": exc.offset,
                "message": str(exc),
            })
        except (SandboxError, FileNotFoundError) as exc:
            results.append({"file": path, "status": "error", "message": str(exc)})
    else:
        # Validate all .py files in fork:
        try:
            entries = _s().list_dir("fork:")
            for entry in entries:
                if not entry.endswith(".py"):
                    continue
                try:
                    resolved = _s().resolve(f"fork:{entry}", "read")
                    source = resolved.real.read_text(encoding="utf-8")
                    ast.parse(source, filename=str(resolved.real))
                    results.append({"file": entry, "status": "ok"})
                except SyntaxError as exc:
                    results.append({
                        "file": entry,
                        "status": "syntax_error",
                        "line": exc.lineno,
                        "offset": exc.offset,
                        "message": str(exc),
                    })
                except Exception as exc:
                    results.append({"file": entry, "status": "error", "message": str(exc)})
        except SandboxError as exc:
            return tool_error(str(exc))

    ok = all(r.get("status") == "ok" for r in results)
    return tool_result(valid=ok, results=results)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


registry.register(
    name="read_own_source",
    toolset="code",
    schema={
        "description": (
            "Read a file from the agent's own source code (self: namespace).  "
            "Use this to inspect your own implementation.  Pass a bare "
            "filename like 'main.py' or 'entry/agent.py'.  "
            "With no arguments, lists available files."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "file": {
                    "type": "string",
                    "description": "Filename to read (e.g. 'main.py', 'component/llm.py').",
                },
            },
        },
    },
    handler=_handle_read_own_source,
    emoji="🔬",
)


registry.register(
    name="write_fork",
    toolset="code",
    schema={
        "description": (
            "Write an evolved version of a source file to the fork (slow) "
            "directory.  After writing all changes, call validate_code to "
            "check syntax, then call evolve_code to trigger the swap.  "
            "Accepts bare filenames (e.g. 'main.py')."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "file": {
                    "type": "string",
                    "description": "Target filename (e.g. 'main.py').",
                },
                "content": {
                    "type": "string",
                    "description": "The new source code content.",
                },
            },
            "required": ["file", "content"],
        },
    },
    handler=_handle_write_fork,
    emoji="🧬",
)


registry.register(
    name="validate_code",
    toolset="code",
    schema={
        "description": (
            "Check Python source files for syntax errors using ast.parse().  "
            "If a filename is given, validates that file.  Otherwise "
            "validates all .py files in the fork: namespace.  "
            "Call this after writing evolved code."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "file": {
                    "type": "string",
                    "description": "Optional: specific file to validate.",
                },
            },
        },
    },
    handler=_handle_validate_code,
    emoji="✅",
)