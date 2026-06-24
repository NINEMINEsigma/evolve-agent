"""文件系统工具 — 所有路径均为逻辑路径（带命名空间前缀）。

模块导入时通过 ``registry.register()`` 注册。
每个工具 handler 通过共享的 ``Sandbox`` 实例解析路径
（由 ``main.py`` 在 agent 循环启动前通过 ``set_sandbox()`` 设置）。

路径格式：``namespace:relative/path``
  - ``fork:``    读写（进化代码目标）
  - ``ws:``      读写（通用 agent 工作空间）
  - ``fix:``     读写（修复目标，仅 fallback 模式）
  - ``skills:``  读写（skill 文件目录）
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict

from abstract.tools.registry import registry, tool_error, tool_result
from entity.constant import EDIT_FILE_MAX_CHARS, FILE_SNIFF_BYTES, READ_FILE_DEFAULT_LIMIT, READ_FILE_MAX_LINES, WRITE_FILE_MAX_CHARS, WRITE_FILE_TRUNCATION_TAIL
from system.sandbox import Access, Sandbox, SandboxError

logger = logging.getLogger(__name__)

# 由 main.py 在 agent 循环启动前填充。
_sandbox: Sandbox | None = None


def set_sandbox(s: Sandbox) -> None:
    global _sandbox
    _sandbox = s


def _s() -> Sandbox:
    if _sandbox is None:
        raise RuntimeError("Sandbox not initialized — call set_sandbox() first")
    return _sandbox


# ---------------------------------------------------------------------------
# 工具 handler
# ---------------------------------------------------------------------------

def _handle_read(args: dict[str, Any]) -> dict:
    path: str = str(args.get("path", "")).strip()
    if not path:
        return tool_error("path is required", path=path)
    offset: int = int(args.get("offset", 0))
    limit: int = int(args.get("limit", READ_FILE_DEFAULT_LIMIT))
    if offset < 0:
        return tool_error("offset must be >= 0", path=path, offset=offset)
    if limit < 1:
        return tool_error("limit must be >= 1", path=path, limit=limit)
    if limit > READ_FILE_MAX_LINES:
        limit = READ_FILE_MAX_LINES
    try:
        content: str = _s().read(path, offset=offset, limit=limit)
        lines: list[str] = content.splitlines()
        numbered: str = "\n".join(
            f"{offset + i + 1}: {line}" for i, line in enumerate(lines)
        )
        total: int = _s().count_lines(path)
        last_line: int = offset + len(lines)
        remaining: int = max(0, total - last_line)
        return tool_result(
            content=numbered, path=path, offset=offset, limit=limit,
            total_lines=total, remaining=remaining,
        )
    except SandboxError as exc:
        return tool_error(str(exc), path=path)


def _handle_write(args: dict[str, Any]) -> dict:
    path: str = str(args.get("path", "")).strip()
    content: str = str(args.get("content", ""))
    if not path:
        return tool_error("path is required", path=path)
    truncated: bool = False
    tail: str = ""
    if len(content) > WRITE_FILE_MAX_CHARS:
        tail = content[WRITE_FILE_MAX_CHARS:WRITE_FILE_MAX_CHARS + WRITE_FILE_TRUNCATION_TAIL]
        content = content[:WRITE_FILE_MAX_CHARS]
        truncated = True
        logger.warning(
            "write_file | content truncated from %d to %d chars | path=%s | tail=%s",
            len(args.get("content", "")), WRITE_FILE_MAX_CHARS, path, repr(tail),
        )
    try:
        _s().write(path, content)
        if truncated:
            return tool_result(
                success=True, path=path, 
                bytes=len(content.encode("utf-8")),
                truncated=True,
                tail=tail,
            )
        else:
            return tool_result(
                success=True, path=path, 
                bytes=len(content.encode("utf-8")),
            )
    except SandboxError as exc:
        return tool_error(str(exc), path=path)


def _handle_list(args: dict[str, Any]) -> dict:
    path: str = str(args.get("path", "")).strip()
    if not path:
        return tool_error("path is required", path=path)
    try:
        raw: list[str] = _s().list_dir(path)
        resolved = _s().resolve_read(path)
        entries: list[str] = []
        for name in raw:
            p = resolved.real / name
            entries.append(f"{name}/" if p.is_dir() else name)
        return tool_result(entries=entries, path=path, count=len(entries))
    except SandboxError as exc:
        return tool_error(str(exc), path=path)


def _handle_delete(args: dict[str, Any]) -> dict:
    path: str = str(args.get("path", "")).strip()
    if not path:
        return tool_error("path is required", path=path)
    try:
        if _s().is_dir(path):
            return tool_error(
                "Path is a directory — use delete_folder for directories",
                path=path,
            )
        _s().delete(path)
        return tool_result(success=True, path=path, deleted=True)
    except SandboxError as exc:
        return tool_error(str(exc), path=path)


def _handle_exists(args: dict[str, Any]) -> dict:
    path: str = str(args.get("path", "")).strip()
    if not path:
        return tool_error("path is required", path=path)
    exists: bool = _s().exists(path)
    return tool_result(exists=exists, path=path)


# ---------------------------------------------------------------------------
# 注册（模块导入时执行）
# ---------------------------------------------------------------------------


def _param(path_desc: str, required: bool = True) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                # 逻辑路径（{path_desc}）。必须使用命名空间前缀：fork:、ws:、fix: 或 skills:。
                "description": f"Logical path ({path_desc}). "
                "Must use a namespace prefix: fork:, ws:, fix:, or skills:.",
            },
        },
        "required": (["path"] if required else []),
    }


# -- read_file
registry.register(
    name="read_file",
    toolset="filesystem",
    schema={
        # 读取文件内容并附带行号。路径必须使用命名空间前缀：
        # 'ws:' 用于 workspace 数据，'fork:' 用于进化代码，
        # 'fix:' 用于修复目标，'skills:' 用于 skill 文件。
        #
        # ## 前置条件
        # 文件必须存在于命名空间对应路径。
        #
        # ## 调用效果
        # 无副作用，纯查询。返回文件内容，每行前缀为 1-indexed 行号。
        # 支持分页：offset（0-indexed 起始行）和 limit（最大行数，硬上限 {READ_FILE_MAX_LINES}，默认 {READ_FILE_DEFAULT_LIMIT}）。
        #
        # ## 返回
        # ```json
        # {"path": "ws:example.txt", "content": "1|first line\n2|second line", "total_lines": 100, "remaining": 98, "offset": 0, "limit": 100}
        # ```
        # `total_lines` 为文件总行数。`remaining` 为当前读取的最后一行到文件末尾还剩多少行（0 表示已读至文件末尾）。
        #
        # ## 何时使用
        # - 编辑前查看文件内容。
        # - 分页浏览大文件。
        # - 通过行号引用具体位置。
        # - 利用 `remaining` 判断是否需要继续分页读取。
        #
        # ## 副作用/注意
        # - 无副作用，纯查询。
        # - offset < 0 或 limit < 1 返回错误。
        # - 文件不存在或沙箱拒绝访问返回描述性错误。
        "description": f"""Read file content with line numbers. Path must use a namespace prefix: 'ws:' for workspace data, 'fork:' for evolution code, 'fix:' for repair targets, 'skills:' for skill files.

## Prerequisites
The file must exist at the namespace-resolved path.

## Effect
No side effects, read-only query. Returns file content with each line prefixed by a 1-indexed line number.
Supports pagination via offset (0-indexed starting line) and limit (max lines, hard cap {READ_FILE_MAX_LINES}, default {READ_FILE_DEFAULT_LIMIT}).

## Returns
```json
{{"path": "ws:example.txt", "content": "1|first line\n2|second line", "total_lines": 100, "remaining": 98, "offset": 0, "limit": 100}}
```
`total_lines` is the total line count of the file. `remaining` is how many lines remain after the last line read (0 means the read reached the end of file).

## When to Use
- Inspect file content before editing.
- Browse large files in pages.
- Reference specific locations by line number.
- Use `remaining` to determine whether another page of reading is needed.

