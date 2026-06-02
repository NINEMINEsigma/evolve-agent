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


def _resolve_sandboxed_path(path: str, mode: str) -> str:
    # Note: 遗留辅助函数 — 当前无 handler 使用。
    # Handler 通过 sandbox 内联自己的路径解析。
    """通过 sandbox 将逻辑路径解析为绝对路径。

    特殊情况：无命名空间前缀的裸文件名视为
    相对于 ``self:``（用于 read_own_source / write_fork）。
    """
    if ":" not in path:
        # 裸文件名 — 读取时相对于 self:，写入时相对于 fork:
        return str(_s().resolve(f"{'fork' if mode == 'write' else 'self'}:{path}",
                                Access.WRITE if mode == "write" else Access.READ).real)
    raise SandboxError("Use bare filenames (e.g. 'main.py') for code tools")


# ---------------------------------------------------------------------------
# 工具 handler
# ---------------------------------------------------------------------------


def _handle_read_own_source(args: Dict[str, Any]) -> str:
    """从 agent 自身源码目录（self: 命名空间）读取文件。

    接受裸文件名（如 'main.py'，解析到 self:）或完整逻辑路径。
    仅允许可读命名空间。

    支持通过 offset 和 limit 进行按行分页。
    limit=0 表示读取完整文件。
    """
    path: str = str(args.get("file", args.get("path", ""))).strip()
    if not path:
        # 返回目录列表，使 agent 能发现可用文件
        try:
            entries: list[str] = _s().list_dir("self:")
            return tool_result(entries=entries, tip="Use read_own_source with file=<name>")
        except SandboxError as exc:
            return tool_error(str(exc))

    offset: int = int(args.get("offset", 0))
    limit: int = int(args.get("limit", 0))
    if offset < 0:
        return tool_error("offset must be >= 0", path=path, offset=offset)
    if limit < 0:
        return tool_error("limit must be >= 0", path=path, limit=limit)

    resolved: Any
    try:
        if ":" in path:
            # 显式逻辑路径 — 必须可读
            resolved = _s().resolve(path, Access.READ)
        else:
            # 裸文件名 — 相对于 self: 解析
            resolved = _s().resolve(f"self:{path}", Access.READ)
        if resolved.real.is_dir():
            return tool_result(
                entries=_s().list_dir(f"self:{path}" if ":" not in path else path),
                tip="Use read_own_source with file=<name> to read a specific file",
            )
        content: str = resolved.real.read_text(encoding="utf-8")
        if limit > 0 or offset > 0:
            lines: list[str] = content.splitlines()
            chunk: list[str] = lines[offset:offset + limit] if limit > 0 else lines[offset:]
            content = "\n".join(chunk)
        return tool_result(content=content, path=path, offset=offset, limit=limit)
    except (SandboxError, FileNotFoundError, IsADirectoryError, PermissionError) as exc:
        return tool_error(str(exc), path=path)


