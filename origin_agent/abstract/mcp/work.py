"""Native MCP work retained until the real thread and request handoff finish."""

from __future__ import annotations

import asyncio
import concurrent.futures
import threading
from collections.abc import Callable
from contextvars import copy_context
from typing import Any, TypeVar

from entity.constant import SYSTEM_QUIESCE_TIMEOUT_SECONDS
from entity.puretype.lifecycle import SyncToolCallRecord
from system.lifecycle import (
    ApplicationStoppingError, LifecycleFailure, contains_lifecycle_failure,
)

T = TypeVar("T")


def _only_stopping(error: BaseException) -> bool:
    if isinstance(error, (ApplicationStoppingError, asyncio.CancelledError)):
        return True
    return isinstance(error, BaseExceptionGroup) and all(_only_stopping(item) for item in error.exceptions)


class MCPThreadWork:
    """Own one executor on one loop; cancellation never removes live futures."""

    def __init__(self, name: str, on_failure: Callable[[BaseException], None]) -> None:
        self._name = name
        self._on_failure = on_failure
        self._executor: concurrent.futures.ThreadPoolExecutor | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._records: dict[concurrent.futures.Future[Any], SyncToolCallRecord] = {}
        self._changed = asyncio.Event()
        self._closed = False
        self._failures: list[BaseException] = []
        self._join_task: asyncio.Task[None] | None = None

    def start(self) -> None:
        if self._loop is not None:
            raise LifecycleFailure("MCP thread work cannot be started twice")
        self._loop = asyncio.get_running_loop()
        self._executor = concurrent.futures.ThreadPoolExecutor(thread_name_prefix=self._name)

    def _check_loop(self) -> asyncio.AbstractEventLoop:
        if asyncio.get_running_loop() is not self._loop:
            raise LifecycleFailure("MCP native work used from a foreign loop")
        return self._loop

    def _report(self, error: BaseException) -> None:
        if not any(item is error for item in self._failures):
            self._failures.append(error)
            self._on_failure(error)

    def _settle(self, record: SyncToolCallRecord) -> None:
        self._check_loop()
        future = record.future
        if future.done():
            error = future.exception()
            if error is not None and not record.failure_reported:
                if record.cancelled_while_running and not _only_stopping(error):
                    record.failure_reported = True
                    failure = LifecycleFailure("MCP native work failed after request cancellation")
                    failure.__cause__ = error
                    self._report(failure)
                elif contains_lifecycle_failure(error):
                    record.failure_reported = True
                    self._report(error)
            if record.request_released:
                self._records.pop(future, None)
        self._changed.set()

    async def run(self, factory: Callable[[], T]) -> T:
        loop = self._check_loop()
        if self._closed:
            raise ApplicationStoppingError("MCP native work admission is closed")
        executor = self._executor
        if executor is None:
            raise LifecycleFailure("MCP native executor is unavailable")
        context = copy_context()
        ready = threading.Event()

        def invoke() -> T:
            ready.wait()
            return context.run(factory)

        future = executor.submit(invoke)
        record = SyncToolCallRecord(future=future)
        self._records[future] = record
        future.add_done_callback(lambda done: loop.call_soon_threadsafe(self._settle, record))
        ready.set()
        adapter = asyncio.wrap_future(future)
        # 异常仍由等待方/真实Future记录负责；适配Future只消除无人读取警告。
        adapter.add_done_callback(lambda done: None if done.cancelled() else done.exception())
        try:
            return await asyncio.shield(adapter)
        except asyncio.CancelledError:
            record.cancelled_while_running = not future.done()
            raise
        finally:
            record.request_released = True
            self._settle(record)

    def close_admission(self) -> None:
        self._check_loop()
        self._closed = True

    @property
    def is_idle(self) -> bool:
        self._check_loop()
        return (
            not self._records and self._executor is None
            and (self._join_task is None or self._join_task.done())
        )

    async def wait_idle(self) -> None:
        loop = self._check_loop()
        deadline = loop.time() + SYSTEM_QUIESCE_TIMEOUT_SECONDS
        while self._records:
            self._changed.clear()
            remaining = deadline - loop.time()
            if remaining <= 0:
                error = LifecycleFailure(f"MCP native work did not stop: {self._name}")
                self._report(error)
                raise error
            try:
                await asyncio.wait_for(self._changed.wait(), remaining)
            except TimeoutError:
                continue
        if self._failures:
            raise BaseExceptionGroup("MCP native work failed", list(self._failures))

    async def close(self) -> None:
        self.close_admission()
        errors: list[BaseException] = []
        try:
            await self.wait_idle()
        except BaseException as error:
            errors.append(error)
        if not self._records and self._executor is not None:
            if self._join_task is None:
                self._join_task = asyncio.create_task(
                    asyncio.to_thread(self._executor.shutdown, wait=True),
                    name=f"{self._name}-join",
                )
                self._join_task.add_done_callback(self._observe_join)
            done, _ = await asyncio.wait({self._join_task}, timeout=SYSTEM_QUIESCE_TIMEOUT_SECONDS)
            if not done:
                error = LifecycleFailure("MCP native executor join did not complete")
                self._report(error)
                errors.append(error)
            else:
                try:
                    self._join_task.result()
                except BaseException as error:
                    errors.append(error)
                else:
                    self._executor = None
        if errors:
            raise BaseExceptionGroup("MCP native executor cleanup failed", errors)

    def _observe_join(self, task: asyncio.Task[None]) -> None:
        if task.cancelled():
            self._report(LifecycleFailure("MCP executor join was cancelled"))
        elif (error := task.exception()) is not None:
            self._report(error)
