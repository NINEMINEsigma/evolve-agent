'''
最近上传文件扩展上下文 hook。

在每轮最新 UserMessage 末尾附加过去 5 分钟内上传的文件列表，
让 agent 自动感知用户刚上传的内容。

文件命名格式：
    <UTC时间戳>_<8位hash>_<原始文件名>
例如：
    20250617_123045_utc_a1b2c3d4_filename.ext
'''

import datetime
import json
import re
from pathlib import Path
from typing import * # type: ignore

from entity.constant import UPLOAD_FILENAME_TIME_FORMAT, UPLOAD_TIME_RE_PATTERN
from system.context import RuntimeContext

# 和 list_uploads 工具保持一致的正则与格式
_UPLOAD_TIME_RE = re.compile(UPLOAD_TIME_RE_PATTERN)
_RECENT_SECONDS = 300  # 5 分钟


def hook_tag_name(**kwargs) -> str:
    return "recent_uploads"


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


def hook_message(runtime_ctx: RuntimeContext, **kwargs) -> str:
    agentspace: Path = runtime_ctx.agentspace

    upload_dir = agentspace / "uploads"
    if not upload_dir.is_dir():
        return json.dumps({"recent_uploads": [], "reason": "uploads directory not found"})

    now = datetime.datetime.now(datetime.timezone.utc)
    recent: list[dict[str, Any]] = []

    for path in upload_dir.iterdir():
        if not path.is_file():
            continue
        upload_dt = _parse_upload_time(path.name)
        if upload_dt is None:
            # 回退到文件 mtime
            upload_dt = datetime.datetime.fromtimestamp(
                path.stat().st_mtime, tz=datetime.timezone.utc
            )

        age_seconds = (now - upload_dt).total_seconds()
        if age_seconds <= _RECENT_SECONDS:
            match = _UPLOAD_TIME_RE.match(path.name)
            original_name = match.group(2) if match else path.name
            recent.append({
                "filename": path.name,
                "original_name": original_name,
                "size": path.stat().st_size,
                "upload_time": upload_dt.strftime("%Y-%m-%d %H:%M:%S UTC"),
                "path": f"ws:uploads/{path.name}",
                "age_seconds": int(age_seconds),
            })

    if len(recent) == 0:
        return ""
    recent.sort(key=lambda e: e["age_seconds"])
    return json.dumps({
        "recent_uploads": recent,
        "window_seconds": _RECENT_SECONDS,
        "count": len(recent),
    }, ensure_ascii=False)
