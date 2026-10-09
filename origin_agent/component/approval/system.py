"""审批系统：模式存储、后端与白名单的唯一生命周期所有者。"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from framework import AsyncSystem

from component.approval.allowlist import ToolAllowlistStore
from component.approval.manager import ApprovalBackendManager
from component.approval.mode_store import ApprovalModeStore
from entity.constant import SESSIONS_DIR_NAME, SYSTEM_QUIESCE_TIMEOUT_SECONDS
from entity.messages import BaseMessage
from system.lifecycle import ApplicationStoppingError, TaskOwner
from system.llm_profile_store import LLMProfileStore
from system.runtime import RuntimeSystem


class ApprovalSystem(AsyncSystem):
    """不在唤醒时请求模型；已配置模型的调用由明确请求方等待。"""

    def __init__(self) -> None:
        super().__init__(dependencies=(RuntimeSystem, LLMProfileStore))
        self._runtime: RuntimeSystem
        self._mode_store: ApprovalModeStore
        self._backend_manager: ApprovalBackendManager
        self._allowlist: ToolAllowlistStore
        self._requests: TaskOwner
        self._admission_closed = False

    async def virtual_awake(self) -> None:
        self._runtime = self.get_system(RuntimeSystem)
        profiles = self.get_system(LLMProfileStore)
        ctx = self._runtime.context
        self._mode_store = ApprovalModeStore(ctx.workspace / SESSIONS_DIR_NAME)
        self._backend_manager = ApprovalBackendManager(ctx, profiles)
        self._allowlist = ToolAllowlistStore(ctx.workspace)
        self._requests = TaskOwner("ApprovalSystem", self._runtime.record_failure)

    @property
    def mode_store(self) -> ApprovalModeStore:
        return self._mode_store

    @property
    def backend_manager(self) -> ApprovalBackendManager:
        return self._backend_manager

    @property
    def allowlist(self) -> ToolAllowlistStore:
        return self._allowlist

    @contextmanager
    def _admit_request(self) -> Iterator[None]:
        with self._runtime.admission():
            if self._admission_closed:
                raise ApplicationStoppingError("Approval request admission is closed")
            yield

    async def chat(self, messages: list[BaseMessage]) -> str:
        return await self._requests.run_request(
            lambda: self._chat(messages), name="approval-model-request",
            admission=self._admit_request,
        )

    async def _chat(self, messages: list[BaseMessage]) -> str:
        backend = self._backend_manager.get_backend()
        if backend is None:
            raise RuntimeError("Approval Profile is not available")
        return await backend.chat(messages)

    def close_admission(self) -> None:
        self._admission_closed = True

    async def cancel_pending(self) -> None:
        self.close_admission()
        await self._requests.cancel_and_wait(timeout=SYSTEM_QUIESCE_TIMEOUT_SECONDS)

    async def virtual_shotdown(self) -> None:
        # 未退出的请求仍可能使用后端；先等待，成功退出后才释放缓存。
        try:
            await self.cancel_pending()
        except BaseException as failure:
            if self._requests.is_idle:
                try:
                    await self._backend_manager.shutdown()
                except BaseException as cleanup_error:
                    raise BaseExceptionGroup(
                        "Approval cleanup failed", [failure, cleanup_error]
                    ) from None
            raise
        await self._backend_manager.shutdown()
