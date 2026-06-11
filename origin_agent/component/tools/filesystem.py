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
from typing import Any, Dict

from abstract.tools.registry import registry, tool_error, tool_result
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

def _handle_read(args: Dict[str, Any]) -> str:
    path: str = str(args.get("path", "")).strip()
    if not path:
        return tool_error("path is required", path=path)
    offset: int = int(args.get("offset", 0))
    limit: int = int(args.get("limit", 100))
    if offset < 0:
        return tool_error("offset must be >= 0", path=path, offset=offset)
    if limit < 1:
        return tool_error("limit must be >= 1", path=path, limit=limit)
    if limit > 100:
        limit = 100
    try:
        content: str = _s().read(path, offset=offset, limit=limit)
        return tool_result(content=content, path=path, offset=offset, limit=limit)
    except SandboxError as exc:
        return tool_error(str(exc), path=path)


def _handle_write(args: Dict[str, Any]) -> str:
    path: str = str(args.get("path", "")).strip()
    content: str = str(args.get("content", ""))
    if not path:
        return tool_error("path is required", path=path)
    if len(content) > 1000:
        return tool_error(
            f"content exceeds 1000 characters (got {len(content)})",
            path=path,
        )
    try:
        _s().write(path, content)
        return tool_result(success=True, path=path, bytes=len(content.encode("utf-8")))
    except SandboxError as exc:
        return tool_error(str(exc), path=path)


def _handle_list(args: Dict[str, Any]) -> str:
    path: str = str(args.get("path", "")).strip()
    if not path:
        return tool_error("path is required", path=path)
    try:
        entries: list[str] = _s().list_dir(path)
        return tool_result(entries=entries, path=path, count=len(entries))
    except SandboxError as exc:
        return tool_error(str(exc), path=path)


def _handle_delete(args: Dict[str, Any]) -> str:
    path: str = str(args.get("path", "")).strip()
    if not path:
        return tool_error("path is required", path=path)
    try:
        _s().delete(path)
        return tool_result(success=True, path=path, deleted=True)
    except SandboxError as exc:
        return tool_error(str(exc), path=path)


def _handle_exists(args: Dict[str, Any]) -> str:
    path: str = str(args.get("path", "")).strip()
    if not path:
        return tool_error("path is required", path=path)
    exists: bool = _s().exists(path)
    return tool_result(exists=exists, path=path)


# ---------------------------------------------------------------------------
# 注册（模块导入时执行）
# ---------------------------------------------------------------------------


def _param(path_desc: str, required: bool = True) -> Dict[str, Any]:
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
        # 读取文件内容。路径必须使用命名空间前缀：
        # 'ws:' 用于 workspace 数据，'fork:' 用于进化代码，
        # 'fix:' 用于修复目标。
        # 示例：'ws:logs/error.log'、'fork:main.py'。
        # 支持通过 offset 和 limit 进行按行分页。
        # 默认 limit 为 100 行（硬上限）；使用 offset 跳过行。
        "description": (
            "Read file content. Path must use a namespace prefix: "
            "'ws:' for workspace data, 'fork:' for evolution code, "
            "'fix:' for repair targets, 'skills:' for skill files. "
            "Example: 'ws:logs/error.log', 'fork:main.py', 'skills:my_skill.md'.\n\n"
            "Supports line-based pagination via offset and limit. "
            "Default limit is 100 lines (hard cap); use offset to skip lines."
        ),
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
                    # 起始行号（0-indexed，默认 0）。
                    "description": "Starting line number (0-indexed, default 0).",
                    "default": 0,
                    "minimum": 0,
                },
                "limit": {
                    "type": "integer",
                    # 最大返回行数（硬上限：100）。
                    "description": "Maximum number of lines to return (hard cap: 100).",
                    "default": 100,
                    "minimum": 1,
                    "maximum": 100,
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
        # 使用 'ws:' 写入 workspace 数据，'fork:' 写入进化代码。
        # 目录会自动创建。
        "description": (
            "Write content to a file. Path must use a namespace prefix. "
            "Use 'ws:' for workspace data, 'fork:' for evolution code, "
            "'skills:' for skill files. "
            "Directories are created automatically. "
            "Max 1000 characters per call. "
            "If rejected for exceeding the limit, do NOT use run_python to write files; "
            "use edit_file for incremental changes instead."
        ),
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
                    # 要写入文件的内容。最多 1000 个字符。
                    "description": "Content to write to the file. Max 1000 characters.",
                },
            },
            "required": ["path", "content"],
        },
    },
    handler=_handle_write,
    emoji="✏️",
    danger_level="write",
)


