from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from pathlib import Path
from typing import TYPE_CHECKING, ContextManager

from entity.puretype import (
    AgentspaceEntry,
    AgentspaceEvent,
    AgentspaceFileSnapshot,
    AgentspaceLockInfo,
    AgentspaceLockOwner,
    AgentspaceTrashEntry,
)
from framework import AsyncSystem

from .sandbox import ISandbox

if TYPE_CHECKING:
    from system.session_file_changes import SessionFileChangeStore
    from system.session_variables import SessionVariableService
    from system.session_visual_resources import SessionVisualResourceService


class IAgentspaceService(AsyncSystem, ABC):
    """Declare file, lock, event and leaf-service operations for Agentspace."""

    @property
    @abstractmethod
    def sandbox(self) -> ISandbox:
        """Return the shared path sandbox used by Agentspace operations."""
        ...

    @property
    @abstractmethod
    def root(self) -> Path:
        """Return the resolved Agentspace root directory."""
        ...

    @property
    @abstractmethod
    def visual_resources(self) -> SessionVisualResourceService:
        """Return the session visual-resource leaf service."""
        ...

    @property
    @abstractmethod
    def session_variables(self) -> SessionVariableService:
        """Return the session-variable leaf service."""
        ...

    @property
    @abstractmethod
    def file_changes(self) -> SessionFileChangeStore:
        """Return the session file-change aggregation leaf service."""
        ...

    @property
    @abstractmethod
    def watcher_available(self) -> bool:
        """Report whether the Agentspace watcher completed startup."""
        ...

    @abstractmethod
    def list_directory(self, relative_path: str) -> list[AgentspaceEntry]:
        """List one normalized Agentspace directory."""
        ...

    @abstractmethod
    def read_file(self, relative_path: str) -> AgentspaceFileSnapshot:
        """Read one UTF-8 Agentspace file snapshot."""
        ...

    @abstractmethod
    def write_file(
        self,
        relative_path: str,
        content: str,
        expected_version: str | None,
        operation_id: str = ""
        ) -> AgentspaceFileSnapshot:
        """Write one version-checked Agentspace file."""
        ...

    @abstractmethod
    def create_directory(
        self,
        relative_path: str,
        operation_id: str = ""
        ) -> AgentspaceEntry:
        """Create one Agentspace directory without overwriting."""
        ...

    @abstractmethod
    def rename_path(
        self,
        relative_path: str,
        new_name: str,
        operation_id: str = ""
        ) -> tuple[str, str]:
        """Rename one Agentspace path without replacing its target."""
        ...

    @abstractmethod
    def move_to_trash(
        self,
        relative_path: str,
        operation_id: str = ""
        ) -> AgentspaceTrashEntry:
        """Move one user-owned Agentspace path into the trash store."""
        ...

    @abstractmethod
    def list_trash(self) -> list[AgentspaceTrashEntry]:
        """List recoverable Agentspace trash entries."""
        ...

    @abstractmethod
    def restore_trash(
        self,
        entry_id: str,
        operation_id: str = ""
        ) -> tuple[AgentspaceTrashEntry, str]:
        """Restore one trash entry without replacing an existing target."""
        ...

    @abstractmethod
    def purge_trash(
        self,
        entry_id: str,
        operation_id: str = ""
        ) -> None:
        """Permanently remove one trash entry."""
        ...

    @abstractmethod
    def empty_trash(self, operation_id: str = "") -> tuple[int, list[str]]:
        """Permanently empty the trash and report partial failures."""
        ...

    @abstractmethod
    def agent_access(
        self,
        owner: AgentspaceLockOwner,
        paths: list[tuple[str, bool]]
        ) -> ContextManager[None]:
        """Acquire reply-scoped locks for explicit ws paths."""
        ...

    @abstractmethod
    def acquire_agent_access(
        self,
        owner_id: str,
        session_id: str,
        character_name: str,
        logical_path: str,
        recursive: bool = False
        ) -> None:
        """Acquire one explicit Agentspace lock for a reply round."""
        ...

    @abstractmethod
    def release_agent_access(self, round_id: str) -> None:
        """Release all Agentspace locks owned by one reply round."""
        ...

    @abstractmethod
    def locks_snapshot(self) -> list[AgentspaceLockInfo]:
        """Return a read-only snapshot of active Agentspace locks."""
        ...

    @abstractmethod
    def subscribe_events(self) -> tuple[str, asyncio.Queue[AgentspaceEvent]]:
        """Subscribe to the Agentspace event queue on its bound loop."""
        ...

    @abstractmethod
    def unsubscribe_events(self, subscription_id: str) -> None:
        """Remove one Agentspace event subscription."""
        ...

    @abstractmethod
    def record_user_change(
        self,
        operation: str,
        path: str,
        old_path: str | None = None
        ) -> None:
        """Record a successful user-visible Agentspace change."""
        ...

    @abstractmethod
    def flush_pending_changes(self) -> str | None:
        """Consume pending user-change summaries for prompt injection."""
        ...
