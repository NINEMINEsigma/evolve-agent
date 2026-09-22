"""发布实时聊天消息到正典 History 索引的非持久化关联事件。"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

from entity.puretype import HistoryRowLink

if TYPE_CHECKING:
    from entry.agent_sink import AgentSink

logger = logging.getLogger(__name__)


def _validate_links(links: list[HistoryRowLink]) -> None:
    live_ids = [link.live_id for link in links]
    row_ids = [link.history_row_id for link in links]
    if any(not value for value in live_ids + row_ids):
        raise ValueError("History link IDs must be non-empty")
    if len(live_ids) != len(set(live_ids)):
        raise ValueError("History link live IDs must be unique")
    if len(row_ids) != len(set(row_ids)):
        raise ValueError("History link target IDs must be unique")


async def emit_history_links(
    sink: AgentSink,
    session_id: str,
    *,
    stream_id: str = "",
    history_index: int | None = None,
    links: list[HistoryRowLink] | None = None,
    visible_characters: list[str] | None = None,
    response_characters: list[str] | None = None,
) -> None:
    """在 History 写入完成后发送实时行到正典行的权威关联。"""
    if history_index is not None and history_index < 0:
        raise ValueError("History index must be non-negative")
    normalized_links = list(links or [])
    _validate_links(normalized_links)
    if not stream_id and history_index is not None:
        raise ValueError("A stream ID is required when history_index is provided")
    if not stream_id and not normalized_links:
        return

    meta: dict[str, object] = {}
    if stream_id:
        meta["stream_id"] = stream_id
    if history_index is not None:
        meta["history_index"] = history_index
    if normalized_links:
        meta["live_history_links"] = [link.model_dump() for link in normalized_links]
    if visible_characters is not None:
        meta["visible_characters"] = visible_characters
    if response_characters is not None:
        meta["response_characters"] = response_characters

    try:
        await sink.emit_system_message(
            session_id, json.dumps({"stream_meta": meta}, ensure_ascii=False),
        )
    except Exception:
        logger.warning(
            "Failed to send History links | session=%s stream=%s links=%d",
            session_id, stream_id, len(normalized_links), exc_info=True,
        )


async def emit_stream_history_link(
    sink: AgentSink,
    session_id: str,
    stream_id: str,
    history_index: int,
    *,
    visible_characters: list[str] | None = None,
    response_characters: list[str] | None = None,
    links: list[HistoryRowLink] | None = None,
) -> None:
    """兼容入口：发送 assistant stream 与可选工具行关联。"""
    if not stream_id or history_index < 0:
        return
    await emit_history_links(
        sink,
        session_id,
        stream_id=stream_id,
        history_index=history_index,
        links=links,
        visible_characters=visible_characters,
        response_characters=response_characters,
    )
