from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import TYPE_CHECKING

from entity.puretype import (
    ClientInfo,
    LoopMeta,
    LLMProfile,
    Role,
    SessionInfo,
    ShutdownInputReport,
    SubAgentFeedbackDelivery,
)
from framework import AsyncSystem

from .frontend_sink import IFrontendSink

if TYPE_CHECKING:
    from entry.base_agent_loop import IMainSessionLoop
    from gateway.chat import SessionManager as ChatSessionManager


class ISessionManager(AsyncSystem, ABC):
    """Declare session index, Loop ownership and shutdown coordination."""

    @property
    @abstractmethod
    def chat_manager(self) -> ChatSessionManager:
        """Return the underlying persistent session index manager."""
        ...

    @abstractmethod
    def get(self, session_id: str) -> SessionInfo | None:
        """Return persisted metadata for one session when it exists."""
        ...

    @abstractmethod
    def exists(self, session_id: str) -> bool:
        """Report whether a session exists in the persistent index."""
        ...

    @abstractmethod
    def begin_session_delete(self, session_id: str) -> bool:
        """Atomically mark a session as being permanently deleted."""
        ...

    @abstractmethod
    def is_session_deleting(self, session_id: str) -> bool:
        """Report whether permanent deletion is in progress."""
        ...

    @abstractmethod
    def end_session_delete(self, session_id: str) -> None:
        """Release the permanent-deletion marker."""
        ...

    @abstractmethod
    def get_all(self) -> list[SessionInfo]:
        """Return all indexed session metadata."""
        ...

    @abstractmethod
    def create_with_context(
        self,
        context: str,
        parent_sid: str | None = None,
        parents: list[str] | None = None,
        role: Role = Role.USER,
        loop_meta: LoopMeta | None = None
        ) -> str:
        """Create a session with inherited context and initialized approval mode."""
        ...

    @abstractmethod
    def archive(
        self,
        session_id: str,
        continuation_sid: str | None = None
        ) -> None:
        """Archive one session and optionally link its continuation."""
        ...

    @abstractmethod
    def set_session_tags(
        self,
        session_id: str,
        tags: list[str]
        ) -> None:
        """Persist the supplied session tags."""
        ...

    @abstractmethod
    def set_store_dir(self, path: str) -> None:
        """Set the persistent session-store directory."""
        ...

    @abstractmethod
    def get_client_info(self, session_id: str) -> ClientInfo | None:
        """Return connection metadata for one session."""
        ...

    @abstractmethod
    def set_client_info(
        self,
        session_id: str,
        info: ClientInfo
        ) -> None:
        """Update connection metadata for one session."""
        ...

    @abstractmethod
    def get_all_tags(self) -> list[str]:
        """Return all known session tags."""
        ...

    @abstractmethod
    def create(
        self,
        parent_sid: str | None = None,
        parents: list[str] | None = None,
        session_id: str | None = None
        ) -> str:
        """Create and index a new session."""
        ...

    @abstractmethod
    def remove(self, session_id: str) -> None:
        """Remove a session and its persistent runtime data."""
        ...

    @abstractmethod
    def remove_from_index(self, session_id: str) -> None:
        """Remove a session from the index without deleting its files."""
        ...

    @abstractmethod
    def update_title(
        self,
        session_id: str,
        title: str
        ) -> None:
        """Persist a session title update."""
        ...

    @abstractmethod
    def update_last_activity(self, session_id: str) -> None:
        """Update the session activity timestamp."""
        ...

    @abstractmethod
    def toggle_pin(self, session_id: str) -> bool:
        """Toggle and return a session's pinned state."""
        ...

    @abstractmethod
    def validate_merge_sources(self, source_ids: list[str]) -> str | None:
        """Validate merge sources and return an error message when invalid."""
        ...

    @abstractmethod
    def load_from_disk(self) -> None:
        """Load the persistent session index into memory."""
        ...

    @property
    @abstractmethod
    def count(self) -> int:
        """Return the number of indexed sessions."""
        ...

    @abstractmethod
    def get_all_loops(self) -> dict[str, IMainSessionLoop]:
        """Return a snapshot of active session Loop owners."""
        ...

    @abstractmethod
    def freeze_inputs(self) -> None:
        """Freeze new session inputs while retaining accepted deliveries."""
        ...

    @abstractmethod
    def track_retiring_loop(self, loop: IMainSessionLoop) -> None:
        """Retain a Loop until its outstanding work has finished."""
        ...

    @abstractmethod
    async def stop_rounds(self) -> None:
        """Stop active session rounds and wait for retirement tasks."""
        ...

    @abstractmethod
    def accept_shutdown_feedback(
        self,
        parent_session_id: str,
        items: list[SubAgentFeedbackDelivery]
        ) -> None:
        """Transfer frozen sub-agent feedback into a parent input queue."""
        ...

    @abstractmethod
    async def flush_inputs(self) -> ShutdownInputReport:
        """Persist all accepted session inputs in sequence order."""
        ...

    @abstractmethod
    def replace_idle_loops_using_profile(
        self,
        source_profile: LLMProfile,
        replacement_profile: LLMProfile | None
        ) -> tuple[list[str], list[str]]:
        """Replace profiles on idle loops and report switched or busy sessions."""
        ...

    @abstractmethod
    def create_session(
        self,
        session_id: str,
        frontend_sink: IFrontendSink,
        history_store_dir: Path | None = None
        ) -> IMainSessionLoop:
        """Create or restore the appropriate main session Loop."""
        ...

    @abstractmethod
    def get_loop(self, session_id: str) -> IMainSessionLoop | None:
        """Return the active main Loop for one session."""
        ...

    @abstractmethod
    def terminate_session(self, session_id: str) -> None:
        """Interrupt and retire one session Loop."""
        ...

    @abstractmethod
    async def delete_session_runtime(self, session_id: str) -> None:
        """Release runtime resources for a permanently deleted session."""
        ...

    @abstractmethod
    async def replace_loop(
        self,
        session_id: str,
        new_loop: IMainSessionLoop
        ) -> None:
        """Replace a session Loop while preserving ownership and routing."""
        ...

    @abstractmethod
    def rotate_session(
        self,
        old_sid: str,
        new_sid: str
        ) -> None:
        """Migrate session-owned runtime routing during continuation."""
        ...

    @abstractmethod
    def ensure_colloquy_session(self) -> None:
        """Ensure the built-in Colloquy session is indexed."""
        ...
