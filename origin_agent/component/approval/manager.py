"""Application 审批系统持有的 Profile 后端与客户端缓存。"""

from __future__ import annotations

from component.approval.backend import ApprovalBackend, ProfileApprovalBackend
from entity.puretype import ApprovalProfileState
from system.context import RuntimeContext
from interface.llm_profile_store import ILLMProfileStore


class ApprovalBackendManager:
    """不自行创建全局入口，生命周期由 ApprovalSystem 管理。"""

    def __init__(
        self,
        ctx: RuntimeContext,
        llm_profile_store: ILLMProfileStore
        ) -> None:
        self._llm_profile_store = llm_profile_store
        self._backend = ProfileApprovalBackend(ctx, llm_profile_store)

    def get_backend(self) -> ApprovalBackend | None:
        return self._backend if self._backend.is_available() else None

    def get_state(self) -> ApprovalProfileState:
        with self._llm_profile_store.locked():
            profile = self._llm_profile_store.get_approval_profile()
            if profile is None:
                return ApprovalProfileState()
            return ApprovalProfileState(
                profile_name=profile.name,
                model=profile.model or None,
                available=self._backend.is_available(),
            )

    def invalidate(self) -> None:
        self._backend.invalidate()

    async def shutdown(self) -> None:
        """活动审批请求已收尾后释放缓存引用；不停止用户外部模型服务。"""
        self.invalidate()
