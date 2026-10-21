"""Cron 定时任务工具 — 薄工具层。

工具 ``handle`` 仅做参数解析与委托 ``CronRouter`` 实例方法；
模块导出顶层 ``TOOLSET``（``BaseToolSet``），由 ToolDiscoverySystem 显式发现并注册。
``_CronTask`` 及时间解析已迁入 ``component/cron_tasks.py``。
持久化、恢复、Timer 调度、执行、清理/迁移、查询、触发/取消
均由 ``CronRouter`` 实例持有。

支持两种一次性调度格式：
  1. ``interval_seconds`` — 从现在起延迟指定秒数后执行一次
  2. Cron 表达式 — 在下一个匹配 5 字段 ``分 时 日 月 周`` 的时间执行一次

每个任务仅运行一次，执行后自动停止调度但保留记录。
"""

from __future__ import annotations

from interface.cron_router import ICronRouter

from typing import Any

from abstract.tools.tool import (
    BaseTool,
    BaseToolSet,
    ToolExecution,
    ToolHandlerResult,
    tool_error,
    tool_result,
)
from component.cron_router import CronRouter
from component.cron_tasks import next_cron_time
from entity.puretype import ToolDangerLevel
from entity.constant import CRON_MIN_INTERVAL_SECONDS


# ── CronRouter 获取辅助 ──────────────────────────────────────


def _get_cr() -> CronRouter:
    """获取 Application 的 CronRouter 实例。"""
    from system.application import Application
    return Application.current().get_system(ICronRouter)


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
            next_cron_time(raw_schedule)
        except ValueError as exc:
            return tool_error(f"Invalid cron expression: {exc}")

    result = _get_cr().schedule_task(
        session_id=session_id, name=name, schedule_type=schedule_type,
        schedule_value=schedule_value, command=cmd_parts, cwd=cwd,
    )
    if "error" in result:
        return result
    result["message"] = (
        f"One-shot cron job scheduled (task_id={result['task_id']}, next_run={result['next_run']}). "
        "After it finishes, a [cron-result] message will wake the Agent. "
        "If the task must continue, schedule only the next run then."
    )
    return result


async def _handle_list_cron_jobs(args: dict[str, Any]) -> dict:
    """列出当前会话的所有定时任务。"""
    session_id: str = str(args.get("_session_id", ""))

    tasks = [task.model_dump() for task in _get_cr().list_cron_tasks_for_session(session_id)]

    return tool_result(success=True, count=len(tasks), tasks=tasks)


async def _handle_cancel_cron_job(args: dict[str, Any]) -> dict:
    """取消指定定时任务。"""
    task_id: str = str(args.get("task_id", "")).strip()
    session_id: str = str(args.get("_session_id", ""))

    if not task_id:
        return tool_error("'task_id' is required")

    cr = _get_cr()
    result = cr.cancel_cron_task(session_id, task_id)
    if not result.get("success"):
        return tool_error(result.get("message", "Task not found"))
    return tool_result(success=True, **{k: v for k, v in result.items() if k != "success"})


async def _handle_run_cron_job_now(args: dict[str, Any]) -> dict:
    """立即触发指定任务执行一次（不影响正常调度）。"""
    task_id: str = str(args.get("task_id", "")).strip()
    session_id: str = str(args.get("_session_id", ""))

    if not task_id:
        return tool_error("'task_id' is required")

    cr = _get_cr()
    result = cr.trigger_cron_task(session_id, task_id)
    if not result.get("success"):
        return tool_error(result.get("message", "Task not found"))
    return tool_result(success=True, **{k: v for k, v in result.items() if k != "success"})


async def _handle_reschedule_cron_job(args: dict[str, Any]) -> dict:
    """基于已有任务配置重新创建并调度一个新任务（所有参数不可修改）。"""
    task_id: str = str(args.get("task_id", "")).strip()
    session_id: str = str(args.get("_session_id", ""))

    if not task_id:
        return tool_error("'task_id' is required")

    result = _get_cr().reschedule_task(session_id, task_id)
    if "error" in result:
        return result
    result["message"] = (
        f"Rescheduled cron job (new task_id={result['task_id']}, next_run={result['next_run']})"
    )
    return result


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

    result = _get_cr().schedule_task(
        session_id=session_id, name="wait", schedule_type="interval",
        schedule_value=str(duration_sec), command=[], cwd="ws:",
        is_wait=True, wait_message=message,
    )
    if "error" in result:
        return result
    return tool_result(
        success=True, task_id=result["task_id"], duration=duration_sec, next_run=result["next_run"],
        message=(f"Wait task scheduled (task_id={result['task_id']}, duration={duration_sec}s, "
                 f"next_run={result['next_run']}). A [cron-result] message will be sent when the wait completes."),
    )


# ── 工具对象声明 ─────────────────────────────────────────────


