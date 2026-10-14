"""Shared tool chain summary preparation without History mutation."""

from __future__ import annotations

from typing import TYPE_CHECKING

from entity.messages import BaseMessage
from entity.puretype_after import ToolChainReplacement
from entry.agent_support.tool_chain_compress import (
    build_compressed_chain_messages,
    chain_to_summary_input,
    detect_compressible_chains,
)

if TYPE_CHECKING:
    from system.session_metadata import SessionMetadataService


async def prepare_tool_chain_replacements(
    messages: list[BaseMessage],
    *,
    session_id: str,
    metadata_service: SessionMetadataService,
    start_index: int = 0,
) -> list[ToolChainReplacement]:
    """Prepare all replacements from start_index; propagate failures and cancellation."""
    replacements: list[ToolChainReplacement] = []
    for span in detect_compressible_chains(messages[start_index:]):
        start = start_index + span.start
        end = start_index + span.end
        chain_messages = messages[start:end]
        summary = await metadata_service.generate_tool_chain_summary(
            session_id, chain_to_summary_input(chain_messages),
        )
        replacements.append(
            ToolChainReplacement(
                start=start,
                end=end,
                messages=build_compressed_chain_messages(chain_messages, summary),
            )
        )
    return replacements
