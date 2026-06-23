"""代码自省和进化工具。

所有路径均为逻辑路径（带命名空间前缀），通过共享 Sandbox 解析。
这些工具让 agent 能够读取自身源码、写入进化代码并验证变更。
"""

from __future__ import annotations

import ast
import json
import logging
import subprocess  # nosec
from typing import Any, Dict, List

from abstract.tools.registry import registry, tool_error, tool_result
from entity.constant import WRITE_FILE_MAX_CHARS, SUBPROCESS_TIMEOUT_DEFAULT
from system.sandbox import Access, SandboxError, ResolvedPath

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


def _handle_write_fork(args: dict[str, Any]) -> dict:
    """将文件写入进化目标目录（fork: 命名空间）。

    仅在 'fast' 模式下允许。接受裸文件名或逻辑路径。

    支持三种模式：
      - 完全覆盖：提供 file + content。内容最多 {WRITE_FILE_MAX_CHARS} 个字符。
      - 增量编辑：提供 file + old_string + new_string。
        old_string 必须在现有文件中精确匹配一次。
      - 追加模式：提供 file + content + append=true。
        将内容追加到文件末尾，内容最多 10 行。
    """
    path: str = str(args.get("file", args.get("path", ""))).strip()
    content: str = str(args.get("content", ""))
    old_string: str = str(args.get("old_string", ""))
    new_string: str | None = str(args.get("new_string", "")) if "new_string" in args else None
    append: bool = bool(args.get("append", False))

    if not path:
        return tool_error("file is required")

    resolved: ResolvedPath

    # ---- 追加模式 ----
    if append:
        if old_string:
            return tool_error("Cannot combine append with old_string/new_string")
        if not content:
            return tool_error("content is required in append mode")

        lines = content.splitlines()
        if len(lines) > 10:
            return tool_error(
                f"content exceeds 10 lines (got {len(lines)}) in append mode",
            )

        try:
            if ":" in path:
                resolved = _s().resolve(path, Access.READ)
            else:
                resolved = _s().resolve(f"fork:{path}", Access.READ)
            existing = resolved.real.read_text(encoding="utf-8")
        except (SandboxError, FileNotFoundError) as exc:
            return tool_error(str(exc), path=path)

        content = existing.rstrip("\n") + "\n" + content

    # ---- 增量编辑模式 ----
    elif old_string:
        if new_string is None:
            return tool_error("new_string is required when old_string is provided")
        try:
            if ":" in path:
                resolved = _s().resolve(path, Access.READ)
            else:
                resolved = _s().resolve(f"fork:{path}", Access.READ)
            existing: str = resolved.real.read_text(encoding="utf-8")
        except (SandboxError, FileNotFoundError) as exc:
            return tool_error(str(exc), path=path)

        if old_string not in existing:
            return tool_error("old_string not found in file", path=path)

        count: int = existing.count(old_string)
        if count > 1:
            return tool_error(
                f"old_string matches {count} locations. Use more surrounding "
                f"context to make it unique.",
                path=path, matches=count,
            )

        content = existing.replace(old_string, new_string, 1)

    # ---- 完全覆盖模式 ----
    elif not content:
        return tool_error("content is required when old_string is not provided")

    # 完全覆盖模式下限制字符数
    if not old_string and not append and len(content) > WRITE_FILE_MAX_CHARS:
        return tool_error(
            f"content exceeds {WRITE_FILE_MAX_CHARS} characters (got {len(content)}) in overwrite mode",
        )

    try:
        if ":" in path:
            resolved = _s().resolve(path, Access.WRITE)
        else:
            resolved = _s().resolve(f"fork:{path}", Access.WRITE)
        resolved.real.parent.mkdir(parents=True, exist_ok=True)
        resolved.real.write_text(content, encoding="utf-8")
        return tool_result(success=True, path=path, bytes=len(content.encode("utf-8")))
    except SandboxError as exc:
        return tool_error(str(exc), path=path)


