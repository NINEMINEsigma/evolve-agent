"""长期交互式 Windows ConPTY Shell 工具。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from abstract.tools.registry import registry, tool_error, tool_result
from entity.constant import (
    SHELL_DEFAULT_TYPE,
    SHELL_READ_DEFAULT_CHARS,
    SHELL_READ_MAX_CHARS,
    SHELL_SUPPORTED_TYPES,
    SHELL_WAIT_TIMEOUT_SECONDS,
)
from entity.puretype import ToolAvailability, ToolDangerLevel
from system.shell_manager import ShellAccessError, ShellError, ShellManager

if TYPE_CHECKING:
    from entry.base_agent_loop import ToolContext


def _shell_available() -> bool:
    return ShellManager.is_available()


def _context_identity(context: ToolContext | None) -> tuple[str, str]:
    if context is None:
        raise ShellError("ToolContext is required for Shell operations")
    return context.resource_session_id, context.character_name


async def _handle_start_shell(
    args: dict[str, Any],
    context: ToolContext | None = None,
) -> dict:
    shell_type = str(args.get("shell", SHELL_DEFAULT_TYPE)).strip().lower()
    command = args.get("command")
    cwd = str(args.get("cwd", "ws:")).strip()
    if not isinstance(command, str):
        return tool_error("command must be a string")
    try:
        owner_session_id, character_name = _context_identity(context)
        if context is not None and cwd.startswith("ws:"):
            with context.agentspace_access([(cwd, True)]):
                pass
        info, output, namespace_env = await context.app.shell_manager.start_shell(
            owner_session_id,
            character_name,
            shell_type,
            cwd,
            command,
        )
        return tool_result(
            shell_id=info.shell_id,
            shell=info.model_dump(),
            output=output.model_dump(),
            namespace_env=namespace_env,
            message=(
                "Shell session started. Keep shell_id and output.next_offset for "
                "ReadShell, WriteShell, InterruptShell, or StopShell."
            ),
        )
    except (ShellError, ShellAccessError) as exc:
        return tool_error(str(exc), shell=shell_type, cwd=cwd)
    except Exception as exc:
        return tool_error(
            f"Failed to start Shell: {type(exc).__name__}: {exc}",
            shell=shell_type,
            cwd=cwd,
        )


async def _handle_read_shell(
    args: dict[str, Any],
    context: ToolContext | None = None,
) -> dict:
    shell_id = str(args.get("shell_id", "")).strip()
    try:
        offset = int(args.get("offset", 0))
        limit = int(args.get("limit", SHELL_READ_DEFAULT_CHARS))
        timeout = float(args.get("timeout", SHELL_WAIT_TIMEOUT_SECONDS))
    except (TypeError, ValueError):
        return tool_error("offset, limit, and timeout must be numeric", shell_id=shell_id)
    try:
        owner_session_id, character_name = _context_identity(context)
        output = await context.app.shell_manager.read_shell(
            owner_session_id,
            character_name,
            shell_id,
            offset,
            limit,
            timeout,
        )
        return tool_result(**output.model_dump())
    except (ShellError, ShellAccessError) as exc:
        return tool_error(str(exc), shell_id=shell_id)
    except Exception as exc:
        return tool_error(
            f"Failed to read Shell: {type(exc).__name__}: {exc}",
            shell_id=shell_id,
        )


async def _handle_write_shell(
    args: dict[str, Any],
    context: ToolContext | None = None,
) -> dict:
    shell_id = str(args.get("shell_id", "")).strip()
    text = args.get("text")
    if not isinstance(text, str):
        return tool_error("text must be a string", shell_id=shell_id)
    try:
        owner_session_id, character_name = _context_identity(context)
        output = await context.app.shell_manager.write_shell(
            owner_session_id,
            character_name,
            shell_id,
            text,
        )
        return tool_result(**output.model_dump())
    except (ShellError, ShellAccessError) as exc:
        return tool_error(str(exc), shell_id=shell_id)
    except Exception as exc:
        return tool_error(
            f"Failed to write Shell: {type(exc).__name__}: {exc}",
            shell_id=shell_id,
        )


async def _handle_interrupt_shell(
    args: dict[str, Any],
    context: ToolContext | None = None,
) -> dict:
    shell_id = str(args.get("shell_id", "")).strip()
    try:
        owner_session_id, character_name = _context_identity(context)
        output = await context.app.shell_manager.interrupt_shell(
            owner_session_id,
            character_name,
            shell_id,
        )
        return tool_result(**output.model_dump())
    except (ShellError, ShellAccessError) as exc:
        return tool_error(str(exc), shell_id=shell_id)
    except Exception as exc:
        return tool_error(
            f"Failed to interrupt Shell: {type(exc).__name__}: {exc}",
            shell_id=shell_id,
        )


async def _handle_stop_shell(
    args: dict[str, Any],
    context: ToolContext | None = None,
) -> dict:
    shell_id = str(args.get("shell_id", "")).strip()
    try:
        owner_session_id, character_name = _context_identity(context)
        info = await context.app.shell_manager.stop_shell(
            owner_session_id,
            character_name,
            shell_id,
        )
        return tool_result(
            stopped=True,
            termination=info.termination,
            exit_code=info.exit_code,
            shell=info.model_dump(),
        )
    except (ShellError, ShellAccessError) as exc:
        return tool_error(str(exc), shell_id=shell_id)
    except Exception as exc:
        return tool_error(
            f"Failed to stop Shell: {type(exc).__name__}: {exc}",
            shell_id=shell_id,
        )


_COMMON_USAGE = """Shell sessions are persistent Windows ConPTY command interpreters owned by the current main session and Agent character.

