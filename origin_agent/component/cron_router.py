"""Cron 任务、持久化、Timer 与运行中命令的唯一生命周期所有者。"""

from __future__ import annotations

import asyncio
import datetime
import json
import math
import subprocess
import threading
import time
import uuid
from pathlib import Path
from typing import Any, TYPE_CHECKING

from framework import AsyncSystem

from component.cron_tasks import _CronTask, next_cron_time
from entity.constant import (
    CRON_MAX_JOBS_PER_SESSION, CRON_MIN_INTERVAL_SECONDS,
    CRON_STDOUT_PREVIEW_MAX_LENGTH, CRON_STORE_FILENAME, CRON_TASK_TIMEOUT,
    CRON_PROCESS_SESSION_PREFIX,
    SYSTEM_CHARACTER_NAME, SYSTEM_QUIESCE_TIMEOUT_SECONDS,
)
from entity.puretype import CronTaskInfo
from system.atomic_io import write_text_atomic
from system.lifecycle import ApplicationStoppingError, LifecycleFailure
from interface.cron_router import ICronRouter
from interface.runtime_system import IRuntimeSystem
from interface.sandbox import ISandbox
from interface.subprocess_runner import ISubprocessRunner

if TYPE_CHECKING:
    from entry.base_agent_loop import BaseAgentLoop


