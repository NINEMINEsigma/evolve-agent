"""Shell 命令工具 — 执行已由统一入口审批的 CLI 命令。

模块导入时通过 ``registry.register()`` 注册。
审批与“始终允许”由工具执行入口的统一 allowlist 层处理。
"""

from __future__ import annotations

import logging
import subprocess  # nosec
from typing import Any, Dict, List

from abstract.tools.registry import registry, tool_error, tool_result
from entity.puretype import ToolDangerLevel
from entity.constant import NAMESPACE_PREFIXES
from system.context import get_runtime_context
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
        if any(part.startswith(p) for p in NAMESPACE_PREFIXES):
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
        result = _s().run(resolved_parts, cwd_ns=cwd)
    except SandboxError as exc:
        return tool_error(str(exc))
    except subprocess.TimeoutExpired:
        return tool_error(
            f"Command timed out after {get_runtime_context().tool_timeout}s",
            command=cmd_parts,
        )
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
        # 在沙箱中执行 shell 命令。
        #
        # ## 前置条件
        # 首次使用前必须向用户详细说明此工具的用途和风险，并询问用户明确意见（允许/禁止/条件允许）。
        # 禁止使用此工具替代沙箱已有的文件读写和搜索操作（如 read_file、write_file、grep 等）。
        # 禁止用于执行安装命令（pip install、npm install 等）或需要较长时间运行的测试，此工具默认 30 秒超时。
        #
        # ## 调用效果
        # 命令中的沙箱逻辑路径（`ws:`、`fork:` 等前缀）会被自动展开为真实绝对路径后执行。
        # 执行结果（stdout/stderr/exit_code）直接返回。
        # 每次调用需用户审批（允许一次/总是允许/拒绝）。总是允许的审批由统一工具白名单层持久化。
        #
        # ## 返回
        # ```json
        # {"exit_code": 0, "stdout": "...", "stderr": "...", "command": ["git", "status"]}
        # ```
        #
        # ## 何时使用
        # - 执行版本控制操作（git 命令）。
        # - 其他无法通过内置工具完成且能在 30 秒内完成的 shell 操作。
        #
        # ## 副作用/注意
        # - 错误调用可对整台机器造成毁灭性打击。
        # - 禁止用于替代沙箱已有的文件读写和搜索操作（read_file、write_file、grep、glob 等），这些操作有更安全的内置工具。
        # - 禁止用于安装命令或长流程测试，默认 30 秒超时。
        # - 默认工作目录为 `ws:`（agentspace）。
        "description": """Execute shell commands in the sandbox.

## Prerequisites
Before the first use, the agent MUST explain this tool's purpose and risks to the user in detail and ask for explicit consent (allow / deny / conditional allow).
Do NOT use this tool to replace sandbox file I/O and search operations (read_file, write_file, grep, glob, etc.).
Do NOT use this tool for install commands (pip install, npm install, etc.) or long-running tests; it has a default 30-second timeout.

## Effect
Sandbox logical paths in the command (`ws:`, `fork:` prefixes) are automatically resolved to real absolute paths before execution.
Execution results (stdout/stderr/exit_code) are returned directly.
Each invocation requires user approval (allow once / always allow / deny). Always-allow approvals are persisted by the unified tool allowlist layer.

## Returns
```json
{"exit_code": 0, "stdout": "...", "stderr": "...", "command": ["git", "status"]}
```

## When to Use
- Perform version control operations (git commands).
- Other shell operations that cannot be accomplished with built-in tools and complete within 30 seconds.

## Side Effects / Notes
- Misuse can cause catastrophic damage to the entire machine.
- Do NOT use this tool to replace sandbox file I/O and search operations (read_file, write_file, grep, glob, etc.); those have safer built-in tools.
- Do NOT use this tool for install commands or long-running tests; default timeout is 30 seconds.
- Default working directory is `ws:` (agentspace).""",
        "parameters": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "array",
                    "items": {"type": "string"},
                    # 命令及参数列表，例如 ['git', 'status']。
                    "description": "Command and argument list, e.g. ['git', 'status'].",
                },
                "reason": {
                    "type": "string",
                    # agent 需要执行此命令的原因（用于审批提示）。
                    "description": "The reason the agent needs to execute this command (shown in the approval prompt).",
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
    danger_level=ToolDangerLevel.dangerous,
)