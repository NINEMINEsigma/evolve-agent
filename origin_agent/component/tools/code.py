"""代码自省和进化工具。

所有路径均为逻辑路径（带命名空间前缀），通过共享 Sandbox 解析。
这些工具让 agent 能够读取自身源码、写入进化代码并验证变更。
"""

from __future__ import annotations

import logging
from typing import Any

from abstract.tools.registry import registry, tool_error, tool_result
from entity.constant import SUBPROCESS_TIMEOUT_DEFAULT
from system.sandbox import Access, SandboxError

logger = logging.getLogger(__name__)

# 从 filesystem 模块导入 sandbox 引用
# （同一个单例 — main.py 为所有工具设置一次）。
from .filesystem import _s as _get_sandbox


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------


def _s():
    return _get_sandbox()


# ---------------------------------------------------------------------------
# 工具 handler
# ---------------------------------------------------------------------------


def _handle_validate_code(args: dict[str, Any]) -> dict:
    """验证 Python 代码的语法错误。

    *file* — 要验证的裸文件名或逻辑路径。
    未指定文件时递归验证 fork: 命名空间中所有 .py 文件。
    *deep* — 是否额外运行 py_compile 编译检查（默认 False）。
    """
    from evolve.validator import validate_directory, validate_syntax, validate_compile, summary

    path: str = str(args.get("file", "")).strip()
    deep: bool = bool(args.get("deep", False))
    compile_timeout: int = int(args.get("compile_timeout", SUBPROCESS_TIMEOUT_DEFAULT))

    if path:
        # 验证单个文件
        try:
            if ":" in path:
                resolved = _s().resolve(path, Access.READ)
            else:
                resolved = _s().resolve(f"fork:{path}", Access.READ)
            results: list[dict[str, Any]] = [validate_syntax(resolved.real)]
            if deep and results[0].get("status") == "ok":
                compile_result: dict[str, Any] = validate_compile(resolved.real, timeout=compile_timeout)
                if compile_result["status"] != "ok":
                    results[0] = compile_result
        except SandboxError as exc:
            results = [{"file": path, "status": "error", "message": str(exc)}]
    else:
        # 验证 fork: 中所有 .py 文件（递归子目录）
        try:
            fork_resolved = _s().resolve_read("fork:")
            results = validate_directory(fork_resolved.real, deep=deep, timeout=compile_timeout)
        except SandboxError as exc:
            return tool_error(str(exc))

    return tool_result(**summary(results))


def _handle_evolve_code(args: dict[str, Any]) -> dict:
    """完成代码进化：验证 fork 然后触发热替换。

    agent 通过 Write/PatchEdit 将进化代码写入 fork: 并通过 validate_code
    检查语法后，调用此工具运行彻底验证（语法 + 编译检查），
    如果全部通过则通知编排器执行 slow→fast 交换。

    仅在 'fast' 模式下工作。在 'fallback' 模式下返回错误。
    """
    from evolve.code import finalize_evolution

    deep: bool = bool(args.get("deep", True))
    compile_timeout: int = int(args.get("compile_timeout", SUBPROCESS_TIMEOUT_DEFAULT))

    try:
        return finalize_evolution(
            _s(),
            deep=deep,
            compile_timeout=compile_timeout,
        )
    except Exception as exc:
        return tool_error(str(exc))


# ---------------------------------------------------------------------------
# 注册
# ---------------------------------------------------------------------------


registry.register(
    name="ValidateCode",
    toolset="code",
    schema={
        # 用 ast.parse() 检查 fork: 命名空间中 Python 文件的语法错误，可选 py_compile 编译检查。
        # 前置条件：已通过 Write/PatchEdit 将进化代码写入 fork:。仅 fast 模式下可用。
        # file: 可选。指定时只验证该文件（裸名或 'fork:xxx.py'）；省略时递归验证 fork: 下所有 .py 文件（含子目录）。
        # deep: 默认 false（仅语法检查）。设为 true 额外运行 py_compile 子进程编译检查。
        # 调用效果：只读分析，不修改任何文件。
        # 返回：{ valid, total, ok, errors, details: [{ file, status: "ok"|"syntax_error"|"compile_error"|"error", line?, offset?, message? }] }
        # 典型场景：进化工作流第二步 — 写入进化代码之后、EvolveCode 之前调用，确保语法无误。
        "description": """Check Python source files in the fork: namespace for syntax errors using ast.parse(), with optional py_compile check.

## Prerequisites
Evolved code must have been written to fork: via `Write` or `PatchEdit` with `fork:` prefix. Only available in fast mode.

## Effect
Read-only analysis. Does not modify any files. When `file` is omitted, recursively validates all `.py` files in fork: (including subdirectories).

## Parameters
- `file` (string, optional): Specific file to validate, as bare name ('main.py') or logical path ('fork:main.py'). Omit to validate all `.py` files in fork: recursively.
- `deep` (boolean, default false): When true, also runs `py_compile` subprocess compile check on each file. When false, syntax check only (faster).
- `compile_timeout` (integer): Timeout in seconds for each file's `py_compile` subprocess.

## Returns
```json
{
  "valid": true|false,
  "total": N,
  "ok": N,
  "errors": N,
  "details": [
    { "file": "<relative_path>", "status": "ok"|"syntax_error"|"compile_error"|"error", "line": N, "offset": N, "message": "<detail>" }
  ]
}
```
`valid` is `true` only when all files have status `"ok"`.

## When to Use
Evolution workflow step 2 — call after writing evolved code via `Write`/`PatchEdit` and before `EvolveCode` to ensure syntax correctness.""",
        "parameters": {
            "type": "object",
            "properties": {
                "file": {
                    "type": "string",
                    # 可选。要验证的特定文件，裸名（'main.py'）或逻辑路径（'fork:main.py'）。省略则递归验证 fork: 下所有 .py 文件（含子目录）。
                    "description": """Optional. Specific file to validate, as bare name ('main.py') or logical path ('fork:main.py'). Omit to validate all .py files in fork: recursively.""",
                },
                "deep": {
                    "type": "boolean",
                    # 是否运行 py_compile 编译检查。默认 false（仅语法检查）。设为 true 额外运行编译检查（较慢但更彻底）。
                    "description": """Whether to run py_compile check. Default false (syntax only). Set true to also run compile check (slower but more thorough).""",
                },
                "compile_timeout": {
                    "type": "integer",
                    # 每个文件 py_compile 子进程的超时秒数。
                    "description": """Timeout in seconds for each file's py_compile subprocess.""",
                },
            },
        },
    },
    handler=_handle_validate_code,
    emoji="✅",
)


