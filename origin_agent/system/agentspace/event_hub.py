"""Agentspace SSE 事件总线。"""

from __future__ import annotations

import asyncio
import threading
import uuid
from datetime import datetime, timezone

from entity.puretype import (
    AgentspaceEvent,
    AgentspaceEventKind,
    AgentspaceEventSource,
)


class AgentspaceEventHub:
    """把任意线程产生的文件事件串行投递到 Gateway 事件循环。"""

    def __init__(self, queue_size: int) -> None:
        self._queue_size = queue_size
        self._loop: asyncio.AbstractEventLoop | None = None
        self._loop_thread_id: int | None = None
        self._subscribers: dict[str, asyncio.Queue[AgentspaceEvent]] = {}
        self._sequence = 0
        self._closed = False

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        if self._loop is not None and self._loop is not loop:
            raise RuntimeError("AgentspaceEventHub is already bound to another loop")
        self._loop = loop
        self._loop_thread_id = threading.get_ident()
        self._closed = False

    def _require_loop_thread(self) -> None:
        if self._loop is None:
            raise RuntimeError("AgentspaceEventHub has not been bound to an event loop")
        if threading.get_ident() != self._loop_thread_id:
            raise RuntimeError("AgentspaceEventHub queue operations must run on its bound loop")

    def subscribe(self) -> tuple[str, asyncio.Queue[AgentspaceEvent]]:
        self._require_loop_thread()
        if self._closed:
            raise RuntimeError("AgentspaceEventHub is closed")
        subscription_id = uuid.uuid4().hex
        queue: asyncio.Queue[AgentspaceEvent] = asyncio.Queue(maxsize=self._queue_size)
        self._subscribers[subscription_id] = queue
        return subscription_id, queue

    def unsubscribe(self, subscription_id: str) -> None:
        self._require_loop_thread()
        self._subscribers.pop(subscription_id, None)

    def publish_threadsafe(self, event: AgentspaceEvent) -> None:
        loop = self._loop
        if loop is None or loop.is_closed() or self._closed:
            return
        if threading.get_ident() == self._loop_thread_id:
            self._publish_on_loop(event)
        else:
            loop.call_soon_threadsafe(self._publish_on_loop, event)

    def _publish_on_loop(self, event: AgentspaceEvent) -> None:
        self._require_loop_thread()
        if self._closed:
            return
        self._sequence += 1
        sequenced = event.model_copy(update={"sequence": self._sequence})
        for queue in tuple(self._subscribers.values()):
            if queue.full():
                while not queue.empty():
                    try:
                        queue.get_nowait()
                    except asyncio.QueueEmpty:
                        break
                self._sequence += 1
                overflow = AgentspaceEvent(
                    sequence=self._sequence,
                    kind=AgentspaceEventKind.RESYNC,
                    source=AgentspaceEventSource.SYSTEM,
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    message="event_queue_overflow",
                )
                queue.put_nowait(overflow)
                continue
            queue.put_nowait(sequenced)

    def close(self) -> None:
        self._require_loop_thread()
        self._closed = True
        self._subscribers.clear()
