"""文件系统工具 — 所有路径均为逻辑路径（带命名空间前缀）。

模块导入时通过 ``registry.register()`` 注册。
每个工具 handler 通过共享的 ``Sandbox`` 实例解析路径
（由 ``main.py`` 在 agent 循环启动前通过 ``set_sandbox()`` 设置）。

路径格式：``namespace:relative/path``
  - ``fork:``  读写（进化代码目标）
  - ``ws:``    读写（通用 agent 工作空间）
  - ``fix:``   读写（修复目标，仅 fallback 模式）

不存在 ``self:`` 命名空间 — agent 不能读取或修改自身的运行时副本。
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
                "description": f"逻辑路径（{path_desc}）。"
                "必须使用命名空间前缀：fork:、ws: 或 fix:。",
            },
        },
        "required": (["path"] if required else []),
    }


# -- read_file
registry.register(
    name="read_file",
    toolset="filesystem",
    schema={
        "description": (
            "读取文件内容。路径必须使用命名空间前缀："
            "'ws:' 用于 workspace 数据，'fork:' 用于进化代码，"
            "'fix:' 用于修复目标。"
            "示例：'ws:logs/error.log'、'fork:main.py'。\n\n"
            "支持通过 offset 和 limit 进行按行分页。"
            "默认 limit 为 100 行（硬上限）；使用 offset 跳过行。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "文件逻辑路径。"
                    "必须使用命名空间前缀：fork:、ws: 或 fix:。",
                },
                "offset": {
                    "type": "integer",
                    "description": "起始行号（0-indexed，默认 0）。",
                    "default": 0,
                    "minimum": 0,
                },
                "limit": {
                    "type": "integer",
                    "description": "最大返回行数（硬上限：100）。",
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
        "description": (
            "将内容写入文件。路径必须使用命名空间前缀。"
            "使用 'ws:' 写入 workspace 数据，'fork:' 写入进化代码。"
            "目录会自动创建。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "逻辑路径。必须使用 ws: 或 fork: 前缀。",
                },
                "content": {
                    "type": "string",
                    "description": "要写入文件的内容。",
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
        "description": (
            "列出目录内容。返回条目名称（非完整路径）。"
            "可使用任意命名空间前缀。"
        ),
        "parameters": _param("要列出的目录"),
    },
    handler=_handle_list,
    emoji="📂",
)


# -- delete_file
registry.register(
    name="delete_file",
    toolset="filesystem",
    schema={
        "description": (
            "删除文件或空目录。仅允许可写命名空间"
            "（ws:、fork:、fix:）。"
        ),
        "parameters": _param("要删除的文件或目录"),
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
        "description": (
            "通过替换文件中一处精确匹配的 old_string 为 new_string 来进行精准编辑。"
            "old_string 必须仅匹配一次 — 包含足够的上下文（前后各 2-3 行）使其唯一。"
            "仅需修改几行时使用此工具替代 write_file — 避免重新发送整个文件内容。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "逻辑路径（ws:/fork:/fix: 前缀）。",
                },
                "old_string": {
                    "type": "string",
                    "description": "要查找并替换的精确文本。",
                },
                "new_string": {
                    "type": "string",
                    "description": "替换文本（使用 '' 表示删除）。",
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
        "description": "检查文件或目录是否存在（所有命名空间）。",
        "parameters": _param("要检查的文件或目录", required=True),
    },
    handler=_handle_exists,
    emoji="🔍",
)