## Side Effects / Notes
- No side effects, read-only query.
- offset < 0 or limit < 1 returns an error.
- File not found or sandbox access denied returns a descriptive error.""",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    # 文件逻辑路径。必须使用命名空间前缀：fork:、ws: 或 fix:。
                    "description": "File logical path. "
                    "Must use a namespace prefix: fork:, ws:, fix:, or skills:.",
                },
                "offset": {
                    "type": "integer",
                    # 起始行号（0-indexed，默认 0）。输出使用 1-indexed 行号前缀。
                    "description": "Starting line number, 0-indexed (default 0). "
                    "Output uses 1-indexed line number prefixes for display.",
                    "default": 0,
                    "minimum": 0,
                },
                "limit": {
                    "type": "integer",
                    # 最大返回行数（默认 100，硬上限见 READ_FILE_MAX_LINES）。
                    "description": "Maximum number of lines to return (default 100, hard cap defined by READ_FILE_MAX_LINES).",
                    "default": 100,
                    "minimum": 1,
                    "maximum": READ_FILE_MAX_LINES,
                },
            },
            "required": ["path"],
        },
    },
    handler=_handle_read,
    emoji="📖",
)


# -- write_file
registry.register(
    name="write_file",
    toolset="filesystem",
    schema={
        # 将内容写入文件。路径必须使用命名空间前缀。
        #
        # ## 前置条件
        # 确定文件不存在需要新建文件，或确定文件内容已完全无效需要覆写。
        # 小范围修改或追加内容应使用 edit_file 或 append_file。
        #
        # ## 调用效果
        # 以 `content` 完整覆盖目标文件。若文件已存在则被覆盖，若不存在则创建。每次调用最多 {WRITE_FILE_MAX_CHARS} 个字符。
        # 超出限制时自动截断至 {WRITE_FILE_MAX_CHARS}，返回结果中 `truncated=true` 提示内容不完整。
        # 同时返回 `tail` 字段（被截断内容的前 {WRITE_FILE_TRUNCATION_TAIL} 个字符），可作为 edit_file 的 old_string 继续写入，剩余内容也可用 append_file 追加。
        # 不得使用 run_python 替代此工具写文件。
        #
        # ## 返回
        # 未截断时：
        # ```json
        # {{"success": true, "path": "ws:example.txt", "bytes": 42}}
        # ```
        # 截断时额外包含 `truncated=true` 和 `tail` 字段：
        # ```json
        # {{"success": true, "path": "ws:example.txt", "bytes": {WRITE_FILE_MAX_CHARS}, "truncated": true, "tail": "..."}}
        # ```
        # `tail` 为被截断部分的前 {WRITE_FILE_TRUNCATION_TAIL} 个字符，用作 edit_file 的 old_string。
        #
        # ## 何时使用
        # - 创建新文件。
        # - 完整覆写小文件（不超过 {WRITE_FILE_MAX_CHARS} 字符）。
        #
        # ## 副作用/注意
        # - 写入文件系统，覆盖已有文件。
        # - 超出 {WRITE_FILE_MAX_CHARS} 限制时自动截断，应继续用 `tail` 作为 old_string 调用 edit_file，或用 append_file 追加剩余内容。
        # - 路径使用命名空间前缀：'ws:' 用于 workspace 数据，'fork:' 用于进化代码，'skills:' 用于 skill 文件。
        "description": f"""Write content to a file. Path must use a namespace prefix.

## Prerequisites
The file must not exist yet (new file creation), or the file content is confirmed to be completely invalid and needs overwriting.
For small edits or appending, use edit_file or append_file instead.

## Effect
Overwrites the target file entirely with `content`. Creates the file if it doesn't exist. Max {WRITE_FILE_MAX_CHARS} characters per call.
Content exceeding the limit is automatically truncated to {WRITE_FILE_MAX_CHARS}; the result includes `truncated=true` to indicate incomplete content.
When truncated, a `tail` field is also returned containing the first {WRITE_FILE_TRUNCATION_TAIL} characters of the truncated portion — use it as the `old_string` for a follow-up edit_file call, and append the remaining content with append_file.
Do NOT use run_python as a substitute for this tool.

## Returns
Without truncation:
```json
{{"success": true, "path": "ws:example.txt", "bytes": 42}}
```
When truncated, additionally includes `truncated=true` and `tail`:
```json
{{"success": true, "path": "ws:example.txt", "bytes": {WRITE_FILE_MAX_CHARS}, "truncated": true, "tail": "..."}}
```
`tail` contains the first {WRITE_FILE_TRUNCATION_TAIL} characters of the truncated portion to use as old_string for edit_file.

## When to Use
- Create new files.
- Completely overwrite small files (within {WRITE_FILE_MAX_CHARS} characters).

## Side Effects / Notes
- Writes to the file system, overwriting existing files.
- Content exceeding {WRITE_FILE_MAX_CHARS} is auto-truncated; continue with edit_file using `tail` as old_string, or use append_file to add the remaining content.
- Use namespace prefixes: 'ws:' for workspace data, 'fork:' for evolution code, 'skills:' for skill files.""",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    # 逻辑路径。必须使用 ws:、fork: 或 skills: 前缀。
                    "description": "Logical path. Must use ws:, fork:, or skills: prefix.",
                },
                "content": {
                    "type": "string",
                    # 要写入文件的内容。最多 WRITE_FILE_MAX_CHARS 个字符。
                    "description": f"Content to write to the file. Max {WRITE_FILE_MAX_CHARS} characters.",
                },
            },
            "required": ["path", "content"],
        },
    },
    handler=_handle_write,
    emoji="✏️",
    danger_level="write",
)


# -- append_file
def _handle_append(args: dict[str, Any]) -> dict:
    path: str = str(args.get("path", "")).strip()
    content: str = str(args.get("content", ""))
    if not path:
        return tool_error("path is required", path=path)
    truncated: bool = False
    tail: str = ""
    if len(content) > WRITE_FILE_MAX_CHARS:
        tail = content[WRITE_FILE_MAX_CHARS:WRITE_FILE_MAX_CHARS + WRITE_FILE_TRUNCATION_TAIL]
        content = content[:WRITE_FILE_MAX_CHARS]
        truncated = True
        logger.warning(
            "append_file | content truncated from %d to %d chars | path=%s | tail=%s",
            len(args.get("content", "")), WRITE_FILE_MAX_CHARS, path, repr(tail),
        )
    if not _s().exists(path):
        return tool_error("File not found — use write_file to create it first", path=path)
    try:
        _s().append(path, content)
        if truncated:
            return tool_result(
                success=True, path=path,
                bytes=len(content.encode("utf-8")),
                truncated=True,
                tail=tail,
            )
        else:
            return tool_result(
                success=True, path=path,
                bytes=len(content.encode("utf-8")),
            )
    except SandboxError as exc:
        return tool_error(str(exc), path=path)


registry.register(
    name="append_file",
    toolset="filesystem",
    schema={
        # 将内容追加到文件末尾。路径必须使用命名空间前缀。
        #
        # ## 前置条件
        # 文件必须已存在。使用 write_file 先创建文件。
        #
        # ## 调用效果
        # 将 `content` 追加到目标文件末尾，不影响已有内容。每次调用最多 {WRITE_FILE_MAX_CHARS} 个字符。
        # 超出限制时自动截断至 {WRITE_FILE_MAX_CHARS}，返回结果中 `truncated=true` 提示内容不完整，应继续用下一次 append_file 追加剩余内容。
        #
        # ## 返回
        # 未截断时：
        # ```json
        # {{"success": true, "path": "ws:example.txt", "bytes": 42}}
        # ```
        # 截断时额外包含 `truncated=true` 和 `tail` 字段：
        # ```json
        # {{"success": true, "path": "ws:example.txt", "bytes": {WRITE_FILE_MAX_CHARS}, "truncated": true, "tail": "..."}}
        # ```
        # `tail` 为被截断部分的前 {WRITE_FILE_TRUNCATION_TAIL} 个字符。
        #
        # ## 何时使用
        # - 向已有文件末尾追加新内容。
        # - 配合 write_file 使用：先 write_file 创建，再 append_file 追加。
        #
        # ## 副作用/注意
        # - 写入文件系统，追加到文件末尾。
        # - 超出 {WRITE_FILE_MAX_CHARS} 限制时自动截断，`tail` 可协助继续用下一次 append_file 追加剩余内容。
        # - 路径使用命名空间前缀：'ws:' 用于 workspace 数据，'fork:' 用于进化代码，'skills:' 用于 skill 文件。
        "description": f"""Append content to the end of a file. Path must use a namespace prefix.

## Prerequisites
The file must already exist. Use write_file to create it first.

## Effect
Appends `content` to the end of the target file without affecting existing content. Max {WRITE_FILE_MAX_CHARS} characters per call.
Content exceeding the limit is automatically truncated to {WRITE_FILE_MAX_CHARS}; the result includes `truncated=true` to indicate incomplete content — continue with another append_file call for the remainder.

## Returns
Without truncation:
```json
{{"success": true, "path": "ws:example.txt", "bytes": 42}}
```
When truncated, additionally includes `truncated=true` and `tail`:
```json
{{"success": true, "path": "ws:example.txt", "bytes": {WRITE_FILE_MAX_CHARS}, "truncated": true, "tail": "..."}}
```
`tail` contains the first {WRITE_FILE_TRUNCATION_TAIL} characters of the truncated portion.

