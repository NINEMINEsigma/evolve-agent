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
        # 将源代码的进化版本写入 fork（slow）目录。
        # 写入所有更改后，调用 validate_code 检查语法，
        # 然后调用 evolve_code 触发交换。
        # 接受裸文件名（如 'main.py'）。
        # 三种模式：
        # - 完全覆盖：传递 file + content。内容最多 {WRITE_FILE_MAX_CHARS} 个字符。
        # - 增量编辑：传递 file + old_string + new_string。
        #   old_string 必须精确匹配一次 — 包含足够的上下文（前后各 2-3 行）使其唯一。
        # - 追加模式：传递 file + content + append=true。将内容追加到文件末尾。内容最多 10 行。
        "description": f"""Write the evolved version of source code to the fork (slow) directory. After writing all changes, call validate_code to check syntax, then call evolve_code to trigger the swap. Accepts bare filenames (e.g. 'main.py').

Three modes:
- Full overwrite: pass file + content. Content max {WRITE_FILE_MAX_CHARS} characters.
- Incremental edit: pass file + old_string + new_string. old_string must match exactly once — include enough context (2-3 lines before and after) to make it unique.
- Append mode: pass file + content + append=true. Appends content to the end of the file. Content max 10 lines.""",
        "parameters": {
            "type": "object",
            "properties": {
                "file": {
                    "type": "string",
                    # 目标文件名（如 'main.py'）。
                    "description": "Target filename (e.g. 'main.py').",
                },
                "content": {
                    "type": "string",
                    # 新的源码内容。完全覆盖模式下最多 {WRITE_FILE_MAX_CHARS} 个字符；追加模式下最多 10 行。
                    "description": (
                        "New source code content. "
                        f"Max {WRITE_FILE_MAX_CHARS} characters in full overwrite mode; "
                        "max 10 lines in append mode."
                    ),
                },
                "old_string": {
                    "type": "string",
                    # 要查找替换的精确文本（启用增量编辑模式）。
                    "description": "Exact text to find and replace (enables incremental edit mode).",
                },
                "new_string": {
                    "type": "string",
                    # 替换文本。使用空字符串删除 old_string。
                    "description": "Replacement text. Use empty string to delete old_string.",
                },
                "append": {
                    "type": "boolean",
                    # 追加模式：将 content 追加到现有文件末尾。最多 10 行。
                    "description": "Append mode: appends content to end of file. Max 10 lines.",
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
        # 使用 ast.parse() 检查 Python 源文件的语法错误。
        # 给定文件名时验证该文件。否则验证 fork: 命名空间中所有 .py 文件。
        # 在写入进化代码后调用。
        "description": """Check Python source files for syntax errors using ast.parse(). If a filename is given, validates that file. Otherwise validates all .py files in the fork: namespace. Call after writing evolved code.""",
        "parameters": {
            "type": "object",
            "properties": {
                "file": {
                    "type": "string",
                    # 可选：要验证的特定文件。
                    "description": "Optional: specific file to validate.",
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
        # 完成代码进化周期。在通过 write_fork 将进化源码写入 fork: 并
        # 通过 validate_code 验证语法（如果修改了前端文件还需通过
        # validate_frontend）之后调用此工具。此工具对 fork 目录中
        # 所有 **.py 文件** 运行彻底验证（语法 + 编译检查）。
        # 不会验证 TypeScript 或前端构建 — 如果触碰到前端代码，
        # 必须预先调用 validate_frontend。如果全部通过，进程退出，
        # 编排器将 slow（进化后）代码交换到位，然后用新版本重启 agent。
        # 如果验证失败，返回错误详情以便修复问题后重试。
        # 设置 deep=false 跳过编译检查（更快但不彻底）。
        "description": """Complete the code evolution cycle. After writing evolved source code to fork: via write_fork and passing validate_code syntax check (and validate_frontend if frontend files were modified), call this tool. It runs thorough validation (syntax + compile check) on all **.py files** in the fork directory. Does not validate TypeScript or frontend builds — if you touched frontend code, you must call validate_frontend first. If all checks pass, the process exits, the orchestrator swaps the slow (evolved) code into place, and restarts the agent with the new version. If validation fails, error details are returned so you can fix and retry. Set deep=false to skip compile checks (faster but less thorough).""",
        "parameters": {
            "type": "object",
            "properties": {
                "deep": {
                    "type": "boolean",
                    # 是否运行 py_compile 检查（默认 true）。
                    "description": "Whether to run py_compile check (default true).",
                },
                "compile_timeout": {
                    "type": "integer",
                    # 每个文件编译检查的超时秒数（默认 SUBPROCESS_TIMEOUT_DEFAULT）。
                    "description": "Timeout per file for compile check in seconds.",
                },
            },
        },
    },
    handler=_handle_evolve_code,
    emoji="🚀",
)