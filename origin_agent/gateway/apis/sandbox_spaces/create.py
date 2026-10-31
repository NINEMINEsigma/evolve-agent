"""Create a dynamic sandbox mapping."""

from typing import Any
from fastapi import APIRouter
from entity.error import DynamicSandboxInputError, DynamicSandboxNotFoundError, SandboxError
from entity.puretype import DynamicSandboxSpaceCreateRequest
from gateway.api_support.domain_errors import raise_sandbox_space_http
from interface.api_component import APIComponent
from interface.sandbox import ISandbox


class CreateSandboxSpaceAPI(APIComponent):
    def display(self, router: APIRouter) -> None:
        router.add_api_route("/api/sandbox-spaces", self.handler, methods=["POST"], name="create_sandbox_space")

    async def handler(self, payload: DynamicSandboxSpaceCreateRequest) -> dict[str, Any]:
        try:
            space, created = self.get_system(ISandbox).add_dynamic_space(name=payload.name, path=payload.path, description=payload.description, is_readonly=payload.is_readonly)
            return {"space": space, "created": created}
        except (DynamicSandboxInputError, DynamicSandboxNotFoundError, SandboxError) as exc:
            raise_sandbox_space_http(exc)
