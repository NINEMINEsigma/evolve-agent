"""Shell会话的纯数据类型。"""

from pydantic import BaseModel

from .resource_cleanup import CleanupReport


class ShellInfo(BaseModel):
    """Shell会话元数据快照。cleanup 为 None 表示未发起资源清理，不等于清理完成。"""

    shell_id: str
    pid: int | None = None
    session_id: str
    character_name: str
    shell_type: str
    cwd: str
    started_at: float
    last_activity_at: float
    running: bool
    exit_code: int | None = None
    termination: str | None = None
    cleanup: CleanupReport | None = None


class ShellStopResult(BaseModel):
    """显式停止结果。stopped 只能在 cleanup.complete 为 true 时为 true。"""

    stopped: bool
    shell: ShellInfo
    cleanup: CleanupReport


class ShellOutputSlice(BaseModel):
    """Shell会话规范化输出的绝对字符位置切片。"""

    shell_id: str
    content: str
    offset: int
    next_offset: int
    base_offset: int
    total_chars: int
    remaining_chars: int
    truncated: bool
    running: bool
    exit_code: int | None = None
    wait_reason: str
