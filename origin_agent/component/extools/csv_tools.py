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


def _handle_read_csv(args: dict[str, Any]) -> dict:
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


def _handle_write_csv(args: dict[str, Any]) -> dict:
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
            "description": """CSV file logical path, must use a namespace prefix (ws:, fork:). E.g. 'ws:data/report.csv'.""",
        },
    },
    "required": ["path"],
}


registry.register(
    name="read_csv",
    toolset="extools",
    schema={
        # 读取 CSV 文件并返回结构化行列表。
        #
        # ## 前置条件
        # path 必须使用命名空间前缀（如 ws:、fork:）。
        #
        # ## 调用效果
        # 自动探测分隔符（逗号、制表符、分号等），支持 UTF-8 BOM。
        # 以首行为列名，每行返回一个字典。
        #
        # ## 返回
        # ```json
        # {"path": "ws:data/report.csv", "rows": [{"col1": "value1"}], "count": 1, "columns": ["col1"]}
        # ```
        #
        # ## 何时使用
        # - 读取 CSV 表格数据。
        # - 导入结构化数据进行后续处理。
        #
        # ## 副作用/注意
        # - 只读操作，不会修改源文件。
        # - 无表头文件可通过 has_header=false 控制（当前实现默认按表头处理）。
        "description": """Read a CSV (comma-separated values) file and return a structured list of rows.

## Prerequisites
The path must use a namespace prefix (e.g. ws:, fork:).

## Effect
Auto-detects the delimiter (comma, tab, semicolon, etc.) and supports UTF-8 BOM. Uses the first row as column names and returns each subsequent row as a dict.

## Returns
```json
{"path": "ws:data/report.csv", "rows": [{"col1": "value1"}], "count": 1, "columns": ["col1"]}
```

## When to Use
- Read CSV tabular data.
- Import structured data for further processing.

## Side Effects / Notes
- Read-only operation; does not modify the source file.
- Files without headers are still treated as having a header by the current implementation.""",
        "parameters": {
            **_CSV_PARAMS,
            "properties": {
                **_CSV_PARAMS["properties"],
                "has_header": {
                    "type": "boolean",
                    # 第一行是否为表头（默认 True）。
                    "description": """Whether the first row is a header (default True).""",
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
        #
        # ## 前置条件
        # path 必须使用命名空间前缀（如 ws:、fork:）。
        # data 必须为非空字典列表。
        #
        # ## 调用效果
        # 根据 columns 或第一行字典的键写入表头和数据行。
        # 只有 columns 中列出的字段会被写入。
        #
        # ## 返回
        # ```json
        # {"path": "ws:data/report.csv", "rows": 3, "columns": ["col1", "col2"], "success": true}
        # ```
        #
        # ## 何时使用
        # - 将表格数据导出为 CSV。
        # - 生成可导入其他工具的数据文件。
        #
        # ## 副作用/注意
        # - 会写入新文件，可能覆盖同名文件。
        # - 未在 columns 中列出的字段会被忽略。
        "description": """Write a structured list of rows to a CSV file.

## Prerequisites
The path must use a namespace prefix (e.g. ws:, fork:). data must be a non-empty list of dicts.

## Effect
Writes headers and data rows based on columns or the keys of the first row dict. Only fields listed in columns are written.

## Returns
```json
{"path": "ws:data/report.csv", "rows": 3, "columns": ["col1", "col2"], "success": true}
```

## When to Use
- Export tabular data to CSV.
- Generate data files for import into other tools.

## Side Effects / Notes
- Writes a new file and may overwrite an existing file with the same name.
- Fields not listed in columns are ignored.""",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    # CSV 文件逻辑路径，必须使用命名空间前缀（ws:、fork:）。
                    "description": """CSV file logical path, must use a namespace prefix (ws:, fork:).""",
                },
                "data": {
                    "type": "array",
                    "items": {"type": "object"},
                    # 要写入的行数据，每行一个字典。
                    "description": """Row data to write, each row a dict.""",
                },
                "columns": {
                    "type": "array",
                    "items": {"type": "string"},
                    # 列顺序。省略时使用第一行字典的键顺序。
                    "description": """Column order. When omitted, uses keys from the first row dict.""",
                },
            },
            "required": ["path", "data"],
        },
    },
    handler=_handle_write_csv,
    emoji="📊",
    danger_level="write",
)