class CronRouter(ICronRouter):
    """加载不调度；关闭只冻结运行资源，不删除持久任务。"""

    def __init__(self) -> None:
        super().__init__(dependencies=(IRuntimeSystem, ISandbox, ISubprocessRunner))
        self._runtime: IRuntimeSystem | None = None
        self._sandbox: ISandbox | None = None
        self._runner: ISubprocessRunner | None = None
        self._routes: dict[str, BaseAgentLoop] = {}
        self._tasks: dict[str, dict[str, _CronTask]] = {}
        self._lock = threading.RLock()
        # Timer 本身执行命令；取消/回调返回都不提前删除真实线程记录。
        self._timers: set[threading.Timer] = set()
        self._running: dict[str, _CronTask] = {}
        self._failures: list[BaseException] = []
        self._frozen = False
        self._activated = False
        self._stop_task: asyncio.Task[None] | None = None

    async def virtual_awake(self) -> None:
        self._runtime = self.get_system(IRuntimeSystem)
        self._sandbox = self.get_system(ISandbox)
        self._runner = self.get_system(ISubprocessRunner)
        self._load_all_tasks()

    @property
    def runtime(self) -> IRuntimeSystem:
        if self._runtime is None:
            raise LifecycleFailure("CronRouter has not been awakened")
        return self._runtime

    @property
    def sandbox(self) -> ISandbox:
        if self._sandbox is None:
            raise LifecycleFailure("CronRouter has not been awakened")
        return self._sandbox

    @property
    def runner(self) -> ISubprocessRunner:
        if self._runner is None:
            raise LifecycleFailure("CronRouter has not been awakened")
        return self._runner

    def _record_failure(self, error: BaseException) -> None:
        with self._lock:
            if not any(item is error for item in self._failures):
                self._failures.append(error)
        # 统一锁顺序 Runtime -> Cron，不在 Cron 锁内取得 Runtime 锁。
        self.runtime.record_failure(error)

    def _require_open(self) -> None:
        if self._frozen:
            raise ApplicationStoppingError("Cron scheduling has been frozen")

    def register(self, session_id: str, loop: BaseAgentLoop) -> None:
        with self.runtime.admission(), self._lock:
            self._require_open()
            self._routes[session_id] = loop

    def unregister(self, session_id: str) -> None:
        with self._lock:
            self._routes.pop(session_id, None)

    def dispatch(self, session_id: str, task_id: str, name: str,
                 exit_code: int, stdout_preview: str) -> bool:
        status = "completed" if exit_code == 0 else f"failed (exit={exit_code})"
        text = f"[cron-result] {name} ({task_id}) — {status}\n{stdout_preview}"
        try:
            with self.runtime.admission(), self._lock:
                self._require_open()
                loop = self._routes.get(session_id)
                if loop is None:
                    return False
                # S16 将主队列改为输入投递记录；此处保留同一接收边界。
                queue = loop.message_queue
                if queue is not None:
                    queue.push(text, character_name=SYSTEM_CHARACTER_NAME, source="cron")
                else:
                    from entry.base_agent_loop import UserMessage
                    loop.inbox.put(UserMessage(content=text, character_name=SYSTEM_CHARACTER_NAME))
                    loop.inbox.wake()
                return True
        except ApplicationStoppingError:
            # 关闭后迟到的命令仍保存结局，但不得再投递或唤醒模型。
            return False

    def _store_path(self) -> Path:
        return self.runtime.context.workspace / CRON_STORE_FILENAME

    def _save_all_tasks(self) -> None:
        try:
            # 快照与同路径临时文件写入在同一事务锁内，禁止陈旧快照覆盖。
            with self._lock:
                path = self._store_path()
                path.parent.mkdir(parents=True, exist_ok=True)
                payload = {
                    sid: {tid: task.model_dump() for tid, task in tasks.items()}
                    for sid, tasks in self._tasks.items()
                }
                write_text_atomic(path, json.dumps(payload, ensure_ascii=False, indent=2), tmp_suffix=".tmp")
        except Exception as error:
            failure = LifecycleFailure("Failed to persist cron tasks")
            failure.__cause__ = error
            self._record_failure(failure)
            raise failure

    @staticmethod
    def _next_run(schedule_type: str, schedule_value: str) -> float:
        if schedule_type == "interval":
            interval = float(schedule_value)
            if not math.isfinite(interval) or interval < CRON_MIN_INTERVAL_SECONDS:
                raise ValueError("Invalid cron interval")
            return time.time() + interval
        if schedule_type != "cron":
            raise ValueError(f"Unknown cron schedule type: {schedule_type}")
        return next_cron_time(schedule_value).timestamp()

    def _load_all_tasks(self) -> None:
        try:
            text = self._store_path().read_text(encoding="utf-8")
        except FileNotFoundError:
            return
        raw = json.loads(text)
        if not isinstance(raw, dict):
            raise ValueError("Cron store root must be an object")
        tasks: dict[str, dict[str, _CronTask]] = {}
        known_ids: set[str] = set()
        for sid, entries in raw.items():
            if not isinstance(entries, dict):
                raise ValueError("Cron session tasks must be an object")
            tasks[sid] = {}
            for tid, data in entries.items():
                task = _CronTask.model_validate(data)
                if task.session_id != sid or task.task_id != tid or tid in known_ids:
                    raise ValueError("Cron task identity does not match its store key")
                known_ids.add(tid)
                next_run = self._next_run(task.schedule_type, task.schedule_value)
                if not task.is_wait and not task.command:
                    raise ValueError("Cron command must not be empty")
                if not math.isfinite(task.next_run) or not math.isfinite(task.last_run):
                    raise ValueError("Cron timestamps must be finite")
                if task.should_schedule and (task.schedule_type == "cron" or task.next_run <= time.time()):
                    task.next_run = next_run
                tasks[sid][tid] = task
        self._tasks = tasks

    def activate(self) -> None:
        with self.runtime.admission(), self._lock:
            self._require_open()
            if self._activated:
                return
            self._activated = True
            tasks = tuple(task for group in self._tasks.values() for task in group.values())
        for task in tasks:
            self._arm(task)

    def _reap_finished_locked(self) -> None:
        for timer in tuple(self._timers):
            if timer.ident is not None and not timer.is_alive():
                timer.join(timeout=0)
                self._timers.remove(timer)

    def _arm(self, task: _CronTask, *, immediate: bool = False) -> None:
        try:
            with self.runtime.admission(), self._lock:
                self._require_open()
                if not self._activated or not task.should_schedule:
                    return
                if self._tasks.get(task.session_id, {}).get(task.task_id) is not task:
                    return
                if task.task_id in self._running:
                    return
                self._reap_finished_locked()
                delay = 0.0 if immediate else max(0.0, task.next_run - time.time())
                timer = threading.Timer(delay, self._timer_callback, args=(task,))
                self._timers.add(timer)
                task.set_timer(timer)
        except ApplicationStoppingError:
            # 已接收并保存的任务保留 should_schedule，重启后恢复，而非开启新Timer。
            return
        except Exception as error:
            failure = LifecycleFailure("Failed to start cron Timer")
            failure.__cause__ = error
            self._record_failure(failure)
            raise failure

    def freeze(self) -> None:
        # 不能使用只允许RUNNING的admission，STOPPING也必须可冻结。
        with self._lock:
            self._frozen = True
            for timer in self._timers:
                timer.cancel()
            for tasks in self._tasks.values():
                for task in tasks.values():
                    task.cancel_timer()

    def _timer_callback(self, task: _CronTask) -> None:
        entered = False
        try:
            with self.runtime.admission(), self._lock:
                self._require_open()
                if not task.should_schedule or task._timer is not threading.current_thread():
                    return
                if self._tasks.get(task.session_id, {}).get(task.task_id) is not task:
                    return
                if task.task_id in self._running:
                    return
                self._running[task.task_id] = task
                entered = True
                task.cancel_timer()
            self._run_task(task)
        except ApplicationStoppingError:
            # 原生执行前被停止拒绝，不消耗持久化的一次执行机会。
            return
        except BaseException as error:
            self._record_failure(error)
        finally:
            if entered:
                with self._lock:
                    self._running.pop(task.task_id, None)
            # Timer在回调返回后才真正退出；由reap/join确认，不在这里清除。

    def _run_task(self, task: _CronTask) -> None:
        self.runtime.require_running()
        with self._lock:
            if self._frozen or not task.should_schedule:
                return
            command = list(task.command)
            cwd = task.cwd
            log_path = task.log_path
        started = time.time()
        if task.is_wait:
            exit_code = 0
            output = task.wait_message or "Wait time is up."
        else:
            cwd_real = str(self.sandbox.resolve_read(cwd).real)
            try:
                result = self.runner.run(command, cwd=cwd_real, timeout=CRON_TASK_TIMEOUT,
                                         session_id=f"{CRON_PROCESS_SESSION_PREFIX}{task.task_id}")
                exit_code = result.returncode
                output = (result.stdout or "") + (result.stderr or "")
            except subprocess.TimeoutExpired:
                exit_code = -1
                output = f"[TIMEOUT after {CRON_TASK_TIMEOUT}s]"
        with self._lock:
            task.last_run = started
            task.run_count += 1
            task.should_schedule = False
            run_count = task.run_count
        if log_path:
            path = self.sandbox.resolve_write(log_path).real
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as stream:
                stream.write(f"\n{'=' * 60}\n[{datetime.datetime.now().isoformat()}] Run #{run_count} | Exit: {exit_code}\n")
                if not task.is_wait:
                    stream.write(f"Command: {' '.join(command)}\n")
                stream.write(f"Stdout:\n{output}")
        self._save_all_tasks()
        preview = output if len(output) <= CRON_STDOUT_PREVIEW_MAX_LENGTH else (
            f"task output is too long, you can view the full output in the log file: {log_path}"
        )
        try:
            # 与取消/会话迁移同步读取最终投递目标，不使用锁外的旧session快照。
            with self.runtime.admission(), self._lock:
                self._require_open()
                if not task.skip_agent_notify:
                    self.dispatch(task.session_id, task.task_id, task.name, exit_code, preview)
        except ApplicationStoppingError:
            return

    def _stop_blocking(self) -> None:
        deadline = time.monotonic() + SYSTEM_QUIESCE_TIMEOUT_SECONDS
        failures: list[BaseException] = []
        with self._lock:
            # 独立运行表覆盖已取消/删除/迁移而仍在执行的任务。
            sessions = tuple(f"{CRON_PROCESS_SESSION_PREFIX}{tid}" for tid in self._running)
            timers = tuple(self._timers)
        for sid in sessions:
            try:
                self.runner.kill_active(sid)
            except BaseException as error:
                failures.append(error)
        for timer in timers:
            try:
                if timer.ident is not None:
                    timer.join(timeout=max(0.0, deadline - time.monotonic()))
                if timer.is_alive():
                    raise LifecycleFailure(f"Cron thread {timer.name} did not exit")
            except BaseException as error:
                failures.append(error)
            else:
                with self._lock:
                    self._timers.discard(timer)
        with self._lock:
            failures.extend(self._failures)
        if failures:
            raise BaseExceptionGroup("Cron shutdown failed", failures)

    def _observe_stop(self, task: asyncio.Task[None]) -> None:
        if task.cancelled():
            self._record_failure(LifecycleFailure("Cron native cleanup was cancelled"))
        else:
            error = task.exception()
            if error is not None:
                self._record_failure(error)

    async def stop_running(self) -> None:
        self.freeze()
        if self._stop_task is None:
            self._stop_task = asyncio.create_task(asyncio.to_thread(self._stop_blocking), name="cron-stop")
            self._stop_task.add_done_callback(self._observe_stop)
        done, _ = await asyncio.wait({self._stop_task}, timeout=SYSTEM_QUIESCE_TIMEOUT_SECONDS)
        if not done:
            failure = LifecycleFailure("Cron native cleanup exceeded its deadline")
            self._record_failure(failure)
            raise failure
        self._stop_task.result()

    async def virtual_shotdown(self) -> None:
        await self.stop_running()
        with self._lock:
            self._routes.clear()
            self._tasks.clear()

    def schedule_task(self, *, session_id: str, name: str, schedule_type: str,
                      schedule_value: str, command: list[str], cwd: str,
                      is_wait: bool = False, wait_message: str = "") -> dict[str, Any]:
        next_run = self._next_run(schedule_type, schedule_value)
        tid = uuid.uuid4().hex[:12]
        task = _CronTask(task_id=tid, session_id=session_id, name=name or f"cron-{tid}",
                         schedule_type=schedule_type, schedule_value=schedule_value,
                         command=command, cwd=cwd, next_run=next_run,
                         log_path=f"ws:logs/cron/{session_id}/{tid}.log",
                         is_wait=is_wait, wait_message=wait_message)
        with self.runtime.admission(), self._lock:
            self._require_open()
            tasks = self._tasks.setdefault(session_id, {})
            if is_wait:
                for existing in tasks.values():
                    if existing.is_wait and existing.should_schedule:
                        return {"error": "A wait task is already pending for this session (task_id: "
                                f"{existing.task_id}). Cancel it first with cancel_cron_job before creating a new one."}
                for old_id, existing in tuple(tasks.items()):
                    if existing.is_wait:
                        existing.cancel_timer()
                        del tasks[old_id]
            if len(tasks) >= CRON_MAX_JOBS_PER_SESSION:
                return {"error": f"Maximum {CRON_MAX_JOBS_PER_SESSION} cron jobs per session reached"}
            tasks[tid] = task
        self._save_all_tasks()
        self._arm(task)
        return {"success": True, "task_id": tid, "name": task.name,
                "schedule_type": schedule_type, "schedule_value": schedule_value,
                "next_run": _iso_time(next_run), "log_path": task.log_path}

    def reschedule_task(self, session_id: str, task_id: str) -> dict[str, Any]:
        with self._lock:
            source = self._tasks.get(session_id, {}).get(task_id)
            if source is None:
                return {"error": f"Task not found: {task_id}"}
            config = source.model_copy(deep=False)
            command = list(source.command)
        # 保留原reschedule协议：复制命令配置，新ID，不复制运行结局。
        return self.schedule_task(session_id=session_id, name=config.name,
                                  schedule_type=config.schedule_type, schedule_value=config.schedule_value,
                                  command=command, cwd=config.cwd,
                                  is_wait=config.is_wait, wait_message=config.wait_message)

    def cleanup_session_cron_jobs(self, session_id: str) -> int:
        with self._lock:
            tasks = self._tasks.pop(session_id, {})
            for task in tasks.values():
                task.should_schedule = False
                task.skip_agent_notify = True
                task.cancel_timer()
        if tasks:
            self._save_all_tasks()
        return len(tasks)

    def migrate_session_cron_jobs(self, old_sid: str, new_sid: str) -> int:
        with self.runtime.admission(), self._lock:
            self._require_open()
            source = self._tasks.get(old_sid, {})
            target = self._tasks.get(new_sid, {})
            if old_sid == new_sid:
                return 0
            if source.keys() & target.keys():
                raise LifecycleFailure("Cron task identity collision during session migration")
            tasks = self._tasks.pop(old_sid, {})
            if tasks:
                target = self._tasks.setdefault(new_sid, {})
            for task in tasks.values():
                task.cancel_timer()
                task.session_id = new_sid
                target[task.task_id] = task
        if tasks:
            self._save_all_tasks()
            for task in tasks.values():
                self._arm(task)
        return len(tasks)

    def list_cron_tasks_for_session(self, session_id: str) -> list[CronTaskInfo]:
        with self._lock:
            return [_build_task_info(task) for task in self._tasks.get(session_id, {}).values()]

    def trigger_cron_task(self, session_id: str, task_id: str) -> dict[str, Any]:
        with self.runtime.admission(), self._lock:
            self._require_open()
            task = self._tasks.get(session_id, {}).get(task_id)
            if task is None:
                return {"success": False, "message": f"Task not found: {task_id}"}
        self._arm(task, immediate=True)
        return {"success": True, "task_id": task_id, "name": task.name,
                "message": f"Triggered: {task.name or task_id}"}

    def cancel_cron_task(self, session_id: str, task_id: str) -> dict[str, Any]:
        with self._lock:
            task = self._tasks.get(session_id, {}).pop(task_id, None)
            if task is None:
                return {"success": False, "message": f"Task not found: {task_id}"}
            task.should_schedule = False
            task.skip_agent_notify = True
            task.cancel_timer()
        self._save_all_tasks()
        return {"success": True, "task_id": task_id, "name": task.name,
                "message": f"Cancelled: {task.name or task_id}"}


def _iso_time(timestamp: float) -> str | None:
    return datetime.datetime.fromtimestamp(timestamp, tz=datetime.timezone.utc).isoformat() if timestamp else None


def _build_task_info(task: _CronTask) -> CronTaskInfo:
    return CronTaskInfo(task_id=task.task_id, name=task.name, schedule_type=task.schedule_type,
                        schedule_value=task.schedule_value, command=list(task.command),
                        should_schedule=task.should_schedule, next_run=_iso_time(task.next_run),
                        run_count=task.run_count, last_run=_iso_time(task.last_run), log_path=task.log_path,
                        is_wait=task.is_wait, wait_message=task.wait_message)
