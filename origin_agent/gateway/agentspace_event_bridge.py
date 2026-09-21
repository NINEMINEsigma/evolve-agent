"""Agentspace 事件到 Gateway 传输层的共享桥接辅助。"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone

from entity.puretype import (
    AgentspaceEvent,
    AgentspaceEventKind,
    AgentspaceEventSource,
)
from system.agentspace import AgentspaceService

logger = logging.getLogger(__name__)


def build_initial_agentspace_events(
    service: AgentspaceService,
) -> list[AgentspaceEvent]:
    """构造 SSE 与聊天 WebSocket 共用的 Agentspace 初始状态。"""
    now = datetime.now(timezone.utc).isoformat()
    events = [
        AgentspaceEvent(
            sequence=0,
            kind=AgentspaceEventKind.RESYNC,
            source=AgentspaceEventSource.SYSTEM,
            timestamp=now,
        ),
        AgentspaceEvent(
            sequence=0,
            kind=AgentspaceEventKind.LOCKS,
            source=AgentspaceEventSource.LOCKS,
            locks=service.locks_snapshot(),
            timestamp=now,
        ),
    ]
    if not service.watcher_available:
        events.append(
            AgentspaceEvent(
                sequence=0,
                kind=AgentspaceEventKind.WATCHER_ERROR,
                source=AgentspaceEventSource.SYSTEM,
                timestamp=now,
                message="外部文件实时同步不可用，请使用手动刷新。",
            )
        )
    return events


def coalesce_agentspace_event(
    first: AgentspaceEvent,
    queue: asyncio.Queue[AgentspaceEvent],
) -> tuple[AgentspaceEvent, int]:
    """把当前积压折叠为 resync；sequence 取本批事件最大值。"""
    maximum_sequence = first.sequence
    dropped = 0
    while True:
        try:
            event = queue.get_nowait()
        except asyncio.QueueEmpty:
            break
        maximum_sequence = max(maximum_sequence, event.sequence)
        dropped += 1
    if dropped == 0:
        return first, 0
    return (
        AgentspaceEvent(
            sequence=maximum_sequence,
            kind=AgentspaceEventKind.RESYNC,
            source=AgentspaceEventSource.SYSTEM,
            timestamp=datetime.now(timezone.utc).isoformat(),
            message="websocket_event_coalesced",
        ),
        dropped,
    )


async def attach_agentspace_events(
    service: AgentspaceService,
    send_event: Callable[[AgentspaceEvent], Awaitable[None]],
    *,
    connection_label: str,
) -> tuple[str, asyncio.Task[None]]:
    """订阅 EventHub、发送初始状态并启动转发；失败时回滚订阅。"""
    subscription_id, queue = service.subscribe_events()
    try:
        for event in build_initial_agentspace_events(service):
            await send_event(event)
        task = asyncio.create_task(
            forward_agentspace_events(
                queue,
                send_event,
                connection_label=connection_label,
            ),
            name=f"agentspace-ws-{connection_label[:8]}",
        )
        return subscription_id, task
    except BaseException:
        service.unsubscribe_events(subscription_id)
        raise


async def detach_agentspace_events(
    service: AgentspaceService,
    subscription_id: str | None,
    task: asyncio.Task[None] | None,
) -> None:
    """幂等收割转发 task 并注销 EventHub 订阅。"""
    if task is not None:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    if subscription_id is not None:
        service.unsubscribe_events(subscription_id)


async def forward_agentspace_events(
    queue: asyncio.Queue[AgentspaceEvent],
    send_event: Callable[[AgentspaceEvent], Awaitable[None]],
    *,
    connection_label: str,
) -> None:
    """低优先级转发事件；突发积压只发送一个 resync。"""
    while True:
        first = await queue.get()
        # 先让聊天、审批、中断与心跳等既有任务取得运行机会。
        await asyncio.sleep(0)
        event, dropped = coalesce_agentspace_event(first, queue)
        if dropped:
            logger.warning(
                "Agentspace WebSocket events coalesced | connection=%s dropped=%d sequence=%d",
                connection_label,
                dropped,
                event.sequence,
            )
        await send_event(event)