Output rules:
- Calls wait at most 30 seconds. Timeout only ends the current wait; it never stops the Shell.
- After output starts, the call returns after a short quiet window, or at the 30-second hard deadline.
- Output is normalized text addressed by absolute character offsets. Preserve `next_offset` for later ReadShell calls.
- A Shell remains alive across commands and response turns until StopShell, session termination/deletion, or application shutdown. Reuse it while the task is unfinished or the Shell remains useful.
- Completing a command or reply is not a reason to call StopShell. StopShell is for intentionally destroying the entire Shell; it also terminates running child processes.

Path rules:
- `cwd` is a sandbox logical directory such as `ws:`.
- Command text is never rewritten. StartShell returns `namespace_env`, which maps logical prefixes to shell-specific environment references.
- Use the returned `EVOLVE_PYTHON` reference when the Agent's own Python interpreter is required.
- Prefer dedicated Read, Write, PatchEdit, SearchFiles, and Grep tools over shell equivalents."""


registry.register(
    name="StartShell",
    toolset="shell",
    schema={
        "description": f"""Start a new persistent Windows ConPTY Shell and submit its first command.

{_COMMON_USAGE}

Supported shell values: {', '.join(sorted(SHELL_SUPPORTED_TYPES))}. The command must be one line without CR/LF. Starting a Shell and executing arbitrary commands can have irreversible effects.""",
        "parameters": {
            "type": "object",
            "properties": {
                "shell": {
                    "type": "string",
                    "enum": sorted(SHELL_SUPPORTED_TYPES),
                    "default": SHELL_DEFAULT_TYPE,
                    "description": "Shell interpreter: powershell, pwsh, or cmd.",
                },
                "command": {
                    "type": "string",
                    "description": "Non-empty single-line command submitted after the Shell starts.",
                },
                "cwd": {
                    "type": "string",
                    "default": "ws:",
                    "description": "Sandbox logical working directory.",
                },
                "reason": {
                    "type": "string",
                    "description": "Accurate reason for starting the Shell and executing the command.",
                },
            },
            "required": ["command", "reason"],
        },
    },
    handler=_handle_start_shell,
    is_async=True,
    check_fn=_shell_available,
    danger_level=ToolDangerLevel.dangerous,
    availability=ToolAvailability.EVERY,
)

registry.register(
    name="ReadShell",
    toolset="shell",
    schema={
        "description": f"""Read normalized output from an owned persistent Shell.

