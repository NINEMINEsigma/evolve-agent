"""Shell会话的纯数据类型。"""

from pydantic import BaseModel


class ShellInfo(BaseModel):
    """Shell会话元数据快照。"""

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
