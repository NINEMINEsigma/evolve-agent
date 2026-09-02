"""会话级消息队列（SP-4）。

每个主会话 Loop 持有一个实例；消息逐条 FIFO 消费，当前工具轮期间到达的消息
保留到后续轮次，不再通过 ``drain_injected`` 提前移出队列。
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from datetime import datetime
from typing import TYPE_CHECKING

from entity.constant import SYSTEM_CHARACTER_NAME
from entity.puretype import MessageContent, QueuedMessage

if TYPE_CHECKING:
    from entry.base_agent_loop import IMainSessionLoop

logger = logging.getLogger(__name__)


class SessionMessageQueue:
    """会话级消息队列——生产永不阻塞、消费双模态、独立异步类、会话级持有。

    由 ParentAgentLoop / MultiAgentLoop（及继承的 ColloquyLoop）在 ``__init__`` 构造。
    生命周期随 loop：gateway 在 terminate/replace 时调用 ``stop()``；旋转复用 loop 不停止。
    """

    def __init__(self, loop: "IMainSessionLoop") -> None:
        self._loop: IMainSessionLoop = loop
        self._pending: deque[QueuedMessage] = deque()
        self._wakeup: asyncio.Event | None = None
        # 队列永远在事件循环线程内被构造（loop __init__ → SessionManager.create_session → async gateway），
        # 构造时直接捕获事件循环，push 从任意线程经此引用 call_soon_threadsafe 入队。
        self._event_loop: asyncio.AbstractEventLoop = asyncio.get_running_loop()
        self._consumer_task: asyncio.Task | None = None
        self._stopped: bool = False
        # SP-4 D9：旋转检测——拿锁后比对当前 session_id，变更即知刚旋转
        self.last_known_sid: str = loop.loop.session_id

    # -- 生产 API --------------------------------------------------------

    def push(
        self,
        content: MessageContent,
        *,
        character_name: str = "",
        source: str = "",
        timestamp: str = "",
        client_message_id: str | None = None,
        visible_characters: list[str] | None = None,
        response_characters: list[str] | None = None,
        llm_profile_name: str | None = None,
    ) -> None:
        """非阻塞投递一条消息。

        线程安全：从任意线程调用，经 ``call_soon_threadsafe`` 落到事件循环入队。
        ``llm_profile_name`` 保留每条消息自己的选择；None 仅供内部消息沿用当前配置。
        push 不回显，回显由消息真正开始处理时完成。
        """
        if not character_name:
            character_name = SYSTEM_CHARACTER_NAME
        if not timestamp:
            timestamp = datetime.fromtimestamp(time.time()).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        item = QueuedMessage(
            content=content,
            character_name=character_name,
            source=source,
            timestamp=timestamp,
            visible_characters=visible_characters,
            response_characters=response_characters,
            llm_profile_name=llm_profile_name,
            client_message_id=client_message_id,
        )

        self._event_loop.call_soon_threadsafe(self._enqueue_on_loop, item)

    def _enqueue_on_loop(
        self,
        item: QueuedMessage,
    ) -> None:
        """事件循环线程内的入队 + 唤醒。"""
        with self._loop.loop.app.profile_lock:
            self._pending.append(item)

        self._ensure_consumer()
        if self._wakeup is not None:
            self._wakeup.set()

    def _ensure_consumer(self) -> None:
        """懒启动 consumer task（仅事件循环线程调用）。"""
        if self._consumer_task is not None or self._stopped:
            return
        self._wakeup = asyncio.Event()
        self._consumer_task = asyncio.create_task(
            self._consume_loop(),
            name=f"session-message-queue-{self._loop.loop.session_id[:8]}",
        )
        self._consumer_task.add_done_callback(self._on_consumer_done)

    # -- 消费循环（模态 B：空闲消费）----------------------------------------

    async def _consume_loop(self) -> None:
        """按 FIFO 每次只处理一条消息。"""
        while not self._stopped:
            self._wakeup.clear()
            while not self._stopped:
                with self._loop.loop.app.profile_lock:
                    if not self._pending:
                        break
                    item = self._pending.popleft()
                await self._loop.run_pending_round([item])
            await self._wakeup.wait()

    def _on_consumer_done(self, task: asyncio.Task) -> None:
        """consumer task 结束回调：观测异常 + 复位引用支持重启（R2）。"""
        if task.cancelled():
            self._consumer_task = None
            return
        exc = task.exception()
        if exc is not None:
            logger.error(
                "SessionMessageQueue consumer died | session=%s",
                self._loop.loop.session_id,
                exc_info=exc,
            )
        self._consumer_task = None

    # -- 模态 A：链中注入（由 finalize_tool_result 的 field_injector 调用）----

    def drain_injected(self, result: dict) -> dict | None:
        """保留当前工具轮期间到达的消息，等待后续 FIFO 轮次处理。"""
        return None

    # -- 生命周期 ---------------------------------------------------------

    def stop(self) -> None:
        """停止队列消费者（可跨线程调用）。

        gateway 在 loop 消亡时调用；旋转复用 loop 不调用。残留消息计数后丢弃。
        """
        self._stopped = True
        if self._pending:
            logger.warning(
                "Discarding %d queued messages on stop | session=%s",
                len(self._pending),
                self._loop.loop.session_id,
            )
        if not self._event_loop.is_closed():
            if self._wakeup is not None:
                self._event_loop.call_soon_threadsafe(self._wakeup.set)
            if self._consumer_task is not None:
                self._event_loop.call_soon_threadsafe(self._consumer_task.cancel)

    def mark_stopped(self) -> None:
        """标记队列停止但不取消正在运行的 consumer task。

        用于 replace_loop 场景：旧 loop 的 consumer task 正在执行工具调用
        （如 enter_multi_agent / exit_multi_agent），立即 cancel 会导致
        CancelledError 穿透。标记 _stopped 后，consumer 在当前 run_pending_round
        自然完成后退出 _consume_loop 循环。
        """
        self._stopped = True
        if self._pending:
            logger.warning(
                "Discarding %d queued messages on mark_stopped | session=%s",
                len(self._pending),
                self._loop.loop.session_id,
            )
        if not self._event_loop.is_closed():
            if self._wakeup is not None:
                self._event_loop.call_soon_threadsafe(self._wakeup.set)