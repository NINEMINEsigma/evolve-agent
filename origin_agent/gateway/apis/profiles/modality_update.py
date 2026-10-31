"""Update one global modality fallback reference."""

from fastapi import APIRouter
from entity.constant import GatewayErrorCode
from entity.error import ProfileNotFoundError, ProfileConflictError
from entity.puretype import ModalityProfileUpdateRequest, ModalityProfileMutationResponse
from gateway.api_support.profiles import missing_profile_connection_fields, get_modality_profile_states
from gateway.http_boundary import business_http_error
from interface.api_component import APIComponent
from interface.frontend_sink import IFrontendSink
from interface.llm_profile_store import ILLMProfileStore


class UpdateModalityProfileAPI(APIComponent):
    def display(self, router: APIRouter) -> None:
        router.add_api_route("/api/modality/profiles", self.handler, methods=["PUT"], name="put_modality_profile", response_model=ModalityProfileMutationResponse)

    async def handler(self, payload: ModalityProfileUpdateRequest) -> ModalityProfileMutationResponse:
        """Set or clear one media type's global fallback Profile."""
        store = self.get_system(ILLMProfileStore)
        try:
            with store.locked():
                profile = store.get_profile(payload.profile_name) if payload.profile_name is not None else None
                if profile is not None:
                    missing = missing_profile_connection_fields(profile)
                    if missing:
                        raise ProfileConflictError(f"Modality Profile {profile.name!r} is missing required fields: " + ", ".join(missing))
                store.set_global_modality_profile(payload.media_type, profile)
                states = get_modality_profile_states(store)
                if payload.media_type == "image":
                    state = states.image
                elif payload.media_type == "audio":
                    state = states.audio
                else:
                    state = states.video
        except ProfileNotFoundError as exc:
            raise business_http_error(404, GatewayErrorCode.PROFILE_NOT_FOUND, f"Profile not found: {payload.profile_name!r}") from exc
        except ProfileConflictError as exc:
            raise business_http_error(409, GatewayErrorCode.PROFILE_CONFLICT, str(exc)) from exc
        failures = await self.get_system(IFrontendSink).broadcast_modality_profile_change(states)
        return ModalityProfileMutationResponse(state=state, notification_failures=failures)
