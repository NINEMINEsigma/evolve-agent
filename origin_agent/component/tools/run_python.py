"""Python 执行工具 — 始终使用与 agent 进程相同的解释器运行 Python 代码。

模块导入时通过 ``registry.register()`` 注册。
与 ``run_command`` 不同，此工具固定使用 ``sys.executable``
（即启动 agent 的那个 Python），不受 PATH 影响。

支持两种模式：
  - 内联代码：传递 ``code``（等效于 ``python -c "..."``）
  - 脚本文件：传递 ``script``（逻辑路径，支持 ``ws:``、``fork:`` 命名空间）

两种模式都可以传递附加的 ``args`` 列表作为脚本参数。
"""

from __future__ import annotations

import locale
import logging
import subprocess  # nosec
import sys
from typing import Any, Dict, List

from abstract.tools.registry import registry, tool_error, tool_result
from system.sandbox import Access, SandboxError
from entity.constant import SUBPROCESS_TIMEOUT_DEFAULT

logger = logging.getLogger(__name__)

# ── 文件系统模块的 sandbox 引用 ──────────────────────────────────────

from .filesystem import _s as _get_sandbox


def _s():
    return _get_sandbox()


# ── 工具 handler ─────────────────────────────────────────────────────


async def _handle_run_python(args: dict[str, Any]) -> dict:
    """执行 Python 代码，始终使用与 agent 进程相同的解释器。"""
    code: str = str(args.get("code", "")).strip()
    script: str = str(args.get("script", "")).strip()
    extra_args: list[str] = [str(a) for a in args.get("args", [])]
    python_path: str = str(args.get("python_path", "")).strip()
    cwd: str = str(args.get("cwd", "ws:")).strip()
    timeout: int = int(args.get("timeout", SUBPROCESS_TIMEOUT_DEFAULT))

    if not code and not script:
        return tool_error("Either 'code' or 'script' is required")
    if code and script:
        return tool_error("Provide either 'code' or 'script', not both")

    # ── 确定解释器路径 ──
    if python_path:
        try:
            resolved_interp = _s().resolve(python_path, Access.READ)
            interpreter = str(resolved_interp.real)
        except SandboxError as exc:
            return tool_error(str(exc), python_path=python_path)
    else:
        interpreter = sys.executable

    # ── 构建完整的命令数组 ──
    cmd_parts: list[str] = [interpreter]

    if code:
        cmd_parts += ["-c", code]
    else:
        # script — 通过 sandbox 解析逻辑路径
        try:
            resolved = _s().resolve(script, Access.READ)
            cmd_parts.append(str(resolved.real))
        except SandboxError as exc:
            return tool_error(str(exc), script=script)
        if extra_args:
            cmd_parts.extend(extra_args)

    # 审批由 AgentLoop 统一入口处理（handler 内不再重复确认）
    return _execute(cmd_parts, cwd, timeout)


def _execute(cmd_parts: list[str], cwd: str, timeout: int = SUBPROCESS_TIMEOUT_DEFAULT) -> dict:
    """执行已批准的命令并返回结果。"""
    logger.info("run_python | cwd=%s cmd=%s", cwd, cmd_parts)
    result: subprocess.CompletedProcess
    try:
        _enc = locale.getpreferredencoding(False) or sys.getfilesystemencoding() or "utf-8"
        result = _s().run(cmd_parts, cwd_ns=cwd, timeout=timeout, encoding=_enc, errors="replace")
    except SandboxError as exc:
        return tool_error(str(exc))
    except subprocess.TimeoutExpired:
        return tool_error(f"Python execution timed out after {timeout}s", command=cmd_parts)
    except Exception as exc:
        return tool_error(str(exc), command=cmd_parts)

    return tool_result(
        exit_code=result.returncode,
        stdout=result.stdout,
        stderr=result.stderr,
        command=cmd_parts,
    )


# ── 注册 ─────────────────────────────────────────────────────

registry.register(
    name="run_python",
    toolset="python",
    schema={
        # Execute code using the same Python interpreter as the agent process.
        # Unlike run_command, this tool always uses the full path of the current interpreter,
        # unaffected by which python PATH points to.
        # Two modes:
        #   1. Inline code: pass code="print('hello')" (equivalent to python -c).
        #   2. Script file: pass script="ws:scripts/test.py", optionally with args=["--flag", "val"].
        # The user will be prompted to approve (allow once / always allow / deny).
        # Always-allow approvals are persisted by the unified tool allowlist layer.
        "description": """Execute code using the same Python interpreter as the agent process. Unlike run_command, this tool always uses the full path of the current interpreter, unaffected by which python PATH points to.

Two modes:
  1. Inline code: pass code="print('hello')" (equivalent to python -c).
  2. Script file: pass script="ws:scripts/test.py", optionally with args=["--flag", "val"].

The user will be prompted to approve (allow once / always allow / deny). Always-allow approvals are persisted by the unified tool allowlist layer.""",
        "parameters": {
            "type": "object",
            "properties": {
                "code": {
                    "type": "string",
                    # Inline Python code to execute (equivalent to python -c "..."). Mutually exclusive with script.
                    "description": """Inline Python code to execute (equivalent to python -c "..."). Mutually exclusive with script.""",
                },
                "script": {
                    "type": "string",
                    # Logical path to a Python script to execute (e.g. 'ws:script.py', 'fork:test.py'). Mutually exclusive with code.
                    "description": """Logical path to a Python script to execute (e.g. 'ws:script.py', 'fork:test.py'). Mutually exclusive with code.""",
                },
                "args": {
                    "type": "array",
                    "items": {"type": "string"},
                    # Additional arguments to pass to the script (script mode only).
                    "description": """Additional arguments to pass to the script (script mode only).""",
                },
                "python_path": {
                    "type": "string",
                    # Path to the Python interpreter to use (e.g. path to a virtualenv python). Leave empty to use the current interpreter.
                    "description": """Path to the Python interpreter to use (e.g. path to a virtualenv python). Leave empty to use the current interpreter.""",
                    "default": "",
                },
                "reason": {
                    "type": "string",
                    # The reason for executing this Python code.
                    "description": """The reason for executing this Python code.""",
                },
                "cwd": {
                    "type": "string",
                    # Working directory (ws: namespace, default 'ws:').
                    "description": """Working directory (ws: namespace, default 'ws:').""",
                    "default": "ws:",
                },
                "timeout": {
                    "type": "integer",
                    # Timeout in seconds.
                    "description": """Timeout in seconds.""",
                    "default": SUBPROCESS_TIMEOUT_DEFAULT,
                },
            },
            "required": ["reason"],
        },
    },
    handler=_handle_run_python,
    is_async=True,
    emoji="🐍",
    danger_level="dangerous",
)