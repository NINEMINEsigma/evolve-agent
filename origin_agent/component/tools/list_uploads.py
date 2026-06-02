"""获取最晚上传文件的工具 — 按修改时间排序，返回文件名、大小、路径。"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List

from abstract.tools.registry import registry, tool_error, tool_result
from system.sandbox import Access, Sandbox, SandboxError

logger = logging.getLogger(__name__)

_sandbox: Sandbox | None = None


def set_sandbox(s: Sandbox) -> None:
    global _sandbox
    _sandbox = s


def _s() -> Sandbox:
    if _sandbox is None:
        raise RuntimeError("Sandbox not initialized — call set_sandbox() first")
    return _sandbox


def _handle_list_uploads(args: Dict[str, Any]) -> str:
    """处理获取最晚上传文件的请求。"""
    n: int = args.get("n", 10)
    if not isinstance(n, int) or n < 1:
        return tool_error("n must be a positive integer", n=n)
    if n > 100:
        n = 100

    try:
        names: List[str] = _s().list_dir("ws:uploads/")
    except SandboxError as exc:
        # uploads 目录可能还不存在
        logger.info("uploads directory not available: %s", exc)
        return tool_result(files=[])

    entries: List[dict] = []
    for name in names:
        try:
            r = _s().resolve_read(f"ws:uploads/{name}")
            st = r.real.stat()
            entries.append({
                "filename": name,
                "size": st.st_size,
                "mtime": st.st_mtime,
                "path": f"ws:uploads/{name}",
            })
        except Exception as exc:
            logger.debug("skipping %s: %s", name, exc)
            continue

    # 按修改时间降序排列，取前 n 个
    entries.sort(key=lambda e: e["mtime"], reverse=True)
    top = entries[:n]

    # 格式化 mtime 为可读字符串
    import datetime
    for e in top:
        e["mtime"] = datetime.datetime.fromtimestamp(
            e["mtime"], tz=datetime.timezone.utc
        ).strftime("%Y-%m-%d %H:%M:%S UTC")

    return tool_result(files=top)


# ---------------------------------------------------------------------------
# 注册
# ---------------------------------------------------------------------------

registry.register(
    name="list_uploads",
    toolset="filesystem",
    schema={
        "description": "获取最晚上传的文件列表。返回每个文件的原始文件名、大小（字节）、修改时间和逻辑路径（ws:uploads/...）。",
        "parameters": {
            "type": "object",
            "properties": {
                "n": {
                    "type": "integer",
                    "description": "要返回的最新文件数量（默认 10，最大 100）。",
                    "default": 10,
                },
            },
        },
    },
    handler=_handle_list_uploads,
    emoji="📂",
    danger_level="readonly",
)