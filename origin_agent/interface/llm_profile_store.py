from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import ContextManager, Literal

from entity.puretype.llm import LLMProfile, LLMProfileData, LLMProfilePayload
from framework import AsyncSystem


class ILLMProfileStore(AsyncSystem, ABC):
    """Declare the process-wide LLM Profile root storage contract."""

    @property
    @abstractmethod
    def path(self) -> Path:
        """Return the persistent Profile root path after wake-up."""
        ...

    @property
    @abstractmethod
    def agentspace_dir(self) -> Path:
        """Return the agentspace directory containing the Profile root."""
        ...

    @property
    @abstractmethod
    def data(self) -> LLMProfileData:
        """Return the shared Profile root; mutations use store methods."""
        ...

    @abstractmethod
    def locked(self) -> ContextManager[None]:
        """Enter the store-wide transaction lock for coordinated access."""
        ...

    @abstractmethod
    def get_data(self) -> LLMProfileData:
        """Return the current Profile root under the store lock."""
        ...

    @abstractmethod
    def get_approval_profile(self) -> LLMProfile | None:
        """Return the Profile referenced for model approval."""
        ...

    @abstractmethod
    def set_approval_profile(self, profile: LLMProfile | None) -> None:
        """Persist the approval Profile reference after validating ownership."""
        ...

    @abstractmethod
    def is_approval_profile(self, profile: LLMProfile) -> bool:
        """Check whether the instance is the active approval Profile."""
        ...

    @abstractmethod
    def get_metadata_profile(self) -> LLMProfile | None:
        """Return the global metadata Profile reference."""
        ...

    @abstractmethod
    def set_metadata_profile(self, profile: LLMProfile | None) -> None:
        """Persist the global metadata Profile reference."""
        ...

    @abstractmethod
    def is_metadata_profile(self, profile: LLMProfile) -> bool:
        """Check whether the instance is the active metadata Profile."""
        ...

    @abstractmethod
    def get_toolchain_summary_profile(self) -> LLMProfile | None:
        """Return the global tool-chain summary Profile reference."""
        ...

    @abstractmethod
    def set_toolchain_summary_profile(self, profile: LLMProfile | None) -> None:
        """Persist the global tool-chain summary Profile reference."""
        ...

    @abstractmethod
    def is_toolchain_summary_profile(self, profile: LLMProfile) -> bool:
        """Check whether the instance is the active summary Profile."""
        ...

    @abstractmethod
    def get_global_modality_profile(
        self,
        media_type: Literal["image", "audio", "video"],
    ) -> LLMProfile | None:
        """Return the configured global fallback Profile for one modality."""
        ...

    @abstractmethod
    def set_global_modality_profile(
        self,
        media_type: Literal["image", "audio", "video"],
        profile: LLMProfile | None
        ) -> None:
        """Persist one modality's global fallback Profile reference."""
        ...

    @abstractmethod
    def is_global_modality_profile(
        self,
        profile: LLMProfile,
        media_type: Literal["image", "audio", "video"]
        ) -> bool:
        """Check whether a Profile is referenced by one modality fallback."""
        ...

    @abstractmethod
    def is_any_global_modality_profile(self, profile: LLMProfile) -> bool:
        """Check whether a Profile is referenced by any modality fallback."""
        ...

    @abstractmethod
    def list_profiles(self) -> list[LLMProfile]:
        """Return a stable list snapshot of registered Profile instances."""
        ...

    @abstractmethod
    def snapshot_profile(self, profile: LLMProfile) -> LLMProfile:
        """Return a deep snapshot of a Profile owned by the root."""
        ...

    @abstractmethod
    def get_profile(self, name: str) -> LLMProfile:
        """Return a named Profile or raise the established not-found error."""
        ...

    @abstractmethod
    def resolve_profile_name(self, name: str) -> LLMProfile | None:
        """Resolve an empty name to no Profile and validate non-empty names."""
        ...

    @abstractmethod
    def to_payload(self, profile: LLMProfile) -> LLMProfilePayload:
        """Convert a Profile instance to its flat transport payload."""
        ...

    @abstractmethod
    def create_profile(self, payload: LLMProfilePayload) -> LLMProfile:
        """Create and persist a new Profile from a flat payload."""
        ...

    @abstractmethod
    def update_profile(
        self,
        original_name: str,
        payload: LLMProfilePayload
        ) -> LLMProfile:
        """Update a Profile while preserving its root instance identity."""
        ...

    @abstractmethod
    def assert_removable(
        self,
        profile: LLMProfile,
        *,
        clear_global_selections: bool = False
        ) -> None:
        """Reject deletion when any protected Profile reference remains."""
        ...

    @abstractmethod
    def remove_profile(
        self,
        name: str,
        *,
        clear_global_selections: bool = False
        ) -> LLMProfile:
        """Remove and persist a named Profile after reference checks."""
        ...
