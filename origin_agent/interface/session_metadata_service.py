from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from entity.messages import History
from entity.puretype import (
    LLMProfile,
    MetadataProfileState,
    ToolchainSummaryProfileState,
)
from framework import AsyncSystem
from system.lifecycle import TaskOwner

from .llm_profile_store import ILLMProfileStore
from .runtime_system import IRuntimeSystem

if TYPE_CHECKING:
    from system.session_store import SessionStore


class ISessionMetadataService(AsyncSystem, ABC):
    """Declare metadata Profile selection and session text-generation operations."""

    @property
    @abstractmethod
    def runtime(self) -> IRuntimeSystem:
        """Return the runtime service used for metadata admission."""
        ...

    @property
    @abstractmethod
    def llm_profile_store(self) -> ILLMProfileStore:
        """Return the shared Profile store used by metadata generation."""
        ...

    @property
    @abstractmethod
    def session_store(self) -> SessionStore:
        """Return the session persistence service."""
        ...

    @property
    @abstractmethod
    def task_owner(self) -> TaskOwner:
        """Return the owner for metadata request tasks."""
        ...

    @abstractmethod
    def close_admission(self) -> None:
        """Reject new metadata generation requests."""
        ...

    @abstractmethod
    async def cancel_pending(self) -> None:
        """Cancel and await metadata requests during shutdown."""
        ...

    @abstractmethod
    def get_state(self) -> MetadataProfileState:
        """Return the global metadata Profile state."""
        ...

    @abstractmethod
    def select_profile(self, profile: LLMProfile | None) -> MetadataProfileState:
        """Set or clear the global metadata Profile reference."""
        ...

    @abstractmethod
    def is_selected_profile(self, profile: LLMProfile) -> bool:
        """Check whether a Profile is selected for metadata generation."""
        ...

    @abstractmethod
    def get_toolchain_summary_state(self) -> ToolchainSummaryProfileState:
        """Return the global tool-chain summary Profile state."""
        ...

    @abstractmethod
    def select_toolchain_summary_profile(
        self,
        profile: LLMProfile | None,
    ) -> ToolchainSummaryProfileState:
        """Set or clear the global tool-chain summary Profile."""
        ...

    @abstractmethod
    def is_selected_toolchain_summary_profile(self, profile: LLMProfile) -> bool:
        """Check whether a Profile is selected for tool-chain summaries."""
        ...

    @abstractmethod
    async def generate_title(self, session_id: str) -> str:
        """Generate and persist a session title."""
        ...

    @abstractmethod
    async def generate_tags(self, session_id: str, existing_tags: list[str]) -> list[str]:
        """Generate session tags from existing tags and session history."""
        ...

    @abstractmethod
    async def generate_summary(self, session_id: str, history: History | None = None) -> str:
        """Generate a summary for the supplied or persisted session history."""
        ...

    @abstractmethod
    async def regenerate_summary(self, session_id: str) -> str:
        """Regenerate and persist a session summary."""
        ...

    @abstractmethod
    async def ensure_summary(self, session_id: str) -> str:
        """Return an existing summary or generate one when required."""
        ...

    @abstractmethod
    async def generate_tool_chain_summary(self, session_id: str, chain_text: str) -> str:
        """Generate a compact summary for one complete tool chain."""
        ...

    @abstractmethod
    def maybe_generate_first_title(self, session_id: str, text: str) -> None:
        """Schedule first-message title generation without blocking the route."""
        ...