def _handle_validate_code(args: dict[str, Any]) -> dict:
    """验证 Python 代码的语法错误。

    *file* — 要验证的裸文件名或逻辑路径。
    未指定文件时验证 fork: 命名空间中所有 .py 文件。
    """
    path: str = str(args.get("file", "")).strip()
    results: list[dict[str, Any]] = []

    if path:
        # 验证单个文件
        resolved: Any
        try:
            if ":" in path:
                resolved = _s().resolve(path, Access.READ)
            else:
                resolved = _s().resolve(f"fork:{path}", Access.READ)
            source: str = resolved.real.read_text(encoding="utf-8")
            ast.parse(source, filename=str(resolved.real))
            results.append({"file": path, "status": "ok"})
        except SyntaxError as exc:
            results.append({
                "file": path,
                "status": "syntax_error",
                "line": exc.lineno,
                "offset": exc.offset,
                "message": str(exc),
            })
        except (SandboxError, FileNotFoundError) as exc:
            results.append({"file": path, "status": "error", "message": str(exc)})
    else:
        # 验证 fork: 中所有 .py 文件
        try:
            entries: list[str] = _s().list_dir("fork:")
            for entry in entries:
                if not entry.endswith(".py"):
                    continue
                try:
                    resolved = _s().resolve(f"fork:{entry}", Access.READ)
                    source = resolved.real.read_text(encoding="utf-8")
                    ast.parse(source, filename=str(resolved.real))
                    results.append({"file": entry, "status": "ok"})
                except SyntaxError as exc:
                    results.append({
                        "file": entry,
                        "status": "syntax_error",
                        "line": exc.lineno,
                        "offset": exc.offset,
                        "message": str(exc),
                    })
                except Exception as exc:
                    results.append({"file": entry, "status": "error", "message": str(exc)})
        except SandboxError as exc:
            return tool_error(str(exc))

    ok: bool = all(r.get("status") == "ok" for r in results)
    return tool_result(valid=ok, results=results)


def _handle_evolve_code(args: dict[str, Any]) -> dict:
    """完成代码进化：验证 fork 然后触发热替换。

    agent 通过 write_fork 将进化代码写入 fork: 并通过 validate_code
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
    name="write_fork",
    toolset="code",
    schema={
        # 将进化源码写入 fork: 命名空间（slow 目录）。
        # 前置条件：agent 运行在 fast 模式下。fallback 模式下 fork: 命名空间不可用。
        # file 可以是裸文件名（'main.py'）或逻辑路径（'fork:main.py'）。
        # 三种模式互斥，按优先级检测：append > old_string/new_string > content 覆盖。
        #   - 完全覆盖：file + content。content 最大 10000 字符。
        #   - 增量编辑：file + old_string + new_string。old_string 必须精确匹配一次。
        #   - 追加模式：file + content + append=true。content 最大 10 行。
        # 调用效果：文件写入 fork: 命名空间，不影响当前运行的 agent 代码。
        # 返回：{ success, path, bytes }
        # 典型场景：进化工作流第一步 → 后续调用 validate_code 检查语法。
        "description": f"""Write evolved source code to the fork: namespace (slow directory).

## Prerequisites
Agent must be running in fast mode. The fork: namespace is not available in fallback mode.

## Modes (mutually exclusive, checked in priority order: append > old_string > content)
- **Full overwrite**: `file` + `content`. Content max {WRITE_FILE_MAX_CHARS} characters.
- **Incremental edit**: `file` + `old_string` + `new_string`. `old_string` must match exactly once — include 2-3 lines of surrounding context to make it unique.
- **Append**: `file` + `content` + `append=true`. Content max 10 lines, appended to end of file.

## Effect
Writes to the fork: namespace only. Does not affect the currently running agent code.

## Returns
```json
{{ "success": true, "path": "<path>", "bytes": N }}
```

