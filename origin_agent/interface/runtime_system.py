from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from contextlib import AbstractContextManager
from typing import TYPE_CHECKING

from entity.constant import ApplicationState, ShutdownReason
from framework import AsyncSystem
from system.context import RuntimeContext

if TYPE_CHECKING:
    from system.resource_cleanup import ResourceCleanupRegistry


class IRuntimeSystem(AsyncSystem, ABC):
    """Declare the process-wide runtime contract for state, admission and shutdown.

    Every other System reads lifecycle state through this slot; the concrete
    implementation owns the single process-level state machine and the failure set.
    """

    @property
    @abstractmethod
    def cleanup(self) -> ResourceCleanupRegistry:
        """Return the process-level external resource cleanup registry."""
        ...

    @property
    @abstractmethod
    def context(self) -> RuntimeContext:
        """Return the immutable runtime context built once per process start."""
        ...

    @property
    @abstractmethod
    def main_agent_character_name(self) -> str:
        """Return the main Agent character name currently in effect."""
        ...

    @property
    @abstractmethod
    def loop(self) -> asyncio.AbstractEventLoop:
        """Return the event loop captured during awake; usable only on that loop."""
        ...

    @property
    @abstractmethod
    def state(self) -> ApplicationState:
        """Return the current application lifecycle state."""
        ...

    @property
    @abstractmethod
    def shutdown_event(self) -> asyncio.Event:
        """Return the event that is set once shutdown is requested."""
        ...

    @property
    @abstractmethod
    def shutdown_reason(self) -> ShutdownReason | None:
        """Return the recorded shutdown cause, or None before any shutdown request.

        A failure reason replaces an earlier non-failure reason.
        """
        ...

    @property
    @abstractmethod
    def failures(self) -> tuple[BaseException, ...]:
        """Return every failure recorded during this run in arrival order."""
        ...

    @property
    @abstractmethod
    def exit_code(self) -> int:
        """Return the process exit code derived from failures and shutdown reason."""
        ...

    @abstractmethod
    def refresh_main_agent_character_name(self, soul_file: str = "SOUL.md") -> str:
        """Reload the main Agent character name from the soul meta file and return it."""
        ...

    @abstractmethod
    def mark_running(self) -> None:
        """Move the application from starting to running so it starts accepting work."""
        ...

    @abstractmethod
    def require_running(self) -> None:
        """Raise unless the application is running and still accepting new work."""
        ...

    @abstractmethod
    def admission(self) -> AbstractContextManager[None]:
        """Hold the runtime lock so acceptance and input sequencing stay atomic.

        Callers must allocate input sequences inside the same admission scope.
        """
        ...

    @abstractmethod
    def next_input_sequence(self) -> int:
        """Allocate the next input sequence number; call only inside an admission scope."""
        ...

    @abstractmethod
    def request_shutdown(self, reason: ShutdownReason) -> None:
        """Record the shutdown reason once and signal the shutdown event."""
        ...

    @abstractmethod
    def record_failure(self, error: BaseException) -> None:
        """Store a failure and request a failure-driven shutdown; never re-raises."""
        ...

    @abstractmethod
    def arm_shutdown_deadline(self) -> None:
        """Start the hard deadline that force-exits the process if stopping hangs."""
        ...

    @abstractmethod
    def disarm_shutdown_deadline(self) -> None:
        """Cancel the hard shutdown deadline timer before final exit."""
        ...
