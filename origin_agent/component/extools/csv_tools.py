"""CSV 工具 — 结构化读写逗号/制表符分隔值文件。

模块导入时通过 ``registry.register()`` 注册。
"""

from __future__ import annotations

import csv
import io
import logging
from typing import Any, Dict, List

from abstract.tools.registry import registry, tool_error, tool_result
from component.tools.filesystem import _s as _get_sandbox

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------


def _handle_read_csv(args: Dict[str, Any]) -> dict:
    path: str = str(args.get("path", "")).strip()
    if not path:
        return tool_error("path is required")

    try:
        sandbox = _get_sandbox()
        r = sandbox.resolve_read(path)
        raw: str = r.real.read_text(encoding="utf-8-sig")  # BOM-safe
    except FileNotFoundError:
        return tool_error(f"File not found: {path}", path=path)
    except Exception as e:
        return tool_error(str(e), path=path)

    # 自动探测分隔符
    try:
        dialect = csv.Sniffer().sniff(raw[:4096])
    except csv.Error:
        dialect = csv.excel  # 默认逗号分隔

    reader = csv.DictReader(io.StringIO(raw), dialect=dialect)
    rows: list[dict[str, str]] = list(reader)

    columns: list[str] = list(rows[0].keys()) if rows else []

    return tool_result(
        path=path,
        rows=rows,
        count=len(rows),
        columns=columns,
    )


def _handle_write_csv(args: Dict[str, Any]) -> dict:
    path: str = str(args.get("path", "")).strip()
    data: list[dict[str, Any]] = args.get("data", [])

    if not path:
        return tool_error("path is required")
    if not data or not isinstance(data, list):
        return tool_error("data must be a non-empty list of objects")

    # 列顺序：显式指定 > 第一行的键
    columns: list[str] = args.get("columns") or list(data[0].keys())

    try:
        sandbox = _get_sandbox()
        r = sandbox.resolve_write(path)
        r.real.parent.mkdir(parents=True, exist_ok=True)

        with r.real.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(data)
    except Exception as e:
        return tool_error(str(e), path=path)

    return tool_result(
        path=path,
        rows=len(data),
        columns=columns,
        success=True,
    )


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

_CSV_PARAMS: dict = {
    "type": "object",
    "properties": {
        "path": {
            "type": "string",
            # CSV 文件逻辑路径，必须使用命名空间前缀（ws:、fork:）。例如 'ws:data/report.csv'。
            "description": (
                "CSV file logical path, must use a namespace prefix "
                "(ws:, fork:). E.g. 'ws:data/report.csv'."
            ),
        },
    },
    "required": ["path"],
}


registry.register(
    name="read_csv",
    toolset="extools",
    schema={
        # 读取 CSV（逗号分隔值）文件并以结构化行列表形式返回。
        # 自动探测分隔符（逗号、制表符、分号等）。
        # 支持 UTF-8 BOM。返回每行作为字典，键来自表头。
        "description": (
            "Read a CSV (comma-separated values) file and return as a "
            "structured list of rows. "
            "Auto-detects delimiter (comma, tab, semicolon, etc.). "
            "Supports UTF-8 BOM. Returns each row as a dict, keys from header."
        ),
        "parameters": {
            **_CSV_PARAMS,
            "properties": {
                **_CSV_PARAMS["properties"],
                "has_header": {
                    "type": "boolean",
                    # 第一行是否为表头（默认 True）。
                    "description": "Whether the first row is a header (default True).",
                    "default": True,
                },
            },
        },
    },
    handler=_handle_read_csv,
    emoji="📊",
)


registry.register(
    name="write_csv",
    toolset="extools",
    schema={
        # 将结构化行列表写入 CSV 文件。
        # 每行是一个字典，表头取自列名（columns）或第一行的键。
        # 仅有在 columns 中列出的字段会被写入。
        "description": (
            "Write a structured list of rows to a CSV file. "
            "Each row is a dict; headers are taken from columns or first row keys. "
            "Only fields listed in columns will be written."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    # CSV 文件逻辑路径，必须使用命名空间前缀（ws:、fork:）。
                    "description": (
                        "CSV file logical path, must use a namespace prefix "
                        "(ws:, fork:)."
                    ),
                },
                "data": {
                    "type": "array",
                    "items": {"type": "object"},
                    # 要写入的行数据，每行一个字典。
                    "description": "Row data to write, each row a dict.",
                },
                "columns": {
                    "type": "array",
                    "items": {"type": "string"},
                    # 列顺序。省略时使用第一行字典的键顺序。
                    "description": (
                        "Column order. When omitted, uses keys from the first row dict."
                    ),
                },
            },
            "required": ["path", "data"],
        },
    },
    handler=_handle_write_csv,
    emoji="📊",
    danger_level="write",
)