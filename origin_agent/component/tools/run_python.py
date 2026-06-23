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
        # 使用与 agent 进程相同的 Python 解释器执行代码。始终使用当前解释器的完整路径，不受 PATH 指向影响。
        #
        # ## 前置条件
        # 首次使用前必须向用户详细说明此工具的用途和风险，并询问用户明确意见（允许/禁止/条件允许）。
        # 禁止使用此工具替代沙箱已有的文件读写和搜索操作（如 read_file、write_file、grep 等）。
        # 禁止用于执行下载任务或需要较长时间运行的服务。
        #
        # ## 模式
        # 两种互斥模式，必须提供且仅提供其一。
        # 1. 内联代码：`code="print('hello')"`（等效于 `python -c`）。
        # 2. 脚本文件：`script="ws:scripts/test.py"`，可选 `args=["--flag", "val"]` 传参。
        #
        # ## 调用效果
        # 若 `python_path` 指定，通过沙箱解析并作为解释器；否则使用 `sys.executable`。
        # `script` 路径通过沙箱命名空间解析（支持 `ws:`、`fork:` 等前缀）。
        # 执行结果（stdout/stderr/exit_code）直接返回。
        # 每次调用需用户审批（允许一次/总是允许/拒绝）。总是允许的审批由统一工具白名单层持久化。
        #
        # ## 返回
        # ```json
        # {"exit_code": 0, "stdout": "...", "stderr": "...", "command": ["python", "-c", "..."]}
        # ```
        #
        # ## 何时使用
        # - 需要执行 Python 代码进行数据处理、复杂逻辑运算。
        # - 需要在沙箱内运行脚本。
        # - 需要精确控制 Python 版本（通过 `python_path` 指定虚拟环境中的解释器）。
        #
        # ## 副作用/注意
        # - 错误调用可对整台机器造成毁灭性打击。
        # - 禁止用于替代沙箱已有的文件读写和搜索操作（read_file、write_file、grep、glob 等），这些操作有更安全的内置工具。
        # - 禁止用于执行下载任务或需要较长时间运行的服务。
        # - `code` 和 `script` 互斥，同时提供会报错。
        # - `args` 仅在 script 模式生效。
        # - 默认工作目录为 `ws:`（agentspace）。
        # - 默认超时见 `timeout` 参数默认值。
        "description": """Execute code using the same Python interpreter as the agent process. Always uses the full path of the current interpreter, unaffected by which python PATH points to.

## Prerequisites
Before the first use, the agent MUST explain this tool's purpose and risks to the user in detail and ask for explicit consent (allow / deny / conditional allow).
Do NOT use this tool to replace sandbox file I/O and search operations (read_file, write_file, grep, glob, etc.).
Do NOT use this tool for downloads or services that require significant runtime.

## Modes
Two mutually exclusive modes; exactly one of `code` or `script` must be provided.
1. Inline code: `code="print('hello')"` (equivalent to `python -c`).
2. Script file: `script="ws:scripts/test.py"`, optionally with `args=["--flag", "val"]`.

## Effect
If `python_path` is specified, it is resolved through the sandbox and used as the interpreter; otherwise `sys.executable` is used.
`script` paths are resolved through sandbox namespaces (supporting `ws:`, `fork:` prefixes).
Execution results (stdout/stderr/exit_code) are returned directly.
Each invocation requires user approval (allow once / always allow / deny). Always-allow approvals are persisted by the unified tool allowlist layer.

## Returns
```json
{"exit_code": 0, "stdout": "...", "stderr": "...", "command": ["python", "-c", "..."]}
```

## When to Use
- Execute Python code for data processing or complex logic operations.
- Run scripts within the sandbox.
- Precisely control the Python version via `python_path` (e.g. pointing to a virtualenv interpreter).

## Side Effects / Notes
- Misuse can cause catastrophic damage to the entire machine.
- Do NOT use this tool to replace sandbox file I/O and search operations (read_file, write_file, grep, glob, etc.); those have safer built-in tools.
- Do NOT use this tool for downloads or services that require significant runtime.
- `code` and `script` are mutually exclusive; providing both returns an error.
- `args` only takes effect in script mode.
- Default working directory is `ws:` (agentspace).
- Default timeout is set by the `timeout` parameter default value.""",
        "parameters": {
            "type": "object",
            "properties": {
                "code": {
                    "type": "string",
                    # 内联 Python 代码（等效于 `python -c "..."`）。与 script 互斥。
                    "description": """Inline Python code to execute (equivalent to python -c "..."). Mutually exclusive with script.""",
                },
                "script": {
                    "type": "string",
                    # 要执行的 Python 脚本逻辑路径（如 'ws:script.py'、'fork:test.py'）。通过沙箱命名空间解析。与 code 互斥。
                    "description": """Logical path to a Python script to execute (e.g. 'ws:script.py', 'fork:test.py'). Resolved through sandbox namespaces. Mutually exclusive with code.""",
                },
                "args": {
                    "type": "array",
                    "items": {"type": "string"},
                    # 传递给脚本的额外参数列表。仅 script 模式生效。
                    "description": """Additional arguments to pass to the script. Only takes effect in script mode.""",
                },
                "python_path": {
                    "type": "string",
                    # 要使用的 Python 解释器路径（如虚拟环境中的 python）。通过沙箱解析。留空则使用当前解释器。
                    "description": """Path to the Python interpreter to use (e.g. a virtualenv python). Resolved through the sandbox. Leave empty to use the current interpreter.""",
                    "default": "",
                },
                "reason": {
                    "type": "string",
                    # 执行此 Python 代码的原因（用于审批提示）。
                    "description": """The reason for executing this Python code (shown in the approval prompt).""",
                },
                "cwd": {
                    "type": "string",
                    # 工作目录（ws: 命名空间，默认 'ws:'）。
                    "description": """Working directory (ws: namespace, default 'ws:').""",
                    "default": "ws:",
                },
                "timeout": {
                    "type": "integer",
                    # 超时秒数。默认值由系统配置决定。
                    "description": """Timeout in seconds. Default value is system-configured.""",
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