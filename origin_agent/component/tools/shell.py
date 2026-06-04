"""Shell 命令工具 — 经用户同意后执行 CLI 命令。

模块导入时通过 ``registry.register()`` 注册。
每个命令都需要通过 CONFIRM_REQUEST/CONFIRM_RESPONSE
WebSocket 握手获得用户确认。

允许列表
    将*完整*命令（例如 "git log --oneline"）存储在
    ``workspace/logs/shell_allowlist.json`` 持久化 JSON 文件中。
    仅完全匹配的命令跳过确认提示。前端提供三种操作：
    允许一次 / 始终允许 / 拒绝。
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
from system.sandbox import SandboxError

logger = logging.getLogger(__name__)

# 从 filesystem 模块导入 sandbox 引用。
from .filesystem import _s as _get_sandbox

# ── 持久化允许列表 ─────────────────────────────────────────────

from system.pathutils import find_repo_root


_ALLOWLIST_PATH: Path = find_repo_root() / ".shell_allowlist.json"
_SEED_COMMANDS: Set[str] = {
    "dir", "ls", "echo .",
}


def _load_allowlist() -> Set[str]:
    """从持久化文件加载允许列表。"""
    try:
        if _ALLOWLIST_PATH.exists():
            data: list = json.loads(_ALLOWLIST_PATH.read_text(encoding="utf-8"))
            if isinstance(data, list):
                return set(data) | _SEED_COMMANDS
    except Exception:
        pass
    return set(_SEED_COMMANDS)


def _save_allowlist(entries: Set[str]) -> None:
    """将允许列表保存到持久化文件。"""
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


from component.approval import ApprovalResult, request_user_confirm


# ── 工具 handler ─────────────────────────────────────────────────────

async def _handle_run_command(args: Dict[str, Any]) -> str:
    """经过允许列表 + 用户确认检查后执行 shell 命令。

    预期参数：
        command: list[str] — 命令及参数
        reason:  str      — agent 执行此命令的原因
        cwd:     str      — 工作目录（ws: 命名空间），可选
    """
    raw_cmd: Any = args.get("command")
    reason: str = str(args.get("reason", "(no reason given)")).strip()
    cwd: str = str(args.get("cwd", "ws:")).strip()
    session_id: str = str(args.get("_session_id", ""))

    # ── 验证命令 ──
    if not raw_cmd or not isinstance(raw_cmd, list):
        return tool_error("'command' must be a non-empty list of strings")
    cmd_parts: List[str] = [str(p) for p in raw_cmd]
    if not cmd_parts:
        return tool_error("'command' must be a non-empty list")

    cmd_full: str = " ".join(cmd_parts)

    # ── 允许列表检查（完整命令精确匹配）──
    allowlist: Set[str] = _load_allowlist()
    if cmd_full in allowlist:
        # 已受信任 — 跳过确认
        return _execute(cmd_parts, cwd)

    # ── 用户确认 ──
    result: ApprovalResult
    if session_id:
        cmd_str = " ".join(cmd_parts)
        result = await request_user_confirm(
            session_id, "run_command",
            {"command": cmd_parts, "reason": reason},
            reason,
            f"command: `{cmd_str}`\nreason: {reason}"
        )
    else:
        result = ApprovalResult(action="deny", deny_reason="session_id is required")

    if result.action == "deny":
        # 审批模型/用户/系统
        source_label = {"model": "approval model", "user": "user", "system": "system"}.get(result.denied_by, "system")
        return tool_error(
            f"[{source_label} denied] {result.deny_reason or 'unknown reason'}",
            command=cmd_parts,
            denied=True,
        )

    if result.action == "allow_always":
        allowlist.add(cmd_full)
        _save_allowlist(allowlist)
        logger.info("Added to allowlist: %s", cmd_full)

    # action 为 allow_once 或 allow_always — 执行
    return _execute(cmd_parts, cwd)


def _execute(cmd_parts: List[str], cwd: str) -> str:
    """执行已受信任 / 已批准的命令并返回结果。"""
    # if cmd_parts and cmd_parts[0] not in _s().allowed_commands:
    #     return tool_error(f"Command '{cmd_parts[0]}' not in the allowed list")

    # 将命令参数中的沙箱逻辑路径（ws:/fork:/fix:）展开为真实绝对路径。
    # sandbox.run() 要求 tool handler 预先展开，不接收未解析的逻辑路径。
    resolved_parts: List[str] = []
    for part in cmd_parts:
        if any(part.startswith(p) for p in ("ws:", "fork:", "fix:")):
            try:
                r = _s().resolve_read(part)
                resolved_parts.append(str(r.real))
            except SandboxError:
                resolved_parts.append(part)
        else:
            resolved_parts.append(part)

    logger.info("run_command | cwd=%s cmd=%s", cwd, cmd_parts)
    _enc: str
    result: subprocess.CompletedProcess
    try:
        _enc = locale.getpreferredencoding(False) or sys.getfilesystemencoding() or "utf-8"
        result = _s().run(resolved_parts, cwd_ns=cwd, timeout=30, encoding=_enc, errors="replace")
    except SandboxError as exc:
        return tool_error(str(exc))
    except subprocess.TimeoutExpired:
        return tool_error("Command timed out after 30s", command=cmd_parts)
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
    name="run_command",
    toolset="shell",
    schema={
        # 在 workspace 中执行 shell 命令。
        # 用户将被提示批准（允许一次）、永久信任（始终允许）或拒绝该命令。
        # 之前以'始终允许'批准的命令跳过提示。
        # 始终包含 'reason' 解释命令的用途。
        # 用于安装软件包、运行测试或检查文件。
        "description": (
            "Execute shell commands in the workspace. "
            "The user will be prompted to approve (allow once), "
            "permanently trust (always allow), or deny the command. "
            "Commands previously approved with 'always allow' skip the prompt. "
            "Always include 'reason' explaining the command's purpose. "
            "Useful for installing packages, running tests, or inspecting files."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "array",
                    "items": {"type": "string"},
                    # 命令及参数列表，例如 ['pip', 'install', 'requests']。
                    "description": "Command and argument list, e.g. ['pip', 'install', 'requests'].",
                },
                "reason": {
                    "type": "string",
                    # agent 需要执行此命令的原因。
                    "description": "The reason the agent needs to execute this command.",
                },
                "cwd": {
                    "type": "string",
                    # 工作目录（ws: 命名空间，默认 'ws:'）。
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
    danger_level="dangerous",
)