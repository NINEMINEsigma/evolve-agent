"""会话级消息队列（SP-4）。

每主会话 loop 持有一个实例：生产永不阻塞、消费双模态、事件驱动无周期计时器。

线程模型：``_pending`` 的一切变更只发生在事件循环线程——``push`` 从任意线程进来，
经 ``call_soon_threadsafe`` 落到事件循环后才入队；``drain_injected`` 由 finalize 触发，
天然运行在该 loop 的轮次协程（即事件循环线程）。无需任何锁。
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import deque
from datetime import datetime
from typing import TYPE_CHECKING, Any

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
        display_content: Any | None = None,
        client_message_id: str | None = None,
    ) -> None:
        """非阻塞投递一条消息并即时回显（D5）。

        线程安全：从任意线程调用，经 ``call_soon_threadsafe`` 落到事件循环入队。
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
        )

        self._event_loop.call_soon_threadsafe(self._enqueue_on_loop, item, display_content, client_message_id)

    def _enqueue_on_loop(
        self,
        item: QueuedMessage,
        display_content: Any | None,
        client_message_id: str | None,
    ) -> None:
        """事件循环线程内的入队 + 回显 + 唤醒。"""
        self._pending.append(item)

        # D5 回显：预测 index（与现状 router 的"收到即追加时 index=count"语义一致）
        predicted_index = self._loop.loop.history.count + len(self._pending) - 1
        echo_content = display_content if display_content is not None else item.content
        asyncio.create_task(
            self._loop.loop.get_sink().emit_user_message(
                self._loop.loop.session_id,
                echo_content,
                item.character_name,
                predicted_index,
                client_message_id=client_message_id,
            )
        )

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
        """空闲消费循环：单唤醒源（仅 push）+ run_pending_round 内部锁排队（D4）。

        PM2：无兜底 try/except，异常经 done_callback 观测后上抛终止 task。
        """
        while not self._stopped:
            self._wakeup.clear()
            while not self._stopped and self._pending:
                items: list[QueuedMessage] = []
                while self._pending:
                    items.append(self._pending.popleft())
                await self._loop.run_pending_round(items)
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
        """排空队列并就地展开为 ``_blocks`` 原生块流（D7）。

        PM5 结构性不丢消息：先只读快照 + 构造产物（可抛——P1 上抛给 finalize
        既有 try/except willing catcher），构造成功后才从 deque 移除；构造异常时
        deque 未动，消息滞留队列等下轮消费。
        """
        if not self._pending:
            return None
        items = list(self._pending)                  # 只读快照
        blocks = self._build_injection_blocks(items)  # 构造可抛——deque 未动
        for _ in range(len(items)):
            self._pending.popleft()                  # 构造成功后移除（事件循环单线程，快照即队首）
        existing = result.get("_blocks")
        merged: list = list(existing) if isinstance(existing, list) else []
        merged.extend(blocks)
        return {"_blocks": merged}

    def _build_injection_blocks(self, items: list[QueuedMessage]) -> list[dict]:
        """每条消息就地展开为：元数据头 JSON text 块 + 原始内容块（保序，媒体在原位）。"""
        blocks: list[dict] = []
        for m in items:
            header = json.dumps(
                {
                    "queued_message": {
                        "role": "user",
                        "character_name": m.character_name,
                        "source": m.source,
                        "timestamp": m.timestamp,
                    }
                },
                ensure_ascii=False,
            )
            blocks.append({"type": "text", "text": header})
            if isinstance(m.content, str):
                blocks.append({"type": "text", "text": m.content})
            elif isinstance(m.content, list):
                # 原始块 dict 逐个原样追加（序位不动，媒体就在本来位置）
                for b in m.content:
                    if isinstance(b, dict):
                        blocks.append(b)
        return blocks

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