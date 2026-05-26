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
from system.sandbox import Access, SandboxError

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
    # NOTE: Legacy helper — not currently used by any handler.
    # Handlers inline their own path resolution through the sandbox.
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

    Supports line-based pagination via offset and limit.
    Pass limit=0 to read the entire file.
    """
    path = str(args.get("file", args.get("path", ""))).strip()
    if not path:
        # Return a directory listing so the agent can discover what's available
        try:
            entries = _s().list_dir("self:")
            return tool_result(entries=entries, tip="Use read_own_source with file=<name>")
        except SandboxError as exc:
            return tool_error(str(exc))

    offset = int(args.get("offset", 0))
    limit = int(args.get("limit", 0))
    if offset < 0:
        return tool_error("offset must be >= 0", path=path, offset=offset)
    if limit < 0:
        return tool_error("limit must be >= 0", path=path, limit=limit)

    try:
        if ":" in path:
            # Explicit logical path — must be readable
            resolved = _s().resolve(path, Access.READ)
        else:
            # Bare filename — resolve relative to self:
            resolved = _s().resolve(f"self:{path}", Access.READ)
        if resolved.real.is_dir():
            return tool_result(
                entries=_s().list_dir(f"self:{path}" if ":" not in path else path),
                tip="Use read_own_source with file=<name> to read a specific file",
            )
        content = resolved.real.read_text(encoding="utf-8")
        if limit > 0 or offset > 0:
            lines = content.splitlines()
            chunk = lines[offset:offset + limit] if limit > 0 else lines[offset:]
            content = "\n".join(chunk)
        return tool_result(content=content, path=path, offset=offset, limit=limit)
    except (SandboxError, FileNotFoundError, IsADirectoryError, PermissionError) as exc:
        return tool_error(str(exc), path=path)


def _handle_write_fork(args: Dict[str, Any]) -> str:
    """Write a file to the evolution target directory (fork: namespace).

    Only allowed in 'fast' mode.  Accepts bare filenames or logical paths.

    Supports two modes:
      - Full overwrite: provide file + content (the default).
      - Incremental edit: provide file + old_string + new_string.
        The old_string must match exactly once in the existing file.
    """
    path = str(args.get("file", args.get("path", ""))).strip()
    content = str(args.get("content", ""))
    old_string = str(args.get("old_string", ""))
    new_string = str(args.get("new_string", "")) if "new_string" in args else None

    if not path:
        return tool_error("file is required")

    # ---- incremental edit mode ----
    if old_string:
        if new_string is None:
            return tool_error("new_string is required when old_string is provided")
        try:
            if ":" in path:
                resolved = _s().resolve(path, Access.READ)
            else:
                resolved = _s().resolve(f"fork:{path}", Access.READ)
            existing = resolved.real.read_text(encoding="utf-8")
        except (SandboxError, FileNotFoundError) as exc:
            return tool_error(str(exc), path=path)

        if old_string not in existing:
            return tool_error("old_string not found in file", path=path)

        count = existing.count(old_string)
        if count > 1:
            return tool_error(
                f"old_string matches {count} locations. Use more surrounding "
                f"context to make it unique.",
                path=path, matches=count,
            )

        content = existing.replace(old_string, new_string, 1)

    # ---- full overwrite mode ----
    elif not content:
        return tool_error("content is required when old_string is not provided")

    try:
        if ":" in path:
            resolved = _s().resolve(path, Access.WRITE)
        else:
            resolved = _s().resolve(f"fork:{path}", Access.WRITE)
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
                resolved = _s().resolve(path, Access.READ)
            else:
                resolved = _s().resolve(f"fork:{path}", Access.READ)
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
                    resolved = _s().resolve(f"fork:{entry}", Access.READ)
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


def _handle_evolve_code(args: Dict[str, Any]) -> str:
    """Finalize code evolution: validate fork then trigger the hot swap.

    After the agent has written evolved code to fork: via write_fork
    and checked syntax via validate_code, call this tool to run a
    thorough validation (syntax + compile check) and, if everything
    passes, signal the orchestrator to swap slow→fast.

    Only works in 'fast' mode.  In 'fallback' mode, returns an error.
    """
    from evolve.code import finalize_evolution

    deep = bool(args.get("deep", True))
    compile_timeout = int(args.get("compile_timeout", 30))

    try:
        return finalize_evolution(
            _s(),
            deep=deep,
            compile_timeout=compile_timeout,
        )
    except Exception as exc:
        return tool_error(str(exc))


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

'''
registry.register(
    name="read_own_source",
    toolset="code",
    schema={
        "description": (
            "Read a file from the agent's own source code (self: namespace).  "
            "Use this to inspect your own implementation.  Pass a bare "
            "filename like 'main.py' or 'entry/agent.py'.  "
            "With no arguments, lists available files.\n\n"
            "Supports line-based pagination via offset and limit.  "
            "Pass limit=0 (default) to read the entire file."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "file": {
                    "type": "string",
                    "description": "Filename to read (e.g. 'main.py', 'component/llm.py').",
                },
                "offset": {
                    "type": "integer",
                    "description": "0-indexed line number to start from (default 0).",
                    "default": 0,
                    "minimum": 0,
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum lines to return.  Pass 0 to read the whole file (default 0).",
                    "default": 0,
                    "minimum": 0,
                },
            },
        },
    },
    handler=_handle_read_own_source,
    emoji="🔬",
)
'''

registry.register(
    name="write_fork",
    toolset="code",
    schema={
        "description": (
            "Write an evolved version of a source file to the fork (slow) "
            "directory.  After writing all changes, call validate_code to "
            "check syntax, then call evolve_code to trigger the swap.  "
            "Accepts bare filenames (e.g. 'main.py').\n\n"
            "Two modes:\n"
            "- Full overwrite: pass file + content.\n"
            "- Incremental edit: pass file + old_string + new_string.  "
            "The old_string must match exactly once — include enough "
            "surrounding context (2-3 lines) to make it unique."
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
                    "description": "The new source code content (required for full overwrite).",
                },
                "old_string": {
                    "type": "string",
                    "description": "Exact text to find and replace (enables incremental edit mode).",
                },
                "new_string": {
                    "type": "string",
                    "description": "Replacement text. Use empty string to delete old_string.",
                },
            },
            "required": ["file"],
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


registry.register(
    name="evolve_code",
    toolset="code",
    schema={
        "description": (
            "Finalize the code evolution cycle.  Call this after you have "
            "written evolved source files to fork: via write_fork and "
            "verified syntax via validate_code (and validate_frontend if "
            "you modified any frontend files).  This tool runs a thorough "
            "validation (syntax + compile check) on all **.py files** in the "
            "fork directory.  It does NOT validate TypeScript or frontend "
            "builds — you must call validate_frontend beforehand if you "
            "touched frontend code.  If everything passes, the process exits "
            "and the orchestrator swaps the slow (evolved) code into place, "
            "then restarts the agent with the new version.  "
            "If validation fails, returns error details so you can fix "
            "the issues and retry.  "
            "Set deep=false to skip compile checks (faster but less thorough)."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "deep": {
                    "type": "boolean",
                    "description": "Whether to run py_compile checks (default true).",
                },
                "compile_timeout": {
                    "type": "integer",
                    "description": "Per-file timeout in seconds for compile checks (default 30).",
                },
            },
        },
    },
    handler=_handle_evolve_code,
    emoji="🚀",
)