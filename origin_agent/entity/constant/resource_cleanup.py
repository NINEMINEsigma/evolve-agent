"""外部资源清理的进程内状态；不参与持久化或前端协议。"""

from enum import Enum


class CleanupState(str, Enum):
    """单个资源代际的清理状态；公开报告不暴露此枚举。"""

    RUNNING = "running"
    PENDING = "pending"
    QUARANTINED = "quarantined"
    RELEASED = "released"
    FAILED = "failed"
