"""Live activity event stream."""

import asyncio
from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from entity.constant import ACTIVITY_SSE_EVENT_NAME, ACTIVITY_SSE_GAP_EVENT_NAME, ACTIVITY_SSE_HEARTBEAT_SECONDS
from entity.puretype import ActivityEvent, ActivityStreamGap
from gateway.http_boundary import require_business_http
from interface.api_component import APIComponent
from interface.logger_system import ILoggerSystem
from interface.runtime_system import IRuntimeSystem


def _activity_sse(item: ActivityEvent | ActivityStreamGap) -> str:
    event_name = ACTIVITY_SSE_EVENT_NAME if isinstance(item, ActivityEvent) else ACTIVITY_SSE_GAP_EVENT_NAME
    return f"event: {event_name}\ndata: {item.model_dump_json()}\n\n"


class ActivityEventsAPI(APIComponent):
    def display(self, router: APIRouter) -> None:
        router.add_api_route("/api/activity/events", self.handler, methods=["GET"], name="activity_events")

    async def handler(self, req: Request) -> StreamingResponse:
        """Stream only activity events published after this subscription starts."""
        gateway = self.gateway
        require_business_http(gateway.admission)
        logger_system = self.get_system(ILoggerSystem)
        subscription_id, queue = logger_system.subscribe_activity_events()
        runtime = self.get_system(IRuntimeSystem)

        async def stream():
            shutdown_wait = gateway.task_owner.track(asyncio.create_task(
                runtime.shutdown_event.wait(), name="activity-sse-shutdown-wait",
            ))
            try:
                while not await req.is_disconnected():
                    event_wait = gateway.task_owner.track(asyncio.create_task(
                        queue.get(), name="activity-sse-event-wait",
                    ))
                    try:
                        done, _ = await asyncio.wait(
                            (event_wait, shutdown_wait), timeout=ACTIVITY_SSE_HEARTBEAT_SECONDS,
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
                        yield _activity_sse(event_wait.result())
                    else:
                        yield ": keepalive\n\n"
            finally:
                if not shutdown_wait.done():
                    gateway.task_owner.cancel(shutdown_wait)
                await asyncio.gather(shutdown_wait, return_exceptions=True)
                logger_system.unsubscribe_activity_events(subscription_id)

        return StreamingResponse(stream(), media_type="text/event-stream", headers={
            "Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no",
        })


api = ActivityEventsAPI()
