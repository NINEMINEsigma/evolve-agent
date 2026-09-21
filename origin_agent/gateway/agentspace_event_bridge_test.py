from __future__ import annotations

import asyncio
import unittest
from types import SimpleNamespace

from entity.puretype import (
    AgentspaceEvent,
    AgentspaceEventKind,
    AgentspaceEventSource,
)
from gateway.agentspace_event_bridge import (
    attach_agentspace_events,
    build_initial_agentspace_events,
    coalesce_agentspace_event,
    detach_agentspace_events,
    forward_agentspace_events,
)


def _event(sequence: int, kind: AgentspaceEventKind = AgentspaceEventKind.MODIFIED):
    return AgentspaceEvent(
        sequence=sequence,
        kind=kind,
        source=AgentspaceEventSource.WATCHER,
        timestamp="2026-09-21T00:00:00+00:00",
        path=f"file-{sequence}.txt",
    )


class AgentspaceEventBridgeTests(unittest.IsolatedAsyncioTestCase):
    def test_initial_events_when_watcher_available(self) -> None:
        service = SimpleNamespace(watcher_available=True, locks_snapshot=lambda: [])
        events = build_initial_agentspace_events(service)
        self.assertEqual(
            [event.kind for event in events],
            [AgentspaceEventKind.RESYNC, AgentspaceEventKind.LOCKS],
        )
        self.assertEqual(events[0].timestamp, events[1].timestamp)

    def test_initial_events_include_watcher_error(self) -> None:
        service = SimpleNamespace(watcher_available=False, locks_snapshot=lambda: [])
        events = build_initial_agentspace_events(service)
        self.assertEqual(events[-1].kind, AgentspaceEventKind.WATCHER_ERROR)

    def test_coalesce_keeps_single_event(self) -> None:
        queue: asyncio.Queue[AgentspaceEvent] = asyncio.Queue()
        result, dropped = coalesce_agentspace_event(_event(4), queue)
        self.assertEqual(result.sequence, 4)
        self.assertEqual(result.kind, AgentspaceEventKind.MODIFIED)
        self.assertEqual(dropped, 0)

    def test_coalesce_uses_maximum_sequence(self) -> None:
        queue: asyncio.Queue[AgentspaceEvent] = asyncio.Queue()
        queue.put_nowait(_event(8))
        queue.put_nowait(_event(6))
        result, dropped = coalesce_agentspace_event(_event(5), queue)
        self.assertEqual(result.kind, AgentspaceEventKind.RESYNC)
        self.assertEqual(result.sequence, 8)
        self.assertEqual(result.message, "websocket_event_coalesced")
        self.assertEqual(dropped, 2)
        self.assertTrue(queue.empty())

    async def test_attach_sends_initial_events_and_detach_unsubscribes_once(self) -> None:
        queue: asyncio.Queue[AgentspaceEvent] = asyncio.Queue()
        calls: list[str] = []
        service = SimpleNamespace(
            watcher_available=True,
            locks_snapshot=lambda: [],
            subscribe_events=lambda: ("subscription", queue),
            unsubscribe_events=lambda subscription_id: calls.append(subscription_id),
        )
        sent: list[AgentspaceEvent] = []

        async def send_event(event: AgentspaceEvent) -> None:
            sent.append(event)

        subscription_id, task = await attach_agentspace_events(
            service,
            send_event,
            connection_label="session-a",
        )
        self.assertEqual(subscription_id, "subscription")
        self.assertEqual(
            [event.kind for event in sent],
            [AgentspaceEventKind.RESYNC, AgentspaceEventKind.LOCKS],
        )
        await detach_agentspace_events(service, subscription_id, task)
        self.assertEqual(calls, ["subscription"])

    async def test_attach_rolls_back_subscription_when_initial_send_fails(self) -> None:
        queue: asyncio.Queue[AgentspaceEvent] = asyncio.Queue()
        calls: list[str] = []
        service = SimpleNamespace(
            watcher_available=True,
            locks_snapshot=lambda: [],
            subscribe_events=lambda: ("subscription", queue),
            unsubscribe_events=lambda subscription_id: calls.append(subscription_id),
        )

        async def send_event(_event: AgentspaceEvent) -> None:
            raise RuntimeError("closed")

        with self.assertRaises(RuntimeError):
            await attach_agentspace_events(
                service,
                send_event,
                connection_label="session-a",
            )
        self.assertEqual(calls, ["subscription"])

    async def test_forward_task_propagates_cancellation(self) -> None:
        queue: asyncio.Queue[AgentspaceEvent] = asyncio.Queue()

        async def send_event(_event: AgentspaceEvent) -> None:
            self.fail("send_event should not run")

        task = asyncio.create_task(
            forward_agentspace_events(
                queue,
                send_event,
                connection_label="test",
            )
        )
        await asyncio.sleep(0)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task


if __name__ == "__main__":
    unittest.main()
