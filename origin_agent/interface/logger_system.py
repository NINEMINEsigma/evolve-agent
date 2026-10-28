from __future__ import annotations

from typing import * # type: ignore
import asyncio
from abc import ABC, abstractmethod

from entity.puretype import ActivityEvent, ActivityEventDraft, ActivityStreamItem
from framework import AsyncSystem


class ILoggerSystem(AsyncSystem, ABC):
    """Declare structured process activity logging and subscription."""

    @abstractmethod
    def log(
        self, 
        level: str, 
        message: str
        ) -> None:
        """Dispatch a compatibility text log to Logger components."""
        ...

    @abstractmethod
    def record_activity(self, draft: ActivityEventDraft) -> ActivityEvent:
        """Record one Draft on the owning event loop and return its final event."""
        ...

    @abstractmethod
    def record_activity_threadsafe(self, draft: ActivityEventDraft) -> None:
        """Queue one Draft from a non-owning thread without blocking it."""
        ...

    @abstractmethod
    def get_activity_snapshot(self) -> list[ActivityEvent]:
        """Return the bounded in-memory event snapshot for future readers."""
        ...

    @abstractmethod
    def subscribe_activity_events(self) -> tuple[str, asyncio.Queue[ActivityStreamItem]]:
        """Create one live subscription without replaying the event buffer."""
        ...

    @abstractmethod
    def unsubscribe_activity_events(self, subscription_id: str) -> None:
        """Remove one live subscription idempotently."""
        ...


class ILoggableSystem(AsyncSystem):
    def __init__(
        self, 
        dependencies: Iterable[type[AsyncSystem]] = []
        ) -> None:
        super().__init__(
            list(dependencies) + [ILoggerSystem]
            )

    def log(self, level: str, message: str) -> None:
        """Dispatch a compatibility text log to Logger components."""
        self.get_system(ILoggerSystem).log(level, message)

    def record_activity(self, draft: ActivityEventDraft) -> ActivityEvent:
        """Record one Draft on the owning event loop and return its final event."""
        return self.get_system(ILoggerSystem).record_activity(draft)

    def record_activity_threadsafe(self, draft: ActivityEventDraft) -> None:
        """Queue one Draft from a non-owning thread without blocking it."""
        self.get_system(ILoggerSystem).record_activity_threadsafe(draft)