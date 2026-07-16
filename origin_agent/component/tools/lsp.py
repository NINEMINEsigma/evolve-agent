"""LSP 代码识别工具 — 类型推断、引用追踪、定义跳转、语义诊断。

通过 pyright (Language Server Protocol) 提供:
  - ``lsp_start``      : 启动/替换 LSP server（指定根目录）
  - ``lsp_references`` : 查找符号的所有引用
  - ``lsp_definition`` : 跳转到符号定义
  - ``lsp_diagnostics``: 获取文件的语义诊断
  - ``lsp_symbols``    : 获取文件的符号列表
  - ``lsp_refresh``    : 主动刷新 LSP 索引

模块导入时通过 ``registry.register()`` 自动注册。
"""

from __future__ import annotations

import logging
from typing import Any

from abstract.tools.registry import registry, tool_error, tool_result
from entity.puretype import ToolAvailability, ToolDangerLevel

logger = logging.getLogger(__name__)

# 从 filesystem 模块导入 sandbox 引用（同一单例）
from .filesystem import _s as _get_sandbox


def _s():
    return _get_sandbox()


# ---------------------------------------------------------------------------
# handler 函数
# ---------------------------------------------------------------------------


def _handle_lsp_start(args: dict[str, Any]) -> dict:
    """启动或替换 pyright LSP server。

    root: 逻辑路径（如 'fork:' 或 'ws:src'）。必须是一个存在的目录。
    """
    from system.lsp import get_lsp_manager

    root: str = str(args.get("root", "")).strip()
    if not root:
        return tool_error("root is required")

    manager = get_lsp_manager()
    result = manager.start(root, _s())
    if "error" in result:
        return tool_error(result["error"])
    return tool_result(**result)


async def _handle_lsp_references(args: dict[str, Any]) -> dict:
    """查找符号的所有引用。"""
    from system.lsp import get_lsp_manager

    if not get_lsp_manager().is_ready():
        return tool_error("LSP not started. Call lsp_start first.")

    path: str = str(args.get("file", "")).strip()
    line: int = int(args.get("line", 0))
    column: int = int(args.get("column", 0))
    if not path or line < 1 or column < 1:
        return tool_error("file, line (1-indexed), and column (1-indexed) are required")

    refs = await get_lsp_manager().references(path, line, column, _s())
    return tool_result(
        references=[r.model_dump() for r in refs],
        count=len(refs),
    )


async def _handle_lsp_definition(args: dict[str, Any]) -> dict:
    """跳转到符号定义。"""
    from system.lsp import get_lsp_manager

    if not get_lsp_manager().is_ready():
        return tool_error("LSP not started. Call lsp_start first.")

    path: str = str(args.get("file", "")).strip()
    line: int = int(args.get("line", 0))
    column: int = int(args.get("column", 0))
    if not path or line < 1 or column < 1:
        return tool_error("file, line (1-indexed), and column (1-indexed) are required")

    definition = await get_lsp_manager().definition(path, line, column, _s())
    if definition is None:
        return tool_result(definition=None, message="No definition found.")
    return tool_result(definition=definition.model_dump())


async def _handle_lsp_diagnostics(args: dict[str, Any]) -> dict:
    """获取文件的语义诊断。"""
    from system.lsp import get_lsp_manager

    if not get_lsp_manager().is_ready():
        return tool_error("LSP not started. Call lsp_start first.")

    path: str = str(args.get("file", "")).strip()
    if not path:
        return tool_error("file is required")

    diags = await get_lsp_manager().diagnostics(path, _s())
    return tool_result(
        diagnostics=[d.model_dump() for d in diags],
        count=len(diags),
    )


async def _handle_lsp_symbols(args: dict[str, Any]) -> dict:
    """获取文件的符号列表。"""
    from system.lsp import get_lsp_manager

    if not get_lsp_manager().is_ready():
        return tool_error("LSP not started. Call lsp_start first.")

    path: str = str(args.get("file", "")).strip()
    if not path:
        return tool_error("file is required")

    symbols = await get_lsp_manager().symbols(path, _s())
    return tool_result(
        symbols=[s.model_dump() for s in symbols],
        count=len(symbols),
    )


