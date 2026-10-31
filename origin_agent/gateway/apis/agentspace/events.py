"""Agentspace events for the independent editor."""

import asyncio
from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from entity.constant import AGENTSPACE_SSE_HEARTBEAT_SECONDS
from entity.puretype import AgentspaceEvent
from gateway.agentspace_event_bridge import build_initial_agentspace_events
from gateway.http_boundary import require_business_http
from interface.api_component import APIComponent
from interface.agentspace_service import IAgentspaceService
from interface.runtime_system import IRuntimeSystem


def _agentspace_sse(event: AgentspaceEvent) -> str:
    return f"id: {event.sequence}\nevent: agentspace\ndata: {event.model_dump_json()}\n\n"


class AgentspaceEventsAPI(APIComponent):
    def display(self, router: APIRouter) -> None:
        router.add_api_route("/api/agentspace/events", self.handler, methods=["GET"], name="agentspace_events")

    async def handler(self, req: Request) -> StreamingResponse:
        gateway = self.gateway
        require_business_http(gateway.admission)
        service = self.get_system(IAgentspaceService)
        subscription_id, queue = service.subscribe_events()
        runtime = self.get_system(IRuntimeSystem)

        async def stream():
            try:
                for initial_event in build_initial_agentspace_events(service):
                    yield _agentspace_sse(initial_event)
                shutdown_wait = gateway.task_owner.track(asyncio.create_task(
                    runtime.shutdown_event.wait(), name="agentspace-sse-shutdown-wait",
                ))
                try:
                    while not await req.is_disconnected():
                        event_wait = gateway.task_owner.track(asyncio.create_task(
                            queue.get(), name="agentspace-sse-event-wait",
                        ))
                        try:
                            done, _ = await asyncio.wait(
                                (event_wait, shutdown_wait), timeout=AGENTSPACE_SSE_HEARTBEAT_SECONDS,
                                return_when=asyncio.FIRST_COMPLETED,
                            )
                        finally:
                            if not event_wait.done():
                                gateway.task_owner.cancel(event_wait)
                                await asyncio.gather(event_wait, return_exceptions=True)
                        if shutdown_wait in done:
                            return
                        if event_wait in done:
                            error = event_wait.exception()
                            if error is not None:
                                raise error
                            yield _agentspace_sse(event_wait.result())
                        else:
                            yield ": keepalive\n\n"
                finally:
                    gateway.task_owner.cancel(shutdown_wait)
                    await asyncio.gather(shutdown_wait, return_exceptions=True)
            finally:
                service.unsubscribe_events(subscription_id)

        return StreamingResponse(stream(), media_type="text/event-stream", headers={
            "Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no",
        })


api = AgentspaceEventsAPI()