## When to Use
- Append new content to the end of an existing file.
- Use together with write_file: create with write_file, then append with append_file.

## Side Effects / Notes
- Writes to the file system, appending to the end of the file.
- Content exceeding {WRITE_FILE_MAX_CHARS} is auto-truncated; use `tail` to help continue with another append_file call for the remainder.
- Use namespace prefixes: 'ws:' for workspace data, 'fork:' for evolution code, 'skills:' for skill files.""",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    # 逻辑路径。必须使用 ws:、fork: 或 skills: 前缀。
                    "description": "Logical path. Must use ws:, fork:, or skills: prefix.",
                },
                "content": {
                    "type": "string",
                    # 要追加到文件末尾的内容。最多 WRITE_FILE_MAX_CHARS 个字符。
                    "description": f"Content to append to the file. Max {WRITE_FILE_MAX_CHARS} characters.",
                },
            },
            "required": ["path", "content"],
        },
    },
    handler=_handle_append,
    emoji="📝",
    danger_level="write",
)


# -- list_directory
# 列出目录内容。返回条目名称列表，目录名称以 "/" 结尾便于区分。
# 可使用任意命名空间前缀（ws:、fork:、fix:、skills:）。
#
# ## 前置条件
# 目录必须存在。
#
# ## 调用效果
# 列出目录中的文件和子目录名称（不是完整路径）。
# 目录条目以 "/" 后缀标识。返回结果包含条目总数 `count`。
#
# ## 返回
# ```json
# {"entries": ["file.py", "subdir/", "data.json"], "path": "ws:src", "count": 3}
# ```
#
# ## 何时使用
# - 浏览目录结构，确认文件/目录存在。
# - 为 read_file、delete_file 等工具提供精确的路径。
#
# ## 副作用/注意
# - 无副作用，只读查询。
# - 目录不存在或沙箱拒绝访问返回错误。
# - 不能列出单个文件（需使用 file_exists 或 is_file）。
registry.register(
    name="list_directory",
    toolset="filesystem",
    schema={
        "description": """List directory contents. Returns entry names; directory entries are suffixed with '/' for easy identification. Any namespace prefix (ws:, fork:, fix:, skills:) can be used.

## Prerequisites
The directory must exist.

## Effect
Lists files and subdirectory names (not full paths) inside the directory. Directory entries are suffixed with '/'. The result includes a `count` of entries.

## Returns
```json
{"entries": ["file.py", "subdir/", "data.json"], "path": "ws:src", "count": 3}
```

## When to Use
- Browse directory structure to confirm file/directory existence.
- Provide exact paths for tools like read_file, delete_file.

## Side Effects / Notes
- No side effects, read-only query.
- Directory not found or sandbox access denied returns a descriptive error.
- Cannot list a single file (use file_exists or is_file instead).""",
        "parameters": _param("directory to list"),
    },
    handler=_handle_list,
    emoji="📂",
)


# -- delete_file
# 删除文件。仅允许可写命名空间（ws:、fork:、fix:、skills:）。
# 如需删除目录，使用 delete_folder。
#
# ## 前置条件
# - 文件必须存在且不是目录。
# - 路径必须使用可写命名空间前缀。
#
# ## 调用效果
# 删除指定文件。如果路径是目录，返回错误并提示使用 delete_folder。
#
# ## 返回
# ```json
# {"success": true, "path": "ws:temp.txt", "deleted": true}
# ```
#
# ## 何时使用
# - 删除不再需要的文件。
# - 清理 workspace 中的临时文件。
#
# ## 副作用/注意
# - 危险操作：删除后无法恢复（沙箱无回收站）。
# - 只读命名空间返回访问错误。
# - 不接受目录路径；非空目录使用 delete_folder。
registry.register(
    name="delete_file",
    toolset="filesystem",
    schema={
        "description": """Delete a file. Only writable namespaces are allowed (ws:, fork:, fix:, skills:). For directory deletion, use delete_folder.

## Prerequisites
- The file must exist and must not be a directory.
- The path must use a writable namespace prefix.

## Effect
Deletes the specified file. If the path is a directory, returns an error directing the caller to use delete_folder.

## Returns
```json
{"success": true, "path": "ws:temp.txt", "deleted": true}
```

## When to Use
- Remove files that are no longer needed.
- Clean up temporary files in the workspace.

## Side Effects / Notes
- DANGEROUS: Deletion is irreversible (no trash/recycle bin in the sandbox).
- Read-only namespaces return an access error.
- Does not accept directory paths; use delete_folder for directories.""",
        # 要删除的文件路径
        "parameters": _param("file to delete"),
    },
    handler=_handle_delete,
    emoji="🗑️",
    danger_level="write",
)


def _handle_edit(args: dict[str, Any]) -> dict:
    """精准文本替换 — 查找并替换一处精确匹配。"""
    path: str = str(args.get("path", "")).strip()
    old_string: str = str(args.get("old_string", ""))
    new_string: str = str(args.get("new_string", ""))
    replace_all: bool = bool(args.get("replace_all", False))

    if not path:
        return tool_error("path is required")
    if not old_string:
        return tool_error("old_string is required")
    if len(old_string) > EDIT_FILE_MAX_CHARS:
        return tool_error(
            f"old_string exceeds {EDIT_FILE_MAX_CHARS} characters (got {len(old_string)}). "
            "Use a smaller, unique snippet with surrounding context instead.",
            path=path,
        )
    if len(new_string) > EDIT_FILE_MAX_CHARS:
        return tool_error(
            f"new_string exceeds {EDIT_FILE_MAX_CHARS} characters (got {len(new_string)}). "
            "Split the change into multiple sequential edit_file calls.",
            path=path,
        )
    if old_string == new_string:
        return tool_error("old_string and new_string are identical — nothing to change", path=path)

    if not _s().exists(path):
        return tool_error("File not found — use write_file to create it first", path=path)

    try:
        content: str = _s().read(path, limit=0)
    except SandboxError as exc:
        return tool_error(str(exc), path=path)

    if old_string not in content:
        return tool_error("old_string not found in file", path=path)

    if replace_all:
        new_content: str = content.replace(old_string, new_string)
    else:
        count: int = content.count(old_string)
        if count > 1:
            return tool_error(
                f"old_string matches {count} locations. Use more surrounding "
                f"context to make it unique, or set replace_all=true.",
                path=path, matches=count,
            )
        new_content = content.replace(old_string, new_string, 1)

    try:
        _s().write(path, new_content)
    except SandboxError as exc:
        return tool_error(str(exc), path=path)

    return tool_result(success=True, path=path, replaced=True)


registry.register(
    name="edit_file",
    toolset="filesystem",
    schema={
        # 通过替换 old_string 为 new_string 来精准编辑文件。
        # 默认情况下，old_string 必须仅匹配一次 — 包含足够的周围上下文（前后各 2-3 行）使其唯一。
        # old_string 和 new_string 各自不能超过 {EDIT_FILE_MAX_CHARS} 字符，且不能相同。
        # 仅需修改几行时使用此工具替代 write_file — 避免重新发送整个文件内容。
        # 如需更大更改，请多次顺序调用 edit_file。
        #
        # 使用方式：
        # - 必须先使用 read_file 查看当前内容及行号。
        # - 从 read_file 输出中选取 old_string 时，保留行号前缀之后的精确缩进。
        # - 包含 2-3 行周围上下文以确保唯一匹配。
        # - 设置 replace_all=true 可替换所有匹配项（跳过唯一性检查）。
        # - 修改少量行时始终优先使用此工具替代 write_file。
        #
        # 参数：
        #   path:       带命名空间前缀的逻辑路径（ws:/fork:/fix:/skills:）（必需）
        #   old_string: 要查找并替换的精确文本，最多 {EDIT_FILE_MAX_CHARS} 字符（必需）
        #   new_string: 替换文本，使用 '' 表示删除，最多 {EDIT_FILE_MAX_CHARS} 字符（必需）
        #   replace_all: 替换所有匹配项而非仅第一处（默认 false）
        #
        # 错误：
        #   - 文件中未找到 old_string → 编辑失败，返回描述性错误
        #   - old_string 匹配到 2+ 处（当 replace_all=false 时）→ 编辑失败，
        #     提示设置 replace_all=true 或添加更多周围上下文
        #   - 文件不存在 → 提示先使用 write_file 创建
        #   - 字符串相同 → 无变更，报错
        "description": f"""Precisely edit a file by replacing old_string with new_string. By default, old_string must match exactly once — include enough surrounding context (2-3 lines before and after) to make it unique. Both old_string and new_string are limited to {EDIT_FILE_MAX_CHARS} characters each and must not be identical. Use this instead of write_file when only a few lines need changing — avoids resending the entire file content. For larger changes, make multiple sequential edit_file calls.

