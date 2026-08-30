from pydantic import BaseModel

# ---------------------------------------------------------------------------
# Cron Types
# ---------------------------------------------------------------------------

class CronTaskInfo(BaseModel):
    """定时任务信息（供 Handler 层与 API 层共用）。"""
    task_id: str
    name: str
    schedule_type: str
    schedule_value: str
    command: list[str]
    should_schedule: bool
    next_run: str | None = None  # ISO 格式时间戳，未调度时为 None
    run_count: int = 0
    last_run: str | None = None  # ISO 格式时间戳，从未执行时为 None
    log_path: str = ""


# ---------------------------------------------------------------------------
# Dynamic Endpoint Types
# ---------------------------------------------------------------------------

class DynamicEndpointInfo(BaseModel):
    """动态 HTTP 端点的注册记录（供内存注册表与磁盘持久化共用）。"""
    session_id: str
    agent_name: str
    name: str          # 即 URL 路径段，全局唯一 key
    created_at: float  # Unix 时间戳