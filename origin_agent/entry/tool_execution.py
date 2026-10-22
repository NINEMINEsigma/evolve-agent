"""Shared batch admission before an assistant tool-call message is committed."""

from __future__ import annotations

from interface.tool_registry import IToolRegistry
from entity.puretype import LLMResponse
from interface.agent_sink import IAgentSink


async def accept_tool_batch(
    response: LLMResponse,
    registry: IToolRegistry,
    sink: IAgentSink,
    session_id: str,
    stream_id: str
    ) -> LLMResponse:
    """Retain only the declared accepted prefix, independent of approval outcome."""
    decision = registry.plan_tool_batch(response.tool_calls)
    if decision.discarded:
        await sink.emit_tool_calls_discarded(
            session_id, stream_id, [call.id for call in decision.discarded],
        )
    return response.model_copy(update={"tool_calls": decision.accepted})
