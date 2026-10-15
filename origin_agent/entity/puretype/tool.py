"""Pre-message pure types for tool batch planning."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from .llm import ToolCallRequest


class ToolBatchDecision(BaseModel):
    """Accepted and discarded calls from one model tool-call batch."""

    model_config = ConfigDict(frozen=True)

    accepted: list[ToolCallRequest]
    discarded: list[ToolCallRequest]
    cutoff_tool_call_id: str | None = None
