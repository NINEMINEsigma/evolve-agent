from __future__ import annotations

from abc import ABC, abstractmethod

from entity.puretype import (
    ApprovalProfileState,
    AskAnswerItem,
    MetadataProfileState,
    ModalityProfileStates,
    ToolchainSummaryProfileState,
)
from fastapi import WebSocket
from framework import AsyncSystem

from .agent_sink import IAgentSink


class IFrontendSink(AsyncSystem, IAgentSink, ABC):
    """Declare frontend-specific connection, broadcast and interaction resolution.

    The upward event contract comes from ``IAgentSink``; this interface only adds
    the WebSocket connection ownership and Profile broadcast operations.
    """

    @abstractmethod
    def close_admission(self) -> None:
        """Close new interaction admission while retaining required output."""
        ...

    @abstractmethod
    def cancel_pending_interactions(self) -> None:
        """Resolve all pending approval and question interactions."""
        ...

    @abstractmethod
    def register_ws(
        self,
        session_id: str,
        ws: WebSocket,
        token: str
        ) -> None:
        """Register one frontend WebSocket connection."""
        ...

    @abstractmethod
    def unregister_ws(self, session_id: str) -> None:
        """Remove one frontend WebSocket connection and its waits."""
        ...

    @abstractmethod
    def rebind_ws(self, old_sid: str, new_sid: str) -> bool:
        """Move one live connection from the archived session to its continuation."""
        ...

    @abstractmethod
    async def close_session(
        self,
        session_id: str,
        *,
        code: int,
        reason: str
        ) -> bool:
        """Invalidate and close one session connection."""
        ...

    @abstractmethod
    async def close_all_connections(self) -> None:
        """Close all frontend connections during application shutdown."""
        ...

    @abstractmethod
    def get_ws(self, session_id: str) -> WebSocket | None:
        """Return one session's active WebSocket when connected."""
        ...

    @abstractmethod
    def get_all_ws(self) -> dict[str, WebSocket]:
        """Return a snapshot of all active WebSocket connections."""
        ...

    @abstractmethod
    async def broadcast_profile_change(
        self,
        operation: str,
        old_name: str,
        new_name: str | None
        ) -> list[str]:
        """Broadcast one LLM Profile change and return failed session IDs."""
        ...

    @abstractmethod
    async def broadcast_approval_profile_change(self, state: ApprovalProfileState) -> list[str]:
        """Broadcast approval Profile state to connected clients."""
        ...

    @abstractmethod
    async def broadcast_metadata_profile_change(self, state: MetadataProfileState) -> list[str]:
        """Broadcast metadata Profile state to connected clients."""
        ...

    @abstractmethod
    async def broadcast_toolchain_summary_profile_change(self, state: ToolchainSummaryProfileState) -> list[str]:
        """Broadcast tool-chain summary Profile state to connected clients."""
        ...

    @abstractmethod
    async def broadcast_modality_profile_change(self, states: ModalityProfileStates) -> list[str]:
        """Broadcast modality fallback Profile states to connected clients."""
        ...

    @abstractmethod
    def is_session_occupied(
        self,
        session_id: str,
        token: str | None
        ) -> bool:
        """Check whether a session is occupied by another connection token."""
        ...

    @abstractmethod
    def resolve_confirm(
        self,
        request_id: str,
        action: str,
        deny_reason: str | None = None,
        denied_by: str = "user"
        ) -> bool:
        """Resolve one pending approval request."""
        ...

    @abstractmethod
    def resolve_ask(
        self,
        request_id: str,
        answers: list[AskAnswerItem] | None = None
        ) -> bool:
        """Resolve one pending question form."""
        ...
