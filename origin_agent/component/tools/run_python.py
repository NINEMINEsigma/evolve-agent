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

logger = logging.getLogger(__name__)

# ── 文件系统模块的 sandbox 引用 ──────────────────────────────────────

from .filesystem import _s as _get_sandbox


def _s():
    return _get_sandbox()


from component.approval import ApprovalResult, request_user_confirm


# ── 工具 handler ─────────────────────────────────────────────────────


async def _handle_run_python(args: Dict[str, Any]) -> dict:
    """执行 Python 代码，始终使用与 agent 进程相同的解释器。"""
    code: str = str(args.get("code", "")).strip()
    script: str = str(args.get("script", "")).strip()
    extra_args: List[str] = [str(a) for a in args.get("args", [])]
    reason: str = str(args.get("reason", "(no reason given)")).strip()
    cwd: str = str(args.get("cwd", "ws:")).strip()
    timeout: int = int(args.get("timeout", 60))
    session_id: str = str(args.get("_session_id", ""))

    if not code and not script:
        return tool_error("Either 'code' or 'script' is required")
    if code and script:
        return tool_error("Provide either 'code' or 'script', not both")

    # ── 构建完整的命令数组 ──
    cmd_parts: List[str] = [sys.executable]

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

    # ── 用户确认（若已由工具执行入口预审批则跳过）──
    _pre_approved: bool = args.get("_pre_approved", False)
    _approval_action: str = args.get("_approval_action", "allow_once")
    result: ApprovalResult
    if _pre_approved:
        result = ApprovalResult(action=_approval_action)
    elif session_id:
        cmd_str = " ".join(cmd_parts)
        result = await request_user_confirm(
            session_id, "run_python",
            {"command": cmd_parts, "reason": reason},
            reason,
            f"Python execution: `{cmd_str}`\nReason: {reason}",
        )
    else:
        result = ApprovalResult(action="deny", deny_reason="缺少 session_id")

    if result.action == "deny":
        # 审批模型/用户/系统
        source_label = {"model": "approval model", "user": "user", "system": "system"}.get(result.denied_by, "system")
        return tool_error(
            f"[{source_label} denied] {result.deny_reason or 'unknown reason'}",
            command=cmd_parts,
            denied=True,
        )

    return _execute(cmd_parts, cwd, timeout)


def _execute(cmd_parts: List[str], cwd: str, timeout: int = 60) -> dict:
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
        # 使用与 agent 进程相同的 Python 解释器执行代码。
        # 与 run_command 不同，此工具固定使用当前解释器的完整路径，
        # 不受 PATH 中 python 指向的影响。
        # 两种模式：
        #   1. 内联代码：传递 code="print('hello')"（等效于 python -c）。
        #   2. 脚本文件：传递 script="ws:scripts/test.py"，可选地传递 args。
        # 用户将被提示批准（允许一次/始终允许/拒绝）。
        # “始终允许”由统一工具 allowlist 层按工具名和参数指纹持久化。
        "description": (
            "Execute code using the same Python interpreter as the agent process. "
            "Unlike run_command, this tool always uses the full path of the current interpreter, "
            "unaffected by which python PATH points to.\n\n"
            "Two modes:\n"
            "  1. Inline code: pass code=\"print('hello')\" (equivalent to python -c).\n"
            "  2. Script file: pass script=\"ws:scripts/test.py\", "
            "optionally with args=[\"--flag\", \"val\"].\n\n"
            "The user will be prompted to approve (allow once / always allow / deny). "
            "Always-allow approvals are persisted by the unified tool allowlist layer."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "code": {
                    "type": "string",
                    # 要执行的 Python 内联代码（等效于 python -c "..."）。与 script 互斥。
                    "description": "Inline Python code to execute (equivalent to python -c \"...\"). Mutually exclusive with script.",
                },
                "script": {
                    "type": "string",
                    # 要执行的 Python 脚本的逻辑路径（如 'ws:script.py'、'fork:test.py'）。与 code 互斥。
                    "description": "Logical path to a Python script to execute (e.g. 'ws:script.py', 'fork:test.py'). Mutually exclusive with code.",
                },
                "args": {
                    "type": "array",
                    "items": {"type": "string"},
                    # 传递给脚本的附加参数（仅 script 模式可用）。
                    "description": "Additional arguments to pass to the script (script mode only).",
                },
                "reason": {
                    "type": "string",
                    # 执行此 Python 代码的原因。
                    "description": "The reason for executing this Python code.",
                },
                "cwd": {
                    "type": "string",
                    # 工作目录（ws: 命名空间，默认 'ws:'）。
                    "description": "Working directory (ws: namespace, default 'ws:').",
                    "default": "ws:",
                },
                "timeout": {
                    "type": "integer",
                    # 超时秒数（默认 60，最大 300）。
                    "description": "Timeout in seconds (default 60, max 300).",
                    "default": 60,
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