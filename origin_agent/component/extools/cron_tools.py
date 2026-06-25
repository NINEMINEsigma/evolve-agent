"""Cron 定时任务工具 — 创建和管理单次执行的后台任务。

任务状态持久化到磁盘，后端重启后自动恢复并重新调度。
会话断开不会终止定时任务，任务在后台继续运行直到完成或被显式取消。

支持两种一次性调度格式：
  1. ``interval_seconds`` — 从现在起延迟指定秒数后执行一次，最小 CRON_MIN_INTERVAL_SECONDS 秒
  2. Cron 表达式 — 在下一个匹配 5 字段 ``分 时 日 月 周`` 的时间执行一次

Weekday 遵循标准 cron 语义：0=Sunday, 1=Monday, ..., 6=Saturday。

每个任务仅运行一次，执行后自动停止调度但保留记录。
需要循环、轮询或长期观察时，只安排下一次任务；等 [cron-result] 返回后再决定是否继续安排。
可通过 reschedule_cron_job 在 [cron-result] 返回后基于已有任务配置再次创建相同的新任务。

模块导入时通过 ``registry.register()`` 注册 6 个工具：
  - ``schedule_cron``       — 创建定时任务（仅执行一次）
  - ``list_cron_jobs``      — 列出当前会话的任务
  - ``cancel_cron_job``     — 取消指定任务
  - ``run_cron_job_now``    — 立即触发执行一次
  - ``reschedule_cron_job`` — 基于已有任务配置重新创建任务（参数不可修改）
  - ``wait_cron``           — 创建一个只等待、不执行脚本的精简定时提醒任务
"""

from __future__ import annotations

import datetime
import json
import logging
import subprocess  # nosec
import sys
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from abstract.tools.registry import registry, tool_error, tool_result
from entity.constant import CRON_STDOUT_PREVIEW_MAX_LENGTH, CRON_TASK_TIMEOUT, CRON_STORE_FILENAME, CRON_MIN_INTERVAL_SECONDS, CRON_MAX_JOBS_PER_SESSION
from system.subprocess_utils import build_subprocess_env, completed_process_from_bytes, windows_process_group_flags

logger = logging.getLogger(__name__)

# ── 持久化路径 ────────────────────────────────────────────────

def _get_cron_store_path() -> Path:
    """返回 cron 任务持久化文件路径。

    从 ``RuntimeContext.workspace`` 获取实际工作空间路径。
    RuntimeContext 未初始化时抛出 RuntimeError。
    """
    from system.context import get_runtime_context

    ctx = get_runtime_context()
    return ctx.workspace / CRON_STORE_FILENAME


# ── cron 解析器（标准库实现）──────────────────────────────────


def _parse_cron_field(field: str, min_val: int, max_val: int) -> Set[int]:
    """解析单个 cron 字段，返回允许值的集合。

    支持的语法::

        *        — 任意值
        */n      — 每 n 个单位
        a-b      — 范围
        a,b,c    — 列表
        a-b/n    — 范围内每 n 个单位
    """
    result: Set[int] = set()
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


def _match_cron(cron_expr: str, dt: datetime.datetime) -> bool:
    """检查给定时间是否匹配 5 字段 cron 表达式 ``分 时 日 月 周``。

    weekday 遵循标准 cron 语义：0=Sunday, 1=Monday, ..., 6=Saturday。
    """
    parts = cron_expr.split()
    if len(parts) != 5:
        raise ValueError(f"Cron expression must have 5 fields, got: {cron_expr}")

    minute_s, hour_s, day_s, month_s, weekday_s = parts

    if dt.minute not in _parse_cron_field(minute_s, 0, 59):
        return False
    if dt.hour not in _parse_cron_field(hour_s, 0, 23):
        return False
    if dt.day not in _parse_cron_field(day_s, 1, 31):
        return False
    if dt.month not in _parse_cron_field(month_s, 1, 12):
        return False

    # Python weekday: Monday=0 ... Sunday=6
    # Cron weekday:   Sunday=0 ... Saturday=6
    cron_wday = (dt.weekday() + 1) % 7
    if cron_wday not in _parse_cron_field(weekday_s, 0, 6):
        return False

    return True


def _next_cron_time(
    cron_expr: str,
    after: Optional[datetime.datetime] = None,
) -> datetime.datetime:
    """计算给定 cron 表达式的下一个执行时间。

    从 *after* 之后的第一分钟开始逐分钟检查，返回最早匹配的时间。
    最多搜索一年，未找到时抛出 ValueError。
    """
    after = after or datetime.datetime.now()
    candidate = after.replace(second=0, microsecond=0) + datetime.timedelta(minutes=1)

    max_iter = 366 * 24 * 60
    for _ in range(max_iter):
        if _match_cron(cron_expr, candidate):
            return candidate
        candidate += datetime.timedelta(minutes=1)

    raise ValueError(f"No next execution time found for cron expression: {cron_expr}")


# ── 任务数据结构 ───────────────────────────────────────────


@dataclass
class _CronTask:
    task_id: str
    session_id: str
    name: str
    schedule_type: str  # "interval" | "cron"
    schedule_value: str
    command: list[str]
    cwd: str
    should_schedule: bool = True  # 控制任务是否继续被 Timer 调度；False 时停止后续执行
    next_run: float = 0.0
    run_count: int = 0
    last_run: float = 0.0
    log_path: str = ""
    skip_agent_notify: bool = False  # 用户显式取消时设为 True，抑制在途执行完成后的通知
    is_wait: bool = False  # 为 True 时不执行任何脚本，仅返回固定提醒内容
    wait_message: str = ""  # wait 任务触发时返回的固定内容
    _timer: Optional[threading.Timer] = field(default=None, repr=False)


# ── 任务注册表 ──────────────────────────────────────────────

_cron_tasks: dict[str, dict[str, _CronTask]] = {}
_cron_lock: threading.RLock = threading.RLock()