class ScheduleCronTool(BaseTool):
    """创建一次性后台定时任务。"""

    def __init__(self) -> None:
        super().__init__(
            name="ScheduleCron",
            toolset="cron",
            is_async=True,
            danger_level=ToolDangerLevel.dangerous,
            schema={
            # 创建一个一次性后台定时任务。
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
                        "description": """One-shot schedule. Either a number of seconds to delay, or a 5-field cron expression 'min hour day month weekday'. Examples: '60' = run once after 60 seconds; '0 9 * * 1' = run once at next Monday 9:00 AM. Weekday: 0=Sunday.""",
                    },
                    "command": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": """Command and arguments to execute, e.g. ['python', '-c', 'print(1)'].""",
                    },
                    "reason": {
                        "type": "string",
                        "description": """Reason for creating this scheduled task.""",
                    },
                    "name": {
                        "type": "string",
                        "description": """Optional human-readable name for the task.""",
                    },
                    "cwd": {
                        "type": "string",
                        "description": """Working directory (ws: namespace, default 'ws:').""",
                        "default": "ws:",
                    },
                },
                "required": ["schedule", "command", "reason"],
            },
        },
        )

    async def handle(self, execution: ToolExecution) -> ToolHandlerResult:
        """创建定时任务。复用模块级无状态 handler，显式传入调用参数。"""
        return ToolHandlerResult(result=await _handle_schedule_cron(execution.arguments))


class ListCronJobsTool(BaseTool):
    """列出当前会话的所有定时任务。"""

    def __init__(self) -> None:
        super().__init__(
            name="ListCronJobs",
            toolset="cron",
            is_async=True,
            danger_level=ToolDangerLevel.safe,
            schema={
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
        )

    async def handle(self, execution: ToolExecution) -> ToolHandlerResult:
        """列出定时任务。复用模块级无状态 handler，显式传入调用参数。"""
        return ToolHandlerResult(result=await _handle_list_cron_jobs(execution.arguments))


class CancelCronJobTool(BaseTool):
    """取消并移除指定定时任务。"""

    def __init__(self) -> None:
        super().__init__(
            name="CancelCronJob",
            toolset="cron",
            is_async=True,
            danger_level=ToolDangerLevel.safe,
            schema={
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
                        "description": """task_id returned by schedule_cron.""",
                    },
                },
                "required": ["task_id"],
            },
        },
        )

    async def handle(self, execution: ToolExecution) -> ToolHandlerResult:
        """取消定时任务。复用模块级无状态 handler，显式传入调用参数。"""
        return ToolHandlerResult(result=await _handle_cancel_cron_job(execution.arguments))


class RunCronJobNowTool(BaseTool):
    """立即触发指定任务执行一次，不影响正常调度。"""

    def __init__(self) -> None:
        super().__init__(
            name="RunCronJobNow",
            toolset="cron",
            is_async=True,
            danger_level=ToolDangerLevel.dangerous,
            schema={
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
                        "description": """task_id returned by schedule_cron.""",
                    },
                },
                "required": ["task_id"],
            },
        },
        )

    async def handle(self, execution: ToolExecution) -> ToolHandlerResult:
        """立即触发任务。复用模块级无状态 handler，显式传入调用参数。"""
        return ToolHandlerResult(result=await _handle_run_cron_job_now(execution.arguments))


class RescheduleCronJobTool(BaseTool):
    """复制已有任务配置并重新创建调度一个新任务。"""

    def __init__(self) -> None:
        super().__init__(
            name="RescheduleCronJob",
            toolset="cron",
            is_async=True,
            danger_level=ToolDangerLevel.dangerous,
            schema={
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
                        "description": """task_id of the existing task to copy configuration from.""",
                    },
                },
                "required": ["task_id"],
            },
        },
        )

    async def handle(self, execution: ToolExecution) -> ToolHandlerResult:
        """重新调度任务。复用模块级无状态 handler，显式传入调用参数。"""
        return ToolHandlerResult(result=await _handle_reschedule_cron_job(execution.arguments))


class WaitCronTool(BaseTool):
    """创建一个只等待、不执行脚本的精简定时提醒任务。"""

    def __init__(self) -> None:
        super().__init__(
            name="WaitCron",
            toolset="cron",
            is_async=True,
            danger_level=ToolDangerLevel.safe,
            schema={
            "description": """Schedule a lightweight wait reminder that does not execute any script.

## Prerequisites
duration must be a positive integer in seconds and at least CRON_MIN_INTERVAL_SECONDS.

## Effect
Waits non-blockingly for the specified number of seconds, then sends a [cron-result] with the fixed reminder text. Only one wait task is allowed per session; calling wait_cron again while one exists returns an error.

## Returns
```json
{"success": true, "task_id": "...", "duration": 60, "next_run": "...", "message": "..."}
```

## When to Use
- Resume processing something after a delay.
- Simple countdown reminder without running a command.

## Side Effects / Notes
- Does not execute any command; only sends a reminder message.
- This is not a blocking sleep; the Agent can continue with other tasks.
- Calling wait_cron again while a wait task already exists for the session returns an error; cancel the existing one first.""",
            "parameters": {
                "type": "object",
                "properties": {
                    "duration": {
                        "type": "string",
                        "description": f"""Delay in seconds before the reminder triggers. Minimum {CRON_MIN_INTERVAL_SECONDS} seconds.""",
                    },
                    "message": {
                        "type": "string",
                        "description": """Fixed reminder text returned when the wait completes. Default: 'Wait time is up.'""",
                        "default": "Wait time is up.",
                    },
                },
                "required": ["duration"],
            },
        },
        )

    async def handle(self, execution: ToolExecution) -> ToolHandlerResult:
        """创建等待提醒。复用模块级无状态 handler，显式传入调用参数。"""
        return ToolHandlerResult(result=await _handle_wait_cron(execution.arguments))


TOOLSET = BaseToolSet(
    name="cron",
    tools=(
        ScheduleCronTool(),
        ListCronJobsTool(),
        CancelCronJobTool(),
        RunCronJobNowTool(),
        RescheduleCronJobTool(),
        WaitCronTool(),
    ),
)
