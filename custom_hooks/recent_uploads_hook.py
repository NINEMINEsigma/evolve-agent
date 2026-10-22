'''
最近上传文件扩展上下文 hook。

在每轮最新 UserMessage 末尾附加过去 5 分钟内上传的文件列表，
让 agent 自动感知用户刚上传的内容。

文件命名格式（`UPLOAD_TIME_RE_PATTERN`）：
    <UTC时间戳>_<8位hash>_<原始文件名>
例如：
    20250617_123045_utc_a1b2c3d4_filename.ext

该正则只有两个捕获组：第 1 组是时间戳，第 2 组是原始文件名。

内部导入全部放在函数体内：hook 以 spec_from_file_location 动态加载，
模块级导入会在 sys.path 尚未注入 agent 根目录时导致整个文件加载失败。
'''

import datetime
import json
import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    # 仅在类型检查时导入：hook 以 spec_from_file_location 动态加载，
    # 模块级导入内部模块会在 sys.path 尚未注入 agent 根目录时让整个文件加载失败。
    from system.context import RuntimeContext

logger = logging.getLogger(__name__)

# 只注入该时间窗口内上传的文件（秒）
_RECENT_SECONDS = 300  # 5 分钟


def hook_tag_name(**kwargs) -> str:
    return "recent_uploads"


def _upload_time_pattern() -> re.Pattern[str]:
    from entity.constant import UPLOAD_TIME_RE_PATTERN
    return re.compile(UPLOAD_TIME_RE_PATTERN)


def _parse_upload_time(filename: str) -> datetime.datetime | None:
    """从文件名前缀解析 UTC 上传时间；解析失败返回 None。"""
    from entity.constant import UPLOAD_FILENAME_TIME_FORMAT
    match = _upload_time_pattern().match(filename)
    if not match:
        return None
    time_str = match.group(1)
    try:
        return datetime.datetime.strptime(
            time_str, UPLOAD_FILENAME_TIME_FORMAT
        ).replace(tzinfo=datetime.timezone.utc)
    except ValueError:
        return None


def hook_message(
    session_id: str = "",
    workspace: str = "",
    runtime_ctx: "RuntimeContext | None" = None,
    **kwargs,
) -> str:
    if runtime_ctx is None:
        return ""
    try:
        agentspace: Path = runtime_ctx.agentspace

        upload_dir = agentspace / "uploads"
        if not upload_dir.is_dir():
            return ""

        upload_re = _upload_time_pattern()
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
                # 常量正则 ^(<时间戳>)_[a-f0-9]{8}_(<原始文件名>)$ 只有两个分组：
                # 第 1 组是 UTC 时间戳，第 2 组是原始文件名（hash 未被捕获）。
                match = upload_re.match(path.name)
                original_name = match.group(2) if match else path.name
                recent.append({
                    "filename": path.name,
                    "original_name": original_name,
                    "size": path.stat().st_size,
                    "upload_time": upload_dt.strftime("%Y-%m-%d %H:%M:%S UTC"),
                    "path": f"ws:uploads/{path.name}",
                    "age_seconds": int(age_seconds),
                })

        if not recent:
            return ""
        recent.sort(key=lambda e: e["age_seconds"])
        return json.dumps({
            "recent_uploads": recent,
            "window_seconds": _RECENT_SECONDS,
            "count": len(recent),
        }, ensure_ascii=False)
    except Exception:
        logger.debug("recent_uploads_hook failed", exc_info=True)
        return ""
