from __future__ import annotations
from typing import * # type: ignore

from system.context import get_runtime_context

from ._store import SubagentStore


async def _handle_start_agents_group(args: dict[str, Any]) -> dict:
    subagent_registry = SubagentStore(get_runtime_context().agentspace).list()
    raise NotImplementedError("Not implemented")
