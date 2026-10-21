from __future__ import annotations

from abc import ABC, abstractmethod

from entity.puretype import (
    CharacterProfile,
    LLMProfile,
    QueuedMessage,
    SubAgentApprovalResult,
    SubAgentChatResult,
    SubAgentLaunchResult,
    SubAgentSnapshotResponse,
    SubAgentStopResult,
)
from framework import AsyncSystem

from .runtime_system import IRuntimeSystem
from .session_manager import ISessionManager


DecisionValue = str | int | float | bool | None | list[str]
Decision = dict[str, DecisionValue]


class ISubAgentOrchestrator(AsyncSystem, ABC):
    """Declare sub-agent creation, messaging, approval and shutdown operations."""

    @property
    @abstractmethod
    def runtime(self) -> IRuntimeSystem:
        """Return the runtime service used by sub-agent contexts."""
        ...

    @property
    @abstractmethod
    def session_manager(self) -> ISessionManager:
        """Return the parent-session manager used for ownership lookup."""
        ...

    @abstractmethod
    async def launch(
        self,
        parent_session_id: str,
        name: str,
        profile: CharacterProfile,
        temperature: float,
        initial_prompt: str,
        user_name: str,
        message_type: str,
        history_path: str | None = None
        ) -> SubAgentLaunchResult:
        """Launch one persistent sub-agent under a parent session."""
        ...

    @abstractmethod
    async def chat_user_direct(
        self,
        parent_session_id: str,
        session_id: str,
        message: str,
        co_recipients: list[str] | None = None
        ) -> SubAgentChatResult:
        """Deliver a direct user message to a sub-agent."""
        ...

    @abstractmethod
    async def chat(
        self,
        parent_session_id: str,
        session_id: str,
        message: str,
        user_name: str,
        message_type: str,
        co_recipients: list[str] | None = None
        ) -> SubAgentChatResult:
        """Deliver a parent-Agent message to a sub-agent."""
        ...

    @abstractmethod
    async def approve(
        self,
        parent_session_id: str,
        session_id: str,
        decisions: list[Decision]
        ) -> SubAgentApprovalResult:
        """Apply parent-Agent approval decisions to pending sub-agent tools."""
        ...

    @abstractmethod
    async def stop(
        self,
        parent_session_id: str,
        session_id: str
        ) -> SubAgentStopResult:
        """Stop a persistent sub-agent and save its final history."""
        ...

    @abstractmethod
    async def launch_taskagent(
        self,
        parent_session_id: str,
        prompt: str,
        profile: LLMProfile
        ) -> SubAgentLaunchResult:
        """Launch one non-persistent task Agent from a Profile snapshot."""
        ...

    @abstractmethod
    async def stop_taskagent(
        self,
        parent_session_id: str,
        session_id: str
        ) -> SubAgentStopResult:
        """Stop a non-persistent task Agent without saving history."""
        ...

    @abstractmethod
    def interrupt(self, parent_session_id: str) -> None:
        """Request interruption for all sub-agents of one parent session."""
        ...

    @abstractmethod
    def resume(self, parent_session_id: str) -> None:
        """Clear the interruption state for one parent session."""
        ...

    @abstractmethod
    def get_snapshot(self, parent_session_id: str) -> SubAgentSnapshotResponse:
        """Return a snapshot of active sub-agents for one parent session."""
        ...

    @abstractmethod
    def enqueue_user_input(
        self,
        parent_session_id: str,
        session_id: str,
        message: QueuedMessage
        ) -> int:
        """Queue one accepted user input for a sub-agent."""
        ...

    @abstractmethod
    def freeze_inputs(self) -> None:
        """Freeze all sub-agent input admission during shutdown."""
        ...

    @abstractmethod
    async def stop_rounds(self) -> None:
        """Stop all active sub-agent rounds and wait for their tasks."""
        ...

    @abstractmethod
    async def flush_inputs(self) -> None:
        """Commit accepted sub-agent inputs and persistent histories."""
        ...

    @abstractmethod
    async def transfer_shutdown_feedback(self) -> None:
        """Transfer undelivered feedback into parent shutdown batches."""
        ...

    @abstractmethod
    async def shutdown_all(self) -> None:
        """Freeze, stop, flush and clear every sub-agent context."""
        ...

    @abstractmethod
    async def shutdown(self, parent_session_id: str) -> None:
        """Shut down and remove one parent session's sub-agent context."""
        ...