# ── 事件回调 ──────────────────────────────────────────────────
# 由 gateway/server.py 注册，用于在任务执行完成后向前端推送结果。

_CronEventCallback = Any  # Callable[[str, str, str, int, str], None]
_cron_event_callbacks: list[_CronEventCallback] = []


def register_cron_event_callback(cb: _CronEventCallback) -> None:
    """注册一个回调，在定时任务执行完成后触发。

    回调签名::

        cb(session_id, task_id, name, exit_code, stdout_preview) -> None
    """
    _cron_event_callbacks.append(cb)


def _notify_cron_event(
    session_id: str,
    task_id: str,
    name: str,
    exit_code: int,
    stdout_preview: str,
) -> None:
    """通知所有已注册的 cron 事件回调。"""
    for cb in _cron_event_callbacks:
        try:
            cb(session_id, task_id, name, exit_code, stdout_preview)
        except Exception as exc:
            logger.debug("Cron event callback error: %s", exc)


# ── 持久化辅助 ───────────────────────────────────────────────


def _task_to_dict(task: _CronTask) -> dict:
    """将 _CronTask 序列化为字典（不含 _timer）。"""
    return {
        "task_id": task.task_id,
        "session_id": task.session_id,
        "name": task.name,
        "schedule_type": task.schedule_type,
        "schedule_value": task.schedule_value,
        "command": task.command,
        "cwd": task.cwd,
        "should_schedule": task.should_schedule,
        "next_run": task.next_run,
        "run_count": task.run_count,
        "last_run": task.last_run,
        "log_path": task.log_path,
        "skip_agent_notify": task.skip_agent_notify,
        "is_wait": task.is_wait,
        "wait_message": task.wait_message,
    }


def _task_from_dict(data: dict) -> _CronTask:
    """从字典反序列化为 _CronTask。"""
    return _CronTask(
        task_id=data["task_id"],
        session_id=data["session_id"],
        name=data.get("name", ""),
        schedule_type=data["schedule_type"],
        schedule_value=data["schedule_value"],
        command=list(data.get("command", [])),
        cwd=data.get("cwd", "ws:"),
        should_schedule=data.get("should_schedule", True),
        next_run=float(data.get("next_run", 0.0)),
        run_count=int(data.get("run_count", 0)),
        last_run=float(data.get("last_run", 0.0)),
        log_path=data.get("log_path", ""),
        skip_agent_notify=data.get("skip_agent_notify", False),
        is_wait=data.get("is_wait", False),
        wait_message=data.get("wait_message", ""),
    )


def _save_all_tasks() -> None:
    """将所有任务状态持久化到磁盘（原子写入，避免半写损坏）。"""
    try:
        store_path = _get_cron_store_path()
        store_path.parent.mkdir(parents=True, exist_ok=True)
        with _cron_lock:
            payload: dict[str, dict[str, dict]] = {}
            for sid, tasks in _cron_tasks.items():
                payload[sid] = {}
                for tid, task in tasks.items():
                    payload[sid][tid] = _task_to_dict(task)
        # 原子写入：先写临时文件再重命名，防止进程崩溃时留下半写文件
        tmp_path = store_path.with_suffix(".tmp")
        tmp_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        tmp_path.replace(store_path)
    except Exception as exc:
        logger.warning("Failed to save cron jobs: %s", exc)