Usage:
- You must use read_file first to inspect current content with line numbers.
- When picking old_string from read_file output, preserve exact indentation
  as it appears AFTER the line number prefix.
- Include 2-3 lines of surrounding context to ensure a unique match.
- Set replace_all=true to replace all occurrences (skips uniqueness check).
- ALWAYS prefer editing existing files over write_file for small changes.

Parameters:
  path:       Logical path with namespace prefix (ws:/fork:/fix:/skills:) (required)
  old_string: Exact text to find and replace, max {EDIT_FILE_MAX_CHARS} chars (required)
  new_string: Replacement text, use '' to delete, max {EDIT_FILE_MAX_CHARS} chars (required)
  replace_all: Replace all occurrences instead of just one (default false)

Errors:
  - old_string not found in file → edit fails, return descriptive error
  - old_string matches 2+ locations (when replace_all=false) → edit fails,
    tell caller to set replace_all=true or add more surrounding context
  - File does not exist → error telling caller to use write_file first
  - Strings identical → error, nothing to change""",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    # 逻辑路径（ws:/fork:/fix:/skills: 前缀）。
                    "description": "Logical path (ws:/fork:/fix:/skills: prefix).",
                },
                "old_string": {
                    "type": "string",
                    # 要查找并替换的精确文本。
                    "description": "Exact text to find and replace.",
                },
                "new_string": {
                    "type": "string",
                    # 替换文本（使用 '' 表示删除）。
                    "description": "Replacement text (use '' to delete).",
                },
                "replace_all": {
                    "type": "boolean",
                    # 如为 true，替换所有匹配项而非仅替换第一处（默认 false）。
                    "description": "If true, replace ALL occurrences instead of just the first one (default false).",
                    "default": False,
                },
            },
            "required": ["path", "old_string", "new_string"],
        },
    },
    handler=_handle_edit,
    emoji="✂️",
    danger_level="write",
)


# -- file_exists
# 检查文件或目录是否存在。支持所有命名空间（ws:、fork:、fix:、skills:）。
# 不区分文件还是目录——路径存在即返回 true。
# 如需区分文件/目录，使用 is_file 或 is_directory。
#
# ## 前置条件
# 无。路径不存在返回 false，不报错。
#
# ## 调用效果
# 无副作用，纯查询。返回布尔值表示路径是否存在。
#
# ## 返回
# ```json
# {"exists": true, "path": "ws:example.txt"}
# ```
#
# ## 何时使用
# - 在 read_file、delete_file 等操作前确认文件存在。
# - 检查文件是否已被创建或删除。
#
# ## 副作用/注意
# - 无副作用，只读查询。
# - 不区分文件与目录。
# - 路径格式无效（如缺少命名空间前缀）可能返回错误。
registry.register(
    name="file_exists",
    toolset="filesystem",
    schema={
        "description": """Check if a file or directory exists (all namespaces). Does not distinguish between files and directories — returns true if the path exists. Use is_file or is_directory to check the type.

## Prerequisites
None. Non-existent paths return false, not an error.

## Effect
No side effects, read-only query. Returns a boolean indicating whether the path exists.

## Returns
```json
{"exists": true, "path": "ws:example.txt"}
```

## When to Use
- Confirm a file exists before read_file, delete_file, etc.
- Check whether a file has been created or deleted.

## Side Effects / Notes
- No side effects, read-only query.
- Does not distinguish between files and directories.
- Invalid path format (e.g. missing namespace prefix) may return an error.""",
        # 要检查的文件或目录路径
        "parameters": _param("file or directory to check", required=True),
    },
    handler=_handle_exists,
    emoji="🔍",
)


# -- copy_file
def _handle_copy(args: dict[str, Any]) -> dict:
    source: str = str(args.get("source", "")).strip()
    destination: str = str(args.get("destination", "")).strip()
    if not source:
        return tool_error("source is required")
    if not destination:
        return tool_error("destination is required")
    try:
        _s().copy(source, destination)
        return tool_result(success=True, source=source, destination=destination)
    except SandboxError as exc:
        return tool_error(str(exc), source=source, destination=destination)


def _handle_copy_folder(args: dict[str, Any]) -> dict:
    source: str = str(args.get("source", "")).strip()
    destination: str = str(args.get("destination", "")).strip()
    if not source:
        return tool_error("source is required")
    if not destination:
        return tool_error("destination is required")
    try:
        _s().copy_folder(source, destination)
        return tool_result(success=True, source=source, destination=destination)
    except SandboxError as exc:
        return tool_error(str(exc), source=source, destination=destination)


# -- copy_file
# 复制文件。源路径和目标路径均需使用命名空间前缀（ws:、fork:、fix:、skills:）。
# 支持跨命名空间复制（如从 fork: 复制到 ws:）。
#
# ## 前置条件
# - 源文件必须存在。
# - 目标路径不能与源路径相同。
# - 目标路径所在命名空间必须是可写的。
#
# ## 调用效果
# 将源文件完整复制到目标路径。如果目标已存在，会被覆盖。
# 返回 source 和 destination 确认路径。
#
# ## 返回
# ```json
# {"success": true, "source": "fork:src/a.py", "destination": "ws:a.py"}
# ```
#
# ## 何时使用
# - 在不同命名空间之间复制文件（如从 fork: 复制到 ws:）。
# - 备份文件到同一命名空间下的不同路径。
#
# ## 副作用/注意
# - 写入文件系统。目标已存在则被覆盖。
# - 不支持复制目录（只复制单个文件）。
# - 跨命名空间复制时，目标命名空间必须可写。
registry.register(
    name="copy_file",
    toolset="filesystem",
    schema={
        "description": """Copy a file. Both source and destination must use a namespace prefix (ws:, fork:, fix:, skills:). Supports cross-namespace copying (e.g. from fork: to ws:).

## Prerequisites
- The source file must exist.
- The destination must not be the same path as the source.
- The destination namespace must be writable.

## Effect
Copies the source file to the destination path. If the destination already exists, it will be overwritten. Returns both source and destination paths for confirmation.

## Returns
```json
{"success": true, "source": "fork:src/a.py", "destination": "ws:a.py"}
```

## When to Use
- Copy files between different namespaces (e.g. from fork: to ws:).
- Back up files to a different path within the same namespace.

## Side Effects / Notes
- Writes to the file system. Overwrites the destination if it already exists.
- Does not support directories (single file copy only).
- Cross-namespace copy requires a writable destination namespace.""",
        "parameters": {
            "type": "object",
            "properties": {
                "source": {
                    "type": "string",
                    # 要复制的源文件逻辑路径（命名空间前缀 + 路径）。
                    "description": "Source file logical path (namespace prefix + path).",
                },
                "destination": {
                    "type": "string",
                    # 目标文件逻辑路径（命名空间前缀 + 路径）。
                    "description": "Destination file logical path (namespace prefix + path).",
                },
            },
            "required": ["source", "destination"],
        },
    },
    handler=_handle_copy,
    emoji="📋",
    danger_level="write",
)


# -- copy_folder
# 递归复制目录。源路径和目标路径均需使用命名空间前缀（ws:、fork:、fix:、skills:）。
# 支持跨命名空间复制。目标路径**不能已存在**，这是 shutil.copytree 的限制。
#
# ## 前置条件
# - 源目录必须存在。
# - 目标路径**不能已存在**。
# - 目标路径所在命名空间必须是可写的。
#
# ## 调用效果
# 将源目录递归复制到目标路径（包括所有子文件/子目录）。
# 返回 source 和 destination 确认路径。
#
# ## 返回
# ```json
# {"success": true, "source": "fork:src", "destination": "ws:backup/src"}
# ```
#
# ## 何时使用
# - 备份整个目录到另一个命名空间。
# - 在进化流程中复制代码目录。
#
# ## 副作用/注意
# - 写入文件系统。
# - 目标路径必须**不存在**（与 copy_file 不同，copytree 不覆盖）。
# - 如果需要覆盖，先 delete_folder 再 copy_folder。
# - 不支持复制单个文件（使用 copy_file）。
registry.register(
    name="copy_folder",
    toolset="filesystem",
    schema={
        "description": """Recursively copy a directory. Both source and destination must use a namespace prefix (ws:, fork:, fix:, skills:). Supports cross-namespace copying.

## Prerequisites
- The source directory must exist.
- The destination path must **not** already exist (limitation of shutil.copytree).
- The destination namespace must be writable.