async def _handle_lsp_refresh(args: dict[str, Any]) -> dict:
    """主动刷新 LSP 索引。"""
    from system.lsp import get_lsp_manager

    if not get_lsp_manager().is_ready():
        return tool_error("LSP not started. Call lsp_start first.")

    file: str | None = args.get("file")
    if file is not None:
        file = str(file).strip()
        if not file:
            file = None

    result = await get_lsp_manager().refresh(file, _s())
    if "error" in result:
        return tool_error(result["error"])
    return tool_result(**result)


# ---------------------------------------------------------------------------
# 注册
# ---------------------------------------------------------------------------

registry.register(
    name="lsp_start",
    toolset="lsp",
    schema={
        # 启动或替换 pyright LSP server。指定一个逻辑路径作为根目录，
        # pyright 将索引该目录下的所有 .py 文件。
        # 重复调用时直接停止旧进程并以新根目录重启，返回重启信息。
        # 前置条件：root 必须是一个存在的目录（如 'fork:' 或 'ws:src'）。
        # pyright 未安装时返回安装提示。
        # 调用效果：启动 pyright-langserver 子进程，执行 LSP 初始化握手和索引，
        # 完成后标记为 READY。进程以 daemon 方式运行。
        # 返回：{started, root, root_uri, [replaced, previous_root]}
        # 典型场景：agent 需要分析某个命名空间下的代码前，先启动 LSP。
        # 副作用：启动子进程。替换重启时会终止之前的 pyright 进程。
        "description": """Start or replace the pyright LSP server for a given root directory.

## Prerequisites
- `root` must be an existing directory accessible via a sandbox namespace prefix (e.g. 'fork:', 'ws:src').
- pyright must be installed (`pip install pyright`). If not found, returns an install hint.

## Effect
Starts `pyright-langserver --stdio` as a subprocess, performs LSP initialization handshake and indexing. When called again with a different root, the previous pyright process is terminated and a new one starts. The process runs as a daemon.

## Returns
First start:
```json
{"started": true, "root": "fork:", "root_uri": "file:///D:/path/to/fork"}
```
Replacement:
```json
{"started": true, "root": "ws:src", "root_uri": "file:///D:/path/to/ws/src", "replaced": true, "previous_root": "file:///D:/path/to/fork"}
```
Error:
```json
{"error": "pyright-langserver not found. Install with: pip install pyright"}
```

## When to Use
- Before using lsp_references, lsp_definition, lsp_diagnostics, or lsp_symbols.
- When switching to a different namespace or directory for code analysis.

## Side Effects
- Starts a subprocess (pyright-langserver).
- On replacement, the previous pyright process is terminated.""",
        "parameters": {
            "type": "object",
            "properties": {
                "root": {
                    "type": "string",
                    # 逻辑路径（命名空间前缀 + 路径），如 'fork:' 或 'ws:src'。必须是一个存在的目录。
                    "description": "Logical path (namespace prefix + path) to use as LSP root directory. Must be an existing directory. Examples: 'fork:', 'ws:src'.",
                },
            },
            "required": ["root"],
        },
    },
    handler=_handle_lsp_start,
    emoji="🔍",
    danger_level=ToolDangerLevel.write,
    availability=ToolAvailability.EVERY,
)

