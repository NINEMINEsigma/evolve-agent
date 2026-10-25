"""Structured in-memory activity Logger System."""

from __future__ import annotations

import asyncio
from collections import deque
from datetime import datetime, timezone
import threading
import uuid
from typing import Any

from framework import AsyncComponent
from framework.core.logger import BaseLogger, BaseLoggerComponent

from entity.constant import (
    ACTIVITY_EVENT_BUFFER_SIZE,
    ACTIVITY_EVENT_QUEUE_SIZE,
)
from entity.puretype import (
    ActivityEvent,
    ActivityEventDraft,
    ActivityEventKind,
    ActivityEventPhase,
    ActivityEventStatus,
    ActivityStreamGap,
    ActivityStreamItem,
)
from interface.logger_system import ILoggerSystem
from interface.runtime_system import IRuntimeSystem
from system.lifecycle import ApplicationStoppingError, LifecycleFailure


def validate_activity_event_draft(draft: ActivityEventDraft) -> None:
    """Validate cross-field activity semantics at the business boundary."""
    sequences = draft.input_sequences
    if sequences != sorted(set(sequences)) or any(sequence < 1 for sequence in sequences):
        raise ValueError("input_sequences must be sorted unique positive integers")

    ids = {
        "activity_id": draft.activity_id,
        "stream_id": draft.stream_id,
        "tool_call_id": draft.tool_call_id,
        "character_name": draft.character_name,
        "tool_name": draft.tool_name,
    }
    if any(value == "" for value in ids.values() if value is not None):
        raise ValueError("activity event identifiers cannot be empty strings")

    if draft.phase is ActivityEventPhase.completed:
        if draft.status not in {
            ActivityEventStatus.succeeded,
            ActivityEventStatus.failed,
            ActivityEventStatus.denied,
            ActivityEventStatus.interrupted,
        }:
            raise ValueError("completed activity events require a terminal status")
        if draft.duration_ms is None:
            raise ValueError("completed activity events require duration_ms")
    elif draft.duration_ms is not None:
        raise ValueError("duration_ms is only valid for completed activity events")

    if draft.phase is ActivityEventPhase.observed:
        if draft.kind is not ActivityEventKind.message_received:
            raise ValueError("only message_received may be observed")
        if draft.status is not ActivityEventStatus.observed:
            raise ValueError("observed message events require observed status")
        if not sequences or draft.activity_id is not None:
            raise ValueError("message_received requires input_sequences and no activity_id")
    elif draft.phase is ActivityEventPhase.started:
        if draft.status is not ActivityEventStatus.active:
            raise ValueError("started activity events require active status")
        if draft.kind is ActivityEventKind.agent_response:
            if not draft.activity_id or not draft.stream_id:
                raise ValueError("agent_response requires activity_id and stream_id")
        elif draft.kind is ActivityEventKind.tool_call:
            if not draft.activity_id or not draft.stream_id or not draft.tool_call_id or not draft.tool_name:
                raise ValueError("tool_call requires activity, stream and tool identifiers")
        else:
            raise ValueError("message_received cannot be started")
    elif draft.phase is ActivityEventPhase.completed:
        if draft.kind is ActivityEventKind.agent_response:
            if not draft.activity_id or not draft.stream_id:
                raise ValueError("agent_response requires activity_id and stream_id")
        elif draft.kind is ActivityEventKind.tool_call:
            if not draft.activity_id or not draft.stream_id or not draft.tool_call_id or not draft.tool_name:
                raise ValueError("tool_call requires activity, stream and tool identifiers")
        else:
            raise ValueError("message_received cannot be completed")


