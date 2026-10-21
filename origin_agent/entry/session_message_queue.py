"""主会话输入队列：先同步登记投递记录，再通过主loop唤醒消费者。"""

from __future__ import annotations

from interface.runtime_system import IRuntimeSystem

import asyncio
import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from entity.constant import ApplicationState, SYSTEM_CHARACTER_NAME, SYSTEM_QUIESCE_TIMEOUT_SECONDS
from entity.puretype import (
    InputDelivery, MainSessionActivityPhase, MainSessionActivitySource,
    MessageContent, QueuedMessage, ShutdownInputReport,
)
from entry.input_delivery import InputDeliveryBuffer, ToolInputReservation
from system.lifecycle import ApplicationStoppingError, LifecycleFailure

if TYPE_CHECKING:
    from entry.base_agent_loop import IMainSessionLoop


_QUEUE_ACTIVITY_SOURCES: dict[str, MainSessionActivitySource] = {
    "ws": MainSessionActivitySource.user_message,
    "dynamic-endpoint": MainSessionActivitySource.dynamic_endpoint,
    "subagent": MainSessionActivitySource.subagent_feedback,
    "cron": MainSessionActivitySource.cron,
}


def activity_source_for_items(items: list[QueuedMessage]) -> MainSessionActivitySource:
    sources = {_QUEUE_ACTIVITY_SOURCES.get(item.source, MainSessionActivitySource.other) for item in items}
    if not sources:
        return MainSessionActivitySource.other
    return next(iter(sources)) if len(sources) == 1 else MainSessionActivitySource.mixed


