"""异步生命周期公共工具；任务结果责任在创建时确定。"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Coroutine, Sequence
from typing import TYPE_CHECKING, Any, ContextManager, TypeVar

from entity.constant import SYSTEM_QUIESCE_TIMEOUT_SECONDS, TaskOwnership
from entity.puretype.lifecycle import ManagedTaskRecord
from system.cleanup_errors import split_cleanup_timeouts

if TYPE_CHECKING:
    from system.resource_cleanup import ResourceCleanupHandle

logger = logging.getLogger(__name__)

TaskResultT = TypeVar("TaskResultT")


class ApplicationStoppingError(RuntimeError):
    """应用已停止接收新的业务工作。"""


class LifecycleFailure(RuntimeError):
    """生命周期约定被破坏或资源未在期限内结束。"""


def contains_lifecycle_failure(error: BaseException) -> bool:
    """仅检查明确类型和异常组成员，不按文本或普通 cause 推断。"""
    if isinstance(error, LifecycleFailure):
        return True
    return isinstance(error, BaseExceptionGroup) and any(
        contains_lifecycle_failure(member) for member in error.exceptions
    )


def requires_lifecycle_propagation(error: BaseException) -> bool:
    """业务错误转换边界必须放行停止、取消和生命周期失败及其异常组。"""
    if isinstance(error, (ApplicationStoppingError, LifecycleFailure, asyncio.CancelledError)):
        return True
    return isinstance(error, BaseExceptionGroup) and any(
        requires_lifecycle_propagation(member) for member in error.exceptions
    )


def _only_cancellations(error: BaseException) -> bool:
    if isinstance(error, asyncio.CancelledError):
        return True
    return isinstance(error, BaseExceptionGroup) and all(
        _only_cancellations(member) for member in error.exceptions
    )


class TaskOwner:
    """持有真实任务；后台失败上报，请求结果交还唯一等待方。"""

    def __init__(
        self,
        owner_name: str,
        on_failure: Callable[[BaseException], None],
        *,
        allow_cleanup_handoff: bool = False,
    ) -> None:
        self._owner_name = owner_name
        self._on_failure = on_failure
        self._allow_cleanup_handoff = allow_cleanup_handoff
        self._records: dict[asyncio.Task[Any], ManagedTaskRecord] = {}
        self._cleanup_handles: dict[asyncio.Task[Any], ResourceCleanupHandle] = {}
        self._failures: list[BaseException] = []
        self._closing = False
        self._loop: asyncio.AbstractEventLoop | None = None
        self._changed = asyncio.Event()
        self._shutdown_timeout_error: LifecycleFailure | None = None

    def _check_loop(self) -> asyncio.AbstractEventLoop:
        loop = asyncio.get_running_loop()
        if self._loop is None:
            self._loop = loop
        elif self._loop is not loop:
            raise LifecycleFailure(f"Task owner {self._owner_name} used from a foreign loop")
        return loop

    @property
    def pending(self) -> tuple[asyncio.Task[Any], ...]:
        self._check_loop()
        tasks: set[asyncio.Task[Any]] = set()
        for record in self._records.values():
            if not record.task.done():
                tasks.add(record.task)
            if record.cleanup_task is not None and not record.cleanup_task.done():
                tasks.add(record.cleanup_task)
        return tuple(tasks)

    @property
    def is_idle(self) -> bool:
        """空闲还要求请求方已经结束结果/取消交接。"""
        self._check_loop()
        self._settle_all()
        return not self._records

    @property
    def business_idle(self) -> bool:
        """Ignore only records explicitly handed to resource cleanup."""
        self._check_loop()
        self._settle_all()
        return all(record.cleanup_handle_id is not None for record in self._records.values())

    def handoff_cleanup(self, task: asyncio.Task[Any], handle: ResourceCleanupHandle) -> None:
        """Transfer one expected connection task to the cleanup registry.

        The task itself must call this on its owner loop after business work
        has finished. Later owner cancellation observes the handle and does not
        cancel the task again.
        """
        from system.resource_cleanup import ResourceCleanupHandle

        self._check_loop()
        if not self._allow_cleanup_handoff:
            raise LifecycleFailure(
                f"Task owner {self._owner_name} does not allow cleanup handoff"
            )
        if asyncio.current_task() is not task:
            raise LifecycleFailure("Cleanup handoff must be called by the owned task")
        record = self._records.get(task)
        if record is None or handle.task is not task or not isinstance(handle, ResourceCleanupHandle):
            raise LifecycleFailure("Cleanup handoff requires the registered task and its handle")
        if record.waiter is not None and not record.request_released:
            raise LifecycleFailure("Cleanup handoff requires the request result to be released")
        if record.cleanup_handle_id is not None or task in self._cleanup_handles:
            raise LifecycleFailure("Cleanup handoff already exists for this task")
        record.cleanup_handle_id = f"{handle.producer.producer_id}:{handle.resource_id}"
        record.cleanup_handoff_cancel_count = task.cancelling()
        self._cleanup_handles[task] = handle
        self._changed.set()

    def _report(self, error: BaseException) -> None:
        _timeouts, remaining = split_cleanup_timeouts(error)
        if remaining is None:
            return
        if any(existing is remaining for existing in self._failures):
            return
        self._failures.append(remaining)
        self._on_failure(remaining)

    def _register(self, record: ManagedTaskRecord) -> None:
        self._records[record.task] = record
        record.task.add_done_callback(self._observe_done)
        if record.waiter is not None:
            record.waiter.add_done_callback(self._waiter_done)
        self._changed.set()

    def create(
        self,
        coro: Coroutine[Any, Any, TaskResultT],
        *,
        name: str
        ) -> asyncio.Task[TaskResultT]:
        """创建后台任务；有请求等待方时必须使用 run_request。"""
        try:
            loop = self._check_loop()
            if self._closing:
                raise LifecycleFailure(f"Task owner {self._owner_name} is closing")
        except BaseException:
            coro.close()
            raise
        gate: asyncio.Future[None] = loop.create_future()
        started = False

        async def invoke() -> TaskResultT:
            nonlocal started
            await gate
            started = True
            return await coro

        wrapper = invoke()
        try:
            task = asyncio.create_task(wrapper, name=name)
        except BaseException:
            wrapper.close()
            coro.close()
            raise

        def release_unstarted(done: asyncio.Task[TaskResultT]) -> None:
            if not started:
                coro.close()

        task.add_done_callback(release_unstarted)
        self.track(task)
        gate.set_result(None)
        return task

    def track(self, task: asyncio.Task[TaskResultT]) -> asyncio.Task[TaskResultT]:
        loop = self._check_loop()
        if self._closing:
            raise LifecycleFailure(f"Task owner {self._owner_name} is closing")
        if task.get_loop() is not loop:
            raise LifecycleFailure(f"Task owner {self._owner_name} received a foreign-loop task")
        existing = self._records.get(task)
        if existing is not None:
            if existing.ownership != TaskOwnership.BACKGROUND:
                raise LifecycleFailure("A request task cannot be reclassified as background")
            return task
        self._register(ManagedTaskRecord(
            task=task,
            ownership=TaskOwnership.BACKGROUND,
            cancel_timeout=SYSTEM_QUIESCE_TIMEOUT_SECONDS,
        ))
        return task

    def _observe_done(self, task: asyncio.Task[Any]) -> None:
        record = self._records.get(task)
        if record is not None:
            self._settle(record)
        self._changed.set()

    def _settle(self, record: ManagedTaskRecord) -> None:
        """唯一终局分类入口；读取结果不等于已交还给请求方。"""
        task = record.task
        if not task.done():
            return
        if task.cancelled():
            if record.cleanup_handle_id is not None:
                if task.cancelling() > record.cleanup_handoff_cancel_count:
                    record.terminal_error = LifecycleFailure(
                        f"Task {task.get_name()} received a new cancellation after cleanup handoff"
                    )
            elif not record.expected_cancel and record.terminal_error is None:
                record.terminal_error = LifecycleFailure(
                    f"Task {task.get_name()} owned by {self._owner_name} cancelled without an owner request"
                )
        elif record.terminal_error is None:
            error = task.exception()
            if error is not None:
                _timeouts, remaining = split_cleanup_timeouts(error)
                if remaining is None:
                    error = None
                else:
                    error = remaining
            if error is not None:
                if record.cleanup_handle_id is not None:
                    error = None
                elif _only_cancellations(error):
                    if not record.expected_cancel:
                        record.terminal_error = LifecycleFailure(
                            f"Task {task.get_name()} ended with an unexpected cancellation group"
                        )
                        record.terminal_error.__cause__ = error
                elif record.expected_cancel and not contains_lifecycle_failure(error):
                    record.terminal_error = LifecycleFailure(
                        f"Task {task.get_name()} failed during cancellation cleanup"
                    )
                    record.terminal_error.__cause__ = error
                else:
                    record.terminal_error = error

        error = record.terminal_error
        abandoned = record.request_released and not record.result_delivered
        should_report = error is not None and (
            record.ownership == TaskOwnership.BACKGROUND
            or contains_lifecycle_failure(error)
            or abandoned
        )
        if (
            error is not None
            and record.expected_failure
            and record.ownership == TaskOwnership.BACKGROUND
            and not contains_lifecycle_failure(error)
        ):
            # 预期失败（如连接级驱逐）不上报所属 System，仅记录终局异常。
            should_report = False
        if should_report and error is not None and not record.terminal_reported:
            record.terminal_reported = True
            self._report(error)
        self._retire(record)

    def _retire(self, record: ManagedTaskRecord) -> None:
        if not record.task.done():
            return
        if record.cleanup_task is not None and not record.cleanup_task.done():
            return
        if record.ownership == TaskOwnership.REQUEST and not record.request_released:
            return
        if self._records.get(record.task) is record:
            del self._records[record.task]
            if record.waiter is not None and not any(
                other.waiter is record.waiter for other in self._records.values()
            ):
                record.waiter.remove_done_callback(self._waiter_done)
            self._changed.set()

    def _settle_all(self) -> None:
        for record in tuple(self._records.values()):
            self._settle(record)

    def _waiter_done(self, waiter: asyncio.Task[Any]) -> None:
        for record in tuple(self._records.values()):
            if record.waiter is waiter and not record.request_released:
                record.request_released = True
                if not record.task.done():
                    self.cancel(record.task)
                self._settle(record)
        self._changed.set()

    def cancel(self, task: asyncio.Task[Any]) -> bool:
        """请求单次预期取消，不关闭 Owner，也不重复打断任务 finally。"""
        loop = self._check_loop()
        record = self._records.get(task)
        if record is None:
            raise LifecycleFailure("Cannot cancel a task not registered with this owner")
        if record.cleanup_handle_id is not None:
            return False
        if task.done():
            self._settle(record)
            return False
        if record.expected_cancel:
            return False
        if task.cancelling():
            failure = LifecycleFailure(f"Task {task.get_name()} was cancelled outside its owner")
            self._report(failure)
        record.expected_cancel = True
        record.cancel_deadline = loop.time() + record.cancel_timeout
        task.cancel()
        cleanup = asyncio.create_task(
            self._wait_cancel(record), name=f"{self._owner_name}-cancel-{task.get_name()}",
        )
        record.cleanup_task = cleanup
        cleanup.add_done_callback(lambda done: self._cleanup_done(record, done))
        self._changed.set()
        return True

    def mark_expected_failure(self, task: asyncio.Task[Any]) -> bool:
        """Mark a tracked background task's terminal exception as expected.

        Expected failures are settled without reporting to the owning
        system; they represent routine per-connection eviction rather
        than process-level integrity violations. Marking is an
        unconditional precondition of settlement, so this is safe to
        call from a done callback before the owner's own settle
        callback runs. Returns False only when the record has already
        been reported/settled (terminal_reported).
        """
        self._check_loop()
        record = self._records.get(task)
        if record is None:
            raise LifecycleFailure("Cannot mark a task not registered with this owner")
        if record.terminal_reported:
            return False
        record.expected_failure = True
        if task.done():
            self._settle(record)
            return False
        return True

    async def _wait_cancel(self, record: ManagedTaskRecord) -> None:
        deadline = record.cancel_deadline
        if deadline is None:
            raise LifecycleFailure("Cancellation deadline was not registered")
        done, _ = await asyncio.wait(
            {record.task}, timeout=max(0.0, deadline - self._check_loop().time()),
        )
        if done:
            self._settle(record)
        elif record.timeout_error is None:
            failure = LifecycleFailure(
                f"Task {record.task.get_name()} owned by {self._owner_name} did not finish cancellation"
            )
            record.timeout_error = failure
            self._report(failure)

    def _cleanup_done(
        self,
        record: ManagedTaskRecord,
        task: asyncio.Task[None]
        ) -> None:
        if task.cancelled():
            self._report(LifecycleFailure("Task cancellation cleanup was itself cancelled"))
        else:
            error = task.exception()
            if error is not None:
                self._report(error)
        self._settle(record)
        self._changed.set()

    async def run_request(
        self,
        factory: Callable[[], Coroutine[Any, Any, TaskResultT]],
        *,
        name: str,
        admission: Callable[[], ContextManager[None]],
        cancel_timeout: float = SYSTEM_QUIESCE_TIMEOUT_SECONDS
        ) -> TaskResultT:
        """等待完整请求；结果交还调用方，取消后的真实任务仍由本实例持有。"""
        loop = self._check_loop()
        waiter = asyncio.current_task()
        if waiter is None:
            raise LifecycleFailure("Managed request requires a calling task")
        if cancel_timeout <= 0:
            raise ValueError("Request cancellation timeout must be positive")
        with admission():
            if self._closing:
                raise ApplicationStoppingError(f"Task owner {self._owner_name} is closing")
            gate: asyncio.Future[None] = loop.create_future()

            async def invoke() -> TaskResultT:
                await gate
                with admission():
                    if self._closing:
                        raise ApplicationStoppingError(f"Task owner {self._owner_name} is closing")
                    coro = factory()
                return await coro

            wrapper = invoke()
            try:
                task = asyncio.create_task(wrapper, name=name)
            except BaseException:
                wrapper.close()
                raise
            record = ManagedTaskRecord(
                task=task,
                ownership=TaskOwnership.REQUEST,
                waiter=waiter,
                cancel_timeout=cancel_timeout,
            )
            self._register(record)
            gate.set_result(None)

        try:
            result = await asyncio.shield(task)
            if record.expected_cancel:
                raise asyncio.CancelledError("Managed request was cancelled by its owner")
            record.result_delivered = True
            return result
        except asyncio.CancelledError as cancellation:
            if waiter.cancelling():
                # 已完成失败保留原归属，不能在事后重标为取消清理失败。
                if not task.done():
                    self.cancel(task)
                if record.cleanup_task is not None:
                    await asyncio.shield(record.cleanup_task)
                self._settle(record)
                cause = record.terminal_error or record.timeout_error
                if cause is not None:
                    raise cancellation from cause
            else:
                self._settle(record)
            raise
        except BaseException:
            record.result_delivered = True
            raise
        finally:
            # 包括请求方再次取消的路径：取消已交还，清理任务可继续持有子任务。
            record.result_delivered = True
            record.request_released = True
            self._settle(record)
            self._changed.set()

    async def cancel_and_wait(self, *, timeout: float) -> None:
        """封闭接收并等待真实结束和结果交接；不取消外部请求方。"""
        loop = self._check_loop()
        if timeout <= 0:
            raise ValueError("Task shutdown timeout must be positive")
        current = asyncio.current_task()
        if any(
            current is record.task or current is record.waiter or current is record.cleanup_task
            for record in self._records.values()
        ):
            raise LifecycleFailure(f"Task owner {self._owner_name} cannot wait for itself")
        self._closing = True
        deadline = loop.time() + timeout
        for record in tuple(self._records.values()):
            self.cancel(record.task)
        while self._records:
            self._changed.clear()
            self._settle_all()
            if not self._records:
                break
            remaining = deadline - loop.time()
            if remaining <= 0:
                break
            try:
                await asyncio.wait_for(self._changed.wait(), timeout=remaining)
            except asyncio.TimeoutError:
                break
        self._settle_all()
        if self._records and self._shutdown_timeout_error is None:
            self._shutdown_timeout_error = LifecycleFailure(
                f"Task owner {self._owner_name} did not finish task cleanup and result handoff within {timeout}s"
            )
            self._report(self._shutdown_timeout_error)
        if self._failures:
            raise BaseExceptionGroup(f"Task owner {self._owner_name} failed", list(self._failures))


async def close_resources(
    actions: Sequence[Callable[[], Awaitable[None]]],
) -> None:
    """完成必要释放后传播原始失败；仅用于资源收尾，不恢复业务。"""
    failures: list[BaseException] = []
    for action in actions:
        try:
            await action()
        except BaseException as exc:
            _timeouts, remaining = split_cleanup_timeouts(exc)
            if _timeouts:
                logger.warning(
                    "Resource cleanup timeout observed during automatic resource close"
                )
            if remaining is not None:
                failures.append(remaining)
    if failures:
        raise BaseExceptionGroup("Resource cleanup failed", failures)
