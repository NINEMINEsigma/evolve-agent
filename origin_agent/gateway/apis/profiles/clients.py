"""Discover available LLM client implementations."""

from typing import Any
from fastapi import APIRouter
from abstract.llm.loader import list_llm_clients
from interface.api_component import APIComponent


class ListLlmClientsAPI(APIComponent):
    def display(self, router: APIRouter) -> None:
        router.add_api_route("/api/llm/clients", self.handler, methods=["GET"], name="list_llm_clients_endpoint")

    async def handler(self) -> dict[str, Any]:
        """Return available LLM client implementations."""
        return {"clients": list_llm_clients()}
