"""Update a dynamic sandbox mapping without renaming it."""

from typing import Any
from fastapi import APIRouter
from entity.constant import GatewayErrorCode
from entity.error import DynamicSandboxInputError, DynamicSandboxNotFoundError, SandboxError
from entity.puretype import DynamicSandboxSpaceUpdateRequest
from gateway.api_support.domain_errors import raise_sandbox_space_http
from gateway.http_boundary import business_http_error
from interface.api_component import APIComponent
from interface.sandbox import ISandbox


class UpdateSandboxSpaceAPI(APIComponent):
    def display(self, router: APIRouter) -> None:
        router.add_api_route("/api/sandbox-spaces/{name}", self.handler, methods=["PUT"], name="update_sandbox_space")

    async def handler(self, name: str, payload: DynamicSandboxSpaceUpdateRequest) -> dict[str, Any]:
        if name != payload.name:
            raise business_http_error(400, GatewayErrorCode.SANDBOX_SPACE_NAME_MISMATCH, "Sandbox space name cannot change and must match the path parameter")
        try:
            space = self.get_system(ISandbox).update_dynamic_space(name, path=payload.path, description=payload.description, is_readonly=payload.is_readonly)
            return {"space": space}
        except (DynamicSandboxInputError, DynamicSandboxNotFoundError, SandboxError) as exc:
            raise_sandbox_space_http(exc)