registry.register(
    name="EvolveCode",
    toolset="code",
    schema={
        # 完成代码进化周期 — 进化工作流最后一步。
        # 前置条件：已通过 Write/PatchEdit 写入进化代码 + ValidateCode 语法检查通过（修改前端时还需 ValidateFrontend）。
        # 调用效果：对 fork: 下所有 .py 文件运行彻底验证（语法 + 可选编译检查），全部通过后进程以退出码 -1 退出，编排器执行 slow→fast 交换并重启。
        # deep=true（默认）：语法 + py_compile 子进程编译检查（更彻底但更慢）。
        # deep=false：仅语法检查（更快）。
        # 成功返回：{ evolved: true, validation: { valid, total, ok, errors, details }, message } — 进程随即退出，agent 不会收到此响应。
        # 失败返回：{ evolved: false, validation: {...}, _note } — agent 可修复问题后重试。
        # 注意：不会验证 TypeScript/前端构建，触碰前端代码需先调 ValidateFrontend。
        "description": """Complete the code evolution cycle — final step of the evolution workflow.

## Prerequisites
- Evolved source code has been written to fork: via `Write` or `PatchEdit` with `fork:` prefix.
- Syntax check via `ValidateCode` has passed.
- If frontend files were modified, `ValidateFrontend` must also have passed.
- Only available in fast mode.

## Effect
Runs thorough validation (syntax + optional compile check) on all `.py` files in fork:. If all checks pass, the process exits with code -1, the orchestrator performs the slow→fast swap, and the agent restarts with the evolved code. Does **not** validate TypeScript or frontend builds — call `ValidateFrontend` separately if frontend code was touched.

## Parameters
- `deep` (boolean, default true): When true, runs both `ast.parse()` syntax check and `py_compile` subprocess compile check on each file. When false, syntax check only (faster but less thorough).
- `compile_timeout` (integer): Timeout in seconds for each file's `py_compile` subprocess.

## Returns
**Success** — process exits immediately; the agent does not see this response:
```json
{ "evolved": true, "validation": { "valid": true, "total": N, "ok": N, "errors": 0, "details": [...] }, "message": "All N files validated..." }
```
**Failure** — agent can fix errors and retry:
```json
{ "evolved": false, "validation": { "valid": false, "total": N, "ok": N, "errors": N, "details": [...] }, "_note": "Fix the errors above using Write or PatchEdit with fork: prefix, then call ValidateCode..." }
```

## When to Use
Evolution workflow step 3 — call after writing evolved code via `Write`/`PatchEdit` + `ValidateCode` (and optionally `ValidateFrontend`). This is the commit point; once called successfully, the current agent session ends.

## Side Effects
On success, the current agent process exits. The success response is never seen by the calling agent. On failure, the agent continues and can fix issues then retry.""",
        "parameters": {
            "type": "object",
            "properties": {
                "deep": {
                    "type": "boolean",
                    # 是否运行 py_compile 编译检查。默认 true（更彻底，语法+编译）。设为 false 跳过编译检查，仅语法验证。
                    "description": """Whether to run py_compile check. Default true (more thorough: syntax + compile). Set false to skip compile check and only validate syntax.""",
                },
                "compile_timeout": {
                    "type": "integer",
                    # 每个文件 py_compile 子进程的超时秒数。
                    "description": """Timeout in seconds for each file's py_compile subprocess.""",
                },
            },
        },
    },
    handler=_handle_evolve_code,
    emoji="🚀",
)