from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from entity.puretype.extools import CronTaskInfo
from framework import AsyncSystem

from .runtime_system import IRuntimeSystem
from .sandbox import ISandbox
from .subprocess_runner import ISubprocessRunner

if TYPE_CHECKING:
    from entry.base_agent_loop import BaseAgentLoop


class ICronRouter(AsyncSystem, ABC):
    """Declare scheduled-task routing, persistence and shutdown operations."""

    @property
    @abstractmethod
    def runtime(self) -> IRuntimeSystem:
        """Return the runtime admission service."""
        ...

    @property
    @abstractmethod
    def sandbox(self) -> ISandbox:
        """Return the sandbox used by cron command execution."""
        ...

    @property
    @abstractmethod
    def runner(self) -> ISubprocessRunner:
        """Return the owned subprocess runner."""
        ...

    @abstractmethod
    def register(self, session_id: str, loop: BaseAgentLoop) -> None:
        """Register a session loop as a cron result destination."""
        ...

    @abstractmethod
    def unregister(self, session_id: str) -> None:
        """Remove a session loop from cron result routing."""
        ...

    @abstractmethod
    def dispatch(
        self,
        session_id: str,
        task_id: str,
        name: str,
        exit_code: int,
        stdout_preview: str,
    ) -> bool:
        """Deliver one cron result to a session when admission is open."""
        ...

    @abstractmethod
    def activate(self) -> None:
        """Arm persisted cron timers after Application startup."""
        ...

    @abstractmethod
    def freeze(self) -> None:
        """Freeze new scheduling while preserving task records."""
        ...

    @abstractmethod
    async def stop_running(self) -> None:
        """Stop active timers and cron subprocesses."""
        ...

    @abstractmethod
    def schedule_task(
        self,
        *,
        session_id: str,
        name: str,
        schedule_type: str,
        schedule_value: str,
        command: list[str],
        cwd: str,
        is_wait: bool = False,
        wait_message: str = "",
    ) -> dict[str, str | bool | None]:
        """Create, persist and arm one scheduled task."""
        ...

    @abstractmethod
    def reschedule_task(self, session_id: str, task_id: str) -> dict[str, str | bool | None]:
        """Clone one task configuration into a newly scheduled task."""
        ...

    @abstractmethod
    def cleanup_session_cron_jobs(self, session_id: str) -> int:
        """Remove all cron jobs belonging to one session."""
        ...

    @abstractmethod
    def migrate_session_cron_jobs(self, old_sid: str, new_sid: str) -> int:
        """Move cron jobs from one session to another."""
        ...

    @abstractmethod
    def list_cron_tasks_for_session(self, session_id: str) -> list[CronTaskInfo]:
        """Return the public task snapshot for one session."""
        ...

    @abstractmethod
    def trigger_cron_task(self, session_id: str, task_id: str) -> dict[str, str | bool]:
        """Trigger one persisted task immediately."""
        ...

    @abstractmethod
    def cancel_cron_task(self, session_id: str, task_id: str) -> dict[str, str | bool]:
        """Cancel and persist one scheduled task."""
        ...
