"""Process-level ownership of real external-resource cleanup tasks."""

from __future__ import annotations

import asyncio
import concurrent.futures
import logging
import sys
import threading
import uuid
from collections.abc import Callable, Coroutine, Sequence
from typing import Any

from entity.constant.resource_cleanup import CleanupReservationState, CleanupState
from entity.constant.timeouts import RESOURCE_CLEANUP_POLL_SECONDS
from entity.puretype.resource_cleanup import CleanupReport, CleanupWarning
from entity.error import LifecycleFailure, ResourceCleanupTimeout
from system.cleanup_errors import CleanupErrorSink, split_cleanup_timeouts

logger = logging.getLogger(__name__)


def _log_cleanup_diagnostic(level: int, message: str, *args: object) -> None:
    try:
        logger.log(level, message, *args)
    except Exception:
        # 诊断错误不能回滚已发布的释放事实，也不能递归报告生命周期失败。
        try:
            sys.stderr.write("Evolve Agent resource diagnostic logging failed.\n")
        except Exception:
            pass


class CleanupReservation:
    """A creation permit, bound to at most one cleanup generation."""

    def __init__(self, producer: CleanupProducer) -> None:
        self._producer = producer
        self._state = CleanupReservationState.UNUSED
        self._handle: ResourceCleanupHandle | None = None

    @property
    def producer(self) -> CleanupProducer:
        return self._producer

    def bind(self, handle: ResourceCleanupHandle) -> None:
        with self._producer._registry._lock:
            if self._state is CleanupReservationState.BOUND and self._handle is handle:
                return
            if self._state is not CleanupReservationState.UNUSED:
                raise LifecycleFailure("Cleanup reservation is already consumed or returned")
            self._handle = handle
            self._state = CleanupReservationState.BOUND

    def release(self) -> None:
        with self._producer._registry._lock:
            if self._state is not CleanupReservationState.UNUSED:
                raise LifecycleFailure("Only an unused cleanup reservation can be returned")
            self._state = CleanupReservationState.RETURNED
        self._producer._release_reservation(self)

    def complete(self, handle: ResourceCleanupHandle) -> None:
        with self._producer._registry._lock:
            if self._handle is not handle:
                raise LifecycleFailure("Cleanup reservation belongs to a different handle")
            if self._state is CleanupReservationState.RETURNED:
                return
            if self._state is not CleanupReservationState.BOUND:
                raise LifecycleFailure("Cleanup reservation has not been bound")
            self._state = CleanupReservationState.RETURNED
        self._producer._release_reservation(self)

    def rollback_binding(self, handle: ResourceCleanupHandle) -> None:
        with self._producer._registry._lock:
            if self._handle is not handle or self._state is not CleanupReservationState.BOUND:
                raise LifecycleFailure("Cleanup reservation binding cannot be rolled back")
            if handle.task is not None or handle.future is not None:
                raise LifecycleFailure("A started cleanup cannot return its binding")
            self._handle = None
            self._state = CleanupReservationState.UNUSED


class CleanupProducer:
    """Creation admission; finished means no outstanding permits, not closed."""

    def __init__(self, registry: ResourceCleanupRegistry, owner: str, loop: asyncio.AbstractEventLoop) -> None:
        self.owner = owner
        self.loop = loop
        self.producer_id = uuid.uuid4().hex
        self.closed = False
        self._registry = registry
        self._reservations: set[CleanupReservation] = set()
        self.finished: concurrent.futures.Future[None] = concurrent.futures.Future()
        self.finished.set_result(None)

    def reserve(self) -> CleanupReservation:
        with self._registry._lock:
            if self.closed:
                raise LifecycleFailure(f"Cleanup producer {self.owner} is closed")
            if self.finished.done():
                self.finished = concurrent.futures.Future()
            reservation = CleanupReservation(self)
            self._reservations.add(reservation)
            return reservation

    def close(self) -> None:
        with self._registry._lock:
            self.closed = True
            finished = self.finished if not self._reservations else None
        if finished is not None and not finished.done():
            finished.set_result(None)

    def _release_reservation(self, reservation: CleanupReservation) -> None:
        with self._registry._lock:
            self._reservations.remove(reservation)
            finished = self.finished if not self._reservations else None
            if finished is not None:
                # 先发布空闲事实，新reserve据此创建新代际Future；旧等待方锁外唤醒。
                idle: concurrent.futures.Future[None] = concurrent.futures.Future()
                idle.set_result(None)
                self.finished = idle
        if finished is not None and not finished.done():
            finished.set_result(None)