registry.register(
    name="lsp_references",
    toolset="lsp",
    schema={
        # 查找指定位置符号的所有引用（语义级别，非文本匹配）。
        # 前置条件：LSP 已通过 lsp_start 启动。
        # 调用效果：只读查询，向 pyright 发送 textDocument/references 请求。
        # 返回：{references: [{file, line, column, end_line, end_column, preview}], count}
        # 典型场景：评估修改某个函数/类前的影响范围。
        # 副作用：无。
        "description": """Find all references of the symbol at the given position. Semantic-level lookup (not text matching).

## Prerequisites
- LSP must be started via `lsp_start`.
- `file`, `line`, and `column` must be provided.

## Effect
Read-only query. Sends `textDocument/references` to pyright. Returns all locations where the symbol at the given position is referenced.

## Returns
```json
{
  "references": [
    {"file": "fork:main.py", "line": 42, "column": 5, "end_line": 42, "end_column": 20, "preview": "result = my_func()"}
  ],
  "count": 1
}
```

## When to Use
- Before modifying a function/class/variable, to understand the impact scope.
- To trace how a symbol is used across the codebase.

## Side Effects
- None (read-only query).""",
        "parameters": {
            "type": "object",
            "properties": {
                "file": {
                    "type": "string",
                    # 文件逻辑路径（如 'fork:main.py'）。
                    "description": "File logical path (e.g. 'fork:main.py').",
                },
                "line": {
                    "type": "integer",
                    # 符号所在行号（1-indexed）。
                    "description": "Line number of the symbol (1-indexed).",
                },
                "column": {
                    "type": "integer",
                    # 符号所在列号（1-indexed，字符偏移）。
                    "description": "Column number of the symbol (1-indexed, character offset).",
                },
            },
            "required": ["file", "line", "column"],
        },
    },
    handler=_handle_lsp_references,
    is_async=True,
    emoji="📎",
    availability=ToolAvailability.EVERY,
)

registry.register(
    name="lsp_definition",
    toolset="lsp",
    schema={
        # 跳转到指定位置符号的定义位置。
        # 前置条件：LSP 已通过 lsp_start 启动。
        # 调用效果：只读查询，向 pyright 发送 textDocument/definition 请求。
        # 返回：{definition: {file, line, column, end_line, end_column, preview}} 或 {definition: null}
        # 典型场景：理解函数/类/变量的来源定义。
        # 副作用：无。
        "description": """Go to the definition of the symbol at the given position.

## Prerequisites
- LSP must be started via `lsp_start`.
- `file`, `line`, and `column` must be provided.

## Effect
Read-only query. Sends `textDocument/definition` to pyright. Returns the location where the symbol is defined.

## Returns
Found:
```json
{"definition": {"file": "fork:utils.py", "line": 10, "column": 4, "end_line": 15, "end_column": 20, "preview": "def my_func():"}}
```
Not found:
```json
{"definition": null, "message": "No definition found."}
```

## When to Use
- Understand where a function/class/variable is originally defined.
- Navigate to the source of an imported symbol.

## Side Effects
- None (read-only query).""",
        "parameters": {
            "type": "object",
            "properties": {
                "file": {
                    "type": "string",
                    # 文件逻辑路径（如 'fork:main.py'）。
                    "description": "File logical path (e.g. 'fork:main.py').",
                },
                "line": {
                    "type": "integer",
                    # 符号所在行号（1-indexed）。
                    "description": "Line number of the symbol (1-indexed).",
                },
                "column": {
                    "type": "integer",
                    # 符号所在列号（1-indexed，字符偏移）。
                    "description": "Column number of the symbol (1-indexed, character offset).",
                },
            },
            "required": ["file", "line", "column"],
        },
    },
    handler=_handle_lsp_definition,
    is_async=True,
    emoji="🎯",
    availability=ToolAvailability.EVERY,
)

registry.register(
    name="lsp_diagnostics",
    toolset="lsp",
    schema={
        # 获取文件的语义诊断信息（错误、警告、提示）。
        # 前置条件：LSP 已通过 lsp_start 启动。
        # 调用效果：只读查询，返回 pyright 缓存中该文件的最新 diagnostics。
        # 返回：{diagnostics: [{severity, line, column, end_line, end_column, message, source, code}], count}
        # 典型场景：write_file/edit_file 后检查代码错误；主动验证文件语义正确性。
        # 副作用：无。
        "description": """Get semantic diagnostics (errors, warnings, hints) for a file.

## Prerequisites
- LSP must be started via `lsp_start`.
- `file` must be provided.

## Effect
Read-only query. Returns the latest cached diagnostics from pyright for the specified file. Diagnostics are automatically updated when files are modified via `write_file` or `edit_file`.

## Returns
```json
{
  "diagnostics": [
    {"severity": "error", "line": 5, "column": 1, "end_line": 5, "end_column": 10, "message": "Undefined variable 'foo'", "source": "pyright", "code": "reportUndefinedVariable"}
  ],
  "count": 1
}
```

## When to Use
- After writing or editing code, to check for semantic errors.
- Proactively verify file correctness before `evolve_code`.

## Side Effects
- None (read-only query).""",
        "parameters": {
            "type": "object",
            "properties": {
                "file": {
                    "type": "string",
                    # 文件逻辑路径（如 'fork:main.py'）。
                    "description": "File logical path (e.g. 'fork:main.py').",
                },
            },
            "required": ["file"],
        },
    },
    handler=_handle_lsp_diagnostics,
    is_async=True,
    emoji="🔬",
    availability=ToolAvailability.EVERY,
)

