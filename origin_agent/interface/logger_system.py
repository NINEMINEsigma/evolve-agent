from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod

from entity.puretype import ActivityEvent, ActivityEventDraft, ActivityStreamItem
from framework import AsyncSystem

from .runtime_system import IRuntimeSystem


class ILoggerSystem(AsyncSystem, ABC):
    """Declare structured process activity logging and subscription."""

    @property
    @abstractmethod
    def runtime(self) -> IRuntimeSystem:
        """Return the owning runtime lifecycle service."""
        ...

    @abstractmethod
    def log(self, level: str, message: str) -> None:
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
