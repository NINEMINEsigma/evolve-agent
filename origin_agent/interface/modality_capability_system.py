from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from entity.messages import MediaBlock, MessageBlock
from entity.puretype import LLMProfile, ModalityCapability, ModalityDescriptionResult
from framework import AsyncSystem
from system.lifecycle import TaskOwner

from .runtime_system import IRuntimeSystem

if TYPE_CHECKING:
    from entry.base_agent_loop import ToolContext


class IModalityCapabilitySystem(AsyncSystem, ABC):
    """Declare multimodal probing, forwarding and description operations."""

    @property
    @abstractmethod
    def runtime(self) -> IRuntimeSystem:
        """Return the runtime admission and failure service."""
        ...

    @property
    @abstractmethod
    def task_owner(self) -> TaskOwner:
        """Return the owner for modality requests."""
        ...

    @property
    @abstractmethod
    def cache_path(self) -> Path:
        """Return the persistent capability-cache path."""
        ...

    @abstractmethod
    def close_admission(self) -> None:
        """Reject new modality requests during shutdown."""
        ...

    @abstractmethod
    async def cancel_pending(self) -> None:
        """Cancel and await all modality requests."""
        ...

    @abstractmethod
    def probe_lock(self, key: str) -> asyncio.Lock:
        """Return the per-model capability probe lock."""
        ...

    @abstractmethod
    def modality_blocks(self, modality: str) -> list[MessageBlock]:
        """Build the deterministic probe blocks for one modality."""
        ...

    @abstractmethod
    def resolve_effective_modality_reference_profile(
        self,
        active_profile: LLMProfile,
        media_type: Literal["image", "audio", "video"]
        ) -> LLMProfile | None:
        """Resolve the active Profile's effective modality reference."""
        ...

    @abstractmethod
    def get_cached_vision_support(
        self,
        model: str,
        base_url: str
        ) -> bool | None:
        """Return cached tool-message vision support when known."""
        ...

    @abstractmethod
    def get_cached_audio_support(
        self,
        model: str,
        base_url: str
        ) -> bool | None:
        """Return cached tool-message audio support when known."""
        ...

    @abstractmethod
    def get_cached_user_vision_support(
        self,
        model: str,
        base_url: str
        ) -> bool | None:
        """Return cached user-message vision support when known."""
        ...

    @abstractmethod
    def get_cached_user_audio_support(
        self,
        model: str,
        base_url: str
        ) -> bool | None:
        """Return cached user-message audio support when known."""
        ...

    @abstractmethod
    def get_cached_video_support(
        self,
        model: str,
        base_url: str
        ) -> bool | None:
        """Return cached tool-message video support when known."""
        ...

    @abstractmethod
    def get_cached_user_video_support(
        self,
        model: str,
        base_url: str
        ) -> bool | None:
        """Return cached user-message video support when known."""
        ...

    @abstractmethod
    async def run_modality_probe(self, context: ToolContext | None) -> ModalityCapability:
        """Probe all modality paths and persist the capability result."""
        ...

    @abstractmethod
    async def ensure_modality_capability(self, context: ToolContext | None) -> ModalityCapability:
        """Return a complete capability result, probing when required."""
        ...

    @abstractmethod
    async def forward_modality_to_ref_profile(
        self,
        context: ToolContext | None,
        active_profile: LLMProfile,
        media_data: dict[str, str | int | float | bool | None],
        media_type: Literal["image", "audio", "video"]
        ) -> str:
        """Forward one media payload to its effective reference Profile."""
        ...

    @abstractmethod
    async def describe_media_block(
        self,
        context: ToolContext,
        active_profile: LLMProfile,
        block: MediaBlock
        ) -> ModalityDescriptionResult:
        """Describe one media block through the configured reference Profile."""
        ...

    @abstractmethod
    def build_modality_prompt_block(
        self,
        profile: LLMProfile,
        agentspace: Path | None = None
        ) -> str:
        """Build the prompt block describing available modality capabilities."""
        ...
