import json
import unittest
from unittest.mock import AsyncMock

from entry.stream_history_link import emit_stream_history_link
from entry.history_projection import history_row_id
from entity.puretype import SessionHistoryRowKind


class StreamHistoryLinkTests(unittest.IsolatedAsyncioTestCase):
    async def test_message_index_is_not_a_tool_subrow(self) -> None:
        sink = AsyncMock()
        await emit_stream_history_link(sink, "session", "stream-1", 7)
        sink.emit_system_message.assert_awaited_once()
        session_id, payload = sink.emit_system_message.await_args.args
        self.assertEqual(session_id, "session")
        self.assertEqual(history_row_id(7, SessionHistoryRowKind.message), "history:7:message")
        self.assertEqual(
            json.loads(payload),
            {"stream_meta": {"stream_id": "stream-1", "history_index": 7}},
        )

    async def test_multi_agent_metadata_shares_the_authoritative_link(self) -> None:
        sink = AsyncMock()
        await emit_stream_history_link(
            sink, "session", "multi-agent-1", 12,
            visible_characters=["main-agent"], response_characters=[],
        )
        meta = json.loads(sink.emit_system_message.await_args.args[1])["stream_meta"]
        self.assertEqual(meta["history_index"], 12)
        self.assertEqual(meta["visible_characters"], ["main-agent"])
        self.assertEqual(meta["response_characters"], [])

    async def test_missing_persisted_message_has_no_link(self) -> None:
        sink = AsyncMock()
        await emit_stream_history_link(sink, "session", "", 1)
        await emit_stream_history_link(sink, "session", "error", -1)
        sink.emit_system_message.assert_not_awaited()

    async def test_send_failure_does_not_interrupt_history(self) -> None:
        sink = AsyncMock()
        sink.emit_system_message.side_effect = RuntimeError("connection lost")
        await emit_stream_history_link(sink, "session", "stream", 0)
        sink.emit_system_message.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