class SessionMessageQueue:
    """InputDeliveryBuffer是唯一输入记录表；本类只持有消费任务与唤醒事件。"""

    def __init__(self, loop: IMainSessionLoop) -> None:
        self._loop = loop
        self._runtime = loop.loop.app.get_system(IRuntimeSystem)
        self._event_loop = self._runtime.loop
        self._input_buffer = InputDeliveryBuffer[QueuedMessage](self._runtime)
        self._wakeup = asyncio.Event()
        self._consumer_task: asyncio.Task[None] | None = None
        self._round_tasks: set[asyncio.Task[Any]] = set()
        self._tool_reservations: list[ToolInputReservation] = []
        self._stop_task: asyncio.Task[None] | None = None
        self._failures: list[BaseException] = []
        self._handoff_pending = False
        self._handoff_ready = asyncio.Event()
        self._handoff_ready.set()
        self.last_known_sid = loop.loop.session_id

    def push(self, content: MessageContent, *, character_name: str = "", source: str = "",
             timestamp: str = "", client_message_id: str | None = None,
             visible_characters: list[str] | None = None,
             response_characters: list[str] | None = None,
             llm_profile_name: str | None = None, ready: bool = True) -> int:
        item = QueuedMessage(
            content=content, character_name=character_name or SYSTEM_CHARACTER_NAME, source=source,
            timestamp=timestamp or datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3],
            client_message_id=client_message_id, visible_characters=visible_characters,
            response_characters=response_characters, llm_profile_name=llm_profile_name,
        )
        return self.accept(item, ready=ready)

    def accept(self, item: QueuedMessage, *, ready: bool = True) -> int:
        sequence = self._input_buffer.accept(item, ready=ready)
        try:
            self._event_loop.call_soon_threadsafe(self._wake_on_loop)
        except BaseException as error:
            # 已登记记录不能丢；唤醒失败进入失败关闭，由记录承担必要保存。
            self._runtime.record_failure(error)
            raise
        return sequence

    def mark_ready(self, sequence: int) -> None:
        self._input_buffer.mark_ready(sequence)
        self._event_loop.call_soon_threadsafe(self._wake_on_loop)

    def _wake_on_loop(self) -> None:
        if self._handoff_pending or self._input_buffer.frozen or self._runtime.state is not ApplicationState.RUNNING:
            return
        records = self._input_buffer.uncommitted()
        if records:
            activity = self._loop.loop.get_main_session_activity()
            if activity is None or activity.phase is MainSessionActivityPhase.queued:
                self._loop.loop.ensure_main_session_activity(activity_source_for_items([records[0].payload]))
        if self._consumer_task is None:
            self._consumer_task = asyncio.create_task(self._consume_loop(), name=f"input-consumer-{self.last_known_sid}")
            self._consumer_task.add_done_callback(self._consumer_done)
        self._wakeup.set()

    def _record_failure(self, error: BaseException) -> None:
        if not any(existing is error for existing in self._failures):
            self._failures.append(error)
        self._runtime.record_failure(error)

    def _consumer_done(self, task: asyncio.Task[None]) -> None:
        if self._consumer_task is task:
            self._consumer_task = None
        if task.cancelled():
            if not self._input_buffer.frozen:
                self._record_failure(LifecycleFailure("Input consumer cancelled without a stop request"))
        else:
            error = task.exception()
            if error is not None:
                self._record_failure(error)

    def _round_done(self, task: asyncio.Task[Any], reservation_id: str) -> None:
        self._round_tasks.discard(task)
        self._input_buffer.release_reservation(reservation_id)
        if not task.cancelled():
            error = task.exception()
            if error is not None and not (
                isinstance(error, ApplicationStoppingError)
                and (self._input_buffer.frozen or self._runtime.state is not ApplicationState.RUNNING)
            ):
                self._record_failure(error)

    async def _consume_loop(self) -> None:
        while not self._input_buffer.frozen and self._runtime.state is ApplicationState.RUNNING:
            self._wakeup.clear()
            reservation_id = uuid.uuid4().hex
            items = self._input_buffer.reserve_pending(reservation_id=reservation_id)
            if not items:
                await self._wakeup.wait()
                continue
            task = asyncio.create_task(self._loop.run_pending_round(items), name=f"input-round-{self.last_known_sid}")
            self._round_tasks.add(task)
            task.add_done_callback(lambda done, key=reservation_id: self._round_done(done, key))
            try:
                await asyncio.shield(task)
            except ApplicationStoppingError:
                if not self._input_buffer.frozen and self._runtime.state is ApplicationState.RUNNING:
                    raise
                return
            except asyncio.CancelledError:
                current = asyncio.current_task()
                if current is not None and current.cancelling():
                    if not task.done() and not task.cancelling():
                        task.cancel()
                    raise
                # 用户仅中断子轮次，消费者保留；输入仍由记录表负责。
                if not task.cancelled():
                    raise
            finally:
                if task.done():
                    self._input_buffer.release_reservation(reservation_id)

    def require_reply_admission(self) -> None:
        if self._input_buffer.frozen:
            raise ApplicationStoppingError("Session replies have been closed")

    def hold_for_handoff(self) -> None:
        if self._consumer_task is not None:
            raise LifecycleFailure("A replacement queue must be held before consumption starts")
        self._handoff_pending = True
        self._handoff_ready.clear()

    async def wait_handoff(self) -> None:
        await self._handoff_ready.wait()

    async def transfer_after_round(self, target: SessionMessageQueue) -> None:
        self.freeze()
        tasks: set[asyncio.Task[Any]] = set(self._round_tasks)
        if self._consumer_task is not None:
            tasks.add(self._consumer_task)
        if tasks:
            await asyncio.wait(tasks)
            for task in tasks:
                if not task.cancelled():
                    error = task.exception()
                    if error is not None and not isinstance(error, ApplicationStoppingError):
                        raise error
        if self._failures:
            raise BaseExceptionGroup("Cannot hand off a failed input queue", list(self._failures))
        self._input_buffer.transfer_to(target._input_buffer)
        target._handoff_pending = False
        target._handoff_ready.set()
        target._wake_on_loop()

    def abort_tool_reservations(self) -> None:
        for reservation in self._tool_reservations:
            reservation.abort()
        self._tool_reservations.clear()

    def new_tool_reservation(self) -> ToolInputReservation:
        reservation = ToolInputReservation(self._input_buffer, uuid.uuid4().hex)
        self._tool_reservations.append(reservation)
        return reservation

    def mark_appended(self, delivery: InputDelivery[QueuedMessage], index: int) -> None:
        self._input_buffer.mark_appended(delivery.sequence, index)

    def mark_persisted(self, items: list[InputDelivery[QueuedMessage]]) -> None:
        self._input_buffer.mark_persisted([item.sequence for item in items])

    def freeze(self) -> None:
        self._input_buffer.freeze()
        self._event_loop.call_soon_threadsafe(self._wakeup.set)

    def freeze_inputs(self) -> None:
        self.freeze()

    def accept_shutdown_transfer(self, sequence: int, item: QueuedMessage) -> None:
        if asyncio.get_running_loop() is not self._event_loop:
            raise LifecycleFailure("Shutdown transfer requires the owning event loop")
        self._input_buffer.accept_shutdown_transfer(sequence, item)

    def pending_deliveries(self) -> list[InputDelivery[QueuedMessage]]:
        return self._input_buffer.uncommitted()

    def shutdown_report(self) -> ShutdownInputReport:
        return self._input_buffer.shutdown_report()

    def reserve_shutdown(self) -> list[InputDelivery[QueuedMessage]]:
        if self._round_tasks or (self._consumer_task is not None and not self._consumer_task.done()):
            raise LifecycleFailure("Cannot collect shutdown inputs while consumer or rounds are active")
        return self._input_buffer.reserve_shutdown(reservation_id=uuid.uuid4().hex)

    def release_shutdown(self, items: list[InputDelivery[QueuedMessage]]) -> None:
        for item in items:
            if item.reservation_id is not None:
                self._input_buffer.release_reservation(item.reservation_id)

    @property
    def active_round_tasks(self) -> tuple[asyncio.Task[Any], ...]:
        return tuple(self._round_tasks)

    async def _stop_processing(self) -> None:
        tasks: set[asyncio.Task[Any]] = set(self._round_tasks)
        if self._consumer_task is not None:
            tasks.add(self._consumer_task)
        for task in tasks:
            if not task.done() and not task.cancelling():
                task.cancel()
        if tasks:
            done, pending = await asyncio.wait(tasks, timeout=SYSTEM_QUIESCE_TIMEOUT_SECONDS)
            for task in done:
                if not task.cancelled():
                    error = task.exception()
                    if error is not None and not isinstance(error, ApplicationStoppingError):
                        self._record_failure(error)
            if pending:
                self._record_failure(LifecycleFailure("Session input tasks did not finish shutdown"))
        if self._failures:
            raise BaseExceptionGroup("Session input shutdown failed", list(self._failures))

    async def stop_processing(self) -> None:
        self.freeze()
        if self._stop_task is None:
            self._stop_task = asyncio.create_task(self._stop_processing(), name=f"input-stop-{self.last_known_sid}")
            self._stop_task.add_done_callback(self._observe_stop)
        await asyncio.shield(self._stop_task)

    def _observe_stop(self, task: asyncio.Task[None]) -> None:
        if task.cancelled():
            self._record_failure(LifecycleFailure("Input shutdown coordination was cancelled"))
        else:
            error = task.exception()
            if error is not None:
                self._runtime.record_failure(error)

    def stop(self) -> None:
        """删除/终结入口只请求停止；实际等待由会话所有者负责。"""
        self.freeze()
        self._event_loop.call_soon_threadsafe(self._cancel_consumer)

    def _cancel_consumer(self) -> None:
        if self._consumer_task is not None and not self._consumer_task.done() and not self._consumer_task.cancelling():
            self._consumer_task.cancel()

    def mark_stopped(self) -> None:
        """替换Loop不取消正在执行切换工具的回复，记录交接由SessionManager负责。"""
        self.freeze()