# -- list_directory
registry.register(
    name="list_directory",
    toolset="filesystem",
    schema={
        # 列出目录内容。返回条目名称（非完整路径）。可使用任意命名空间前缀。
        "description": (
            "List directory contents. Returns entry names (not full paths). "
            "Any namespace prefix can be used."
        ),
        # 要列出的目录
        "parameters": _param("directory to list"),
    },
    handler=_handle_list,
    emoji="📂",
)


# -- delete_file
registry.register(
    name="delete_file",
    toolset="filesystem",
    schema={
        # 删除文件或空目录。仅允许可写命名空间（ws:、fork:、fix:、skills:）。
        "description": (
            "Delete a file or empty directory. "
            "Only writable namespaces are allowed (ws:, fork:, fix:, skills:)."
        ),
        # 要删除的文件或目录
        "parameters": _param("file or directory to delete"),
    },
    handler=_handle_delete,
    emoji="🗑️",
    danger_level="write",
)


def _handle_edit(args: Dict[str, Any]) -> str:
    """精准文本替换 — 查找并替换一处精确匹配。"""
    path: str = str(args.get("path", "")).strip()
    old_string: str = str(args.get("old_string", ""))
    new_string: str = str(args.get("new_string", ""))

    if not path:
        return tool_error("path is required")
    if not old_string:
        return tool_error("old_string is required")

    try:
        content: str = _s().read(path, limit=0)
    except SandboxError as exc:
        return tool_error(str(exc), path=path)

    if old_string not in content:
        return tool_error("old_string not found in file", path=path)

    count: int = content.count(old_string)
    if count > 1:
        return tool_error(
            f"old_string matches {count} locations. Use more surrounding "
            f"context to make it unique.",
            path=path, matches=count,
        )

    new_content: str = content.replace(old_string, new_string, 1)
    try:
        _s().write(path, new_content)
    except SandboxError as exc:
        return tool_error(str(exc), path=path)

    return tool_result(success=True, path=path, replaced=True)


registry.register(
    name="edit_file",
    toolset="filesystem",
    schema={
        # 通过替换文件中一处精确匹配的 old_string 为 new_string 来进行精准编辑。
        # old_string 必须仅匹配一次 — 包含足够的上下文（前后各 2-3 行）使其唯一。
        # 仅需修改几行时使用此工具替代 write_file — 避免重新发送整个文件内容。
        "description": (
            "Precisely edit a file by replacing one exact match of old_string with new_string. "
            "old_string must match exactly once — include enough surrounding context "
            "(2-3 lines before and after) to make it unique. "
            "Use this instead of write_file when only a few lines need changing "
            "— avoids resending the entire file content. "
            "For larger changes, make multiple sequential edit_file calls."
        ),
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
            },
            "required": ["path", "old_string", "new_string"],
        },
    },
    handler=_handle_edit,
    emoji="✂️",
    danger_level="write",
)


# -- file_exists
registry.register(
    name="file_exists",
    toolset="filesystem",
    schema={
        # 检查文件或目录是否存在（所有命名空间）。
        "description": "Check if a file or directory exists (all namespaces).",
        # 要检查的文件或目录
        "parameters": _param("file or directory to check", required=True),
    },
    handler=_handle_exists,
    emoji="🔍",
)


# -- copy_file
def _handle_copy(args: Dict[str, Any]) -> str:
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


registry.register(
    name="copy_file",
    toolset="filesystem",
    schema={
        # 复制文件。源路径和目标路径均需使用命名空间前缀
        #（ws:、fork:、fix:、skills:）。支持跨命名空间复制。
        "description": (
            "Copy a file. Both source and destination must use "
            "a namespace prefix (ws:, fork:, fix:, skills:). "
            "Supports cross-namespace copying."
        ),
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


# -- move_file
def _handle_move(args: Dict[str, Any]) -> str:
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


registry.register(
    name="move_file",
    toolset="filesystem",
    schema={
        # 移动文件或目录。目标路径可以包含新名称，从而实现重命名。
        # 源和目标路径均需使用命名空间前缀（ws:、fork:、fix:、skills:）。支持跨命名空间移动。
        "description": (
            "Move a file or directory. The destination can include a new name, "
            "effectively renaming. Both source and destination must use "
            "a namespace prefix (ws:, fork:, fix:, skills:). "
            "Supports cross-namespace moving."
        ),
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
def _handle_rename(args: Dict[str, Any]) -> str:
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


registry.register(
    name="rename_file",
    toolset="filesystem",
    schema={
        # 重命名文件。在同一目录下将文件更名为新名称，
        # 路径和命名空间前缀不变。如需跨目录移动，请使用 move_file。
        "description": (
            "Rename a file. The file is renamed within the same directory; "
            "the path and namespace prefix remain unchanged. "
            "For cross-directory moves, use move_file."
        ),
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