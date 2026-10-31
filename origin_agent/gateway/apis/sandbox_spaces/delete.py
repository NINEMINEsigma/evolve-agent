"""Remove a dynamic sandbox mapping."""

from typing import Any
from fastapi import APIRouter
from entity.error import DynamicSandboxInputError, DynamicSandboxNotFoundError, SandboxError
from gateway.api_support.domain_errors import raise_sandbox_space_http
from interface.api_component import APIComponent
from interface.sandbox import ISandbox


class DeleteSandboxSpaceAPI(APIComponent):
    def display(self, router: APIRouter) -> None:
        router.add_api_route("/api/sandbox-spaces/{name}", self.handler, methods=["DELETE"], name="delete_sandbox_space")

    async def handler(self, name: str) -> dict[str, Any]:
        try:
            removed = self.get_system(ISandbox).remove_dynamic_space(name)
            return {"removed": removed, "name": name}
        except (DynamicSandboxInputError, DynamicSandboxNotFoundError, SandboxError) as exc:
            raise_sandbox_space_http(exc)


api = DeleteSandboxSpaceAPI()
