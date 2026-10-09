"""Cron 任务实体与时间解析纯函数。

``_CronTask`` 从 ``component/extools/cron_tools.py`` 迁入，保持原有
JSON 字段、``PrivateAttr(_timer)`` 及实例方法。时间解析器为标准库
纯函数，不依赖任何运行时或 Application 状态。
"""

from __future__ import annotations

import datetime
import threading
from pydantic import BaseModel, ConfigDict, PrivateAttr


# ── cron 解析器（标准库实现，纯函数）──────────────────────────


def parse_cron_field(field: str, min_val: int, max_val: int) -> set[int]:
    """解析单个 cron 字段，返回允许值的集合。

    支持的语法::

        *        — 任意值
        */n      — 每 n 个单位
        a-b      — 范围
        a,b,c    — 列表
        a-b/n    — 范围内每 n 个单位
    """
    result: set[int] = set()
    for part in field.split(","):
        part = part.strip()
        if part == "*":
            result.update(range(min_val, max_val + 1))
        elif "/" in part:
            base, step_str = part.split("/", 1)
            step = int(step_str)
            if base == "*":
                start = min_val
            elif "-" in base:
                start = int(base.split("-")[0])
            else:
                start = int(base)
            result.update(range(start, max_val + 1, step))
        elif "-" in part:
            start, end = part.split("-", 1)
            result.update(range(int(start), int(end) + 1))
        else:
            result.add(int(part))
    return result


def match_cron(cron_expr: str, dt: datetime.datetime) -> bool:
    """检查给定时间是否匹配 5 字段 cron 表达式 ``分 时 日 月 周``。

    weekday 遵循标准 cron 语义：0=Sunday, 1=Monday, ..., 6=Saturday。
    """
    parts = cron_expr.split()
    if len(parts) != 5:
        raise ValueError(f"Cron expression must have 5 fields, got: {cron_expr}")

    minute_s, hour_s, day_s, month_s, weekday_s = parts

    if dt.minute not in parse_cron_field(minute_s, 0, 59):
        return False
    if dt.hour not in parse_cron_field(hour_s, 0, 23):
        return False
    if dt.day not in parse_cron_field(day_s, 1, 31):
        return False
    if dt.month not in parse_cron_field(month_s, 1, 12):
        return False

    # Python weekday: Monday=0 ... Sunday=6
    # Cron weekday:   Sunday=0 ... Saturday=6
    cron_wday = (dt.weekday() + 1) % 7
    if cron_wday not in parse_cron_field(weekday_s, 0, 6):
        return False

    return True


def next_cron_time(
    cron_expr: str,
    after: datetime.datetime | None = None,
) -> datetime.datetime:
    """计算给定 cron 表达式的下一个执行时间。

    从 *after* 之后的第一分钟开始逐分钟检查，返回最早匹配的时间。
    最多搜索一年，未找到时抛出 ValueError。
    """
    after = after or datetime.datetime.now()
    candidate = after.replace(second=0, microsecond=0) + datetime.timedelta(minutes=1)

    max_iter = 366 * 24 * 60
    for _ in range(max_iter):
        if match_cron(cron_expr, candidate):
            return candidate
        candidate += datetime.timedelta(minutes=1)

    raise ValueError(f"No next execution time found for cron expression: {cron_expr}")


# ── 任务数据结构 ───────────────────────────────────────────


class _CronTask(BaseModel):
    """定时任务实体。``_timer`` 为内部私有属性，不参与序列化。"""
    model_config = ConfigDict(arbitrary_types_allowed=True)

    task_id: str
    session_id: str
    name: str = ""
    schedule_type: str  # "interval" | "cron"
    schedule_value: str
    command: list[str] = []
    cwd: str = "ws:"
    should_schedule: bool = True  # 控制任务是否继续被 Timer 调度；False 时停止后续执行
    next_run: float = 0.0
    run_count: int = 0
    last_run: float = 0.0
    log_path: str = ""
    skip_agent_notify: bool = False  # 用户显式取消时设为 True，抑制在途执行完成后的通知
    is_wait: bool = False  # 为 True 时不执行任何脚本，仅返回固定提醒内容
    wait_message: str = ""  # wait 任务触发时返回的固定内容
    _timer: threading.Timer | None = PrivateAttr(default=None)

    def has_timer(self) -> bool:
        """返回任务是否关联了活跃 timer。"""
        return self._timer is not None

    def cancel_timer(self) -> None:
        """取消并清空当前 timer（幂等）。"""
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None

    def set_timer(self, timer: threading.Timer) -> None:
        """取消旧 timer 并设置、启动新 timer。"""
        self.cancel_timer()
        self._timer = timer
        self._timer.daemon = True
        self._timer.start()