## Effect
Recursively copies the source directory to the destination path, including all subdirectories and files. Returns both source and destination paths for confirmation.

## Returns
```json
{"success": true, "source": "fork:src", "destination": "ws:backup/src"}
```

## When to Use
- Back up an entire directory to another namespace.
- Copy code directories during the evolution workflow.

## Side Effects / Notes
- Writes to the file system.
- The destination path must **not** already exist (unlike copy_file, copytree does not overwrite).
- To overwrite, first delete_folder then copy_folder.
- Does not support single file copy (use copy_file).""",
        "parameters": {
            "type": "object",
            "properties": {
                "source": {
                    "type": "string",
                    # 源目录逻辑路径（命名空间前缀 + 路径）。
                    "description": "Source directory logical path (namespace prefix + path).",
                },
                "destination": {
                    "type": "string",
                    # 目标目录逻辑路径（命名空间前缀 + 路径）。必须不存在。
                    "description": "Destination directory logical path (namespace prefix + path). Must not already exist.",
                },
            },
            "required": ["source", "destination"],
        },
    },
    handler=_handle_copy_folder,
    emoji="📂",
    danger_level="write",
)


# -- move_file
def _handle_move(args: dict[str, Any]) -> dict:
    source: str = str(args.get("source", "")).strip()
    destination: str = str(args.get("destination", "")).strip()
    if not source:
        return tool_error("source is required")
    if not destination:
        return tool_error("destination is required")
    try:
        _s().move(source, destination)
        return tool_result(success=True, source=source, destination=destination)
    except SandboxError as exc:
        return tool_error(str(exc), source=source, destination=destination)


# -- move_file
# 移动或重命名文件/目录。目标路径可包含新名称，从而实现重命名。
# 源和目标路径均需使用命名空间前缀（ws:、fork:、fix:、skills:）。
# 支持跨命名空间移动（实现为复制+删除，非原子操作）。
#
# ## 前置条件
# - 源文件或目录必须存在。
# - 目标路径所在命名空间必须是可写的。
#
# ## 调用效果
# 将源文件或目录移动到目标路径。如果目标路径包含不同的文件名，同时完成重命名。
# 如果目标已存在且为文件，会被覆盖。
#
# ## 返回
# ```json
# {"success": true, "source": "ws:src/old.py", "destination": "ws:src/new.py"}
# ```
#
# ## 何时使用
# - 将文件/目录移动到不同路径。
# - 同时移动并重命名文件。
# - 整理目录结构。
#
# ## 副作用/注意
# - 写入文件系统。目标已存在则被覆盖。
# - 源路径在移动后不再存在。
# - 跨命名空间移动使用 shutil.move（内部复制后删除），不是原子操作。
registry.register(
    name="move_file",
    toolset="filesystem",
    schema={
        "description": """Move or rename a file/directory. The destination can include a new name, effectively renaming. Both source and destination must use a namespace prefix (ws:, fork:, fix:, skills:). Supports cross-namespace moving (implemented as copy + delete, not atomic).

## Prerequisites
- The source file or directory must exist.
- The destination namespace must be writable.

## Effect
Moves a file or directory to the destination path. If the destination includes a different filename, the move also acts as a rename. If the destination already exists and is a file, it will be overwritten.

## Returns
```json
{"success": true, "source": "ws:src/old.py", "destination": "ws:src/new.py"}
```

## When to Use
- Move files/directories to a different path.
- Move and rename a file in one operation.
- Reorganize directory structure.

## Side Effects / Notes
- Writes to the file system. Overwrites destination if it already exists.
- The source path no longer exists after the move.
- Cross-namespace moves use shutil.move (copy + delete internally), not atomic.""",
        "parameters": {
            "type": "object",
            "properties": {
                "source": {
                    "type": "string",
                    # 要移动的源文件/目录逻辑路径。
                    "description": "Source file/directory logical path.",
                },
                "destination": {
                    "type": "string",
                    # 目标路径（可包含新文件名）。
                    "description": "Destination path (can include a new filename).",
                },
            },
            "required": ["source", "destination"],
        },
    },
    handler=_handle_move,
    emoji="🚚",
    danger_level="write",
)


# -- rename_file
def _handle_rename(args: dict[str, Any]) -> dict:
    path: str = str(args.get("path", "")).strip()
    new_name: str = str(args.get("new_name", "")).strip()
    if not path:
        return tool_error("path is required")
    if not new_name:
        return tool_error("new_name is required")
    # Rename within the same directory: find parent dir, build destination with new name
    # 在同一目录下重命名：找出父目录，用新名称拼出目标路径
    import re as _re
    m = _re.match(r"^([a-zA-Z]+:)(.*/)?([^/]+)$", path)
    if not m:
        return tool_error(
            "unable to parse path — ensure it has a namespace prefix and filename",
            path=path,
        )
    ns_prefix: str = m.group(1)
    parent_dir: str = m.group(2) or ""
    destination: str = f"{ns_prefix}{parent_dir}{new_name}"
    try:
        _s().move(path, destination)
        return tool_result(success=True, source=path, destination=destination)
    except SandboxError as exc:
        return tool_error(str(exc), source=path, destination=destination)


# -- rename_file
# 在同一目录下重命名文件。路径和命名空间前缀不变。
# 只需提供新文件名（不含路径），工具自动在同一目录下完成重命名。
# 如需跨目录移动或重命名目录，使用 move_file。
#
# ## 前置条件
# - 文件必须存在。
# - 新文件名不能与同一目录下的现有文件/目录冲突。
# - 文件所在命名空间必须是可写的。
#
# ## 调用效果
# 在同一目录下将文件更名为 `new_name`。路径前缀和命名空间保持不变。
# 返回 source 和 destination 确认路径变化。
#
# ## 返回
# ```json
# {"success": true, "source": "ws:src/old.py", "destination": "ws:src/new.py"}
# ```
#
# ## 何时使用
# - 仅需更改文件名，不改变路径。
#
# ## 副作用/注意
# - 写入文件系统。
# - 只支持文件重命名，不支持目录（使用 move_file）。
# - 跨目录移动使用 move_file。
registry.register(
    name="rename_file",
    toolset="filesystem",
    schema={
        "description": """Rename a file within the same directory. The path and namespace prefix remain unchanged. Only the new filename (no path) is needed — the tool automatically renames within the same directory. For cross-directory moves or renaming directories, use move_file.

## Prerequisites
- The file must exist.
- The new name must not conflict with an existing file/directory in the same directory.
- The file's namespace must be writable.

## Effect
Renames the file to `new_name` within the same directory. The namespace prefix and path stay the same. Returns both source and destination paths.

## Returns
```json
{"success": true, "source": "ws:src/old.py", "destination": "ws:src/new.py"}
```

## When to Use
- Change only the filename without changing the path.

