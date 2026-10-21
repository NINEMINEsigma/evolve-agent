"""Gateway 输入接收边界与就绪管理；连接本身不冒充业务输入。"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from entity.constant import ApplicationState
from interface.runtime_system import IRuntimeSystem
from system.lifecycle import ApplicationStoppingError, LifecycleFailure


class GatewayAdmission:
    """HTTP/WS 新业务与 WS 连接共享同一 Runtime 接收状态。"""

    def __init__(self, runtime: IRuntimeSystem) -> None:
        self._runtime = runtime
        self._accepting = True

    def stop_accepting(self) -> None:
        self._accepting = False

    @contextmanager
    def admit_business(self) -> Iterator[None]:
        """RUNNING 且本入口未封闭时允许新业务；调用方不得在此 await。"""
        with self._runtime.admission():
            if not self._accepting:
                raise ApplicationStoppingError("Gateway has stopped accepting new work")
            yield

    @contextmanager
    def admit_connection(self) -> Iterator[None]:
        """STARTING/RUNNING 期间允许建立长连接；STOPPING 后明确拒绝新连接。"""
        if self._runtime.state not in (ApplicationState.STARTING, ApplicationState.RUNNING):
            raise ApplicationStoppingError("Gateway is shutting down")
        yield

    def require_open_connection(self) -> None:
        """已建立连接上的单条输入准入；RUNNING 期间受全局接收状态约束。"""
        if self._runtime.state is ApplicationState.RUNNING:
            self._runtime.require_running()
            return
        if self._runtime.state is ApplicationState.STARTING:
            return
        raise ApplicationStoppingError("Application is shutting down")

    def is_serving(self) -> bool:
        return self._accepting and self._runtime.state is ApplicationState.RUNNING


class GatewayReadyTracker:
    """uvicorn 真实启动完成与接受连接共用同一事件。"""

    def __init__(self) -> None:
        import asyncio
        self._event = asyncio.Event()

    def mark_ready(self) -> None:
        self._event.set()

    async def wait_ready(self) -> None:
        await self._event.wait()

    @property
    def ready(self) -> bool:
        return self._event.is_set()
