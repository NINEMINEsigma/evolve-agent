"""Explicit Profile projections shared by HTTP configuration endpoints."""

from entity.puretype import LLMProfile, ModalityProfileState, ModalityProfileStates
from interface.llm_profile_store import ILLMProfileStore


def missing_profile_connection_fields(profile: LLMProfile) -> list[str]:
    return [
        name for name, value in (
            ("llm_client_name", profile.llm_client_name),
            ("base_url", profile.base_url),
            ("model", profile.model),
        ) if not value.strip()
    ]


def modality_profile_state(profile: LLMProfile | None) -> ModalityProfileState:
    if profile is None:
        return ModalityProfileState()
    return ModalityProfileState(
        profile_name=profile.name, model=profile.model or None,
        available=not missing_profile_connection_fields(profile),
    )


def get_modality_profile_states(store: ILLMProfileStore) -> ModalityProfileStates:
    data = store.get_data()
    return ModalityProfileStates(
        image=modality_profile_state(data.global_vision_image_profile),
        audio=modality_profile_state(data.global_audio_profile),
        video=modality_profile_state(data.global_vision_video_profile),
    )