def _load_all_tasks() -> None:
    """从磁盘加载任务状态并重新调度。"""
    try:
        store_path = _get_cron_store_path()
    except RuntimeError:
        return
    if not store_path.exists():
        return
    try:
        raw: dict = json.loads(store_path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("Failed to load cron jobs: %s", exc)
        return

    restored = 0
    for sid, tasks in raw.items():
        for tid, data in tasks.items():
            try:
                task = _task_from_dict(data)
                with _cron_lock:
                    if sid not in _cron_tasks:
                        _cron_tasks[sid] = {}
                    _cron_tasks[sid][tid] = task
                if task.should_schedule:
                    # 重新计算 next_run
                    _restore_and_schedule_task(task)
                    restored += 1
            except Exception as exc:
                logger.warning("Failed to restore cron job %s: %s", tid, exc)

    if restored:
        logger.info("Restored and rescheduled %d cron jobs from disk", restored)


def _restore_and_schedule_task(task: _CronTask) -> None:
    """进程重启后恢复任务：校正 next_run 并启动 Timer。"""
    now = time.time()

    if task.schedule_type == "interval":
        interval = float(task.schedule_value)
        if task.next_run <= now:
            # 进程终止期间错过了执行时间：从当前时间重新开始
            task.next_run = now + interval
    else:  # cron
        try:
            next_dt = _next_cron_time(task.schedule_value)
            task.next_run = next_dt.timestamp()
        except Exception as exc:
            logger.error(
                "Failed to calculate next run for restored cron task %s: %s",
                task.task_id, exc,
            )
            task.should_schedule = False
            return

    _schedule_next(task)


# ── 公开 API：会话清理 ──────────────────────────────────────


def cleanup_session_cron_jobs(session_id: str) -> int:
    """清理指定会话的所有定时任务。返回清理的任务数量。

    注意：此函数不再由 WebSocket 断开自动调用。
    仅在需要显式清理某个会话的所有任务时使用。
    """
    with _cron_lock:
        session_tasks = _cron_tasks.pop(session_id, {})

    count = 0
    for task in session_tasks.values():
        task.should_schedule = False
        if task._timer:
            task._timer.cancel()
            task._timer = None
        count += 1

    if count:
        logger.info("Cleaned up %d cron jobs for session=%s", count, session_id)
        _save_all_tasks()
    return count


def migrate_session_cron_jobs(old_sid: str, new_sid: str) -> int:
    """将旧会话的定时任务整体迁移到新会话。

    更新每个任务的 session_id，取消旧 timer 并用新 session_id 重新调度。
    返回迁移的任务数量。
    """
    with _cron_lock:
        session_tasks = _cron_tasks.pop(old_sid, {})
        if not session_tasks:
            return 0
        _cron_tasks[new_sid] = session_tasks

    count = 0
    for task in session_tasks.values():
        task.session_id = new_sid
        if task._timer:
            task._timer.cancel()
            task._timer = None
        _schedule_next(task)
        count += 1

    if count:
        logger.info(
            "Migrated %d cron jobs from session=%s to session=%s",
            count, old_sid, new_sid,
        )
        _save_all_tasks()
    return count


# ── 路径解析辅助 ──────────────────────────────────────────────


def _resolve_cwd(cwd: str) -> str:
    """将逻辑路径解析为真实文件系统路径，失败时回退到当前工作目录。"""
    from component.tools.filesystem import _s as _get_sandbox
    from system.sandbox import Access

    try:
        r = _get_sandbox().resolve(cwd, Access.READ)
        return str(r.real)
    except Exception:
        return str(Path.cwd())


def _resolve_log_path(log_path: str) -> str | None:
    """将日志逻辑路径解析为真实文件系统路径。"""
    from component.tools.filesystem import _s as _get_sandbox
    from system.sandbox import Access

    try:
        r = _get_sandbox().resolve(log_path, Access.WRITE)
        return str(r.real)
    except Exception:
        return None


# ── 调度器 ──────────────────────────────────────────────────


def _schedule_next(task: _CronTask) -> None:
    """计算并安排任务的下次执行（Timer 一次性触发）。"""
    with _cron_lock:
        if not task.should_schedule:
            return

        # 取消旧的 timer（如果有）
        if task._timer is not None:
            task._timer.cancel()
            task._timer = None

        now = time.time()

        if task.schedule_type == "interval":
            interval = float(task.schedule_value)
            task.next_run = now + interval
        else:  # cron
            try:
                next_dt = _next_cron_time(task.schedule_value)
                task.next_run = next_dt.timestamp()
            except Exception as exc:
                logger.error(
                    "Failed to calculate next run for cron task %s: %s",
                    task.task_id, exc,
                )
                task.should_schedule = False
                return

        delay = max(0.1, task.next_run - now)
        task._timer = threading.Timer(
            delay, _run_task_wrapper, args=[task.task_id, task.session_id],
        )
        task._timer.daemon = True
        task._timer.start()


def _run_task_wrapper(task_id: str, session_id: str) -> None:
    """Timer 回调包装：在持有锁的情况下查找任务，然后执行。"""
    with _cron_lock:
        session_tasks = _cron_tasks.get(session_id)
        if not session_tasks:
            return
        task = session_tasks.get(task_id)
        if not task or not task.should_schedule:
            return

    _run_task(task)


def _run_task(task: _CronTask) -> None:
    """在后台线程中执行定时任务命令并记录日志。"""
    if not task.should_schedule:
        return

    task.last_run = time.time()

    cwd_real = _resolve_cwd(task.cwd)
    log_file: str | None = None
    if task.log_path:
        log_file = _resolve_log_path(task.log_path)
        if log_file:
            Path(log_file).parent.mkdir(parents=True, exist_ok=True)

    exit_code = -1
    stdout_text = ""

    if task.is_wait:
        exit_code = 0
        stdout_text = task.wait_message or "Wait time is up."
        logger.info(
            "Wait task triggered | task=%s name=%s session=%s",
            task.task_id, task.name, task.session_id,
        )
    else:
        try:
            popen_kwargs: dict[str, Any] = {
                "cwd": cwd_real,
                "stdout": subprocess.PIPE,
                "stderr": subprocess.STDOUT,
                "text": False,
                "env": build_subprocess_env(),
            }
            if sys.platform == "win32":
                popen_kwargs["creationflags"] = windows_process_group_flags()

            result = subprocess.run(task.command, timeout=CRON_TASK_TIMEOUT, **popen_kwargs)
            decoded = completed_process_from_bytes(
                args=task.command,
                returncode=result.returncode,
                stdout=result.stdout,
                stderr=None,
            )
            exit_code = decoded.returncode
            stdout_text = decoded.stdout or ""

            logger.info(
                "Cron task executed | task=%s name=%s session=%s exit=%d",
                task.task_id, task.name, task.session_id, exit_code,
            )
        except subprocess.TimeoutExpired:
            logger.warning(
                "Cron task timed out | task=%s session=%s",
                task.task_id, task.session_id,
            )
            stdout_text = f"[TIMEOUT after {CRON_TASK_TIMEOUT}s]"
        except Exception as exc:
            logger.exception(
                "Cron task failed | task=%s session=%s",
                task.task_id, task.session_id,
            )
            stdout_text = f"[ERROR: {exc}]"

    # 执行完成后递增计数并停止调度（每个任务仅运行一次）
    task.run_count += 1
    task.should_schedule = False

    # 写日志
    if log_file:
        try:
            timestamp = datetime.datetime.now().isoformat()
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(f"\n{'=' * 60}\n")
                f.write(f"[{timestamp}] Run #{task.run_count} | Exit: {exit_code}\n")
                if not task.is_wait:
                    f.write(f"Command: {' '.join(task.command)}\n")
                f.write(f"Stdout:\n")
                f.write(stdout_text)
        except Exception as exc:
            logger.warning("Failed to write cron log: %s", exc)

    # 重新调度（如果仍应继续）并持久化
    if task.should_schedule:
        _schedule_next(task)
    _save_all_tasks()

    # 被用户取消的任务不发送通知（已在执行的子进程无法中止，但结果无需告知 Agent）
    if not task.skip_agent_notify:
        _notify_cron_event(
            task.session_id,
            task.task_id,
            task.name,
            exit_code,
            f"task output is too long, you can view the full output in the log file: {task.log_path}" if len(stdout_text) > CRON_STDOUT_PREVIEW_MAX_LENGTH else stdout_text,
        )


# ── 工具 handler ─────────────────────────────────────────────


async def _handle_schedule_cron(args: dict[str, Any]) -> dict:
    """创建新的定时任务。"""
    raw_schedule: str = str(args.get("schedule", "")).strip()
    raw_command: Any = args.get("command")
    reason: str = str(args.get("reason", "")).strip()
    name: str = str(args.get("name", "")).strip()
    cwd: str = str(args.get("cwd", "ws:")).strip()
    session_id: str = str(args.get("_session_id", ""))

    # ── 参数校验 ──
    if not raw_schedule:
        return tool_error("'schedule' is required")
    if not raw_command or not isinstance(raw_command, list):
        return tool_error("'command' must be a non-empty list of strings")
    cmd_parts: list[str] = [str(p) for p in raw_command]
    if not cmd_parts:
        return tool_error("'command' must be a non-empty list")

    # ── 解析 schedule 类型 ──
    schedule_type: str
    schedule_value: str
    interval_sec: float = 0.0

    if raw_schedule.isdigit():
        schedule_type = "interval"
        schedule_value = raw_schedule
        interval_sec = int(raw_schedule)
        if interval_sec < CRON_MIN_INTERVAL_SECONDS:
            return tool_error(f"Interval must be at least {CRON_MIN_INTERVAL_SECONDS} seconds")
    else:
        schedule_type = "cron"
        schedule_value = raw_schedule
        parts = raw_schedule.split()
        if len(parts) != 5:
            return tool_error(
                "Cron expression must have 5 fields: min hour day month weekday"
            )
        try:
            _next_cron_time(raw_schedule)
        except ValueError as exc:
            return tool_error(f"Invalid cron expression: {exc}")

    # ── 任务数量限制 ──
    with _cron_lock:
        current_count = len(_cron_tasks.get(session_id, {}))
    if current_count >= CRON_MAX_JOBS_PER_SESSION:
        return tool_error(
            f"Maximum {CRON_MAX_JOBS_PER_SESSION} cron jobs per session reached"
        )

    # 审批由 AgentLoop 统一入口处理（handler 内不再重复确认）
    # ── 创建任务 ──
    task_id: str = uuid.uuid4().hex[:12]
    log_path = f"ws:logs/cron/{session_id}/{task_id}.log"

    task = _CronTask(
        task_id=task_id,
        session_id=session_id,
        name=name or f"cron-{task_id}",
        schedule_type=schedule_type,
        schedule_value=schedule_value,
        command=cmd_parts,
        cwd=cwd,
        should_schedule=True,
        log_path=log_path,
    )

    with _cron_lock:
        if session_id not in _cron_tasks:
            _cron_tasks[session_id] = {}
        _cron_tasks[session_id][task_id] = task

    # 计算首次执行时间并启动调度
    if schedule_type == "interval":
        task.next_run = time.time() + interval_sec
    else:
        next_dt = _next_cron_time(schedule_value)
        task.next_run = next_dt.timestamp()

    _schedule_next(task)
    _save_all_tasks()

    logger.info(
        "Cron job scheduled | task=%s session=%s schedule=%s command=%s",
        task_id, session_id, raw_schedule, " ".join(cmd_parts),
    )

    return tool_result(
        success=True,
        task_id=task_id,
        name=task.name,
        schedule_type=schedule_type,
        schedule_value=schedule_value,
        next_run=datetime.datetime.fromtimestamp(
            task.next_run, tz=datetime.timezone.utc,
        ).isoformat(),
        log_path=log_path,
        message=(
            f"One-shot cron job scheduled (task_id={task_id}, "
            f"next_run={datetime.datetime.fromtimestamp(task.next_run, tz=datetime.timezone.utc).isoformat()}). "
            "After it finishes, a [cron-result] message will wake the Agent. "
            "If the task must continue, schedule only the next run then."
        ),
    )


async def _handle_list_cron_jobs(args: dict[str, Any]) -> dict:
    """列出当前会话的所有定时任务。"""
    session_id: str = str(args.get("_session_id", ""))

    with _cron_lock:
        session_tasks = _cron_tasks.get(session_id, {})
        tasks: list[dict] = []
        for task in session_tasks.values():
            tasks.append(
                {
                    "task_id": task.task_id,
                    "name": task.name,
                    "schedule_type": task.schedule_type,
                    "schedule_value": task.schedule_value,
                    "command": task.command,
                    "should_schedule": task.should_schedule,
                    "next_run": (
                        datetime.datetime.fromtimestamp(
                            task.next_run, tz=datetime.timezone.utc,
                        ).isoformat()
                        if task.next_run
                        else None
                    ),
                    "run_count": task.run_count,
                    "last_run": (
                        datetime.datetime.fromtimestamp(
                            task.last_run, tz=datetime.timezone.utc,
                        ).isoformat()
                        if task.last_run
                        else None
                    ),
                    "log_path": task.log_path,
                }
            )

    return tool_result(
        success=True,
        count=len(tasks),
        tasks=tasks,
    )


async def _handle_cancel_cron_job(args: dict[str, Any]) -> dict:
    """取消指定定时任务。"""
    task_id: str = str(args.get("task_id", "")).strip()
    session_id: str = str(args.get("_session_id", ""))

    if not task_id:
        return tool_error("'task_id' is required")

    with _cron_lock:
        session_tasks = _cron_tasks.get(session_id, {})
        task = session_tasks.pop(task_id, None)

    if not task:
        return tool_error(f"Task not found: {task_id}")

    task.should_schedule = False
    task.skip_agent_notify = True
    if task._timer:
        task._timer.cancel()
        task._timer = None

    _save_all_tasks()

    logger.info(
        "Cron job cancelled | task=%s session=%s", task_id, session_id,
    )

    return tool_result(
        success=True,
        task_id=task_id,
        name=task.name,
        message=f"Cancelled cron job: {task.name or task_id}",
    )


async def _handle_run_cron_job_now(args: dict[str, Any]) -> dict:
    """立即触发指定任务执行一次（不影响正常调度）。"""
    task_id: str = str(args.get("task_id", "")).strip()
    session_id: str = str(args.get("_session_id", ""))

    if not task_id:
        return tool_error("'task_id' is required")

    with _cron_lock:
        task = _cron_tasks.get(session_id, {}).get(task_id)

    if not task:
        return tool_error(f"Task not found: {task_id}")

    # 取消当前 timer，避免冲突
    if task._timer:
        task._timer.cancel()
        task._timer = None

    # 在新线程中立即执行
    t = threading.Thread(target=_run_task, args=[task], daemon=True)
    t.start()

    logger.info(
        "Cron job triggered manually | task=%s session=%s",
        task_id, session_id,
    )

    return tool_result(
        success=True,
        task_id=task_id,
        name=task.name,
        message=f"Triggered immediate execution of cron job: {task.name or task_id}",
    )


async def _handle_reschedule_cron_job(args: dict[str, Any]) -> dict:
    """基于已有任务配置重新创建并调度一个新任务（所有参数不可修改）。"""
    task_id: str = str(args.get("task_id", "")).strip()
    session_id: str = str(args.get("_session_id", ""))

    if not task_id:
        return tool_error("'task_id' is required")

    with _cron_lock:
        source_task = _cron_tasks.get(session_id, {}).get(task_id)

    if not source_task:
        return tool_error(f"Task not found: {task_id}")

    # ── 任务数量限制 ──
    with _cron_lock:
        current_count = len(_cron_tasks.get(session_id, {}))
    if current_count >= CRON_MAX_JOBS_PER_SESSION:
        return tool_error(
            f"Maximum {CRON_MAX_JOBS_PER_SESSION} cron jobs per session reached"
        )

    # 审批由 AgentLoop 统一入口处理（handler 内不再重复确认）
    # ── 创建新任务，完全复制原配置（不可修改任何参数）──
    new_task_id: str = uuid.uuid4().hex[:12]
    log_path = f"ws:logs/cron/{session_id}/{new_task_id}.log"

    new_task = _CronTask(
        task_id=new_task_id,
        session_id=session_id,
        name=source_task.name,
        schedule_type=source_task.schedule_type,
        schedule_value=source_task.schedule_value,
        command=list(source_task.command),  # 深拷贝命令列表
        cwd=source_task.cwd,
        should_schedule=True,
        log_path=log_path,
    )

    with _cron_lock:
        if session_id not in _cron_tasks:
            _cron_tasks[session_id] = {}
        _cron_tasks[session_id][new_task_id] = new_task

    # 计算首次执行时间并启动调度
    if new_task.schedule_type == "interval":
        new_task.next_run = time.time() + float(new_task.schedule_value)
    else:
        next_dt = _next_cron_time(new_task.schedule_value)
        new_task.next_run = next_dt.timestamp()

    _schedule_next(new_task)
    _save_all_tasks()

    logger.info(
        "Cron job rescheduled | old_task=%s new_task=%s session=%s schedule=%s",
        task_id, new_task_id, session_id, new_task.schedule_value,
    )

    return tool_result(
        success=True,
        task_id=new_task_id,
        name=new_task.name,
        schedule_type=new_task.schedule_type,
        schedule_value=new_task.schedule_value,
        next_run=datetime.datetime.fromtimestamp(
            new_task.next_run, tz=datetime.timezone.utc,
        ).isoformat(),
        log_path=log_path,
        message=(
            f"Rescheduled cron job (new task_id={new_task_id}, "
            f"next_run={datetime.datetime.fromtimestamp(new_task.next_run, tz=datetime.timezone.utc).isoformat()})"
        ),
    )


async def _handle_wait_cron(args: dict[str, Any]) -> dict:
    """创建一个只等待、不执行任何脚本的精简定时提醒任务。"""
    raw_duration: str = str(args.get("duration", "")).strip()
    message: str = str(args.get("message", "Wait time is up.")).strip()
    session_id: str = str(args.get("_session_id", ""))

    if not raw_duration or not raw_duration.isdigit():
        return tool_error("'duration' is required and must be a positive integer (seconds)")

    duration_sec = int(raw_duration)
    if duration_sec < CRON_MIN_INTERVAL_SECONDS:
        return tool_error(f"Duration must be at least {CRON_MIN_INTERVAL_SECONDS} seconds")

    # ── 同一会话只保留一个 wait 任务 ──
    with _cron_lock:
        session_tasks = _cron_tasks.get(session_id)
        if session_tasks:
            for tid, existing in list(session_tasks.items()):
                if existing.is_wait:
                    existing.should_schedule = False
                    if existing._timer:
                        existing._timer.cancel()
                        existing._timer = None
                    session_tasks.pop(tid, None)
                    logger.info("Replaced previous wait task | old_task=%s session=%s", tid, session_id)

    # ── 任务数量限制 ──
    with _cron_lock:
        current_count = len(_cron_tasks.get(session_id, {}))
    if current_count >= CRON_MAX_JOBS_PER_SESSION:
        return tool_error(
            f"Maximum {CRON_MAX_JOBS_PER_SESSION} cron jobs per session reached"
        )

    task_id: str = uuid.uuid4().hex[:12]
    log_path = f"ws:logs/cron/{session_id}/{task_id}.log"

    task = _CronTask(
        task_id=task_id,
        session_id=session_id,
        name="wait",
        schedule_type="interval",
        schedule_value=str(duration_sec),
        command=[],
        cwd="ws:",
        should_schedule=True,
        log_path=log_path,
        is_wait=True,
        wait_message=message,
    )

    with _cron_lock:
        if session_id not in _cron_tasks:
            _cron_tasks[session_id] = {}
        _cron_tasks[session_id][task_id] = task

    task.next_run = time.time() + duration_sec
    _schedule_next(task)
    _save_all_tasks()

    logger.info(
        "Wait cron scheduled | task=%s session=%s duration=%ds",
        task_id, session_id, duration_sec,
    )

    return tool_result(
        success=True,
        task_id=task_id,
        duration=duration_sec,
        next_run=datetime.datetime.fromtimestamp(
            task.next_run, tz=datetime.timezone.utc,
        ).isoformat(),
        message=(
            f"Wait task scheduled (task_id={task_id}, "
            f"duration={duration_sec}s, "
            f"next_run={datetime.datetime.fromtimestamp(task.next_run, tz=datetime.timezone.utc).isoformat()}). "
            "A [cron-result] message will be sent when the wait completes."
        ),
    )


# ── 公开 API（供 gateway/server.py 调用）────────────────────

def list_cron_tasks_for_session(session_id: str) -> list[dict[str, Any]]:
    """返回指定会话的所有定时任务。"""
    with _cron_lock:
        session_tasks = _cron_tasks.get(session_id, {})
        tasks: list[dict[str, Any]] = []
        for task in session_tasks.values():
            tasks.append(
                {
                    "task_id": task.task_id,
                    "name": task.name,
                    "schedule_type": task.schedule_type,
                    "schedule_value": task.schedule_value,
                    "command": task.command,
                    "should_schedule": task.should_schedule,
                    "next_run": (
                        datetime.datetime.fromtimestamp(
                            task.next_run, tz=datetime.timezone.utc,
                        ).isoformat()
                        if task.next_run
                        else None
                    ),
                    "run_count": task.run_count,
                    "last_run": (
                        datetime.datetime.fromtimestamp(
                            task.last_run, tz=datetime.timezone.utc,
                        ).isoformat()
                        if task.last_run
                        else None
                    ),
                    "log_path": task.log_path,
                }
            )
    return tasks


def trigger_cron_task(session_id: str, task_id: str) -> dict[str, Any]:
    """立即触发指定定时任务执行一次。"""
    with _cron_lock:
        task = _cron_tasks.get(session_id, {}).get(task_id)
    if not task:
        return {"success": False, "message": f"Task not found: {task_id}"}
    if task._timer:
        task._timer.cancel()
        task._timer = None
    t = threading.Thread(target=_run_task, args=[task], daemon=True)
    t.start()
    logger.info("Cron job triggered manually via API | task=%s session=%s", task_id, session_id)
    return {"success": True, "task_id": task_id, "name": task.name, "message": f"Triggered: {task.name or task_id}"}


def cancel_cron_task(session_id: str, task_id: str) -> dict[str, Any]:
    """取消指定定时任务。"""
    with _cron_lock:
        session_tasks = _cron_tasks.get(session_id, {})
        task = session_tasks.pop(task_id, None)
    if not task:
        return {"success": False, "message": f"Task not found: {task_id}"}
    task.should_schedule = False
    task.skip_agent_notify = True
    if task._timer:
        task._timer.cancel()
        task._timer = None
    _save_all_tasks()
    logger.info("Cron job cancelled via API | task=%s session=%s", task_id, session_id)
    return {"success": True, "task_id": task_id, "name": task.name, "message": f"Cancelled: {task.name or task_id}"}


# ── 注册 ─────────────────────────────────────────────────────

registry.register(
    name="schedule_cron",
    toolset="cron",
    schema={
        # 创建一个一次性后台定时任务。
        #
        # ## 前置条件
        # schedule 必须为纯数字秒数或合法的 5 字段 cron 表达式。
        # command 必须为非空字符串列表。
        # 必须提供 reason 说明创建原因。
        # 同一会话任务数不能超过 CRON_MAX_JOBS_PER_SESSION。
        #
        # ## 调用效果
        # 安排任务在未来某个时间点执行一次，执行完成后通过 [cron-result] 消息通知 Agent。
        # 这是非阻塞调用：调用后立即返回，任务在后台运行。
        # 循环、轮询或长期观察场景下，应等待 [cron-result] 后再安排下一次，不要预创建多个未来任务。
        #
        # ## 返回
        # ```json
        # {"success": true, "task_id": "...", "name": "...", "schedule_type": "interval", "schedule_value": "300", "next_run": "...", "log_path": "ws:logs/cron/.../....log", "message": "..."}
        # ```
        #
        # ## 何时使用
        # - 需要延迟执行某个命令。
        # - 需要在指定 cron 时间执行一次任务。
        # - 需要轮询时：每次只安排下一次，收到结果后再决定是否继续。
        #
        # ## 副作用/注意
        # - 任务在后台运行，可能产生文件系统或网络副作用，danger_level 为 dangerous。
        # - 每次调用需要用户审批。
        # - 任务执行日志写入 log_path。
        # - 任务执行后自动停止调度，但记录保留。
        "description": """Schedule a one-shot background task.

## Prerequisites
schedule must be either a plain number of seconds or a valid 5-field cron expression. command must be a non-empty list of strings. A reason explaining why the task is needed must be provided. The number of cron jobs per session cannot exceed CRON_MAX_JOBS_PER_SESSION.

## Effect
Schedules the task to run once at a future time. After execution, a [cron-result] message notifies the Agent. This call is NON-BLOCKING: it returns immediately while the task runs in the background. For loops, polling, or long-running observation, schedule only the next run and wait for the [cron-result] before deciding whether to schedule again.

## Returns
```json
{"success": true, "task_id": "...", "name": "...", "schedule_type": "interval", "schedule_value": "300", "next_run": "...", "log_path": "ws:logs/cron/.../....log", "message": "..."}
```

## When to Use
- Delay execution of a command.
- Run a task once at a specific cron time.
- Polling: schedule only the next run, then decide after receiving the result.

## Side Effects / Notes
- Tasks run in the background and may cause filesystem or network side effects; danger_level is dangerous.
- Each invocation requires user approval.
- Execution logs are written to log_path.
- The task stops scheduling automatically after it runs, but its record remains.""",
        "parameters": {
            "type": "object",
            "properties": {
                "schedule": {
                    "type": "string",
                    # 一次性调度说明：延迟秒数，或用于计算下一个匹配时间的 5 字段 cron 表达式。
                    "description": """One-shot schedule. Either a number of seconds to delay, or a 5-field cron expression 'min hour day month weekday'. Examples: '60' = run once after 60 seconds; '0 9 * * 1' = run once at next Monday 9:00 AM. Weekday: 0=Sunday.""",
                },
                "command": {
                    "type": "array",
                    "items": {"type": "string"},
                    # 要执行的命令及参数列表。
                    "description": """Command and arguments to execute, e.g. ['python', '-c', 'print(1)'].""",
                },
                "reason": {
                    "type": "string",
                    # 创建此定时任务的原因。
                    "description": """Reason for creating this scheduled task.""",
                },
                "name": {
                    "type": "string",
                    # 可选的人类可读任务名称。
                    "description": """Optional human-readable name for the task.""",
                },
                "cwd": {
                    "type": "string",
                    # 工作目录（ws: 命名空间，默认 'ws:'）。
                    "description": """Working directory (ws: namespace, default 'ws:').""",
                    "default": "ws:",
                },
            },
            "required": ["schedule", "command", "reason"],
        },
    },
    handler=_handle_schedule_cron,
    is_async=True,
    emoji="⏰",
    danger_level="dangerous",
)

registry.register(
    name="list_cron_jobs",
    toolset="cron",
    schema={
        # 列出当前会话的所有定时任务。
        #
        # ## 前置条件
        # 无。
        #
        # ## 调用效果
        # 返回当前会话中所有 cron 任务的元数据，包括调度信息、下次执行时间、执行次数、日志路径等。
        #
        # ## 返回
        # ```json
        # {"success": true, "count": 2, "tasks": [{"task_id": "...", "name": "...", "schedule_type": "interval", "schedule_value": "300", "command": ["..."], "should_schedule": true, "next_run": "...", "run_count": 0, "last_run": null, "log_path": "..."}]}
        # ```
        #
        # ## 何时使用
        # - 查看当前有哪些定时任务。
        # - 获取 task_id 以便取消或立即触发任务。
        #
        # ## 副作用/注意
        # - 纯查询，不会修改任务状态。
        "description": """List all scheduled cron jobs for the current session.

## Prerequisites
None.

## Effect
Returns metadata for all cron jobs in the current session, including schedule info, next run time, run count, and log path.

## Returns
```json
{"success": true, "count": 2, "tasks": [{"task_id": "...", "name": "...", "schedule_type": "interval", "schedule_value": "300", "command": ["..."], "should_schedule": true, "next_run": "...", "run_count": 0, "last_run": null, "log_path": "..."}]}
```

## When to Use
- Check what cron jobs are currently scheduled.
- Obtain task_id values for cancel_cron_job or run_cron_job_now.

## Side Effects / Notes
- Read-only query; does not modify task state.""",
        "parameters": {
            "type": "object",
            "properties": {},
        },
    },
    handler=_handle_list_cron_jobs,
    is_async=True,
    emoji="📋",
    danger_level="readonly",
)

registry.register(
    name="cancel_cron_job",
    toolset="cron",
    schema={
        # 取消指定 task_id 的定时任务。
        #
        # ## 前置条件
        # task_id 必须存在且属于当前会话。
        #
        # ## 调用效果
        # 停止该任务的后续调度，移除记录，并抑制在途执行完成后的通知。
        # 已经启动的子进程不会被强行终止。
        #
        # ## 返回
        # ```json
        # {"success": true, "task_id": "...", "name": "...", "message": "Cancelled cron job: ..."}
        # ```
        #
        # ## 何时使用
        # - 不再需要某个延迟/定时任务时。
        # - 停止轮询或等待提醒。
        #
        # ## 副作用/注意
        # - 已在运行的子进程不会被终止。
        # - 取消后该 task_id 失效。
        "description": """Cancel and remove a scheduled cron job by its task_id.

## Prerequisites
task_id must exist and belong to the current session.

## Effect
Stops future scheduling for the task, removes its record, and suppresses notifications if an in-flight execution completes later. Any already-started subprocess is not forcibly terminated.

## Returns
```json
{"success": true, "task_id": "...", "name": "...", "message": "Cancelled cron job: ..."}
```

## When to Use
- When a delayed or scheduled task is no longer needed.
- Stop polling or wait reminders.

## Side Effects / Notes
- A subprocess that has already started is not terminated.
- The task_id becomes invalid after cancellation.""",
        "parameters": {
            "type": "object",
            "properties": {
                "task_id": {
                    "type": "string",
                    # schedule_cron 返回的任务标识。
                    "description": """task_id returned by schedule_cron.""",
                },
            },
            "required": ["task_id"],
        },
    },
    handler=_handle_cancel_cron_job,
    is_async=True,
    emoji="🗑",
    danger_level="readonly",
)

registry.register(
    name="run_cron_job_now",
    toolset="cron",
    schema={
        # 立即触发指定定时任务执行一次。
        #
        # ## 前置条件
        # task_id 必须存在且属于当前会话。
        #
        # ## 调用效果
        # 在新线程中立即执行任务一次，不影响原定调度（interval 类型会重置 timer）。
        # 执行完成后仍会通过 [cron-result] 通知。
        #
        # ## 返回
        # ```json
        # {"success": true, "task_id": "...", "name": "...", "message": "Triggered immediate execution of cron job: ..."}
        # ```
        #
        # ## 何时使用
        # - 需要立刻验证任务行为。
        # - 不想等待原定调度时间时。
        #
        # ## 副作用/注意
        # - 会实际执行 command，可能产生副作用。
        # - interval 类型的原定下次执行时间会基于当前时间重新计算。
        "description": """Immediately trigger a one-time execution of a scheduled cron job.

## Prerequisites
task_id must exist and belong to the current session.

## Effect
Runs the task once immediately in a new thread. The regular schedule is not affected (for interval scheduling, the timer is reset from now). A [cron-result] notification is still sent after execution.

## Returns
```json
{"success": true, "task_id": "...", "name": "...", "message": "Triggered immediate execution of cron job: ..."}
```

## When to Use
- Verify task behavior immediately.
- Avoid waiting for the originally scheduled time.

## Side Effects / Notes
- Actually executes the command and may produce side effects.
- For interval tasks, the next scheduled time is recalculated from the current time.""",
        "parameters": {
            "type": "object",
            "properties": {
                "task_id": {
                    "type": "string",
                    # schedule_cron 返回的任务标识。
                    "description": """task_id returned by schedule_cron.""",
                },
            },
            "required": ["task_id"],
        },
    },
    handler=_handle_run_cron_job_now,
    is_async=True,
    emoji="▶",
    danger_level="dangerous",
)

registry.register(
    name="reschedule_cron_job",
    toolset="cron",
    schema={
        # 基于已有任务配置复制创建一个新的定时任务。
        #
        # ## 前置条件
        # task_id 必须存在且属于当前会话。
        # 同一会话任务数不能超过 CRON_MAX_JOBS_PER_SESSION。
        #
        # ## 调用效果
        # 完全复制源任务的 schedule、command、cwd 等参数，创建新的 task_id 并调度。
        # 新任务的所有参数不可修改；如需修改请使用 schedule_cron。
        #
        # ## 返回
        # ```json
        # {"success": true, "task_id": "...", "name": "...", "schedule_type": "interval", "schedule_value": "300", "next_run": "...", "log_path": "...", "message": "..."}
        # ```
        #
        # ## 何时使用
        # - 收到 [cron-result] 后需要继续执行相同命令时。
        # - 安排轮询的下一次迭代。
        #
        # ## 副作用/注意
        # - 新任务会再次执行 command，可能产生副作用。
        # - 不可用于批量预创建未来任务。
        "description": """Create a new one-shot cron job by copying an existing task's configuration.

## Prerequisites
task_id must exist and belong to the current session. The number of cron jobs per session cannot exceed CRON_MAX_JOBS_PER_SESSION.

## Effect
Copies schedule, command, cwd, and other parameters from the source task, creates a new task_id, and schedules it. All parameters are taken from the source task and cannot be modified; if modifications are needed, use schedule_cron instead.

## Returns
```json
{"success": true, "task_id": "...", "name": "...", "schedule_type": "interval", "schedule_value": "300", "next_run": "...", "log_path": "...", "message": "..."}
```

## When to Use
- Continue running the same command after receiving a [cron-result].
- Schedule the next iteration of a polling loop.

## Side Effects / Notes
- The new task will execute the command again and may produce side effects.
- Do not use it to pre-create batches of future runs.""",
        "parameters": {
            "type": "object",
            "properties": {
                "task_id": {
                    "type": "string",
                    # 要复制配置的已有任务标识。
                    "description": """task_id of the existing task to copy configuration from.""",
                },
            },
            "required": ["task_id"],
        },
    },
    handler=_handle_reschedule_cron_job,
    is_async=True,
    emoji="🔁",
    danger_level="dangerous",
)

registry.register(
    name="wait_cron",
    toolset="cron",
    schema={
        # 创建一个只等待、不执行任何脚本的精简定时提醒任务。
        #
        # ## 前置条件
        # duration 必须为正整数秒数，且不小于 CRON_MIN_INTERVAL_SECONDS。
        #
        # ## 调用效果
        # 非阻塞等待指定秒数，时间到后通过 [cron-result] 返回固定提醒文本。
        # 同一会话中同时只能保留一个 wait 任务，新任务会替换旧任务。
        #
        # ## 返回
        # ```json
        # {"success": true, "task_id": "...", "duration": 60, "next_run": "...", "message": "..."}
        # ```
        #
        # ## 何时使用
        # - 需要让 Agent 在指定时间后继续处理某事。
        # - 简单倒计时提醒，不需要执行命令。
        #
        # ## 副作用/注意
        # - 不执行任何命令，只发送提醒消息。
        # - 不是阻塞式 sleep，Agent 可继续处理其他任务。
        "description": """Schedule a lightweight wait reminder that does not execute any script.

## Prerequisites
duration must be a positive integer in seconds and at least CRON_MIN_INTERVAL_SECONDS.

## Effect
Waits non-blockingly for the specified number of seconds, then sends a [cron-result] with the fixed reminder text. Only one wait task is kept per session; a new wait task replaces any existing one.

## Returns
```json
{"success": true, "task_id": "...", "duration": 60, "next_run": "...", "message": "..."}
```

## When to Use
- Resume processing something after a delay.
- Simple countdown reminder without running a command.

## Side Effects / Notes
- Does not execute any command; only sends a reminder message.
- This is not a blocking sleep; the Agent can continue with other tasks.""",
        "parameters": {
            "type": "object",
            "properties": {
                "duration": {
                    "type": "string",
                    # 等待时长，以秒为单位，最小 CRON_MIN_INTERVAL_SECONDS 秒。
                    "description": f"""Delay in seconds before the reminder triggers. Minimum {CRON_MIN_INTERVAL_SECONDS} seconds.""",
                },
                "message": {
                    "type": "string",
                    # 提醒时返回的固定内容。
                    "description": """Fixed reminder text returned when the wait completes. Default: 'Wait time is up.'""",
                    "default": "Wait time is up.",
                },
            },
            "required": ["duration"],
        },
    },
    handler=_handle_wait_cron,
    is_async=True,
    emoji="⏳",
    danger_level="readonly",
)


# ── 进程启动时自动加载持久化的任务 ───────────────────────────
_load_all_tasks()