{_COMMON_USAGE}

This operation is non-consuming and repeatable. If offset is older than the retained buffer, the response advances to base_offset and sets truncated=true. Set timeout=0 for an immediate snapshot.""",
        "parameters": {
            "type": "object",
            "properties": {
                "shell_id": {"type": "string", "description": "Shell ID returned by StartShell."},
                "offset": {"type": "integer", "minimum": 0, "default": 0, "description": "Absolute character offset."},
                "limit": {"type": "integer", "minimum": 1, "maximum": SHELL_READ_MAX_CHARS, "default": SHELL_READ_DEFAULT_CHARS, "description": "Maximum normalized characters to return."},
                "timeout": {"type": "number", "minimum": 0, "maximum": SHELL_WAIT_TIMEOUT_SECONDS, "default": SHELL_WAIT_TIMEOUT_SECONDS, "description": "Maximum seconds to wait when no output is currently available."},
            },
            "required": ["shell_id"],
        },
    },
    handler=_handle_read_shell,
    is_async=True,
    check_fn=_shell_available,
    danger_level=ToolDangerLevel.safe,
    availability=ToolAvailability.EVERY,
)

registry.register(
    name="WriteShell",
    toolset="shell",
    schema={
        "description": f"""Submit one text line to an owned persistent Shell and wait for new output.

{_COMMON_USAGE}

The text must not contain CR/LF. An empty string sends Enter. Text can answer an interactive prompt or execute a new command at an idle prompt, so this operation is dangerous.""",
        "parameters": {
            "type": "object",
            "properties": {
                "shell_id": {"type": "string", "description": "Shell ID returned by StartShell."},
                "text": {"type": "string", "description": "Single input line; empty sends Enter."},
                "reason": {"type": "string", "description": "Accurate reason for submitting this input."},
            },
            "required": ["shell_id", "text", "reason"],
        },
    },
    handler=_handle_write_shell,
    is_async=True,
    check_fn=_shell_available,
    danger_level=ToolDangerLevel.dangerous,
    availability=ToolAvailability.EVERY,
)

registry.register(
    name="InterruptShell",
    toolset="shell",
    schema={
        "description": f"""Send Ctrl-C to the foreground command in an owned Shell without stopping the Shell.

{_COMMON_USAGE}

This never escalates to process-tree termination. Use StopShell explicitly only when the entire Shell must be destroyed; do not stop a Shell just because the foreground command was interrupted.""",
        "parameters": {
            "type": "object",
            "properties": {
                "shell_id": {"type": "string", "description": "Shell ID returned by StartShell."},
                "reason": {"type": "string", "description": "Accurate reason for interrupting the foreground command."},
            },
            "required": ["shell_id", "reason"],
        },
    },
    handler=_handle_interrupt_shell,
    is_async=True,
    check_fn=_shell_available,
    danger_level=ToolDangerLevel.dangerous,
    availability=ToolAvailability.EVERY,
)

registry.register(
    name="StopShell",
    toolset="shell",
    schema={
        "description": f"""Force-stop an owned Shell and its process tree, then release the ConPTY session.

{_COMMON_USAGE}

This destroys the persistent Shell environment and can corrupt work performed by a running foreground process. Use only when intentionally shutting down the entire Shell, not as routine cleanup after a command or response turn; keep a reusable Shell alive while the task is unfinished. A successful tool result has `stopped=true`; `termination="forced"` describes the Shell termination mode, while `exit_code` is only the process exit code and may be non-zero after forced termination. The process exit code does not make the StopShell operation fail.""",
        "parameters": {
            "type": "object",
            "properties": {
                "shell_id": {"type": "string", "description": "Shell ID returned by StartShell."},
                "reason": {"type": "string", "description": "Accurate reason for destroying the Shell session."},
            },
            "required": ["shell_id", "reason"],
        },
    },
    handler=_handle_stop_shell,
    is_async=True,
    check_fn=_shell_available,
    danger_level=ToolDangerLevel.dangerous,
    availability=ToolAvailability.EVERY,
)