## Side Effects / Notes
- Writes to the file system.
- Only supports files, not directories (use move_file for directories).
- For cross-directory moves, use move_file.""",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    # 要重命名的文件逻辑路径（命名空间前缀 + 完整路径）。
                    "description": "File logical path to rename (namespace prefix + full path).",
                },
                "new_name": {
                    "type": "string",
                    # 新文件名（仅文件名，不含路径）。
                    "description": "New filename (filename only, no path).",
                },
            },
            "required": ["path", "new_name"],
        },
    },
    handler=_handle_rename,
    emoji="🏷️",
    danger_level="write",
)


# -- search_files
def _handle_search_files(args: dict[str, Any]) -> dict:
    path: str = str(args.get("path", "")).strip()
    pattern: str = str(args.get("pattern", "")).strip()
    limit: int = int(args.get("limit", 100))

    if not path:
        return tool_error("path is required")
    if not pattern:
        return tool_error("pattern is required")

    try:
        resolved = _s().resolve_read(path)
    except SandboxError as exc:
        return tool_error(str(exc), path=path)

    if not resolved.real.is_dir():
        return tool_error(f"Not a directory: {path}")

    matches: list[str] = []
    for p in resolved.real.rglob(pattern):
        if p.is_file():
            rel = p.relative_to(resolved.real).as_posix()
            matches.append(f"{resolved.namespace}:{rel}")

    count = len(matches)
    if count > limit:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        log_name = f"ws:logs/search_files_{timestamp}.log"
        log_content = (
            f"# search_files results for {path} pattern={pattern}\n"
            f"Total: {count} matches\n\n"
            + "\n".join(matches)
        )
        try:
            _s().write(log_name, log_content)
        except SandboxError as exc:
            return tool_error(str(exc))
        return tool_result(
            count=count,
            log_path=log_name,
            note=f"Results exceeded {limit} matches. Full list written to log file.",
        )

    return tool_result(matches=matches, count=count)


# -- search_files
# 按文件名 glob 模式递归搜索目录中的文件。返回匹配文件的逻辑路径列表。
# 使用 glob 模式（如 *.py、**/test_*.py），不是正则表达式。
# 结果超过 limit 时自动写入 ws:logs/ 下的日志文件，仅返回数量和日志路径。
#
# ## 前置条件
# - 搜索路径必须是一个存在的目录。
# - 路径必须使用命名空间前缀。
#
# ## 调用效果
# 递归遍历目录，查找文件名匹配 glob pattern 的文件。
# 返回匹配文件的逻辑路径列表（如 ws:src/main.py）。
# 结果超过 limit 条时，完整列表写入 ws:logs/search_files_<timestamp>.log。
#
# ## 返回
# 结果未超限时：
# ```json
# {"matches": ["ws:src/a.py", "ws:src/b.py"], "count": 2}
# ```
# 结果超限时：
# ```json
# {"count": 150, "log_path": "ws:logs/search_files_20250314_120000.log", "note": "..."}
# ```
#
# ## 何时使用
# - 查找特定文件名的文件。
# - 确定目录结构中有哪些文件。
#
# ## 副作用/注意
# - 无副作用，只读查询。
# - 使用 glob 模式（如 *.py），不是正则表达式。
# - 结果超过 limit（默认 100）时写入日志文件，不直接返回完整列表。
# - 不搜索文件内容（使用 grep）。
registry.register(
    name="search_files",
    toolset="filesystem",
    schema={
        "description": """Recursively search for files matching a filename glob pattern in a directory. Uses glob patterns (e.g. *.py, **/test_*.py), NOT regex. Returns a list of matching logical file paths. If results exceed the limit, the full list is written to a log file under ws:logs/ and only the count and log path are returned.

## Prerequisites
- The search path must be an existing directory.
- The path must use a namespace prefix.

## Effect
Recursively traverses the directory looking for files whose names match the glob pattern. Returns logical paths of matching files (e.g. ws:src/main.py). When results exceed the limit, the full list is written to ws:logs/search_files_<timestamp>.log.

## Returns
When results fit within the limit:
```json
{"matches": ["ws:src/a.py", "ws:src/b.py"], "count": 2}
```
When results exceed the limit:
```json
{"count": 150, "log_path": "ws:logs/search_files_20250314_120000.log", "note": "..."}
```

## When to Use
- Find files by name pattern.
- Discover what files exist in a directory tree.

## Side Effects / Notes
- No side effects, read-only query.
- Uses glob patterns (e.g. *.py), NOT regex.
- Results exceeding the limit (default 100) are written to a log file instead of returned inline.
- For searching file contents, use grep.""",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    # 要搜索的目录逻辑路径（如 'ws:'、'fork:src'）。必须使用命名空间前缀。
                    "description": "Directory logical path to search in (e.g. 'ws:', 'fork:src'). Must use a namespace prefix.",
                },
                "pattern": {
                    "type": "string",
                    # 文件名 glob 模式（如 '*.py'、'**/test_*.py'）。不是正则表达式。
                    "description": "Filename glob pattern (e.g. '*.py', '**/test_*.py'). NOT regex.",
                },
                "limit": {
                    "type": "integer",
                    # 内联返回的最大结果数（默认 100）。超出时写入日志文件。
                    "description": "Maximum number of results to return inline (default 100). Excess results are written to a log file.",
                    "default": 100,
                },
            },
            "required": ["path", "pattern"],
        },
    },
    handler=_handle_search_files,
    emoji="🔍",
)


# -- grep
_TEXT_EXTENSIONS: frozenset[str] = frozenset(
    {
        ".py", ".txt", ".md", ".json", ".yaml", ".yml", ".toml", ".csv",
        ".ini", ".cfg", ".conf", ".js", ".ts", ".jsx", ".tsx", ".css",
        ".html", ".htm", ".xml", ".sh", ".bat", ".ps1", ".rs", ".go",
        ".java", ".c", ".cpp", ".h", ".hpp", ".rb", ".php", ".swift",
        ".kt", ".scala", ".sql", ".rst", ".log",
    }
)


def _is_text_file(path: Any) -> bool:
    """通过扩展名和空字节探测判断是否为文本文件。"""
    if path.suffix.lower() in _TEXT_EXTENSIONS:
        return True
    try:
        sample: bytes = path.read_bytes()[:FILE_SNIFF_BYTES]
        return b"\x00" not in sample
    except Exception:
        return False


def _handle_grep(args: dict[str, Any]) -> dict:
    path: str = str(args.get("path", "")).strip()
    pattern: str = str(args.get("pattern", "")).strip()
    limit: int = int(args.get("limit", 100))
    max_file_size: int = int(args.get("max_file_size", 524_288_000))
    context_lines: int = int(args.get("context_lines", 2))

    if not path:
        return tool_error("path is required")
    if not pattern:
        return tool_error("pattern is required")

    try:
        resolved = _s().resolve_read(path)
    except SandboxError as exc:
        return tool_error(str(exc), path=path)

    if not resolved.real.is_dir():
        return tool_error(f"Not a directory: {path}")

    try:
        regex = re.compile(pattern)
    except re.error as exc:
        return tool_error(f"Invalid regex pattern: {exc}")

    matches: list[dict[str, Any]] = []
    for p in resolved.real.rglob("*"):
        if not p.is_file():
            continue
        if p.stat().st_size > max_file_size:
            continue
        if not _is_text_file(p):
            continue

        try:
            content = p.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue

        lines = content.splitlines()
        for i, line in enumerate(lines):
            if regex.search(line):
                rel = p.relative_to(resolved.real).as_posix()
                matches.append(
                    {
                        "file": f"{resolved.namespace}:{rel}",
                        "line": i + 1,
                        "match": line,
                        "context_before": lines[max(0, i - context_lines) : i],
                        "context_after": lines[i + 1 : i + 1 + context_lines],
                    }
                )

    count = len(matches)
    if count > limit:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        log_name = f"ws:logs/grep_{timestamp}.log"
        out_lines = [
            f"# grep results for {path} pattern={pattern}",
            f"Total: {count} matches",
            "",
        ]
        for m in matches:
            out_lines.append(f"{m['file']}:{m['line']}:{m['match']}")
            if m["context_before"]:
                for cb in m["context_before"]:
                    out_lines.append(f"  - {cb}")
            if m["context_after"]:
                for ca in m["context_after"]:
                    out_lines.append(f"  + {ca}")
            out_lines.append("")
        try:
            _s().write(log_name, "\n".join(out_lines))
        except SandboxError as exc:
            return tool_error(str(exc))
        return tool_result(
            count=count,
            log_path=log_name,
            note=f"Results exceeded {limit} matches. Full list written to log file.",
        )

    return tool_result(matches=matches, count=count)


# -- grep
# 按正则表达式递归搜索目录中文本文件的内容。
# 自动跳过二进制文件（通过扩展名 + 空字节探测）和超大文件。
# 返回匹配项的文件路径、行号、匹配文本及周围上下文行。
# 结果超过 limit 时自动写入 ws:logs/ 下的日志文件。
#
# ## 前置条件
# - 搜索路径必须是一个存在的目录。
# - 路径必须使用命名空间前缀。
# - pattern 必须是有效的 Python 正则表达式。
#
# ## 调用效果
# 递归遍历目录中的文本文件，用正则表达式搜索内容。
# 自动跳过二进制文件（通过白名单扩展名 + 前 {FILE_SNIFF_BYTES} 字节的空字节探测）、
# 超过 max_file_size 字节的文件、以及无法以 UTF-8 解码的文件。
# 每条匹配返回文件路径、行号、匹配行文本、前后上下文行。
# 结果超过 limit 条时，完整列表写入 ws:logs/grep_<timestamp>.log。
#
# ## 返回
# 结果未超限时：
# ```json
# {"matches": [{"file": "ws:src/main.py", "line": 42, "match": "def foo():", "context_before": [...], "context_after": [...]}], "count": 2}
# ```
# 结果超限时：
# ```json
# {"count": 150, "log_path": "ws:logs/grep_20250314_120000.log", "note": "..."}
# ```
#
# ## 何时使用
# - 在代码库中搜索特定函数、变量、错误信息等。
# - 配合 read_file 使用，根据 grep 结果的行号读取文件。
#
# ## 副作用/注意
# - 无副作用，只读查询。
# - pattern 是 Python 正则表达式，不是 glob 模式。
# - 自动跳过二进制文件和超大文件。
# - 结果超过 limit（默认 100）时写入日志文件。
# - 按文件名搜索使用 search_files。
registry.register(
    name="grep",
    toolset="filesystem",
    schema={
        "description": f"""Recursively search text file contents using a regex pattern in a directory. Automatically skips binary files (by extension + null-byte sniffing) and oversized files. Returns matches with file path, line number, matched text, and surrounding context lines. If results exceed the limit, the full list is written to a log file under ws:logs/.

