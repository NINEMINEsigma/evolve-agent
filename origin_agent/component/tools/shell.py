"""Shell 命令工具 — 执行已由统一入口审批的 CLI 命令。

模块导入时通过 ``registry.register()`` 注册。
审批与“始终允许”由工具执行入口的统一 allowlist 层处理。
"""

from __future__ import annotations

import logging
import subprocess  # nosec
from typing import Any, Dict, List

from abstract.tools.registry import registry, tool_error, tool_result
from system.sandbox import SandboxError

logger = logging.getLogger(__name__)

# 从 filesystem 模块导入 sandbox 引用。
from .filesystem import _s as _get_sandbox


def _s():
    return _get_sandbox()


# ── 工具 handler ─────────────────────────────────────────────────────

async def _handle_run_command(args: dict[str, Any]) -> dict:
    """执行已由 AgentLoop 统一审批的 shell 命令。

    预期参数：
        command: list[str] — 命令及参数
        cwd:     str      — 工作目录（ws: 命名空间），可选
    """
    raw_cmd: Any = args.get("command")
    cwd: str = str(args.get("cwd", "ws:")).strip()

    # ── 验证命令 ──
    if not raw_cmd or not isinstance(raw_cmd, list):
        return tool_error("'command' must be a non-empty list of strings")
    cmd_parts: list[str] = [str(p) for p in raw_cmd]
    if not cmd_parts:
        return tool_error("'command' must be a non-empty list")

    # 审批由 AgentLoop 统一入口处理（handler 内不再重复确认）
    return _execute(cmd_parts, cwd)


def _execute(cmd_parts: list[str], cwd: str) -> dict:
    """执行已受信任 / 已批准的命令并返回结果。"""
    # if cmd_parts and cmd_parts[0] not in _s().allowed_commands:
    #     return tool_error(f"Command '{cmd_parts[0]}' not in the allowed list")

    # 将命令参数中的沙箱逻辑路径（ws:/fork:/fix:）展开为真实绝对路径。
    # sandbox.run() 要求 tool handler 预先展开，不接收未解析的逻辑路径。
    resolved_parts: list[str] = []
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
    result: subprocess.CompletedProcess
    try:
        result = _s().run(resolved_parts, cwd_ns=cwd, timeout=30)
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
            "Useful for installing packages, running tests, or other shell-specific tasks. "
            "DO NOT use this tool to read or inspect files; use read_file instead."
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