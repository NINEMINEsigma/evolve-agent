"""Structured process activity events used by the global activity dashboard."""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ActivityEventKind(str, Enum):
    message_received = "message_received"
    agent_response = "agent_response"
    tool_call = "tool_call"


class ActivityEventPhase(str, Enum):
    observed = "observed"
    started = "started"
    completed = "completed"


class ActivityEventStatus(str, Enum):
    observed = "observed"
    active = "active"
    succeeded = "succeeded"
    failed = "failed"
    denied = "denied"
    interrupted = "interrupted"


class ActivityEventDraft(BaseModel):
    """Unsequenced activity data prepared by a business event producer."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    kind: ActivityEventKind
    phase: ActivityEventPhase
    status: ActivityEventStatus
    session_id: str = Field(min_length=1)
    activity_id: str | None = None
    input_sequences: list[int] = Field(default_factory=list)
    stream_id: str | None = None
    tool_call_id: str | None = None
    character_name: str | None = None
    tool_name: str | None = None
    duration_ms: int | None = Field(default=None, ge=0)


class ActivityEvent(BaseModel):
    """Final activity event with Logger-assigned process sequence and timestamp."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    sequence: int = Field(ge=1)
    timestamp: str = Field(min_length=1)
    kind: ActivityEventKind
    phase: ActivityEventPhase
    status: ActivityEventStatus
    session_id: str = Field(min_length=1)
    activity_id: str | None = None
    input_sequences: list[int] = Field(default_factory=list)
    stream_id: str | None = None
    tool_call_id: str | None = None
    character_name: str | None = None
    tool_name: str | None = None
    duration_ms: int | None = Field(default=None, ge=0)


class ActivityStreamGap(BaseModel):
    """Non-history SSE notice emitted when a subscriber queue overflows."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    type: Literal["gap"] = "gap"
    dropped: int = Field(ge=1)
    timestamp: str = Field(min_length=1)


ActivityStreamItem = ActivityEvent | ActivityStreamGap


class ActivityOverview(BaseModel):
    """Current process-level counts displayed in the activity dashboard."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    session_count: int = Field(ge=0)
    active_loop_count: int = Field(ge=0)
    tool_count: int = Field(ge=0)
    toolset_count: int = Field(ge=0)
