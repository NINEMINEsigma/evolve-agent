"""Recoverable tool resources."""

from fastapi import APIRouter
from entity.puretype import SessionToolResources
from gateway.api_support.sessions import require_session
from interface.api_component import APIComponent
from interface.dynamic_endpoint_system import IDynamicEndpointSystem
from interface.session_manager import ISessionManager


class SessionToolResourcesAPI(APIComponent):
    def display(self, router: APIRouter) -> None:
        router.add_api_route("/api/sessions/{session_id}/tool-resources", self.handler, methods=["GET"], name="get_session_tool_resources")

    async def handler(self, session_id: str) -> SessionToolResources:
        """Return recoverable tool side-effect resources for the session."""
        manager = self.get_system(ISessionManager)
        require_session(manager, session_id)
        endpoints = self.get_system(IDynamicEndpointSystem).list_session_endpoints(session_id)
        loop = manager.get_loop(session_id)
        if loop is None:
            return SessionToolResources(session_id=session_id, dynamic_endpoints=endpoints)
        return loop.loop.get_tool_resources().model_copy(update={"dynamic_endpoints": endpoints})


api = SessionToolResourcesAPI()