registry.register(
    name="lsp_symbols",
    toolset="lsp",
    schema={
        # 获取文件中的符号列表（函数、类、变量等）。
        # 前置条件：LSP 已通过 lsp_start 启动。
        # 调用效果：只读查询，向 pyright 发送 textDocument/documentSymbol 请求。
        # 返回：{symbols: [{name, kind, line, column, end_line, end_column, detail, children}], count}
        # 典型场景：浏览模块结构；了解文件中定义了哪些函数/类。
        # 副作用：无。
        "description": """Get the list of symbols (functions, classes, variables, etc.) in a file.

## Prerequisites
- LSP must be started via `lsp_start`.
- `file` must be provided.

## Effect
Read-only query. Sends `textDocument/documentSymbol` to pyright. Returns the symbol tree of the file.

## Returns
```json
{
  "symbols": [
    {"name": "MyClass", "kind": "Class", "line": 5, "column": 6, "end_line": 20, "end_column": 1, "detail": null, "children": [
      {"name": "my_method", "kind": "Method", "line": 10, "column": 8, "end_line": 12, "end_column": 15, "detail": null, "children": []}
    ]}
  ],
  "count": 1
}
```

## When to Use
- Browse the structure of a module.
- Understand what functions/classes/variables are defined in a file.

## Side Effects
- None (read-only query).""",
        "parameters": {
            "type": "object",
            "properties": {
                "file": {
                    "type": "string",
                    # 文件逻辑路径（如 'fork:main.py'）。
                    "description": "File logical path (e.g. 'fork:main.py').",
                },
            },
            "required": ["file"],
        },
    },
    handler=_handle_lsp_symbols,
    is_async=True,
    emoji="🧩",
    availability=ToolAvailability.EVERY,
)

registry.register(
    name="lsp_refresh",
    toolset="lsp",
    schema={
        # 主动刷新 LSP 索引。可选指定单个文件，不指定则刷新整个工作区。
        # 前置条件：LSP 已通过 lsp_start 启动。
        # 调用效果：指定文件时发送 didChange 全量替换通知；不指定时触发工作区重分析。
        # 返回：{refreshed: true, file?: "...", scope?: "workspace"}
        # 典型场景：文件被外部手段修改后（绕过 write_file/edit_file），或索引过时时。
        # 副作用：清除该文件的 diagnostics 缓存（指定文件时）或全部缓存（工作区刷新时）。
        "description": """Manually refresh the LSP index for a specific file or the entire workspace.

## Prerequisites
- LSP must be started via `lsp_start`.

## Effect
When `file` is specified: reads the file from disk and sends a full `textDocument/didChange` notification to pyright, then clears the cached diagnostics for that file.
When `file` is omitted: sends `workspace/didChangeConfiguration` to trigger a full workspace re-analysis, and clears all cached diagnostics.

## Returns
File refresh:
```json
{"refreshed": true, "file": "fork:main.py"}
```
Workspace refresh:
```json
{"refreshed": true, "scope": "workspace"}
```

## When to Use
- After a file was modified by external means (bypassing write_file/edit_file).
- When the LSP index appears stale or inconsistent.

## Side Effects
- Clears the diagnostics cache for the specified file (or all files for workspace refresh).""",
        "parameters": {
            "type": "object",
            "properties": {
                "file": {
                    "type": "string",
                    # 可选。要刷新的文件逻辑路径。省略则刷新整个工作区。
                    "description": "Optional. File logical path to refresh. Omit to refresh the entire workspace.",
                },
            },
        },
    },
    handler=_handle_lsp_refresh,
    is_async=True,
    emoji="🔄",
    availability=ToolAvailability.EVERY,
)