class ResourceCleanupHandle:
    """One real cleanup, with success separate from physical release proof."""

    def __init__(
        self, registry: ResourceCleanupRegistry, *, producer: CleanupProducer,
        reservation: CleanupReservation, resource_id: str, phase: str,
        is_released: Callable[[], bool], cleanup_errors: CleanupErrorSink | None,
        kill_authorized: bool, task: asyncio.Task[Any] | None,
        future: concurrent.futures.Future[Any] | None, expected_cancel_count: int,
        owns_cleanup: bool,
    ) -> None:
        self.registry = registry
        self.producer = producer
        self.reservation = reservation
        self.owner = producer.owner
        self.resource_id = resource_id
        self.key = (producer.producer_id, resource_id)
        self.phase = phase
        self.is_released = is_released
        self.cleanup_errors = cleanup_errors
        self.kill_authorized = kill_authorized
        self.task = task
        self.future = future
        self.expected_cancel_count = expected_cancel_count
        self.owns_cleanup = owns_cleanup
        self.state = CleanupState.RUNNING
        self.terminal_error: BaseException | None = None
        self.task_terminal: concurrent.futures.Future[None] = concurrent.futures.Future()
        self.resources_released: concurrent.futures.Future[None] = concurrent.futures.Future()
        self._release_observed: concurrent.futures.Future[None] = concurrent.futures.Future()
        self._warning: CleanupWarning | None = None
        self._retained: list[Any] = []
        self._logged_pending = False
        self._completion_claimed = False
        self._terminal_settled = False

    @property
    def release_observed(self) -> concurrent.futures.Future[None]:
        """Physical release only; errors remain available through wait/drain."""
        return self._release_observed

    def retain(self, resource: Any) -> None:
        self._retained.append(resource)

    def set_phase(self, phase: str) -> None:
        with self.registry._lock:
            self.phase = phase

    def snapshot(self) -> CleanupReport:
        with self.registry._lock:
            return self._snapshot_locked()

    def _raise_failure(self) -> None:
        with self.registry._lock:
            error = self.terminal_error
        if error is not None:
            raise error

    async def wait(self, *, timeout: float) -> CleanupReport:
        if timeout < 0:
            raise LifecycleFailure("Cleanup observation timeout must be non-negative")
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while True:
            self.refresh_completion()
            self._raise_failure()
            if self.resources_released.done():
                return self.snapshot()
            remaining = deadline - loop.time()
            if remaining <= 0:
                self._mark_pending(timeout)
                return self.snapshot()
            await asyncio.sleep(min(RESOURCE_CLEANUP_POLL_SECONDS, remaining))

    def wait_sync(self, *, timeout: float) -> CleanupReport:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            pass
        else:
            raise LifecycleFailure("Cleanup wait_sync cannot run on an event-loop thread")
        import time
        deadline = time.monotonic() + timeout
        while True:
            self.refresh_completion()
            self._raise_failure()
            if self.resources_released.done():
                return self.snapshot()
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                self._mark_pending(timeout)
                return self.snapshot()
            try:
                self.resources_released.result(min(RESOURCE_CLEANUP_POLL_SECONDS, remaining))
            except concurrent.futures.TimeoutError:
                continue

    def refresh_completion(self) -> None:
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if running is self.producer.loop:
            self._refresh_completion()
        else:
            self.producer.loop.call_soon_threadsafe(self._refresh_completion)

    def _operation_done(self) -> bool:
        if self.task is not None:
            return self.task.done()
        if self.future is not None:
            return self.future.done()
        return False

    def _safe_released(self) -> bool:
        try:
            return self.is_released()
        except Exception as error:
            self._fail(error)
            return False

    def _refresh_completion(self) -> None:
        if self._release_observed.done() or not self._terminal_settled:
            return
        if self.state is CleanupState.FAILED:
            self.finish_failed_release()
        elif self._operation_done() and self._safe_released():
            self._mark_released()

    def _mark_pending(self, timeout: float) -> None:
        with self.registry._lock:
            if self.state not in (CleanupState.RUNNING, CleanupState.PENDING):
                return
            self.state = CleanupState.PENDING
            if self._warning is None:
                self._warning = CleanupWarning(
                    owner=self.owner, resource_id=self.resource_id, phase=self.phase,
                    timeout_seconds=timeout,
                    message=f"Resource cleanup pending: owner={self.owner} resource={self.resource_id} phase={self.phase}",
                )
            warning = self._warning
            log_pending = not self._logged_pending
            self._logged_pending = True
        if log_pending:
            _log_cleanup_diagnostic(logging.WARNING, "%s", warning.message)

    def _finish_release(self, *, failed: bool) -> None:
        with self.registry._lock:
            if self._completion_claimed:
                return
            self._completion_claimed = True
            if not failed:
                self.state = CleanupState.RELEASED
            self.registry._handles.pop(self.key, None)
            if self.task is not None:
                self.registry._tasks.pop(self.task, None)
            if self.future is not None:
                self.registry._futures.pop(self.future, None)
            self._retained.clear()
        self.reservation.complete(self)
        if not failed:
            self.resources_released.set_result(None)
        self._release_observed.set_result(None)
        _log_cleanup_diagnostic(logging.INFO, "Resource cleanup released: owner=%s resource=%s phase=%s", self.owner, self.resource_id, self.phase)

    def _mark_released(self) -> None:
        self._finish_release(failed=False)

    def finish_failed_release(self) -> None:
        if self._operation_done() and self._safe_released():
            self._finish_release(failed=True)

    def _fail(self, error: BaseException) -> None:
        with self.registry._lock:
            if self.terminal_error is not None:
                return
            self.terminal_error = error
            self.state = CleanupState.FAILED
            self.registry._terminal_failures.append((self.producer.loop, error))
        self.registry._report_failure(error)

    def _snapshot_locked(self) -> CleanupReport:
        if self.state is CleanupState.RELEASED:
            return CleanupReport(complete=True)
        return CleanupReport(
            complete=False, pending_resources=[self.resource_id],
            warnings=[self._warning] if self._warning is not None else [],
        )

    def _settle_terminal(self, error: BaseException | None, *, unauthorized_cancel: bool) -> None:
        if self._terminal_settled:
            return
        self._terminal_settled = True
        errors = list(self.cleanup_errors.take()) if self.cleanup_errors is not None else []
        if unauthorized_cancel:
            errors.append(LifecycleFailure(f"Unauthorized cleanup cancellation: {self.owner}/{self.resource_id}"))
        elif error is not None and self.owns_cleanup:
            errors.append(error)
        timeouts: list[ResourceCleanupTimeout] = []
        failures: list[BaseException] = []
        for item in errors:
            found, remaining = split_cleanup_timeouts(item)
            timeouts.extend(found)
            if remaining is not None:
                failures.append(remaining)
        if failures:
            self._fail(failures[0] if len(failures) == 1 else BaseExceptionGroup("Resource cleanup failed", failures))
        elif timeouts:
            with self.registry._lock:
                self.state = CleanupState.QUARANTINED
                self._warning = timeouts[0].warning
                log_pending = not self._logged_pending
                self._logged_pending = True
            if log_pending:
                _log_cleanup_diagnostic(logging.WARNING, "%s", timeouts[0].warning.message)
        # 终局Future只表达任务已结束；真正错误单独保留，避免无人读取的异常Future。
        self.task_terminal.set_result(None)
        self._refresh_completion()


