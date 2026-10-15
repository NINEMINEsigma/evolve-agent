"""Shared tool-call pairing helpers for interruption and batch truncation."""

from __future__ import annotations

from entity.messages import CharacterConversationMessage, History, ToolResultMessage
from entity.puretype import Role, ToolCallRequest


def interrupted_tool_result(
    tool_call: ToolCallRequest,
    character_name: str,
    phase: str,
) -> ToolResultMessage:
    """Build a paired result for an accepted tool call that did not execute."""
    return ToolResultMessage(
        role=Role.TOOL,
        character_name=character_name,
        tool_call_id=tool_call.id,
        content={
            "error": "Tool call interrupted by user",
            "_interrupted": True,
            "_interrupted_phase": phase,
        },
    )


def collect_unexecuted_tool_results(
    history: History,
    accepted_tool_calls: list[ToolCallRequest],
    executed_tool_call_ids: set[str],
    character_name: str,
    phase: str,
) -> list[ToolResultMessage]:
    """Return interruption results for accepted calls without a stored result."""
    stored_ids: set[str] = set()
    declared_ids: set[str] = set()
    for message in history.iter_messages():
        if isinstance(message, ToolResultMessage):
            stored_ids.add(message.tool_call_id)
        elif isinstance(message, CharacterConversationMessage) and message.tool_calls:
            declared_ids.update(call.id for call in message.tool_calls)
    return [
        interrupted_tool_result(tool_call, character_name, phase)
        for tool_call in accepted_tool_calls
        if tool_call.id in declared_ids
        and tool_call.id not in executed_tool_call_ids
        and tool_call.id not in stored_ids
    ]
