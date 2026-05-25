"""Shell command tool — execute CLI commands with user consent.

Registered at module-import time via ``registry.register()``.
The tool requires user confirmation for every command via a
CONFIRM_REQUEST/CONFIRM_RESPONSE WebSocket handshake.

Allowlist
    Stores *complete* commands (e.g. "git log --oneline") in a
    persistent JSON file under ``workspace/logs/shell_allowlist.json``.
    Only exact matches skip the consent prompt.  The frontend offers
    three actions: allow once / allow always / deny.
"""

from __future__ import annotations

import asyncio
import json
import locale
import logging
import subprocess  # nosec
import sys
import uuid
from pathlib import Path
from typing import Any, Dict, List, Set

from abstract.tools.registry import registry, tool_error, tool_result
from system.sandbox import SandboxError

logger = logging.getLogger(__name__)

# Import the sandbox reference from the filesystem module.
from .filesystem import _s as _get_sandbox

# ── persistent allowlist ─────────────────────────────────────────────
# Stored outside the workspace sandbox so the AI cannot self-escalate
# by writing to this file via write_file (ws: namespace).

from system.pathutils import find_repo_root


_ALLOWLIST_PATH = find_repo_root() / ".shell_allowlist.json"
# Built-in seed: these complete commands are always trusted without prompting.
_SEED_COMMANDS: Set[str] = {
    "dir", "ls", "echo .",
}


def _load_allowlist() -> Set[str]:
    try:
        if _ALLOWLIST_PATH.exists():
            data = json.loads(_ALLOWLIST_PATH.read_text(encoding="utf-8"))
            if isinstance(data, list):
                return set(data) | _SEED_COMMANDS
    except Exception:
        pass
    return set(_SEED_COMMANDS)


def _save_allowlist(entries: Set[str]) -> None:
    try:
        _ALLOWLIST_PATH.parent.mkdir(parents=True, exist_ok=True)
        _ALLOWLIST_PATH.write_text(
            json.dumps(sorted(entries - _SEED_COMMANDS), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception as exc:
        logger.warning("Failed to save allowlist: %s", exc)


def _s():
    return _get_sandbox()


# ── confirmation helper ──────────────────────────────────────────────

async def _request_user_confirm(
    session_id: str, cmd_parts: List[str], reason: str,
) -> str:
    """Send a CONFIRM_REQUEST to the frontend and wait for the action.

    Returns one of ``"allow_once"``, ``"allow_always"``, or ``"deny"``
    (defaults to ``"deny"`` on timeout).
    """
    from gateway.server import _tool_ws_sinks, _pending_confirms, _register_confirm_session

    request_id = uuid.uuid4().hex[:8]
    cmd_str = " ".join(cmd_parts)

    loop = asyncio.get_event_loop()
    fut: asyncio.Future[str] = loop.create_future()
    _pending_confirms[request_id] = fut
    _register_confirm_session(request_id, session_id)

    ws = _tool_ws_sinks.get(session_id)
    if ws:
        try:
            await ws.send_text(json.dumps({
                "type": "confirm_request",
                "session_id": session_id,
                "request_id": request_id,
                "content": f"命令: `{cmd_str}`\n原因: {reason}",
                "tool": "run_command",
                "args": {"command": cmd_parts, "reason": reason},
            }, ensure_ascii=False))
        except Exception:
            _pending_confirms.pop(request_id, None)
            return "deny"

    try:
        action: str = await asyncio.wait_for(fut, timeout=3600.0)
        if action in ("allow_once", "allow_always"):
            return action
        return "deny"
    except asyncio.CancelledError:
        _pending_confirms.pop(request_id, None)
        return "deny"
    except asyncio.TimeoutError:
        _pending_confirms.pop(request_id, None)
        return "deny"
    except Exception:
        _pending_confirms.pop(request_id, None)
        return "deny"


# ── tool handler ─────────────────────────────────────────────────────

async def _handle_run_command(args: Dict[str, Any]) -> str:
    """Run a shell command after allowlist + user consent checks.

    Expected args:
        command: list[str] — command and arguments
        reason:  str      — why the agent wants to run this
        cwd:     str      — working directory (ws: namespace), optional
    """
    raw_cmd = args.get("command")
    reason = str(args.get("reason", "(no reason given)")).strip()
    cwd = str(args.get("cwd", "ws:")).strip()
    session_id = str(args.get("_session_id", ""))

    # ── validate command ──
    if not raw_cmd or not isinstance(raw_cmd, list):
        return tool_error("'command' must be a non-empty list of strings")
    cmd_parts: List[str] = [str(p) for p in raw_cmd]
    if not cmd_parts:
        return tool_error("'command' must be a non-empty list")

    cmd_full = " ".join(cmd_parts)

    # ── allowlist check (exact full-command match) ──
    allowlist = _load_allowlist()
    if cmd_full in allowlist:
        # Already trusted — skip confirmation
        return _execute(cmd_parts, cwd)

    # ── user confirmation ──
    if session_id:
        action = await _request_user_confirm(session_id, cmd_parts, reason)
    else:
        action = "deny"

    if action == "deny":
        return tool_error(
            "User denied the command or confirmation timed out.",
            command=cmd_parts,
            denied=True,
        )

    if action == "allow_always":
        allowlist.add(cmd_full)
        _save_allowlist(allowlist)
        logger.info("Added to allowlist: %s", cmd_full)

    # action is allow_once or allow_always — execute
    return _execute(cmd_parts, cwd)


def _execute(cmd_parts: List[str], cwd: str) -> str:
    """Execute a trusted / approved command and return the result."""
    if cmd_parts and cmd_parts[0] not in _s().allowed_commands:
        return tool_error(f"Command '{cmd_parts[0]}' not in the allowed list")

    logger.info("run_command | cwd=%s cmd=%s", cwd, cmd_parts)
    try:
        _enc = locale.getpreferredencoding(False) or sys.getfilesystemencoding() or "utf-8"
        result = _s().run(cmd_parts, cwd_ns=cwd, timeout=30, encoding=_enc, errors="replace")
    except SandboxError as exc:
        return tool_error(str(exc))
    except subprocess.TimeoutExpired:
        return tool_error("Command timed out after 30s", command=cmd_parts)
    except Exception as exc:
        return tool_error(str(exc), command=cmd_parts)

    return tool_result(
        exit_code=result.returncode,
        stdout=result.stdout[-4000:] if len(result.stdout) > 4000 else result.stdout,
        stderr=result.stderr[-2000:] if len(result.stderr) > 2000 else result.stderr,
        command=cmd_parts,
    )


# ── registration ─────────────────────────────────────────────────────

registry.register(
    name="run_command",
    toolset="shell",
    schema={
        "description": (
            "Execute a shell command in the workspace.  "
            "The user will be prompted to approve (allow once), "
            "trust permanently (allow always), or deny the command.  "
            "Commands previously allowed with 'allow always' skip the "
            "prompt.  Always include a 'reason' explaining what the "
            "command does.  "
            "Use this to install packages, run tests, or inspect files."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Command and arguments as a list, e.g. ['pip', 'install', 'requests'].",
                },
                "reason": {
                    "type": "string",
                    "description": "Why the agent needs to run this command.",
                },
                "cwd": {
                    "type": "string",
                    "description": "Working directory (ws: namespace, default 'ws:').",
                    "default": "ws:",
                },
            },
            "required": ["command", "reason"],
        },
    },
    handler=_handle_run_command,
    is_async=True,
    emoji="💻",
)