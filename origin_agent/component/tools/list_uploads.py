"""获取最晚上传文件的工具 — 按真实上传时间排序，返回文件名、大小、上传时间、修改时间和路径。"""

from __future__ import annotations

import datetime
import json
import logging
import re
from typing import Any, Dict, List

from abstract.tools.registry import registry, tool_error, tool_result
from entity.puretype import ToolDangerLevel
from entity.constant import UPLOAD_FILENAME_TIME_FORMAT, UPLOAD_TIME_RE_PATTERN
from system.sandbox import SandboxError
from .filesystem import _s

logger = logging.getLogger(__name__)

# 文件名示例：20250617_123045_utc_a1b2c3d4_filename.ext
_UPLOAD_TIME_RE = re.compile(UPLOAD_TIME_RE_PATTERN)


def _parse_upload_time(filename: str) -> datetime.datetime | None:
    """从文件名前缀解析 UTC 上传时间；解析失败返回 None。"""
    match = _UPLOAD_TIME_RE.match(filename)
    if not match:
        return None
    time_str = match.group(1)
    try:
        return datetime.datetime.strptime(
            time_str, UPLOAD_FILENAME_TIME_FORMAT
        ).replace(tzinfo=datetime.timezone.utc)
    except ValueError:
        return None


def _format_time(ts: float) -> str:
    return datetime.datetime.fromtimestamp(
        ts, tz=datetime.timezone.utc
    ).strftime("%Y-%m-%d %H:%M:%S UTC")


def _handle_list_uploads(args: dict[str, Any]) -> dict:
    """处理获取最晚上传文件的请求。"""
    n: int = args.get("n", 10)
    if not isinstance(n, int) or n < 1:
        return tool_error("n must be a positive integer", n=n)
    if n > 100:
        n = 100

    try:
        names: list[str] = _s().list_dir("ws:uploads/")
    except SandboxError as exc:
        # uploads 目录可能还不存在
        logger.info("uploads directory not available: %s", exc)
        return tool_result(files=[])

    entries: list[dict] = []
    for name in names:
        try:
            r = _s().resolve_read(f"ws:uploads/{name}")
            st = r.real.stat()

            upload_dt = _parse_upload_time(name)
            if upload_dt is not None:
                upload_ts = upload_dt.timestamp()
                upload_time = upload_dt.strftime("%Y-%m-%d %H:%M:%S UTC")
            else:
                # 旧文件没有上传时间戳前缀，回退到文件 mtime
                upload_ts = st.st_mtime
                upload_time = _format_time(st.st_mtime)

            entries.append({
                "filename": name,
                "size": st.st_size,
                "upload_time": upload_time,
                "upload_time_ts": upload_ts,
                "mtime": _format_time(st.st_mtime),
                "path": f"ws:uploads/{name}",
            })
        except Exception as exc:
            logger.warning("Skipping upload entry %s: %s", name, exc, exc_info=True)
            entries.append({
                "filename": name,
                "error": f"Failed to stat file: {exc}",
            })
            continue

    # 按真实上传时间降序排列，取前 n 个
    entries.sort(key=lambda e: e["upload_time_ts"], reverse=True)
    top = entries[:n]

    # 移除内部排序字段
    for e in top:
        del e["upload_time_ts"]

    return tool_result(files=top)


# ---------------------------------------------------------------------------
# 注册
# ---------------------------------------------------------------------------

registry.register(
    name="list_uploads",
    toolset="filesystem",
    schema={
        # 列出最近上传的文件，按上传时间降序排列。
        # 前置条件：无（uploads 目录不存在时返回空列表）。
        # 调用效果：只读查询，无副作用。
        # n: 返回数量，默认 10，最大 100。
        # 返回：{ files: [{ filename, size, upload_time, mtime, path }] }。upload_time 从文件名前缀时间戳解析（格式 YYYYMMDD_HHMMSS_utc_rand），旧文件回退到 mtime。
        # 典型场景：查看用户刚上传了哪些文件；获取文件路径后配合 read_file/read_image 读取。
        "description": """List the most recently uploaded files, sorted by upload time (newest first).

## Prerequisites
None. Returns an empty list if the uploads directory does not exist yet.

## Effect
Read-only query. No side effects.

## Parameters
- `n` (integer, default 10, max 100): Number of most recent files to return.

## Returns
```json
{
  "files": [
    { "filename": "20250617_123045_utc_a1b2c3d4_screenshot.png", "size": 12345, "upload_time": "2025-06-17 12:30:45 UTC", "mtime": "2025-06-17 12:30:45 UTC", "path": "ws:uploads/20250617_123045_utc_a1b2c3d4_screenshot.png" }
  ]
}
```
`upload_time` is parsed from the filename prefix timestamp (`YYYYMMDD_HHMMSS_utc_rand`). For older files without a timestamp prefix, falls back to file `mtime`.

## When to Use
- Checking what files the user recently uploaded.
- Getting file paths to use with `read_file` or `read_image`.""",
        "parameters": {
            "type": "object",
            "properties": {
                "n": {
                    "type": "integer",
                    # 返回的最近文件数量。默认 10，最大 100。
                    "description": """Number of most recent files to return. Default 10, max 100.""",
                    "default": 10,
                },
            },
        },
    },
    handler=_handle_list_uploads,
    emoji="📂",
    danger_level=ToolDangerLevel.readonly,
)