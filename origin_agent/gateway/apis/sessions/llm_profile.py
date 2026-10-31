"""Persisted session Profile name pointer."""

from fastapi import APIRouter, Response
from entity.constant import SESSIONS_DIR_NAME
from entity.error import ProfileNotFoundError
from entity.puretype import SessionLlmProfileState
from gateway.api_support.sessions import require_session
from interface.api_component import APIComponent
from interface.llm_profile_store import ILLMProfileStore
from interface.runtime_system import IRuntimeSystem
from interface.session_manager import ISessionManager
from system.session_store import SessionStore


class SessionLlmProfileAPI(APIComponent):
    def display(self, router: APIRouter) -> None:
        router.add_api_route("/api/sessions/{session_id}/llm-profile", self.handler, methods=["GET"], name="get_session_llm_profile", response_model=SessionLlmProfileState)

    async def handler(self, session_id: str, response: Response) -> SessionLlmProfileState:
        """Read the saved name without creating a Loop or committing a pending selection."""
        profile_store = self.get_system(ILLMProfileStore)
        manager = self.get_system(ISessionManager)
        require_session(manager, session_id)
        with profile_store.locked():
            require_session(manager, session_id)
            store = SessionStore(self.get_system(IRuntimeSystem).context.workspace / SESSIONS_DIR_NAME)
            name = store.read_active_profile_name(session_id)
            available = False
            if name:
                try:
                    profile_store.get_profile(name)
                    available = True
                except ProfileNotFoundError:
                    pass
            response.headers["Cache-Control"] = "no-store"
            return SessionLlmProfileState(session_id=session_id, profile_name=name, available=available)


api = SessionLlmProfileAPI()
