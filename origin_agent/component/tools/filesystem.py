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
from entity.constant import EDIT_FILE_MAX_CHARS, FILE_SNIFF_BYTES, WRITE_FILE_MAX_CHARS
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


def _handle_write(args: dict[str, Any]) -> dict:
    path: str = str(args.get("path", "")).strip()
    content: str = str(args.get("content", ""))
    if not path:
        return tool_error("path is required", path=path)
    if len(content) > WRITE_FILE_MAX_CHARS:
        return tool_error(
            f"content exceeds {WRITE_FILE_MAX_CHARS} characters (got {len(content)}). "
            "Use edit_file for incremental changes — split the write into multiple "
            "edit_file calls instead of sending the entire file at once.",
            path=path,
        )
    try:
        _s().write(path, content)
        return tool_result(success=True, path=path, bytes=len(content.encode("utf-8")))
    except SandboxError as exc:
        return tool_error(str(exc), path=path)


def _handle_list(args: dict[str, Any]) -> dict:
    path: str = str(args.get("path", "")).strip()
    if not path:
        return tool_error("path is required", path=path)
    try:
        entries: list[str] = _s().list_dir(path)
        return tool_result(entries=entries, path=path, count=len(entries))
    except SandboxError as exc:
        return tool_error(str(exc), path=path)


def _handle_delete(args: dict[str, Any]) -> dict:
    path: str = str(args.get("path", "")).strip()
    if not path:
        return tool_error("path is required", path=path)
    try:
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
            f"Max {WRITE_FILE_MAX_CHARS} characters per call. "
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
    if len(content) > WRITE_FILE_MAX_CHARS:
        return tool_error(
            f"content exceeds {WRITE_FILE_MAX_CHARS} characters (got {len(content)}). "
            "Split the append into multiple sequential append_file calls.",
            path=path,
        )
    if not _s().exists(path):
        return tool_error("File not found — use write_file to create it first", path=path)
    try:
        _s().append(path, content)
        return tool_result(success=True, path=path, bytes=len(content.encode("utf-8")))
    except SandboxError as exc:
        return tool_error(str(exc), path=path)


registry.register(
    name="append_file",
    toolset="filesystem",
    schema={
        # 将内容追加到文件末尾。路径必须使用命名空间前缀。
        # 使用 'ws:' 写入 workspace 数据，'fork:' 写入进化代码。
        # 文件必须已存在，否则报错；如需创建文件请使用 write_file。
        "description": (
            "Append content to the end of a file. Path must use a namespace prefix. "
            "Use 'ws:' for workspace data, 'fork:' for evolution code, "
            "'skills:' for skill files. "
            "File must already exist; use write_file to create it first. "
            f"Max {WRITE_FILE_MAX_CHARS} characters per call. "
            "If rejected for exceeding the limit, split the append into multiple append_file calls."
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


def _handle_edit(args: dict[str, Any]) -> dict:
    """精准文本替换 — 查找并替换一处精确匹配。"""
    path: str = str(args.get("path", "")).strip()
    old_string: str = str(args.get("old_string", ""))
    new_string: str = str(args.get("new_string", ""))

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
        # old_string 和 new_string 各自不能超过 EDIT_FILE_MAX_CHARS 字符，且不能相同。
        # 仅需修改几行时使用此工具替代 write_file — 避免重新发送整个文件内容。
        "description": (
            "Precisely edit a file by replacing one exact match of old_string with new_string. "
            "old_string must match exactly once — include enough surrounding context "
            "(2-3 lines before and after) to make it unique. "
            f"Both old_string and new_string are limited to {EDIT_FILE_MAX_CHARS} characters each "
            "and must not be identical. "
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


registry.register(
    name="search_files",
    toolset="filesystem",
    schema={
        # 按文件名模式递归搜索目录中的文件。
        # 返回匹配文件的逻辑路径列表。
        # 如果结果超过 limit，完整列表写入 ws:logs/ 下的日志文件，仅返回数量和路径。
        "description": (
            "Recursively search for files matching a filename pattern in a directory. "
            "Returns a list of matching logical file paths. "
            "If results exceed the limit, the full list is written to a log file under ws:logs/ "
            "and only the count and log path are returned."
        ),
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
                    # 文件名 glob 模式（如 '*.py'、'*.md'）。
                    "description": "Filename glob pattern (e.g. '*.py', '*.md').",
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


registry.register(
    name="grep",
    toolset="filesystem",
    schema={
        # 按正则表达式递归搜索目录中文本文件的内容。
        # 只搜索文本文件，跳过超过 max_file_size 的文件。
        # 返回匹配项的文件、行号、匹配文本及上下文。
        # 如果结果超过 limit，完整列表写入 ws:logs/ 下的日志文件，仅返回数量和路径。
        "description": (
            "Recursively search text file contents using a regex pattern in a directory. "
            "Only searches text files and skips files larger than max_file_size. "
            "Returns matches with file path, line number, matched text, and surrounding context. "
            "If results exceed the limit, the full list is written to a log file under ws:logs/ "
            "and only the count and log path are returned."
        ),
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


registry.register(
    name="resolve_path",
    toolset="filesystem",
    schema={
        # 将逻辑路径解析为绝对路径。路径必须使用命名空间前缀
        # (fork:、ws:、fix:、skills:)。返回该路径在磁盘上的绝对路径。
        "description": (
            "Resolve a logical path to an absolute filesystem path. "
            "Path must use a namespace prefix (fork:, ws:, fix:, skills:). "
            "Returns the absolute path on disk."
        ),
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


registry.register(
    name="create_folder",
    toolset="filesystem",
    schema={
        # 创建目录。路径必须使用命名空间前缀
        # (fork:、ws:、fix:、skills:)。
        # 默认自动创建所有缺失的父目录（parents=true）。
        "description": (
            "Create a directory. Path must use a namespace prefix "
            "(fork:, ws:, fix:, skills:). "
            "By default, all missing parent directories are created automatically."
        ),
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
    danger_level="write",
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


registry.register(
    name="delete_folder",
    toolset="filesystem",
    schema={
        # 递归删除目录及其所有内容。路径必须使用命名空间前缀
        # (fork:、ws:、fix:、skills:)。仅允许可写命名空间。
        # 危险操作：会删除目录中的所有文件和子目录。
        "description": (
            "Recursively delete a directory and all its contents. "
            "Path must use a writable namespace prefix (ws:, fork:, fix:, skills:). "
            "DANGEROUS: this removes all files and subdirectories inside the directory."
        ),
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


registry.register(
    name="is_file",
    toolset="filesystem",
    schema={
        # 判断路径是否为文件（不是目录）。路径必须使用命名空间前缀
        # (fork:、ws:、fix:、skills:)。
        "description": (
            "Check whether a path is a file (not a directory). "
            "Path must use a namespace prefix (fork:, ws:, fix:, skills:)."
        ),
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


registry.register(
    name="is_directory",
    toolset="filesystem",
    schema={
        # 判断路径是否为目录。路径必须使用命名空间前缀
        # (fork:、ws:、fix:、skills:)。
        "description": (
            "Check whether a path is a directory. "
            "Path must use a namespace prefix (fork:, ws:, fix:, skills:)."
        ),
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


registry.register(
    name="count_lines",
    toolset="filesystem",
    schema={
        # 返回文件的总行数。路径必须使用命名空间前缀
        # (fork:、ws:、fix:、skills:)。可配合 read_file 的 offset 使用。
        "description": (
            "Return the total number of lines in a file. "
            "Path must use a namespace prefix (fork:, ws:, fix:, skills:). "
            "Useful to know file bounds before calling read_file with offset."
        ),
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
