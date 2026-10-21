"""Agentspace 事件到 Gateway 传输层的共享桥接辅助。"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone

from entity.constant import (
    AGENTSPACE_WS_COALESCE_LOG_WINDOW_SECONDS,
    AGENTSPACE_WS_SEND_TIMEOUT_SECONDS,
)
from entity.puretype import (
    AgentspaceEvent,
    AgentspaceEventKind,
    AgentspaceEventSource,
)
from interface.agentspace_service import IAgentspaceService
from interface.gateway_system import IGatewaySystem

logger = logging.getLogger(__name__)


class AgentspaceSendTimeout(TimeoutError):
    """Per-event send timeout for a slow agentspace WebSocket consumer."""


class AgentspaceConnectionClosed(Exception):
    """聊天 WebSocket 对端已断开：连接级例常结束，不作为应用级失败上报。

    由传输层发送回调在发现连接已关闭（或发送时收到对端断开）时抛出，
    转发循环原样传播。与 `AgentspaceSendTimeout` 的区别是对端已不存在，
    无需也不能再发送 1011 关闭帧。
    """


def is_connection_termination(error: BaseException) -> bool:
    """返回 True 表示该异常属于连接级例常结束，应标记预期失败。

    `AgentspaceSendTimeout` 与 `AgentspaceConnectionClosed` 均只终止当前
    连接，不代表应用不变式破裂，因此不进入应用失败关闭流程。
    """
    return isinstance(error, (AgentspaceSendTimeout, AgentspaceConnectionClosed))


def requires_connection_eviction(error: BaseException) -> bool:
    """返回 True 表示需主动驱逐该连接（对端仍可能存活但接收不过来）。

    仅 `AgentspaceSendTimeout` 返回 True；对端已断开时没有可关闭的连接，
    调用方必须先判定本函数再判定 `is_connection_termination`。
    """
    return isinstance(error, AgentspaceSendTimeout)


def build_initial_agentspace_events(
    service: IAgentspaceService,
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
    service: IAgentspaceService,
    send_event: Callable[[AgentspaceEvent], Awaitable[None]],
    *,
    connection_label: str
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
    service: IAgentspaceService,
    subscription_id: str | None,
    task: asyncio.Task[None] | None
    ) -> None:
    """幂等收割转发 task 并注销 EventHub 订阅。

    转发 task 已登记到 GatewaySystem 的 TaskOwner；取消必须经
    ``owner.cancel`` 标记预期取消，不能让 Owner 看到未授权取消（RV11）。
    应用关闭阶段 Owner 已在收尾时，任务由 cancel_and_wait 统一处理。
    """
    if task is not None:
        from system.application import Application
        from system.lifecycle import LifecycleFailure

        try:
            owner = Application.current().get_system(IGatewaySystem).task_owner
        except Exception:
            owner = None

        cancelled = False
        if owner is not None:
            try:
                cancelled = owner.cancel(task)
            except LifecycleFailure:
                # Owner 已在关闭（closing 或任务记录已结算），任务由
                # cancel_and_wait 持有，不做第二次裸取消。
                cancelled = True
        if not cancelled and not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    if subscription_id is not None:
        service.unsubscribe_events(subscription_id)


async def forward_agentspace_events(
    queue: asyncio.Queue[AgentspaceEvent],
    send_event: Callable[[AgentspaceEvent], Awaitable[None]],
    *,
    connection_label: str
    ) -> None:
    """低优先级转发事件；突发积压只发送一个 resync。

    单事件发送超过 AGENTSPACE_WS_SEND_TIMEOUT_SECONDS 时抛
    AgentspaceSendTimeout 终止转发，由调用方标记预期失败并以 1011
    断连驱逐慢消费者。`send_event` 回调在发现对端已断开时抛
    AgentspaceConnectionClosed；本循环不做包裹也不吞掉任何异常，
    该哨兵原样传播给调用方作为连接级例常结束处理。

    折叠告警按时间窗限流并携带窗口累计 dropped。
    """
    last_warned = -AGENTSPACE_WS_COALESCE_LOG_WINDOW_SECONDS
    window_dropped_total = 0
    while True:
        first = await queue.get()
        # 先让聊天、审批、中断与心跳等既有任务取得运行机会。
        await asyncio.sleep(0)
        event, dropped = coalesce_agentspace_event(first, queue)
        if dropped:
            now = time.monotonic()
            if now - last_warned >= AGENTSPACE_WS_COALESCE_LOG_WINDOW_SECONDS:
                if window_dropped_total:
                    logger.debug(
                        "Agentspace WebSocket events coalesced | connection=%s "
                        "dropped=%d sequence=%d (window suppressed: %d events since last warning)",
                        connection_label, dropped, event.sequence, window_dropped_total,
                    )
                else:
                    logger.debug(
                        "Agentspace WebSocket events coalesced | connection=%s dropped=%d sequence=%d",
                        connection_label, dropped, event.sequence,
                    )
                last_warned = now
                window_dropped_total = 0
            else:
                window_dropped_total += dropped
        try:
            async with asyncio.timeout(AGENTSPACE_WS_SEND_TIMEOUT_SECONDS):
                await send_event(event)
        except TimeoutError as exc:
            raise AgentspaceSendTimeout(
                f"send exceeded {AGENTSPACE_WS_SEND_TIMEOUT_SECONDS}s"
            ) from exc
