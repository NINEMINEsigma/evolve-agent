"""Process-level ownership for external resource cleanup.

The registry records identity, loops, real tasks, and terminal facts. It does
not locate PIDs, kill processes, close PTYs, or read business state.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import logging
import threading
import uuid
from collections.abc import Callable, Coroutine, Sequence
from typing import Any

from entity.constant.resource_cleanup import CleanupState
from entity.constant.timeouts import RESOURCE_CLEANUP_POLL_SECONDS
from entity.puretype.resource_cleanup import CleanupReport, CleanupWarning
from system.cleanup_errors import (
    CleanupErrorSink,
    ResourceCleanupTimeout,
    split_cleanup_timeouts,
)
from system.lifecycle import LifecycleFailure

logger = logging.getLogger(__name__)


class CleanupReservation:
    """One creation permit. A handle consumes it exactly once."""

    def __init__(self, producer: CleanupProducer) -> None:
        self._producer = producer
        self._released = False

    @property
    def producer(self) -> CleanupProducer:
        return self._producer

    def release(self) -> None:
        """Return an unused permit. A consumed permit cannot be released here."""
        if self._released:
            raise LifecycleFailure("Cleanup reservation released twice")
        self._released = True
        self._producer._release_reservation(self)


class CleanupProducer:
    """Barrier that prevents new resource creation after close."""

    def __init__(
        self,
        registry: ResourceCleanupRegistry,
        owner: str,
        loop: asyncio.AbstractEventLoop,
    ) -> None:
        self.owner = owner
        self.loop = loop
        self.producer_id = uuid.uuid4().hex
        self.closed = False
        self._registry = registry
        self._reservations: set[CleanupReservation] = set()
        self.finished: concurrent.futures.Future[None] = concurrent.futures.Future()
        self.finished.set_result(None)

    def reserve(self) -> CleanupReservation:
        """Reserve before native resource creation. Closing rejects new permits."""
        with self._registry._lock:
            if self.closed:
                raise LifecycleFailure(
                    f"Cleanup producer {self.owner} is closed and cannot reserve"
                )
            if self.finished.done():
                self.finished = concurrent.futures.Future()
            reservation = CleanupReservation(self)
            self._reservations.add(reservation)
            return reservation

    def close(self) -> None:
        """Reject future reservations without cancelling existing ones."""
        with self._registry._lock:
            self.closed = True
            if not self._reservations and not self.finished.done():
                self.finished.set_result(None)

    def _release_reservation(self, reservation: CleanupReservation) -> None:
        with self._registry._lock:
            self._reservations.discard(reservation)
            if self.closed and not self._reservations and not self.finished.done():
                self.finished.set_result(None)


class ResourceCleanupHandle:
    """One resource generation and its separately observed release condition."""

    def __init__(
        self,
        registry: ResourceCleanupRegistry,
        *,
        producer: CleanupProducer,
        reservation: CleanupReservation,
        resource_id: str,
        phase: str,
        is_released: Callable[[], bool],
        cleanup_errors: CleanupErrorSink | None,
        kill_authorized: bool,
        task: asyncio.Task[Any] | None,
        future: concurrent.futures.Future[Any] | None,
        expected_cancel_count: int,
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
        self.state = CleanupState.RUNNING
        self.task_terminal: concurrent.futures.Future[None] = concurrent.futures.Future()
        self.resources_released: concurrent.futures.Future[None] = concurrent.futures.Future()
        self._warning: CleanupWarning | None = None
        self._failure_reported = False
        self._retained: list[Any] = []
        self._logged_pending = False
        self._logged_released = False

    def retain(self, resource: Any) -> None:
        """Keep a captured resource alive until its release is proven."""
        self._retained.append(resource)

    def set_phase(self, phase: str) -> None:
        with self.registry._lock:
            self.phase = phase

    def snapshot(self) -> CleanupReport:
        with self.registry._lock:
            return self._snapshot_locked()

    async def wait(self, *, timeout: float) -> CleanupReport:
        """Observe release without cancelling the real cleanup on timeout."""
        if timeout < 0:
            raise LifecycleFailure("Cleanup observation timeout must be non-negative")
        loop = asyncio.get_running_loop()
        if loop is self.producer.loop:
            await self._observe(timeout)
        else:
            adapted = asyncio.wrap_future(self.resources_released)
            try:
                await asyncio.wait_for(asyncio.shield(adapted), timeout)
            except TimeoutError:
                adapted.cancel()
        return self.snapshot()

    def wait_sync(self, *, timeout: float) -> CleanupReport:
        """Block only outside every running event-loop thread."""
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            pass
        else:
            raise LifecycleFailure("Cleanup wait_sync cannot run on an event-loop thread")
        try:
            self.resources_released.result(timeout)
        except concurrent.futures.TimeoutError:
            if self.resources_released.done():
                self.resources_released.result()
        return self.snapshot()

    def refresh_completion(self) -> None:
        """Recheck a proven native condition without replaying SDK release."""
        loop = self.producer.loop
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if running is loop:
            self._refresh_completion()
            return
        loop.call_soon_threadsafe(self._refresh_completion)

    async def _observe(self, timeout: float) -> None:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while not self.resources_released.done():
            self.refresh_completion()
            if self.resources_released.done():
                return
            remaining = deadline - loop.time()
            if remaining <= 0:
                self._mark_pending(timeout)
                return
            try:
                await asyncio.wait_for(
                    asyncio.shield(asyncio.wrap_future(self.resources_released)),
                    min(RESOURCE_CLEANUP_POLL_SECONDS, remaining),
                )
            except TimeoutError:
                continue

    def _refresh_completion(self) -> None:
        if self.resources_released.done() or self.state is CleanupState.FAILED:
            return
        if self.state is CleanupState.QUARANTINED:
            self._complete_if_released()
            return
        terminal = self._operation_done()
        if terminal and self._safe_released():
            self._mark_released()

    def _complete_if_released(self) -> None:
        if self._safe_released():
            self._mark_released()

    def _safe_released(self) -> bool:
        try:
            return self.is_released()
        except Exception as error:
            self._fail(error)
            return False

    def _operation_done(self) -> bool:
        if self.task is not None:
            return self.task.done()
        if self.future is not None:
            return self.future.done()
        return self.task_terminal.done()

    def _mark_pending(self, timeout: float) -> None:
        warning: CleanupWarning | None = None
        with self.registry._lock:
            if self.state is not CleanupState.RUNNING or self.resources_released.done():
                return
            self.state = CleanupState.PENDING
            if self._warning is None:
                self._warning = CleanupWarning(
                    owner=self.owner,
                    resource_id=self.resource_id,
                    phase=self.phase,
                    timeout_seconds=timeout,
                    message=(
                        f"Resource cleanup pending: owner={self.owner} "
                        f"resource={self.resource_id} phase={self.phase}"
                    ),
                )
                warning = self._warning
        if warning is not None and not self._logged_pending:
            self._logged_pending = True
            logger.warning(warning.message)

    def _mark_released(self) -> None:
        reservation: CleanupReservation | None = None
        with self.registry._lock:
            if self.resources_released.done():
                return
            self.state = CleanupState.RELEASED
            if not self.task_terminal.done():
                self.task_terminal.set_result(None)
            self.resources_released.set_result(None)
            self.registry._handles.pop(self.key, None)
            reservation = self.reservation
        if reservation is not None:
            reservation.release()
        if not self._logged_released:
            self._logged_released = True
            logger.info(
                "Resource cleanup released: owner=%s resource=%s phase=%s",
                self.owner,
                self.resource_id,
                self.phase,
            )

    def _mark_quarantined(self, timeouts: Sequence[ResourceCleanupTimeout]) -> None:
        with self.registry._lock:
            if self.state in (CleanupState.RELEASED, CleanupState.FAILED):
                return
            self.state = CleanupState.QUARANTINED
            if not self.task_terminal.done():
                self.task_terminal.set_result(None)
            if timeouts and self._warning is None:
                self._warning = timeouts[0].warning
        for timeout in timeouts:
            if not self._logged_pending:
                self._logged_pending = True
                logger.warning(timeout.warning.message)

    def _fail(self, error: BaseException) -> None:
        reportable = error
        with self.registry._lock:
            if self._failure_reported or self.state is CleanupState.FAILED:
                return
            self.state = CleanupState.FAILED
            self._failure_reported = True
            if not self.task_terminal.done():
                self.task_terminal.set_exception(error)
        self.registry._report_failure(reportable)

    def _snapshot_locked(self) -> CleanupReport:
        if self.state is CleanupState.RELEASED:
            return CleanupReport(complete=True)
        warning = self._warning
        return CleanupReport(
            complete=False,
            pending_resources=[self.resource_id],
            warnings=[warning] if warning is not None else [],
        )

    def _settle_terminal(self, error: BaseException | None, *, unauthorized_cancel: bool) -> None:
        if self.cleanup_errors is not None:
            sink_errors = self.cleanup_errors.take()
        else:
            sink_errors = ()
        timeouts: list[ResourceCleanupTimeout] = []
        remaining: list[BaseException] = []
        for sink_error in sink_errors:
            found, rest = split_cleanup_timeouts(sink_error)
            timeouts.extend(found)
            if rest is not None:
                remaining.append(rest)
        if remaining:
            if len(remaining) == 1:
                self._fail(remaining[0])
            else:
                self._fail(BaseExceptionGroup("resource cleanup failed", remaining))
            return
        if timeouts:
            self._mark_quarantined(timeouts)
            self._complete_if_released()
            return
        if unauthorized_cancel:
            self._fail(LifecycleFailure(
                f"Unauthorized cleanup cancellation: {self.owner}/{self.resource_id}"
            ))
            return
        if error is not None and self.task is not None:
            # A business exception belongs to the original owner. Cleanup facts
            # come only from the sink, cancellation count, and release proof.
            pass
        if self._safe_released():
            self._mark_released()
        elif self.future is not None and error is not None:
            found, rest = split_cleanup_timeouts(error)
            if rest is None and found:
                self._mark_quarantined(found)
            elif rest is not None:
                self._fail(rest)


class ResourceCleanupRegistry:
    """The single process-level cleanup registry owned by RuntimeSystem."""

    def __init__(self, on_failure: Callable[[BaseException], None]) -> None:
        self._on_failure = on_failure
        self._lock = threading.RLock()
        self._producers: dict[str, CleanupProducer] = {}
        self._handles: dict[tuple[str, str], ResourceCleanupHandle] = {}
        self._tasks: dict[asyncio.Task[Any], ResourceCleanupHandle] = {}
        self._futures: dict[concurrent.futures.Future[Any], ResourceCleanupHandle] = {}

    def open_producer(
        self,
        *,
        owner: str,
        loop: asyncio.AbstractEventLoop,
    ) -> CleanupProducer:
        producer = CleanupProducer(self, owner, loop)
        with self._lock:
            self._producers[producer.producer_id] = producer
        return producer

    def begin(
        self,
        reservation: CleanupReservation,
        *,
        resource_id: str,
        phase: str,
        factory: Callable[[], Coroutine[Any, Any, None]],
        is_released: Callable[[], bool],
        kill_authorized: bool = False,
        cleanup_errors: CleanupErrorSink | None = None,
    ) -> ResourceCleanupHandle:
        self._require_owner_loop(reservation)
        started = threading.Event()

        async def _run() -> None:
            started.wait()
            await factory()

        task = asyncio.get_running_loop().create_task(_run())
        handle = self._install(
            reservation,
            resource_id=resource_id,
            phase=phase,
            is_released=is_released,
            cleanup_errors=cleanup_errors,
            kill_authorized=kill_authorized,
            task=task,
            future=None,
            expected_cancel_count=0,
        )
        task.add_done_callback(lambda done: self._on_task_done(handle, done))
        started.set()
        return handle

    def adopt_task(
        self,
        reservation: CleanupReservation,
        *,
        resource_id: str,
        phase: str,
        task: asyncio.Task[Any],
        is_released: Callable[[], bool],
        expected_cancel_count: int = 0,
        cleanup_errors: CleanupErrorSink | None = None,
        kill_authorized: bool = False,
    ) -> ResourceCleanupHandle:
        if task.get_loop() is not reservation.producer.loop:
            raise LifecycleFailure("Cleanup task loop does not match its producer")
        self._require_owner_loop(reservation)
        existing = self._tasks.get(task)
        if existing is not None:
            if existing.key != (reservation.producer.producer_id, resource_id):
                raise LifecycleFailure("Cleanup task is already owned by another resource")
            return existing
        handle = self._install(
            reservation,
            resource_id=resource_id,
            phase=phase,
            is_released=is_released,
            cleanup_errors=cleanup_errors,
            kill_authorized=kill_authorized,
            task=task,
            future=None,
            expected_cancel_count=expected_cancel_count,
        )
        self._tasks[task] = handle
        if task.done():
            self._on_task_done(handle, task)
        else:
            task.add_done_callback(lambda done: self._on_task_done(handle, done))
        return handle

    def adopt_future(
        self,
        reservation: CleanupReservation,
        *,
        resource_id: str,
        phase: str,
        future: concurrent.futures.Future[Any],
        is_released: Callable[[], bool],
        kill_authorized: bool = False,
    ) -> ResourceCleanupHandle:
        if isinstance(future, asyncio.Future):
            raise LifecycleFailure("adopt_future requires a real concurrent future")
        existing = self._futures.get(future)
        if existing is not None:
            return existing
        handle = self._install(
            reservation,
            resource_id=resource_id,
            phase=phase,
            is_released=is_released,
            cleanup_errors=None,
            kill_authorized=kill_authorized,
            task=None,
            future=future,
            expected_cancel_count=0,
        )
        self._futures[future] = handle
        reservation.producer.loop.call_soon_threadsafe(self._watch_future, handle, future)
        return handle

    def begin_threadsafe(
        self,
        reservation: CleanupReservation,
        *,
        resource_id: str,
        phase: str,
        factory: Callable[[], Coroutine[Any, Any, None]],
        is_released: Callable[[], bool],
        kill_authorized: bool = False,
    ) -> concurrent.futures.Future[ResourceCleanupHandle]:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            pass
        else:
            if asyncio.get_running_loop() is reservation.producer.loop:
                raise LifecycleFailure("begin_threadsafe cannot wait on its owner loop")
        result: concurrent.futures.Future[ResourceCleanupHandle] = concurrent.futures.Future()

        def _start() -> None:
            if result.cancelled():
                return
            try:
                handle = self.begin(
                    reservation,
                    resource_id=resource_id,
                    phase=phase,
                    factory=factory,
                    is_released=is_released,
                    kill_authorized=kill_authorized,
                )
            except BaseException as error:
                result.set_exception(error)
                return
            result.set_result(handle)

        reservation.producer.loop.call_soon_threadsafe(_start)
        return result

    async def wait_many(
        self,
        handles: Sequence[ResourceCleanupHandle],
        *,
        timeout: float,
    ) -> CleanupReport:
        if not handles:
            return CleanupReport(complete=True)
        await asyncio.gather(
            *(handle.wait(timeout=timeout) for handle in handles),
            return_exceptions=True,
        )
        return self._combine(handles)

    def snapshot(self) -> CleanupReport:
        with self._lock:
            return self._combine_locked(tuple(self._handles.values()))

    async def drain_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        while True:
            producers, handles = self._loop_snapshot(loop)
            if all(producer.finished.done() for producer in producers) and not handles:
                return
            waits: list[asyncio.Future[Any]] = [
                asyncio.wrap_future(producer.finished)
                for producer in producers
                if not producer.finished.done()
            ]
            waits.extend(
                asyncio.wrap_future(handle.resources_released)
                for handle in handles
                if not handle.resources_released.done()
            )
            if not waits:
                await asyncio.sleep(0)
                continue
            await asyncio.wait(waits, return_when=asyncio.FIRST_COMPLETED)

    async def drain(self) -> None:
        while True:
            with self._lock:
                producers = tuple(self._producers.values())
                handles = tuple(self._handles.values())
            if (
                all(producer.closed and producer.finished.done() for producer in producers)
                and not handles
            ):
                return
            waits: list[asyncio.Future[Any]] = [
                asyncio.wrap_future(producer.finished)
                for producer in producers
                if not producer.finished.done()
            ]
            waits.extend(
                asyncio.wrap_future(handle.resources_released)
                for handle in handles
                if not handle.resources_released.done()
            )
            if not waits:
                await asyncio.sleep(0)
                continue
            await asyncio.wait(waits, return_when=asyncio.FIRST_COMPLETED)

    def _install(
        self,
        reservation: CleanupReservation,
        *,
        resource_id: str,
        phase: str,
        is_released: Callable[[], bool],
        cleanup_errors: CleanupErrorSink | None,
        kill_authorized: bool,
        task: asyncio.Task[Any] | None,
        future: concurrent.futures.Future[Any] | None,
        expected_cancel_count: int,
    ) -> ResourceCleanupHandle:
        handle = ResourceCleanupHandle(
            self,
            producer=reservation.producer,
            reservation=reservation,
            resource_id=resource_id,
            phase=phase,
            is_released=is_released,
            cleanup_errors=cleanup_errors,
            kill_authorized=kill_authorized,
            task=task,
            future=future,
            expected_cancel_count=expected_cancel_count,
        )
        with self._lock:
            current = self._handles.get(handle.key)
            if current is not None:
                return current
            self._handles[handle.key] = handle
        return handle

    def _existing(
        self,
        reservation: CleanupReservation,
        resource_id: str,
    ) -> ResourceCleanupHandle | None:
        with self._lock:
            return self._handles.get((reservation.producer.producer_id, resource_id))

    def _require_owner_loop(self, reservation: CleanupReservation) -> None:
        running = asyncio.get_running_loop()
        if running is not reservation.producer.loop:
            raise LifecycleFailure("Cleanup registration must run on the producer loop")

    def _watch_future(
        self,
        handle: ResourceCleanupHandle,
        future: concurrent.futures.Future[Any],
    ) -> None:
        if not future.done():
            reservation = handle.reservation
            reservation.producer.loop.call_later(
                RESOURCE_CLEANUP_POLL_SECONDS,
                self._watch_future,
                handle,
                future,
            )
            return
        error: BaseException | None = None
        if future.cancelled():
            error = LifecycleFailure("Owned cleanup future was cancelled")
        else:
            error = future.exception()
        handle._settle_terminal(error, unauthorized_cancel=future.cancelled())

    def _on_task_done(
        self,
        handle: ResourceCleanupHandle,
        task: asyncio.Task[Any],
    ) -> None:
        def _classify() -> None:
            error: BaseException | None = None
            unauthorized = False
            if task.cancelled():
                unauthorized = task.cancelling() > handle.expected_cancel_count
            else:
                error = task.exception()
                if isinstance(error, asyncio.CancelledError):
                    unauthorized = task.cancelling() > handle.expected_cancel_count
                    error = None
            handle._settle_terminal(error, unauthorized_cancel=unauthorized)

        handle.producer.loop.call_soon_threadsafe(_classify)

    def _report_failure(self, error: BaseException) -> None:
        logger.error("Resource cleanup failed", exc_info=error)
        self._on_failure(error)

    def _loop_snapshot(
        self,
        loop: asyncio.AbstractEventLoop,
    ) -> tuple[tuple[CleanupProducer, ...], tuple[ResourceCleanupHandle, ...]]:
        with self._lock:
            producers = tuple(
                producer for producer in self._producers.values() if producer.loop is loop
            )
            handles = tuple(
                handle for handle in self._handles.values() if handle.producer.loop is loop
            )
        return producers, handles

    def _combine(self, handles: Sequence[ResourceCleanupHandle]) -> CleanupReport:
        with self._lock:
            return self._combine_locked(handles)

    def _combine_locked(self, handles: Sequence[ResourceCleanupHandle]) -> CleanupReport:
        pending: list[str] = []
        warnings: list[CleanupWarning] = []
        for handle in handles:
            report = handle._snapshot_locked()
            pending.extend(report.pending_resources)
            warnings.extend(report.warnings)
        return CleanupReport(
            complete=not pending,
            pending_resources=pending,
            warnings=warnings,
        )
