"""获取最晚上传文件的工具 — 按真实上传时间排序，返回文件名、大小、上传时间、修改时间和路径。"""

from __future__ import annotations

import datetime
import json
import logging
import re
from typing import Any, Dict, List

from abstract.tools.registry import registry, tool_error, tool_result
from entity.constant import UPLOAD_FILENAME_TIME_FORMAT
from system.sandbox import SandboxError
from .filesystem import _s

logger = logging.getLogger(__name__)

# 文件名示例：20250617_123045_utc_a1b2c3d4_filename.ext
_UPLOAD_TIME_RE = re.compile(
    r"^(\d{8}_\d{6}_utc)_[a-f0-9]{8}_(.+)$"
)


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
            logger.debug("skipping %s: %s", name, exc)
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
        # 获取最晚上传的文件列表。返回每个文件的原始文件名、大小（字节）、上传时间、修改时间和逻辑路径（ws:uploads/...）。
        "description": "Get the most recently uploaded files. Returns the original filename, size (bytes), upload time, modification time, and logical path (ws:uploads/...) for each file.",
        "parameters": {
            "type": "object",
            "properties": {
                "n": {
                    "type": "integer",
                    # 要返回的最新文件数量（默认 10，最大 100）
                    "description": "Number of most recent files to return (default 10, max 100).",
                    "default": 10,
                },
            },
        },
    },
    handler=_handle_list_uploads,
    emoji="📂",
    danger_level="readonly",
)