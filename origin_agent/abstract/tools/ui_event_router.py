"""工具结果的 UI 事件路由；映射与在途发送由唯一 AsyncSystem 持有。"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any, Callable

from framework import AsyncSystem

from entity.constant import SYSTEM_QUIESCE_TIMEOUT_SECONDS
from system.lifecycle import ApplicationStoppingError, LifecycleFailure, TaskOwner
from system.runtime import RuntimeSystem

if TYPE_CHECKING:
    from entry.agent_sink import AgentSink


class UIEventRouter(AsyncSystem):
    """工具显式注册事件 handler；关闭刷新结束前保留结果发送能力。"""

    def __init__(self) -> None:
        super().__init__(dependencies=(RuntimeSystem,))
        self._handlers: dict[str, Callable] = {}
        self._task_owner: TaskOwner | None = None
        self._closed = False

    async def virtual_awake(self) -> None:
        runtime = self.get_system(RuntimeSystem)
        self._task_owner = TaskOwner("tool-ui-events", runtime.record_failure)

    @property
    def task_owner(self) -> TaskOwner:
        if self._task_owner is None:
            raise LifecycleFailure("UIEventRouter has not been awakened")
        return self._task_owner

    def register(self, tool_name: str, handler: Callable) -> None:
        """保存显式注册协议传入的 handler，不在导入期取得全局实例。"""
        if self._closed:
            raise ApplicationStoppingError("UI event registration has closed")
        self._handlers[tool_name] = handler

    def get_handler(self, tool_name: str) -> Callable | None:
        return self._handlers.get(tool_name)

    @contextmanager
    def _admit_emit(self) -> Iterator[None]:
        # 既有结果在 STOPPING 仍须回显；最终注销才封闭本路由。
        if self._closed:
            raise ApplicationStoppingError("UI event output has closed")
        yield

    async def emit_for(
        self,
        tool_name: str,
        result: Any,
        sink: AgentSink,
        session_id: str,
    ) -> None:
        handler = self.get_handler(tool_name)
        if handler is None:
            return
        await self.task_owner.run_request(
            lambda: handler(result, sink, session_id, tool_name),
            name=f"tool-ui-{tool_name}",
            admission=self._admit_emit,
        )
        # 断线由 FrontendSink 的网络边界处理；内部错误不伪装成成功发送。

    async def virtual_shotdown(self) -> None:
        self._closed = True
        await self.task_owner.cancel_and_wait(timeout=SYSTEM_QUIESCE_TIMEOUT_SECONDS)
        self._handlers.clear()