## Prerequisites
- The search path must be an existing directory.
- The path must use a namespace prefix.
- The pattern must be a valid Python regex.

## Effect
Recursively traverses text files in the directory, searching contents with a regex pattern. Automatically skips binary files (via allowlist extension + null-byte probe on first {FILE_SNIFF_BYTES} bytes), files larger than max_file_size, and files that cannot be decoded as UTF-8. Each match returns file path, line number, matched line text, and surrounding context lines. When results exceed the limit, the full list is written to ws:logs/grep_<timestamp>.log.

## Returns
When results fit within the limit:
```json
{{"matches": [{{"file": "ws:src/main.py", "line": 42, "match": "def foo():", "context_before": [...], "context_after": [...]}}], "count": 2}}
```
When results exceed the limit:
```json
{{"count": 150, "log_path": "ws:logs/grep_20250314_120000.log", "note": "..."}}
```

## When to Use
- Search for specific functions, variables, error messages, etc. in a codebase.
- Use with read_file by line number from grep results.

## Side Effects / Notes
- No side effects, read-only query.
- Pattern is a Python regex, NOT a glob pattern.
- Automatically skips binary files and oversized files.
- Results exceeding the limit (default 100) are written to a log file.
- For searching by filename, use search_files.""",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    # 要搜索的目录逻辑路径（如 'ws:'、'fork:src'）。必须使用命名空间前缀。
                    "description": "Directory logical path to search in (e.g. 'ws:', 'fork:src'). Must use a namespace prefix.",
                },
                "pattern": {
                    "type": "string",
                    # 用于匹配文件内容的正则表达式。
                    "description": "Regex pattern to search for in file contents.",
                },
                "limit": {
                    "type": "integer",
                    # 内联返回的最大结果数（默认 100）。超出时写入日志文件。
                    "description": "Maximum number of results to return inline (default 100). Excess results are written to a log file.",
                    "default": 100,
                },
                "max_file_size": {
                    "type": "integer",
                    # 跳过大于此字节数的文件（默认 524288000 = 500MB）。
                    "description": "Skip files larger than this many bytes (default 524288000 = 500MB).",
                    "default": 524288000,
                },
                "context_lines": {
                    "type": "integer",
                    # 每条匹配结果前后包含的上下文行数（默认 2）。
                    "description": "Number of context lines to include before and after each match (default 2).",
                    "default": 2,
                },
            },
            "required": ["path", "pattern"],
        },
    },
    handler=_handle_grep,
    emoji="🔎",
)


# -- resolve_path
# 将沙盒逻辑路径解析为磁盘上的绝对路径
# Resolve sandbox logical path to absolute filesystem path


def _handle_resolve_path(args: dict[str, Any]) -> dict:
    path: str = str(args.get("path", "")).strip()
    if not path:
        return tool_error("path is required", path=path)
    try:
        abs_path: str = _s().resolve_abs(path)
        return tool_result(absolute_path=abs_path, logical_path=path)
    except SandboxError as exc:
        return tool_error(str(exc), path=path)


# -- resolve_path
# 将逻辑路径（如 ws:example.txt）解析为磁盘上的绝对路径。
# 在必要时可用于获取绝对路径（例如传递给外部命令），
# 但使用前必须提前告知用户并说明原因。
# 路径必须使用命名空间前缀。
#
# ## 前置条件
# 路径格式必须合法（命名空间前缀 + 相对路径）。
# 目标文件或目录不需要存在。
#
# ## 调用效果
# 无副作用，纯查询。返回逻辑路径对应的磁盘绝对路径字符串。
# 不检查路径是否存在。
#
# ## 返回
# ```json
# {"absolute_path": "C:\\workspace\\agentspace\\example.txt", "logical_path": "ws:example.txt"}
# ```
#
# ## 何时使用
# - 必要场景（如传递给外部命令），但使用前必须提前告知用户。
# - 调试路径解析问题。
#
# ## 副作用/注意
# - 无副作用，只读查询。
# - 不检查路径是否存在（只做解析）。
# - **必须在调用前告知用户将要使用此工具并说明原因。**
# - 结果应仅用于必要场景，不要硬编码绝对路径。
registry.register(
    name="resolve_path",
    toolset="filesystem",
    schema={
        "description": """Resolve a logical path (e.g. ws:example.txt) to an absolute filesystem path. May be used when necessary to obtain an absolute path (e.g. to pass to an external command), but **the user must be informed beforehand** about why this is needed. Path must use a namespace prefix.

## Prerequisites
The path format must be valid (namespace prefix + relative path). The target file/directory does not need to exist.

## Effect
No side effects, read-only query. Returns the absolute disk path corresponding to the logical path. Does not check whether the path exists.

## Returns
```json
{"absolute_path": "C:\\workspace\\agentspace\\example.txt", "logical_path": "ws:example.txt"}
```

## When to Use
- When necessary (e.g. passing to an external command), but **must inform the user beforehand**.
- Debugging path resolution issues.

## Side Effects / Notes
- No side effects, read-only query.
- Does not check whether the path exists (resolution only).
- **Must inform the user before calling this tool and explain why.**
- Result should only be used when necessary; do not hardcode absolute paths.""",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    # 逻辑路径（命名空间前缀 + 相对路径）。
                    "description": "Logical path (namespace prefix + relative path).",
                },
            },
            "required": ["path"],
        },
    },
    handler=_handle_resolve_path,
    emoji="📍",
)


# -- create_folder
# 创建目录（包括父目录）
# Create directory (including parent directories)


def _handle_create_folder(args: dict[str, Any]) -> dict:
    path: str = str(args.get("path", "")).strip()
    if not path:
        return tool_error("path is required", path=path)
    try:
        parents: bool = bool(args.get("parents", True))
        _s().create_folder(path, parents=parents)
        return tool_result(success=True, path=path, created=True)
    except SandboxError as exc:
        return tool_error(str(exc), path=path)


# -- create_folder
# 创建目录。路径必须使用命名空间前缀（ws:、fork:、fix:、skills:）。
# 默认自动创建所有缺失的父目录。
# 目录已存在时返回成功（幂等操作）。
#
# ## 前置条件
# - 路径所在命名空间必须是可写的。
#
# ## 调用效果
# 创建指定目录。默认同时创建所有缺失的父目录（parents=true）。
# 如果目录已存在，不会报错（幂等）。
#
# ## 返回
# ```json
# {"success": true, "path": "ws:src/subdir", "created": true}
# ```
#
# ## 何时使用
# - 在写入文件前确保目标目录存在。
# - 组织目录结构。
#
# ## 副作用/注意
# - 写入文件系统。
# - 默认创建所有父目录（类似 mkdir -p）。
# - 目录已存在时静默成功（幂等）。
registry.register(
    name="create_folder",
    toolset="filesystem",
    schema={
        "description": """Create a directory. Path must use a namespace prefix (ws:, fork:, fix:, skills:). By default, all missing parent directories are created automatically. Idempotent — returns success if the directory already exists.

## Prerequisites
The path namespace must be writable.

## Effect
Creates the specified directory. By default, also creates all missing parent directories (parents=true). If the directory already exists, no error is raised (idempotent).

## Returns
```json
{"success": true, "path": "ws:src/subdir", "created": true}
```

## When to Use
- Ensure a target directory exists before writing files.
- Organize directory structure.

