"""Dynamic sandbox spaces and availability."""

from typing import Any
from fastapi import APIRouter
from interface.api_component import APIComponent
from interface.sandbox import ISandbox


class ListSandboxSpacesAPI(APIComponent):
    def display(self, router: APIRouter) -> None:
        router.add_api_route("/api/sandbox-spaces", self.handler, methods=["GET"], name="list_sandbox_spaces")

    async def handler(self) -> dict[str, Any]:
        entries = self.get_system(ISandbox).list_dynamic_spaces_with_availability()
        return {"spaces": [{**space.model_dump(), "available": available} for space, available in entries]}
