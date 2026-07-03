from __future__ import annotations
from typing import * # type: ignore

from ._store import get_subagent_registry


async def _handle_start_agents_group(args: dict[str, Any]) -> dict:
    subagent_registry = get_subagent_registry()
    raise NotImplementedError("Not implemented")