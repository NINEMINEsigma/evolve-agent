from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from contextlib import AbstractContextManager
from typing import * # type: ignore

from entity.constant import ApplicationState, ShutdownReason
from entity.puretype.agent_settings import AgentLoopSettingsState
from system.context import RuntimeContext
from framework import AsyncSystem

from .logger_system import ILoggableSystem

if TYPE_CHECKING:
    from system.resource_cleanup import ResourceCleanupRegistry


class IRuntimeSystem(ILoggableSystem, ABC):
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
    def max_tool_turns(self) -> int:
        """Return the current global tool-loop limit without reading storage."""
        ...

    @abstractmethod
    def get_agent_loop_settings(self) -> AgentLoopSettingsState:
        """Return the configured, effective and default global tool-loop limits."""
        ...

    @abstractmethod
    def set_max_tool_turns(self, value: int | None) -> AgentLoopSettingsState:
        """Persist a global limit, or null to use the default; require running."""
        ...

    @property
    @abstractmethod
    def main_agent_character_name(self) -> str:
        """Return the main Agent character name currently in effect."""
        ...

    @property
    @abstractmethod
    def loop(self) -> asyncio.AbstractEventLoop:
        """Return the captured runtime loop.

        Async operations execute on this loop; ordinary threads may submit
        callbacks through call_soon_threadsafe, never call create_task directly.
        """
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
        """Store the original failure, close admission and immediately log its traceback.

        Repeated reports of the same original object are idempotent. Explicit
        resource cleanup timeouts remain diagnostics, not application failures.
        Diagnostic handler errors never replace the original failure.
        """
        ...

    @abstractmethod
    def arm_shutdown_deadline(self) -> None:
        """Start the hard deadline that force-exits the process if stopping hangs."""
        ...

    @abstractmethod
    def disarm_shutdown_deadline(self) -> None:
        """Cancel the hard shutdown deadline timer before final exit."""
        ...


class IRuntimeDPSystem(ILoggableSystem):
    def __init__(
        self, 
        dependencies: Iterable[type[AsyncSystem]] = []
        ) -> None:
        super().__init__(
            list(dependencies) + [IRuntimeSystem]
            )

    @property
    def runtime(self) -> IRuntimeSystem:
        return self.get_system(IRuntimeSystem)