"""Frontend validation tool — verify that evolved frontend code builds.

Registered at module-import time via ``registry.register()``.
Runs ``pnpm install`` and ``pnpm run build`` inside the target frontend
directory (default ``fork:frontend`` in fast mode) to catch TypeScript
or build errors before the evolution swap.
"""

from __future__ import annotations

import logging
import subprocess  # nosec
import sys
from typing import Any, Dict

from abstract.tools.registry import registry, tool_error, tool_result
from system.sandbox import Access, SandboxError

logger = logging.getLogger(__name__)

# Import the sandbox reference from the filesystem module.
from .filesystem import _s as _get_sandbox


def _s():
    return _get_sandbox()


# ---------------------------------------------------------------------------
# Tool handler
# ---------------------------------------------------------------------------


def _handle_validate_frontend(args: Dict[str, Any]) -> str:
    """Validate frontend code by running pnpm install && pnpm run build.

    Expected args:
        path: str — logical path to the frontend directory
                    (default "fork:frontend" in fast mode).
    """
    path = str(args.get("path", "")).strip()

    # ---- resolve target directory ----
    if not path:
        path = "fork:frontend"

    try:
        if ":" in path:
            resolved = _s().resolve(path, Access.READ)
        else:
            resolved = _s().resolve(f"fork:{path}", Access.READ)
        frontend_dir = resolved.real
    except (SandboxError, FileNotFoundError) as exc:
        return tool_error(str(exc), path=path)

    if not frontend_dir.is_dir():
        return tool_error(f"Not a directory: {frontend_dir}", path=path)

    pkg_json = frontend_dir / "package.json"
    if not pkg_json.exists():
        return tool_error("No package.json found in frontend directory", path=path)

    pnpm = "pnpm.cmd" if sys.platform == "win32" else "pnpm"

    # ---- pnpm install ----
    logger.info("validate_frontend | install | cwd=%s", frontend_dir)
    try:
        install_proc = subprocess.run(
            [pnpm, "install", "--no-interactive"],
            cwd=str(frontend_dir),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
        )
        if install_proc.returncode != 0:
            return tool_result(
                valid=False,
                stage="install",
                exit_code=install_proc.returncode,
                stdout=_truncate(install_proc.stdout),
                stderr=_truncate(install_proc.stderr),
                hint=(
                    "pnpm install failed. Check dependency conflicts, "
                    "lock file corruption, or missing peer dependencies."
                ),
            )
    except subprocess.TimeoutExpired:
        return tool_result(
            valid=False, stage="install", error="Timeout after 120s",
        )
    except Exception as exc:
        return tool_result(
            valid=False, stage="install", error=str(exc),
        )

    # ---- pnpm run build ----
    logger.info("validate_frontend | build | cwd=%s", frontend_dir)
    try:
        build_proc = subprocess.run(
            [pnpm, "run", "build"],
            cwd=str(frontend_dir),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
        )
        if build_proc.returncode != 0:
            return tool_result(
                valid=False,
                stage="build",
                exit_code=build_proc.returncode,
                stdout=_truncate(build_proc.stdout),
                stderr=_truncate(build_proc.stderr),
                hint=(
                    "Frontend build failed. Check TypeScript errors, "
                    "missing imports, or build configuration issues."
                ),
            )
    except subprocess.TimeoutExpired:
        return tool_result(
            valid=False, stage="build", error="Timeout after 120s",
        )
    except Exception as exc:
        return tool_result(
            valid=False, stage="build", error=str(exc),
        )

    return tool_result(
        valid=True,
        stage="build",
        exit_code=0,
        message="Frontend validation passed: install + build successful.",
    )


def _truncate(text: str | None, limit: int = 2000) -> str:
    """Return the tail of *text* up to *limit* characters."""
    if not text:
        return ""
    if len(text) <= limit:
        return text
    return "..." + text[-limit:]


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

registry.register(
    name="validate_frontend",
    toolset="frontend",
    schema={
        "description": (
            "Validate frontend code by running ``pnpm install`` and "
            "``pnpm run build`` in the target frontend directory.  "
            "Use this AFTER modifying any file under ``frontend/`` "
            "(e.g. ``.tsx``, ``.ts``, ``.css``) and BEFORE calling "
            "``evolve_code``.  This catches TypeScript and build errors "
            "that ``validate_code`` cannot detect.\n\n"
            "Default path is ``fork:frontend`` (the evolution target)."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": (
                        "Logical path to the frontend directory "
                        "(e.g. 'fork:frontend'). "
                        "Defaults to 'fork:frontend'."
                    ),
                },
            },
        },
    },
    handler=_handle_validate_frontend,
    emoji="🎨",
)