def _handle_write_fork(args: Dict[str, Any]) -> str:
    """将文件写入进化目标目录（fork: 命名空间）。

    仅在 'fast' 模式下允许。接受裸文件名或逻辑路径。

    支持三种模式：
      - 完全覆盖：提供 file + content。内容最多 1000 个字符。
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
            resolved: Any
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
    if not old_string and not append and len(content) > 1000:
        return tool_error(
            f"content exceeds 1000 characters (got {len(content)}) in overwrite mode",
        )

    try:
        resolved: Any
        if ":" in path:
            resolved = _s().resolve(path, Access.WRITE)
        else:
            resolved = _s().resolve(f"fork:{path}", Access.WRITE)
        resolved.real.parent.mkdir(parents=True, exist_ok=True)
        resolved.real.write_text(content, encoding="utf-8")
        return tool_result(success=True, path=path, bytes=len(content.encode("utf-8")))
    except SandboxError as exc:
        return tool_error(str(exc), path=path)


def _handle_validate_code(args: Dict[str, Any]) -> str:
    """验证 Python 代码的语法错误。

    *file* — 要验证的裸文件名或逻辑路径。
    未指定文件时验证 fork: 命名空间中所有 .py 文件。
    """
    path: str = str(args.get("file", "")).strip()
    results: List[Dict[str, Any]] = []

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


def _handle_evolve_code(args: Dict[str, Any]) -> str:
    """完成代码进化：验证 fork 然后触发热替换。

    agent 通过 write_fork 将进化代码写入 fork: 并通过 validate_code
    检查语法后，调用此工具运行彻底验证（语法 + 编译检查），
    如果全部通过则通知编排器执行 slow→fast 交换。

    仅在 'fast' 模式下工作。在 'fallback' 模式下返回错误。
    """
    from evolve.code import finalize_evolution

    deep: bool = bool(args.get("deep", True))
    compile_timeout: int = int(args.get("compile_timeout", 30))

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

'''read_own_source 已禁用，agent 通过 read_file 读取自身源码。
registry.register(
    name="read_own_source",
    toolset="code",
    schema={ ... },
    handler=_handle_read_own_source,
    emoji="🔬",
)
'''

registry.register(
    name="write_fork",
    toolset="code",
    schema={
        "description": (
            "将源代码的进化版本写入 fork（slow）目录。"
            "写入所有更改后，调用 validate_code 检查语法，"
            "然后调用 evolve_code 触发交换。"
            "接受裸文件名（如 'main.py'）。\n\n"
            "三种模式：\n"
            "- 完全覆盖：传递 file + content。内容最多 1000 个字符。\n"
            "- 增量编辑：传递 file + old_string + new_string。"
            "old_string 必须精确匹配一次 — 包含足够的上下文"
            "（前后各 2-3 行）使其唯一。\n"
            "- 追加模式：传递 file + content + append=true。"
            "将内容追加到文件末尾。内容最多 10 行。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "file": {
                    "type": "string",
                    "description": "目标文件名（如 'main.py'）。",
                },
                "content": {
                    "type": "string",
                    "description": (
                        "新的源码内容。完全覆盖模式下最多 1000 个字符；"
                        "追加模式下最多 10 行。"
                    ),
                },
                "old_string": {
                    "type": "string",
                    "description": "要查找替换的精确文本（启用增量编辑模式）。",
                },
                "new_string": {
                    "type": "string",
                    "description": "替换文本。使用空字符串删除 old_string。",
                },
                "append": {
                    "type": "boolean",
                    "description": "追加模式：将 content 追加到现有文件末尾。最多 10 行。",
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
        "description": (
            "使用 ast.parse() 检查 Python 源文件的语法错误。"
            "给定文件名时验证该文件。否则验证 fork: 命名空间中"
            "所有 .py 文件。在写入进化代码后调用。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "file": {
                    "type": "string",
                    "description": "可选：要验证的特定文件。",
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
        "description": (
            "完成代码进化周期。在通过 write_fork 将进化源码写入 fork: 并"
            "通过 validate_code 验证语法（如果修改了前端文件还需通过"
            " validate_frontend）之后调用此工具。此工具对 fork 目录中"
            "所有 **.py 文件** 运行彻底验证（语法 + 编译检查）。"
            "不会验证 TypeScript 或前端构建 — 如果触碰到前端代码，"
            "必须预先调用 validate_frontend。如果全部通过，进程退出，"
            "编排器将 slow（进化后）代码交换到位，然后用新版本重启 agent。"
            "如果验证失败，返回错误详情以便修复问题后重试。"
            "设置 deep=false 跳过编译检查（更快但不彻底）。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "deep": {
                    "type": "boolean",
                    "description": "是否运行 py_compile 检查（默认 true）。",
                },
                "compile_timeout": {
                    "type": "integer",
                    "description": "每个文件编译检查的超时秒数（默认 30）。",
                },
            },
        },
    },
    handler=_handle_evolve_code,
    emoji="🚀",
)