class ActivityLoggerComponent(BaseLoggerComponent, AsyncComponent):
    """Bounded activity buffer and live subscriber queues."""

    def __init__(
        self,
        capacity: int = ACTIVITY_EVENT_BUFFER_SIZE,
        queue_size: int = ACTIVITY_EVENT_QUEUE_SIZE,
        ) -> None:
        AsyncComponent.__init__(self, name="ActivityLoggerComponent")
        if capacity < 1 or queue_size < 2:
            raise ValueError("Activity Logger capacities must be positive")
        self._capacity = capacity
        self._queue_size = queue_size
        self._lock = threading.RLock()
        self._events: deque[ActivityEvent] = deque(maxlen=capacity)
        self._subscribers: dict[str, asyncio.Queue[ActivityStreamItem]] = {}
        self._sequence = 0
        self._loop: asyncio.AbstractEventLoop | None = None
        self._generation = 0
        self._closed = True

    async def init_component(self) -> None:
        loop = asyncio.get_running_loop()
        with self._lock:
            if self._loop is not None and self._loop is not loop:
                raise LifecycleFailure("Activity Logger cannot bind multiple event loops")
            self._loop = loop
            self._generation += 1
            self._closed = False

    def log(self, level: str, message: str) -> None:
        del level, message
        # Text logging remains owned by Python logging and future Rich components.
        return

    def _require_loop(self) -> asyncio.AbstractEventLoop:
        loop = self._loop
        if loop is None:
            raise LifecycleFailure("Activity Logger event loop has not been bound")
        if asyncio.get_running_loop() is not loop:
            raise LifecycleFailure("Activity Logger operation requires its owning event loop")
        return loop

    def _require_open(self) -> None:
        if self._closed:
            raise ApplicationStoppingError("Activity Logger is closed")

    def _finalize(self, draft: ActivityEventDraft) -> ActivityEvent:
        self._require_loop()
        self._require_open()
        validate_activity_event_draft(draft)
        with self._lock:
            self._sequence += 1
            event = ActivityEvent(
                sequence=self._sequence,
                timestamp=datetime.now(timezone.utc).isoformat(),
                **draft.model_dump(),
            )
            self._events.append(event)
            self._publish_locked(event)
            return event

    def record_activity(self, draft: ActivityEventDraft) -> ActivityEvent:
        return self._finalize(draft)

    def record_activity_threadsafe(self, draft: ActivityEventDraft) -> None:
        loop = self._loop
        with self._lock:
            generation = self._generation
            closed = self._closed
        if loop is None:
            raise LifecycleFailure("Activity Logger event loop has not been bound")
        if closed:
            return
        try:
            loop.call_soon_threadsafe(self._record_threadsafe, draft, generation)
        except RuntimeError:
            with self._lock:
                closed_now = self._closed
            if closed_now:
                return
            raise

    def _record_threadsafe(self, draft: ActivityEventDraft, generation: int) -> None:
        with self._lock:
            if self._closed or generation != self._generation:
                return
        try:
            self._finalize(draft)
        except ApplicationStoppingError:
            return

    def snapshot(self) -> list[ActivityEvent]:
        with self._lock:
            return list(self._events)

    def subscribe(self) -> tuple[str, asyncio.Queue[ActivityStreamItem]]:
        self._require_loop()
        self._require_open()
        subscription_id = uuid.uuid4().hex
        with self._lock:
            queue: asyncio.Queue[ActivityStreamItem] = asyncio.Queue(maxsize=self._queue_size)
            self._subscribers[subscription_id] = queue
        return subscription_id, queue

    def unsubscribe(self, subscription_id: str) -> None:
        loop = self._loop
        if loop is None:
            return
        if asyncio.get_running_loop() is not loop:
            raise LifecycleFailure("Activity Logger operation requires its owning event loop")
        with self._lock:
            self._subscribers.pop(subscription_id, None)

    def _publish_locked(self, event: ActivityEvent) -> None:
        for queue in tuple(self._subscribers.values()):
            if queue.full():
                dropped = 0
                while not queue.empty():
                    try:
                        queue.get_nowait()
                        dropped += 1
                    except asyncio.QueueEmpty:
                        break
                queue.put_nowait(ActivityStreamGap(
                    dropped=max(1, dropped),
                    timestamp=datetime.now(timezone.utc).isoformat(),
                ))
            queue.put_nowait(event)

    def shotdown(self) -> None:
        with self._lock:
            self._closed = True
            self._generation += 1
            self._subscribers.clear()
            self._events.clear()
            self._loop = None


class LoggerSystem(ILoggerSystem, BaseLogger):
    """Application System hosting the structured activity Logger component."""

    def __init__(self) -> None:
        super().__init__(dependencies=(IRuntimeSystem,))
        self._runtime: IRuntimeSystem | None = None
        self._activity_component: ActivityLoggerComponent | None = None

    @property
    def runtime(self) -> IRuntimeSystem:
        if self._runtime is None:
            raise LifecycleFailure("LoggerSystem has not been awakened")
        return self._runtime

    @property
    def _activity(self) -> ActivityLoggerComponent:
        component = self._activity_component
        if component is None:
            raise LifecycleFailure("LoggerSystem activity component is unavailable")
        return component

    async def virtual_awake(self) -> None:
        self._runtime = self.get_system(IRuntimeSystem)
        component = ActivityLoggerComponent()
        self.add_component(component)
        await component.init_component()
        self._activity_component = component

    def log(self, level: str, message: str) -> None:
        logger_components: list[BaseLoggerComponent] = [
            component
            for component in self.system_components
            if isinstance(component, BaseLoggerComponent)
        ]
        self.base_logger_log(logger_components, level, message)

    def record_activity(self, draft: ActivityEventDraft) -> ActivityEvent:
        return self._activity.record_activity(draft)

    def record_activity_threadsafe(self, draft: ActivityEventDraft) -> None:
        self._activity.record_activity_threadsafe(draft)

    def get_activity_snapshot(self) -> list[ActivityEvent]:
        return self._activity.snapshot()

    def subscribe_activity_events(self) -> tuple[str, asyncio.Queue[ActivityStreamItem]]:
        return self._activity.subscribe()

    def unsubscribe_activity_events(self, subscription_id: str) -> None:
        component = self._activity_component
        if component is None:
            return
        component.unsubscribe(subscription_id)

    async def virtual_shotdown(self) -> None:
        component = self._activity_component
        if component is not None:
            self.base_logger_shotdown((component,))
            self._activity_component = None