class ResourceCleanupRegistry:
    """Owned by RuntimeSystem; native operations stay with their original owner."""

    def __init__(self, on_failure: Callable[[BaseException], None]) -> None:
        self._on_failure = on_failure
        self._lock = threading.RLock()
        self._sealed = False
        self._producers: dict[str, CleanupProducer] = {}
        self._handles: dict[tuple[str, str], ResourceCleanupHandle] = {}
        self._tasks: dict[asyncio.Task[Any], ResourceCleanupHandle] = {}
        self._futures: dict[concurrent.futures.Future[Any], ResourceCleanupHandle] = {}
        self._terminal_failures: list[tuple[asyncio.AbstractEventLoop, BaseException]] = []

    def open_producer(self, *, owner: str, loop: asyncio.AbstractEventLoop) -> CleanupProducer:
        with self._lock:
            if self._sealed:
                raise LifecycleFailure("Resource cleanup registry is sealed")
            producer = CleanupProducer(self, owner, loop)
            self._producers[producer.producer_id] = producer
            return producer

    def close_producers(self) -> None:
        with self._lock:
            self._sealed = True
            producers = tuple(self._producers.values())
        for producer in producers:
            producer.close()

    def _existing(self, reservation: CleanupReservation, resource_id: str) -> ResourceCleanupHandle | None:
        with self._lock:
            producer = reservation.producer
            if self._producers.get(producer.producer_id) is not producer:
                raise LifecycleFailure("Cleanup reservation belongs to a different registry")
            if reservation._state is CleanupReservationState.RETURNED:
                raise LifecycleFailure("A returned cleanup reservation cannot be reused")
            existing = self._handles.get((producer.producer_id, resource_id))
            if existing is not None and existing.reservation is not reservation:
                raise LifecycleFailure("Cleanup resource already has a different reservation")
            if reservation._state is CleanupReservationState.BOUND and reservation._handle is not existing:
                raise LifecycleFailure("Cleanup reservation is bound to a different resource")
            return existing

    def _new_handle(
        self, reservation: CleanupReservation, *, resource_id: str, phase: str,
        is_released: Callable[[], bool], cleanup_errors: CleanupErrorSink | None,
        kill_authorized: bool, expected_cancel_count: int, owns_cleanup: bool,
    ) -> ResourceCleanupHandle:
        handle = ResourceCleanupHandle(
            self, producer=reservation.producer, reservation=reservation,
            resource_id=resource_id, phase=phase, is_released=is_released,
            cleanup_errors=cleanup_errors, kill_authorized=kill_authorized,
            task=None, future=None, expected_cancel_count=expected_cancel_count,
            owns_cleanup=owns_cleanup,
        )
        with self._lock:
            if self._existing(reservation, resource_id) is not None:
                raise LifecycleFailure("Cleanup resource was concurrently registered")
            reservation.bind(handle)
            self._handles[handle.key] = handle
        return handle

    def begin(
        self, reservation: CleanupReservation, *, resource_id: str, phase: str,
        factory: Callable[[], Coroutine[Any, Any, None]], is_released: Callable[[], bool],
        kill_authorized: bool = False, cleanup_errors: CleanupErrorSink | None = None,
    ) -> ResourceCleanupHandle:
        self._require_owner_loop(reservation)
        existing = self._existing(reservation, resource_id)
        if existing is not None:
            if not existing.owns_cleanup:
                raise LifecycleFailure("Cleanup generation belongs to an adopted task")
            return existing
        handle = self._new_handle(
            reservation, resource_id=resource_id, phase=phase, is_released=is_released,
            cleanup_errors=cleanup_errors, kill_authorized=kill_authorized,
            expected_cancel_count=0, owns_cleanup=True,
        )
        started = asyncio.Event()

        async def run() -> None:
            await started.wait()
            await factory()

        coroutine = run()
        try:
            task = asyncio.get_running_loop().create_task(coroutine)
        except BaseException:
            coroutine.close()
            with self._lock:
                self._handles.pop(handle.key)
                reservation.rollback_binding(handle)
            raise
        handle.task = task
        with self._lock:
            self._tasks[task] = handle
        task.add_done_callback(lambda done: self._on_task_done(handle, done))
        started.set()
        return handle

    def adopt_task(
        self, reservation: CleanupReservation, *, resource_id: str, phase: str,
        task: asyncio.Task[Any], is_released: Callable[[], bool], expected_cancel_count: int = 0,
        cleanup_errors: CleanupErrorSink | None = None, kill_authorized: bool = False,
    ) -> ResourceCleanupHandle:
        self._require_owner_loop(reservation)
        if task.get_loop() is not reservation.producer.loop:
            raise LifecycleFailure("Cleanup task loop does not match its producer")
        existing = self._existing(reservation, resource_id)
        with self._lock:
            previous = self._tasks.get(task)
        if existing is not None:
            if existing.task is not task or existing.owns_cleanup:
                raise LifecycleFailure("Cleanup generation belongs to a different task")
            return existing
        if previous is not None:
            raise LifecycleFailure("Cleanup task already belongs to a different resource")
        handle = self._new_handle(
            reservation, resource_id=resource_id, phase=phase, is_released=is_released,
            cleanup_errors=cleanup_errors, kill_authorized=kill_authorized,
            expected_cancel_count=expected_cancel_count, owns_cleanup=False,
        )
        handle.task = task
        with self._lock:
            self._tasks[task] = handle
        if task.done():
            self._on_task_done(handle, task)
        else:
            task.add_done_callback(lambda done: self._on_task_done(handle, done))
        return handle

    def adopt_future(
        self, reservation: CleanupReservation, *, resource_id: str, phase: str,
        future: concurrent.futures.Future[Any], is_released: Callable[[], bool],
        kill_authorized: bool = False,
    ) -> ResourceCleanupHandle:
        if isinstance(future, asyncio.Future):
            raise LifecycleFailure("adopt_future requires a concurrent future")
        # 此入口可从工作线程登记真实Future；创建/消费在同一个registry锁事务内。
        with self._lock:
            existing = self._existing(reservation, resource_id)
            if existing is not None:
                if existing.future is not future:
                    raise LifecycleFailure("Cleanup generation belongs to a different future")
                return existing
            if future in self._futures:
                raise LifecycleFailure("Cleanup future already belongs to a different resource")
            handle = self._new_handle(
                reservation, resource_id=resource_id, phase=phase, is_released=is_released,
                cleanup_errors=None, kill_authorized=kill_authorized,
                expected_cancel_count=0, owns_cleanup=True,
            )
            handle.future = future
            self._futures[future] = handle
        reservation.producer.loop.call_soon_threadsafe(self._watch_future, handle, future)
        return handle

    def begin_threadsafe(
        self, reservation: CleanupReservation, *, resource_id: str, phase: str,
        factory: Callable[[], Coroutine[Any, Any, None]], is_released: Callable[[], bool],
        kill_authorized: bool = False,
    ) -> concurrent.futures.Future[ResourceCleanupHandle]:
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if running is reservation.producer.loop:
            raise LifecycleFailure("begin_threadsafe cannot wait on its owner loop")
        result: concurrent.futures.Future[ResourceCleanupHandle] = concurrent.futures.Future()

        def start() -> None:
            if not result.set_running_or_notify_cancel():
                return
            try:
                handle = self.begin(
                    reservation, resource_id=resource_id, phase=phase, factory=factory,
                    is_released=is_released, kill_authorized=kill_authorized,
                )
            except BaseException as error:
                result.set_exception(error)
            else:
                result.set_result(handle)

        reservation.producer.loop.call_soon_threadsafe(start)
        return result

    async def wait_many(self, handles: Sequence[ResourceCleanupHandle], *, timeout: float) -> CleanupReport:
        results = await asyncio.gather(*(handle.wait(timeout=timeout) for handle in handles), return_exceptions=True)
        failures = [result for result in results if isinstance(result, BaseException)]
        if failures:
            raise BaseExceptionGroup("Resource cleanup observation failed", failures)
        return self._combine(handles)

    def snapshot(self) -> CleanupReport:
        with self._lock:
            report = self._combine_locked(tuple(self._handles.values()))
            if self._terminal_failures:
                report.complete = False
            return report

    async def drain_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        await self._drain(loop)

    async def drain(self) -> None:
        with self._lock:
            if not self._sealed:
                raise LifecycleFailure("Cleanup producers must be sealed before final drain")
        await self._drain(None)

    async def _drain(self, loop: asyncio.AbstractEventLoop | None) -> None:
        while True:
            with self._lock:
                producers = tuple(p for p in self._producers.values() if loop is None or p.loop is loop)
                handles = tuple(h for h in self._handles.values() if loop is None or h.producer.loop is loop)
            for handle in handles:
                handle.refresh_completion()
            with self._lock:
                remaining = any(loop is None or h.producer.loop is loop for h in self._handles.values())
                finished = all(p.finished.done() and (loop is not None or p.closed) for p in producers)
                failures = [error for owner_loop, error in self._terminal_failures if loop is None or owner_loop is loop]
            if finished and not remaining:
                if failures:
                    raise BaseExceptionGroup("Resource cleanup failed", failures)
                return
            await asyncio.sleep(RESOURCE_CLEANUP_POLL_SECONDS)

    def _require_owner_loop(self, reservation: CleanupReservation) -> None:
        if asyncio.get_running_loop() is not reservation.producer.loop:
            raise LifecycleFailure("Cleanup registration must run on the producer loop")

    def _watch_future(self, handle: ResourceCleanupHandle, future: concurrent.futures.Future[Any]) -> None:
        if not future.done():
            handle.producer.loop.call_later(RESOURCE_CLEANUP_POLL_SECONDS, self._watch_future, handle, future)
            return
        error = LifecycleFailure("Owned cleanup future was cancelled") if future.cancelled() else future.exception()
        handle._settle_terminal(error, unauthorized_cancel=future.cancelled())

    def _on_task_done(self, handle: ResourceCleanupHandle, task: asyncio.Task[Any]) -> None:
        def classify() -> None:
            cancelled = task.cancelled()
            error = None if cancelled else task.exception()
            handle._settle_terminal(
                error,
                unauthorized_cancel=cancelled and (
                    handle.owns_cleanup or task.cancelling() > handle.expected_cancel_count
                ),
            )
        handle.producer.loop.call_soon_threadsafe(classify)

    def _report_failure(self, error: BaseException) -> None:
        self._on_failure(error)

    def _combine(self, handles: Sequence[ResourceCleanupHandle]) -> CleanupReport:
        with self._lock:
            return self._combine_locked(handles)

    def _combine_locked(self, handles: Sequence[ResourceCleanupHandle]) -> CleanupReport:
        reports = [handle._snapshot_locked() for handle in handles]
        return CleanupReport(
            complete=all(report.complete for report in reports),
            pending_resources=[resource for report in reports for resource in report.pending_resources],
            warnings=[warning for report in reports for warning in report.warnings],
        )