## Workflow
This is step 1 of the evolution cycle. After writing all changes, call `validate_code` to check syntax, then `evolve_code` to trigger the swap.""",
        "parameters": {
            "type": "object",
            "properties": {
                "file": {
                    "type": "string",
                    # 目标文件名（如 'main.py'）或逻辑路径（如 'fork:main.py'）。必需。
                    "description": """Target filename (e.g. 'main.py') or logical path (e.g. 'fork:main.py'). Required.""",
                },
                "content": {
                    "type": "string",
                    # 新的源码内容。完全覆盖模式下最多 10000 字符；追加模式下最多 10 行。
                    "description": f"""New source code content. Max {WRITE_FILE_MAX_CHARS} characters in full overwrite mode; max 10 lines in append mode.""",
                },
                "old_string": {
                    "type": "string",
                    # 要查找替换的精确文本。提供此参数即启用增量编辑模式，需同时提供 new_string。
                    "description": """Exact text to find and replace. Providing this enables incremental edit mode; new_string is required.""",
                },
                "new_string": {
                    "type": "string",
                    # 替换文本。使用空字符串删除 old_string。仅在增量编辑模式下有效。
                    "description": """Replacement text. Use empty string to delete old_string. Only valid in incremental edit mode.""",
                },
                "append": {
                    "type": "boolean",
                    # 设为 true 启用追加模式。content 追加到文件末尾，最多 10 行。与 old_string/new_string 互斥。
                    "description": """Set to true to enable append mode. Content is appended to end of file, max 10 lines. Mutually exclusive with old_string/new_string.""",
                },
            },
            "required": ["file"],
        },
    },
    handler=_handle_write_fork,
    emoji="🧬",
    danger_level="write",
)


registry.register(
    name="validate_code",
    toolset="code",
    schema={
        # 用 ast.parse() 检查 fork: 命名空间中 Python 文件的语法错误。
        # 前置条件：已通过 write_fork 将进化代码写入 fork:。仅 fast 模式下可用。
        # file: 可选。指定时只验证该文件（裸名或 'fork:xxx.py'）；省略时验证 fork: 下所有 .py 文件。
        # 调用效果：只读分析，不修改任何文件。
        # 返回：{ valid: bool, results: [{ file, status: "ok"|"syntax_error"|"error", line?, offset?, message? }] }
        # 典型场景：进化工作流第二步 — write_fork 之后、evolve_code 之前调用，确保语法无误。
        "description": """Check Python source files in the fork: namespace for syntax errors using ast.parse().

## Prerequisites
Evolved code must have been written to fork: via `write_fork`. Only available in fast mode.

## Effect
Read-only analysis. Does not modify any files.

## Returns
```json
{
  "valid": true|false,
  "results": [
    { "file": "<path>", "status": "ok"|"syntax_error"|"error", "line": N, "offset": N, "message": "<detail>" }
  ]
}
```
`valid` is `true` only when all files have status `"ok"`.

## When to Use
Evolution workflow step 2 — call after `write_fork` and before `evolve_code` to ensure syntax correctness.""",
        "parameters": {
            "type": "object",
            "properties": {
                "file": {
                    "type": "string",
                    # 可选。要验证的特定文件，裸名（'main.py'）或逻辑路径（'fork:main.py'）。省略则验证 fork: 下所有 .py 文件。
                    "description": """Optional. Specific file to validate, as bare name ('main.py') or logical path ('fork:main.py'). Omit to validate all .py files in fork:.""",
                },
            },
        },
    },
    handler=_handle_validate_code,
    emoji="✅",
)


registry.register(
    name="evolve_code",
    toolset="code",
    schema={
        # 完成代码进化周期 — 进化工作流最后一步。
        # 前置条件：已通过 write_fork 写入进化代码 + validate_code 语法检查通过（修改前端时还需 validate_frontend）。
        # 调用效果：对 fork: 下所有 .py 文件运行彻底验证（语法 + 可选编译检查），全部通过后进程以退出码 -1 退出，编排器执行 slow→fast 交换并重启。
        # deep=true（默认）：语法 + py_compile 子进程编译检查（更彻底但更慢）。
        # deep=false：仅语法检查（更快）。
        # 成功返回：{ evolved: true, validation: { valid, total, ok, errors, details }, message } — 进程随即退出，agent 不会收到此响应。
        # 失败返回：{ evolved: false, validation: {...}, hint } — agent 可修复问题后重试。
        # 注意：不会验证 TypeScript/前端构建，触碰前端代码需先调 validate_frontend。
        "description": """Complete the code evolution cycle — final step of the evolution workflow.

## Prerequisites
- Evolved source code has been written to fork: via `write_fork`.
- Syntax check via `validate_code` has passed.
- If frontend files were modified, `validate_frontend` must also have passed.
- Only available in fast mode.

## Effect
Runs thorough validation (syntax + optional compile check) on all `.py` files in fork:. If all checks pass, the process exits with code -1, the orchestrator performs the slow→fast swap, and the agent restarts with the evolved code. Does **not** validate TypeScript or frontend builds — call `validate_frontend` separately if frontend code was touched.

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
{ "evolved": false, "validation": { "valid": false, "total": N, "ok": N, "errors": N, "details": [...] }, "hint": "Fix the errors above using write_fork, then call validate_code..." }
```

## When to Use
Evolution workflow step 3 — call after `write_fork` + `validate_code` (and optionally `validate_frontend`). This is the commit point; once called successfully, the current agent session ends.

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