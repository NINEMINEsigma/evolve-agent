"""Process activity overview."""

from fastapi import APIRouter
from entity.puretype import ActivityOverview
from interface.api_component import APIComponent
from interface.session_manager import ISessionManager
from interface.tool_registry import IToolRegistry


class ActivityOverviewAPI(APIComponent):
    def display(self, router: APIRouter) -> None:
        router.add_api_route("/api/activity/overview", self.handler, methods=["GET"], name="get_activity_overview", response_model=ActivityOverview)

    async def handler(self) -> ActivityOverview:
        """Return current process-level activity dashboard counts."""
        manager = self.get_system(ISessionManager)
        registry = self.get_system(IToolRegistry)
        return ActivityOverview(
            session_count=manager.count,
            active_loop_count=len(manager.get_all_loops()),
            tool_count=len(registry.get_all_tool_names()),
            toolset_count=len(registry.get_registered_toolset_names()),
        )
