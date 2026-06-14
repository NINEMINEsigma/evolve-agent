"""Cron 定时任务工具 — 创建和管理单次执行的后台任务。

任务状态持久化到磁盘，后端重启后自动恢复并重新调度。
会话断开不会终止定时任务，任务在后台继续运行直到完成或被显式取消。

支持两种一次性调度格式：
  1. ``interval_seconds`` — 从现在起延迟指定秒数后执行一次，最小 10 秒
  2. Cron 表达式 — 在下一个匹配 5 字段 ``分 时 日 月 周`` 的时间执行一次

Weekday 遵循标准 cron 语义：0=Sunday, 1=Monday, ..., 6=Saturday。

每个任务仅运行一次，执行后自动停止调度但保留记录。
需要循环、轮询或长期观察时，只安排下一次任务；等 [cron-result] 返回后再决定是否继续安排。
可通过 reschedule_cron_job 在 [cron-result] 返回后基于已有任务配置再次创建相同的新任务。

模块导入时通过 ``registry.register()`` 注册 5 个工具：
  - ``schedule_cron``       — 创建定时任务（仅执行一次）
  - ``list_cron_jobs``      — 列出当前会话的任务
  - ``cancel_cron_job``     — 取消指定任务
  - ``run_cron_job_now``    — 立即触发执行一次
  - ``reschedule_cron_job`` — 基于已有任务配置重新创建任务（参数不可修改）
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
from system.pathutils import find_repo_root
from system.subprocess_utils import build_subprocess_env, completed_process_from_bytes

logger = logging.getLogger(__name__)

# ── 持久化路径 ────────────────────────────────────────────────

# agent/component/extools/cron_tools.py -> 项目根目录
_REPO_ROOT: Path = find_repo_root()
_CRON_STORE_DIR: Path = _REPO_ROOT / "workspace" / "logs"
_CRON_STORE_PATH: Path = _CRON_STORE_DIR / "cron_jobs.json"


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
    command: List[str]
    cwd: str
    should_schedule: bool = True  # 控制任务是否继续被 Timer 调度；False 时停止后续执行
    next_run: float = 0.0
    run_count: int = 0
    last_run: float = 0.0
    log_path: str = ""
    skip_agent_notify: bool = False  # 用户显式取消时设为 True，抑制在途执行完成后的通知
    _timer: Optional[threading.Timer] = field(default=None, repr=False)


# ── 任务注册表 ──────────────────────────────────────────────

_cron_tasks: Dict[str, Dict[str, _CronTask]] = {}
_cron_lock: threading.RLock = threading.RLock()
_MAX_JOBS_PER_SESSION: int = 20

# ── 事件回调 ──────────────────────────────────────────────────
# 由 gateway/server.py 注册，用于在任务执行完成后向前端推送结果。

_CronEventCallback = Any  # Callable[[str, str, str, int, str], None]
_cron_event_callbacks: List[_CronEventCallback] = []


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
    )


def _save_all_tasks() -> None:
    """将所有任务状态持久化到磁盘（原子写入，避免半写损坏）。"""
    try:
        _CRON_STORE_DIR.mkdir(parents=True, exist_ok=True)
        with _cron_lock:
            payload: Dict[str, Dict[str, dict]] = {}
            for sid, tasks in _cron_tasks.items():
                payload[sid] = {}
                for tid, task in tasks.items():
                    payload[sid][tid] = _task_to_dict(task)
        # 原子写入：先写临时文件再重命名，防止进程崩溃时留下半写文件
        tmp_path = _CRON_STORE_PATH.with_suffix(".tmp")
        tmp_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        tmp_path.replace(_CRON_STORE_PATH)
    except Exception as exc:
        logger.warning("Failed to save cron jobs: %s", exc)


def _load_all_tasks() -> None:
    """从磁盘加载任务状态并重新调度。"""
    if not _CRON_STORE_PATH.exists():
        return
    try:
        raw: dict = json.loads(_CRON_STORE_PATH.read_text(encoding="utf-8"))
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


def _resolve_log_path(log_path: str) -> str|None:
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
    log_file: Optional[str] = None
    if task.log_path:
        log_file = _resolve_log_path(task.log_path)
        if log_file:
            Path(log_file).parent.mkdir(parents=True, exist_ok=True)

    exit_code = -1
    stdout_text = ""

    try:
        popen_kwargs: Dict[str, Any] = {
            "cwd": cwd_real,
            "stdout": subprocess.PIPE,
            "stderr": subprocess.STDOUT,
            "text": False,
            "env": build_subprocess_env(),
        }
        if sys.platform == "win32":
            popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP

        result = subprocess.run(task.command, timeout=300, **popen_kwargs)
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
        stdout_text = "[TIMEOUT after 300s]"
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
            f"task output is too long, you can view the full output in the log file: {task.log_path}" if len(stdout_text) > 5000 else stdout_text,
        )


# ── 工具 handler ─────────────────────────────────────────────


async def _handle_schedule_cron(args: Dict[str, Any]) -> dict:
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
    cmd_parts: List[str] = [str(p) for p in raw_command]
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
        if interval_sec < 10:
            return tool_error("Interval must be at least 10 seconds")
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
    if current_count >= _MAX_JOBS_PER_SESSION:
        return tool_error(
            f"Maximum {_MAX_JOBS_PER_SESSION} cron jobs per session reached"
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


async def _handle_list_cron_jobs(args: Dict[str, Any]) -> dict:
    """列出当前会话的所有定时任务。"""
    session_id: str = str(args.get("_session_id", ""))

    with _cron_lock:
        session_tasks = _cron_tasks.get(session_id, {})
        tasks: List[dict] = []
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


async def _handle_cancel_cron_job(args: Dict[str, Any]) -> dict:
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


async def _handle_run_cron_job_now(args: Dict[str, Any]) -> dict:
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


async def _handle_reschedule_cron_job(args: Dict[str, Any]) -> dict:
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
    if current_count >= _MAX_JOBS_PER_SESSION:
        return tool_error(
            f"Maximum {_MAX_JOBS_PER_SESSION} cron jobs per session reached"
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


# ── 公开 API（供 gateway/server.py 调用）────────────────────

def list_cron_tasks_for_session(session_id: str) -> List[Dict[str, Any]]:
    """返回指定会话的所有定时任务。"""
    with _cron_lock:
        session_tasks = _cron_tasks.get(session_id, {})
        tasks: List[Dict[str, Any]] = []
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


def trigger_cron_task(session_id: str, task_id: str) -> Dict[str, Any]:
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


def cancel_cron_task(session_id: str, task_id: str) -> Dict[str, Any]:
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
        # 创建一个后台一次性定时任务；任务只会执行一次。
        # 数字 schedule 表示延迟 N 秒后执行一次；cron 表达式表示下一个匹配时间执行一次。
        # 循环、轮询或长期观察必须等 [cron-result] 返回后再安排下一次，不要预排未来链式任务。
        # 原始 stdout/stderr 会写入日志并注入回 Agent；用户不会自动看到原始输出。
        "description": (
            "Schedule a one-shot background task. It runs exactly once.\n"
            "Two one-shot schedule formats are supported:\n"
            "  1. Delay: a number in seconds, e.g. '300' means run once after 300 seconds; minimum 10s.\n"
            "  2. Cron expression: 5 fields 'minute hour day month weekday', "
            "e.g. '0 9 * * 1' means run once at the next matching Monday 9:00 AM.\n"
            "     Weekday: 0=Sunday, 1=Monday, ..., 6=Saturday.\n\n"
            "For loops, polling, or long-running observation, schedule only the next run. "
            "Do not pre-create future chains such as 15s, 30s, and 45s unless the user explicitly asks for multiple independent future runs. "
            "After execution, the Agent receives a [cron-result] message and can decide whether to schedule the next one-shot task. "
            "Raw stdout/stderr are written to a log file and injected back to the Agent; the user does not automatically see the raw output.\n\n"
            "Returns:\n"
            "  - success: whether the task was created\n"
            "  - task_id: unique identifier for managing the task\n"
            "  - next_run: ISO timestamp of the one scheduled execution\n"
            "  - log_path: path to the execution log file\n"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "schedule": {
                    "type": "string",
                    # 一次性调度说明：延迟秒数，或用于计算下一个匹配时间的 5 字段 cron 表达式。
                    "description": (
                        "One-shot schedule specification. Either: (1) a number of seconds to delay, "
                        "or (2) a 5-field cron expression 'min hour day month weekday' for the next matching time. "
                        "Examples: '60' = run once after 60 seconds; "
                        "'0 */6 * * *' = run once at the next matching 6-hour boundary; "
                        "'0 9 * * 1' = run once at the next Monday 9:00 AM. Weekday: 0=Sunday."
                    ),
                },
                "command": {
                    "type": "array",
                    "items": {"type": "string"},
                    # 要执行的命令及参数列表。
                    "description": "Command and arguments to execute, e.g. ['python', '-c', 'print(1)'].",
                },
                "reason": {
                    "type": "string",
                    # 创建此定时任务的原因。
                    "description": "Reason for creating this scheduled task.",
                },
                "name": {
                    "type": "string",
                    # 可选的人类可读任务名称。
                    "description": "Optional human-readable name for the task.",
                },
                "cwd": {
                    "type": "string",
                    # 工作目录（ws: 命名空间，默认 'ws:'）。
                    "description": "Working directory (ws: namespace, default 'ws:').",
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
        "description": (
            "List all scheduled cron jobs for the current session.\n"
            "Returns task metadata including schedule, next run time, run count, and log path."
        ),
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
        # 按 task_id 取消并移除指定定时任务。
        "description": (
            "Cancel and remove a scheduled cron job by its task_id.\n"
            "The task will no longer execute. Pending executions are discarded."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "task_id": {
                    "type": "string",
                    # schedule_cron 返回的任务标识。
                    "description": "task_id returned by schedule_cron.",
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
        "description": (
            "Immediately trigger a one-time execution of a scheduled cron job.\n"
            "This does not affect the regular schedule — the next automatic execution "
            "still occurs as originally planned (unless the task uses interval scheduling, "
            "in which case the timer is reset from now)."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "task_id": {
                    "type": "string",
                    # schedule_cron 返回的任务标识。
                    "description": "task_id returned by schedule_cron.",
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
        # 基于已有任务配置重新创建一个一次性任务；适合在 [cron-result] 返回后安排下一轮。
        # 不要用它预排一批未来任务；需要修改参数时应改用 schedule_cron 创建一个新的下一次任务。
        "description": (
            "Create one new one-shot cron job by copying an existing task's configuration.\n"
            "Use this after receiving a [cron-result] when the same command should continue for one more run. "
            "Do not use it to pre-create batches of future runs.\n"
            "All parameters (schedule, command, cwd) are taken from the source task and cannot be modified. "
            "If the next run needs a different delay, cron expression, command, or cwd, create one new task with schedule_cron instead.\n\n"
            "The new task will run exactly once, just like a normally scheduled task."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "task_id": {
                    "type": "string",
                    # 要复制配置的已有任务标识。
                    "description": "task_id of the existing task to copy configuration from.",
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


# ── 进程启动时自动加载持久化的任务 ───────────────────────────
_load_all_tasks()