## Side Effects / Notes
- Writes to the file system.
- Creates all parent directories by default (like mkdir -p).
- Idempotent — silently succeeds if the directory already exists.""",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    # 要创建的目录逻辑路径（命名空间前缀 + 相对路径）。
                    "description": "Directory logical path to create (namespace prefix + relative path).",
                },
                "parents": {
                    "type": "boolean",
                    # 是否同时创建缺失的父目录（默认 true）。
                    "description": "Whether to also create missing parent directories (default true).",
                    "default": True,
                },
            },
            "required": ["path"],
        },
    },
    handler=_handle_create_folder,
    emoji="📁",
    danger_level="readonly",
)


# -- delete_folder
# 递归删除目录及其所有内容
# Recursively delete a directory and all its contents


def _handle_delete_folder(args: dict[str, Any]) -> dict:
    path: str = str(args.get("path", "")).strip()
    if not path:
        return tool_error("path is required", path=path)
    try:
        _s().delete_folder(path)
        return tool_result(success=True, path=path, deleted=True)
    except SandboxError as exc:
        return tool_error(str(exc), path=path)


# -- delete_folder
# 递归删除目录及其所有内容。
# 路径必须使用可写命名空间前缀（ws:、fork:、fix:、skills:）。
# ⚠️ 危险操作：会递归删除目录中的所有文件和子目录，不可恢复。
#
# ## 前置条件
# - 目录必须存在。
# - 路径所在命名空间必须是可写的。
#
# ## 调用效果
# 递归删除指定目录及其所有内容。沙箱无回收站，删除后不可恢复。
#
# ## 返回
# ```json
# {"success": true, "path": "ws:temp", "deleted": true}
# ```
#
# ## 何时使用
# - 清理整个目录树。
# - 为 copy_folder 做准备（目标已存在时需要先删除）。
#
# ## 副作用/注意
# - ⚠️ 危险操作：递归删除，不可恢复。
# - 只接受目录路径；删除单个文件使用 delete_file。
# - 路径指向文件时返回错误。
registry.register(
    name="delete_folder",
    toolset="filesystem",
    schema={
        "description": """Recursively delete a directory and all its contents. Path must use a writable namespace prefix (ws:, fork:, fix:, skills:). ⚠️ DANGEROUS: this recursively removes all files and subdirectories with no way to recover.

## Prerequisites
- The directory must exist.
- The path namespace must be writable.

## Effect
Recursively deletes the specified directory and all its contents. The sandbox has no trash/recycle bin — deletion is irreversible.

## Returns
```json
{"success": true, "path": "ws:temp", "deleted": true}
```

## When to Use
- Clean up an entire directory tree.
- Prepare for copy_folder (delete destination first if it already exists).

## Side Effects / Notes
- ⚠️ DANGEROUS: Recursive deletion, irreversible.
- Only accepts directory paths; use delete_file for single files.
- Returns an error if the path points to a file.""",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    # 要删除的目录逻辑路径（命名空间前缀 + 相对路径）。
                    "description": "Directory logical path to delete (namespace prefix + relative path).",
                },
            },
            "required": ["path"],
        },
    },
    handler=_handle_delete_folder,
    emoji="🗂️",
    danger_level="write",
)


# -- is_file
# 判断路径是否为文件
# Check if a path is a file (not a directory)


def _handle_is_file(args: dict[str, Any]) -> dict:
    path: str = str(args.get("path", "")).strip()
    if not path:
        return tool_error("path is required", path=path)
    try:
        result: bool = _s().is_file(path)
        return tool_result(is_file=result, path=path)
    except SandboxError as exc:
        return tool_error(str(exc), path=path)


# -- is_file
# 判断路径是否为文件（不是目录）。路径必须使用命名空间前缀。
# 路径不存在时返回 false（不报错）。
#
# ## 前置条件
# 无。路径不存在返回 false，不报错。
#
# ## 调用效果
# 无副作用，纯查询。返回布尔值表示路径是否指向一个文件。
#
# ## 返回
# ```json
# {"is_file": true, "path": "ws:example.txt"}
# ```
#
# ## 何时使用
# - 在 read_file、delete_file 等操作前确认路径是文件而非目录。
# - 配合 file_exists 使用：先检查存在，再检查类型。
#
# ## 副作用/注意
# - 无副作用，只读查询。
# - 路径不存在返回 false。
# - 路径指向目录也返回 false。
registry.register(
    name="is_file",
    toolset="filesystem",
    schema={
        "description": """Check whether a path is a file (not a directory). Path must use a namespace prefix. Returns false if the path does not exist (no error).

## Prerequisites
None. Non-existent paths return false, not an error.

## Effect
No side effects, read-only query. Returns a boolean indicating whether the path points to a file.

## Returns
```json
{"is_file": true, "path": "ws:example.txt"}
```

## When to Use
- Confirm a path is a file (not a directory) before read_file, delete_file, etc.
- Use with file_exists: check existence first, then check type.

## Side Effects / Notes
- No side effects, read-only query.
- Returns false if the path does not exist.
- Returns false if the path points to a directory.""",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    # 要检查的逻辑路径（命名空间前缀 + 相对路径）。
                    "description": "Logical path to check (namespace prefix + relative path).",
                },
            },
            "required": ["path"],
        },
    },
    handler=_handle_is_file,
    emoji="📄",
)


# -- is_directory
# 判断路径是否为目录
# Check if a path is a directory


def _handle_is_directory(args: dict[str, Any]) -> dict:
    path: str = str(args.get("path", "")).strip()
    if not path:
        return tool_error("path is required", path=path)
    try:
        result: bool = _s().is_dir(path)
        return tool_result(is_directory=result, path=path)
    except SandboxError as exc:
        return tool_error(str(exc), path=path)


# -- is_directory
# 判断路径是否为目录。路径必须使用命名空间前缀。
# 路径不存在时返回 false（不报错）。
#
# ## 前置条件
# 无。路径不存在返回 false，不报错。
#
# ## 调用效果
# 无副作用，纯查询。返回布尔值表示路径是否指向一个目录。
#
# ## 返回
# ```json
# {"is_directory": true, "path": "ws:src"}
# ```
#
# ## 何时使用
# - 在 list_directory、delete_folder 等操作前确认路径是目录。
# - 配合 file_exists 使用：先检查存在，再检查类型。
#
# ## 副作用/注意
# - 无副作用，只读查询。
# - 路径不存在返回 false。
# - 路径指向文件也返回 false。
registry.register(
    name="is_directory",
    toolset="filesystem",
    schema={
        "description": """Check whether a path is a directory. Path must use a namespace prefix. Returns false if the path does not exist (no error).

## Prerequisites
None. Non-existent paths return false, not an error.

## Effect
No side effects, read-only query. Returns a boolean indicating whether the path points to a directory.

## Returns
```json
{"is_directory": true, "path": "ws:src"}
```

## When to Use
- Confirm a path is a directory before list_directory, delete_folder, etc.
- Use with file_exists: check existence first, then check type.

## Side Effects / Notes
- No side effects, read-only query.
- Returns false if the path does not exist.
- Returns false if the path points to a file.""",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    # 要检查的逻辑路径（命名空间前缀 + 相对路径）。
                    "description": "Logical path to check (namespace prefix + relative path).",
                },
            },
            "required": ["path"],
        },
    },
    handler=_handle_is_directory,
    emoji="📁",
)


# -- count_lines
# 返回文件的总行数，辅助 read_file 的分页读取
# Return total number of lines in a file to assist paginated read_file


def _handle_count_lines(args: dict[str, Any]) -> dict:
    path: str = str(args.get("path", "")).strip()
    if not path:
        return tool_error("path is required", path=path)
    try:
        total: int = _s().count_lines(path)
        return tool_result(total_lines=total, path=path)
    except SandboxError as exc:
        return tool_error(str(exc), path=path)


# -- count_lines
# 返回文件的总行数。路径必须使用命名空间前缀。
# 在调用 read_file 的 offset 前了解文件边界时有用。
#
# ## 前置条件
# 文件必须存在。
#
# ## 调用效果
# 无副作用，纯查询。返回文件的总行数。
# 用于辅助 read_file 的分页策略：先 count_lines 确定文件大小，再逐页读取。
#
# ## 返回
# ```json
# {"total_lines": 150, "path": "ws:example.txt"}
# ```
#
# ## 何时使用
# - 在分页读取文件前确定文件总行数。
# - 快速了解文件大小。
#
# ## 副作用/注意
# - 无副作用，只读查询。
# - 文件不存在返回错误。
# - 用于 read_file 的分页策略：total_lines 配合 limit 确定 offset 范围。
registry.register(
    name="count_lines",
    toolset="filesystem",
    schema={
        "description": """Return the total number of lines in a file. Path must use a namespace prefix. Useful to know file bounds before calling read_file with offset for paginated reading.

## Prerequisites
The file must exist.

## Effect
No side effects, read-only query. Returns the total line count of the file. Used to plan pagination strategy with read_file: count_lines first, then read in pages.

## Returns
```json
{"total_lines": 150, "path": "ws:example.txt"}
```

## When to Use
- Determine total line count before paginated reading.
- Quickly estimate file size.

## Side Effects / Notes
- No side effects, read-only query.
- Returns an error if the file does not exist.
- Use with read_file for pagination: total_lines + limit determines offset range.""",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    # 文件逻辑路径（命名空间前缀 + 相对路径）。
                    "description": "File logical path (namespace prefix + relative path).",
                },
            },
            "required": ["path"],
        },
    },
    handler=_handle_count_lines,
    emoji="📏",
)
