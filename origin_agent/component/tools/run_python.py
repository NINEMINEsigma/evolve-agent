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

import asyncio
import json
import locale
import logging
import subprocess  # nosec
import sys
from pathlib import Path
from typing import Any, Dict, List, Set

from abstract.tools.registry import registry, tool_error, tool_result
from system.sandbox import Access, SandboxError

logger = logging.getLogger(__name__)

# ── 持久化允许列表（复用 shell.py 同一文件）────────────────────────────

from system.pathutils import find_repo_root

_ALLOWLIST_PATH: Path = find_repo_root() / ".shell_allowlist.json"

_SEED_COMMANDS: Set[str] = set()


def _load_allowlist() -> Set[str]:
    try:
        if _ALLOWLIST_PATH.exists():
            data: list = json.loads(_ALLOWLIST_PATH.read_text(encoding="utf-8"))
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


# ── 文件系统模块的 sandbox 引用 ──────────────────────────────────────

from .filesystem import _s as _get_sandbox


def _s():
    return _get_sandbox()


from component.approval import ApprovalResult, request_user_confirm


# ── 工具 handler ─────────────────────────────────────────────────────


async def _handle_run_python(args: Dict[str, Any]) -> str:
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
        # 用于允许列表匹配的规范形式
        canonical: str = f"{sys.executable} -c <inline>"
    else:
        # script — 通过 sandbox 解析逻辑路径
        try:
            resolved = _s().resolve(script, Access.READ)
            cmd_parts.append(str(resolved.real))
        except SandboxError as exc:
            return tool_error(str(exc), script=script)
        if extra_args:
            cmd_parts.extend(extra_args)
        canonical = f"{sys.executable} {script}"

    # ── 允许列表检查 ──
    allowlist: Set[str] = _load_allowlist()
    if canonical in allowlist:
        return _execute(cmd_parts, cwd, timeout)

    # ── 用户确认 ──
    result: ApprovalResult
    if session_id:
        cmd_str = " ".join(cmd_parts)
        result = await request_user_confirm(
            session_id, "run_python",
            {"command": cmd_parts, "reason": reason},
            reason,
            f"Python 执行: `{cmd_str}`\n原因: {reason}",
        )
    else:
        result = ApprovalResult(action="deny", deny_reason="缺少 session_id")

    if result.action == "deny":
        source_label = {"model": "审批模型", "user": "用户", "system": "系统"}.get(result.denied_by, "系统")
        return tool_error(
            f"[{source_label}拒绝] {result.deny_reason or '未知原因'}",
            command=cmd_parts,
            denied=True,
        )

    if result.action == "allow_always":
        allowlist.add(canonical)
        _save_allowlist(allowlist)
        logger.info("Added to allowlist: %s", canonical)

    return _execute(cmd_parts, cwd, timeout)


def _execute(cmd_parts: List[str], cwd: str, timeout: int = 60) -> str:
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
        "description": (
            "使用与 agent 进程相同的 Python 解释器执行代码。"
            "与 run_command 不同，此工具固定使用当前解释器的完整路径，"
            "不受 PATH 中 python 指向的影响。\n\n"
            "两种模式：\n"
            "  1. 内联代码：传递 code=\"print('hello')\"（等效于 python -c）。\n"
            "  2. 脚本文件：传递 script=\"ws:scripts/test.py\"，"
            "可选地传递 args=[\"--flag\", \"val\"]。\n\n"
            "用户将被提示批准（允许一次/始终允许/拒绝）。"
            "对于内联代码模式，规范形式始终为 '<python路径> -c <inline>'，"
            "因此单独允许一次即可。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "code": {
                    "type": "string",
                    "description": "要执行的 Python 内联代码（等效于 python -c \"...\"）。与 script 互斥。",
                },
                "script": {
                    "type": "string",
                    "description": "要执行的 Python 脚本的逻辑路径（如 'ws:script.py'、'fork:test.py'）。与 code 互斥。",
                },
                "args": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "传递给脚本的附加参数（仅 script 模式可用）。",
                },
                "reason": {
                    "type": "string",
                    "description": "执行此 Python 代码的原因。",
                },
                "cwd": {
                    "type": "string",
                    "description": "工作目录（ws: 命名空间，默认 'ws:'）。",
                    "default": "ws:",
                },
                "timeout": {
                    "type": "integer",
                    "description": "超时秒数（默认 60，最大 300）。",
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