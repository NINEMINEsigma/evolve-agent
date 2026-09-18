"""发布流式消息到正典 History 索引的非持久化关联事件。"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from entry.agent_sink import AgentSink

logger = logging.getLogger(__name__)


async def emit_stream_history_link(
    sink: AgentSink,
    session_id: str,
    stream_id: str,
    history_index: int,
    *,
    visible_characters: list[str] | None = None,
    response_characters: list[str] | None = None,
) -> None:
    """消息已存储后发送权威索引；发送失败不影响 History 写入。"""
    if not stream_id or history_index < 0:
        return
    meta: dict[str, str | int | list[str]] = {"stream_id": stream_id, "history_index": history_index}
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
            "Failed to send stream history link for session=%s stream=%s",
            session_id, stream_id, exc_info=True,
        )
