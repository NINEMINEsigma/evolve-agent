from __future__ import annotations

from abc import ABC, abstractmethod

from entity.puretype.shell import ShellInfo, ShellOutputSlice
from framework import AsyncSystem

from .runtime_system import IRuntimeSystem
from .sandbox import ISandbox


class IShellManager(AsyncSystem, ABC):
    """Declare interactive Shell ownership, I/O and cleanup operations."""

    @property
    @abstractmethod
    def runtime(self) -> IRuntimeSystem:
        """Return the runtime service used for Shell admission."""
        ...

    @property
    @abstractmethod
    def sandbox(self) -> ISandbox:
        """Return the sandbox used to resolve Shell working directories."""
        ...

    @abstractmethod
    def close_admission(self) -> None:
        """Reject new Shell operations while allowing cleanup."""
        ...

    @staticmethod
    @abstractmethod
    def is_available() -> bool:
        """Report whether the platform Shell backend is available."""
        ...

    @abstractmethod
    async def start_shell(
        self,
        owner_session_id: str,
        character_name: str,
        shell_type: str,
        cwd: str,
        command: str,
    ) -> tuple[ShellInfo, ShellOutputSlice, dict[str, str]]:
        """Create an owned Shell and execute its first command."""
        ...

    @abstractmethod
    async def read_shell(
        self,
        owner_session_id: str,
        character_name: str,
        shell_id: str,
        offset: int,
        limit: int,
        wait_timeout: float,
    ) -> ShellOutputSlice:
        """Read a bounded output slice from an owned Shell."""
        ...

    @abstractmethod
    async def write_shell(
        self,
        owner_session_id: str,
        character_name: str,
        shell_id: str,
        text: str,
    ) -> ShellOutputSlice:
        """Write one logical line and return its resulting output slice."""
        ...

    @abstractmethod
    async def interrupt_shell(
        self,
        owner_session_id: str,
        character_name: str,
        shell_id: str,
    ) -> ShellOutputSlice:
        """Send an interrupt signal to an owned Shell."""
        ...

    @abstractmethod
    async def stop_shell(
        self,
        owner_session_id: str,
        character_name: str,
        shell_id: str,
    ) -> ShellInfo:
        """Stop one owned Shell and return its terminal metadata."""
        ...

    @abstractmethod
    def list_shells(self, session_id: str) -> list[ShellInfo]:
        """List Shell metadata owned by one session."""
        ...

    @abstractmethod
    async def stop_shell_for_user(self, session_id: str, shell_id: str) -> ShellInfo:
        """Stop one Shell through the user-facing ownership boundary."""
        ...

    @abstractmethod
    def migrate_session(self, old_session_id: str, new_session_id: str) -> int:
        """Move Shell ownership aliases during session rotation."""
        ...

    @abstractmethod
    async def stop_session(self, session_id: str) -> int:
        """Stop every Shell owned by one session."""
        ...

    @abstractmethod
    async def stop_operations(self) -> None:
        """Stop active native Shell operations before resource release."""
        ...
