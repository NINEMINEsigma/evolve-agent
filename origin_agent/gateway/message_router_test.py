from __future__ import annotations

import unittest
from unittest.mock import patch

from entity.puretype import (
    ClientDiagnostic,
    ClientDiagnosticKind,
    ClientDiagnosticPhase,
    Message,
    MessageType,
)
from gateway.message_router import MessageRouter


class _FakeWebSocket:
    def __init__(self) -> None:
        self.sent: list[str] = []

    async def send_text(self, payload: str) -> None:
        self.sent.append(payload)


class MessageRouterDiagnosticTests(unittest.IsolatedAsyncioTestCase):
    async def test_client_diagnostic_logs_current_connection_session_only(self) -> None:
        ws = _FakeWebSocket()
        router = MessageRouter(ws, "server-session")  # type: ignore[arg-type]
        message = Message(
            type=MessageType.CLIENT_DIAGNOSTIC,
            session_id="forged-session",
            client_diagnostic=ClientDiagnostic(
                kind=ClientDiagnosticKind.CRITICAL_REQUEST_TIMEOUT,
                phase=ClientDiagnosticPhase.HISTORY_PAGE,
                duration_ms=15001,
                websocket_state="OPEN",
                last_recv_age_ms=25,
                last_pong_age_ms=50,
            ),
        )
        with self.assertLogs("gateway.message_router", level="WARNING") as captured:
            self.assertTrue(await router.route(message))
        output = "\n".join(captured.output)
        self.assertIn("session=server-session", output)
        self.assertNotIn("forged-session", output)
        self.assertEqual(ws.sent, [])

    async def test_missing_client_diagnostic_payload_is_safe(self) -> None:
        ws = _FakeWebSocket()
        router = MessageRouter(ws, "server-session")  # type: ignore[arg-type]
        message = Message(type=MessageType.CLIENT_DIAGNOSTIC)
        with patch.object(router, "handle_unsupported") as unsupported:
            with self.assertLogs("gateway.message_router", level="WARNING") as captured:
                self.assertTrue(await router.route(message))
        unsupported.assert_not_called()
        self.assertIn("missing payload", "\n".join(captured.output))
        self.assertEqual(ws.sent, [])


if __name__ == "__main__":
    unittest.main()
