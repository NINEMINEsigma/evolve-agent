"""由项目级审批 Profile 驱动的脱手模式 LLM 后端。"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from entity.constant import APPROVAL_MAX_OUTPUT_TOKENS, APPROVAL_TEMPERATURE
from entity.messages import BaseMessage
from entity.puretype import LLMProfile

if TYPE_CHECKING:
    from abstract.llm.client import BaseLLMClient
    from system.context import RuntimeContext
    from system.llm_profile_store import LLMProfileStore

logger = logging.getLogger(__name__)


class ApprovalBackend(ABC):
    """脱手模式审批后端抽象。"""

    @abstractmethod
    async def chat(self, messages: list[BaseMessage]) -> str:
        """发送普通对话请求并返回模型文本。"""
        ...

    @abstractmethod
    def is_available(self) -> bool:
        """返回审批 Profile 是否可解析且具备必需连接字段。"""
        ...


class ProfileApprovalBackend(ApprovalBackend):
    """通过 LLM Profile 根对象连接外部管理模型的审批后端。"""

    def __init__(
        self,
        ctx: RuntimeContext,
        llm_profile_store: LLMProfileStore,
    ) -> None:
        self._ctx = ctx
        self._llm_profile_store = llm_profile_store
        self._client: BaseLLMClient | None = None
        self._client_fingerprint: tuple[str, str, str, str, int] | None = None

    @staticmethod
    def _connection_fingerprint(
        profile: LLMProfile,
    ) -> tuple[str, str, str, str, int]:
        return (
            profile.llm_client_name,
            profile.base_url,
            profile.model,
            profile.api_key,
            profile.max_context_tokens,
        )

    @staticmethod
    def _approval_profile(profile: LLMProfile) -> LLMProfile:
        """创建审批参数副本，不修改 LLM Profile 根对象。"""
        return profile.model_copy(update={
            "temperature": APPROVAL_TEMPERATURE,
            "max_output_tokens": APPROVAL_MAX_OUTPUT_TOKENS,
            "reasoning_effort": "",
        })

    def is_available(self) -> bool:
        profile = self._llm_profile_store.get_approval_profile()
        if profile is None:
            return False
        return all((
            profile.llm_client_name.strip(),
            profile.base_url.strip(),
            profile.model.strip(),
        ))

    def _get_client(self) -> BaseLLMClient:
        profile = self._llm_profile_store.get_approval_profile()
        if profile is None:
            raise RuntimeError("Approval Profile is not configured")
        missing = [
            field
            for field in ("llm_client_name", "base_url", "model")
            if not str(getattr(profile, field, "")).strip()
        ]
        if missing:
            raise ValueError(
                f"Approval Profile {profile.name!r} is missing required fields: "
                + ", ".join(missing)
            )

        fingerprint = self._connection_fingerprint(profile)
        if self._client is None or self._client_fingerprint != fingerprint:
            from abstract.llm.loader import create_llm_client

            approval_profile = self._approval_profile(profile)
            self._client = create_llm_client(
                approval_profile.llm_client_name,
                self._ctx,
                approval_profile,
            )
            self._client_fingerprint = fingerprint
            logger.debug(
                "Approval client (re)created | profile=%s model=%s",
                profile.name,
                profile.model,
            )
        return self._client

    def invalidate(self) -> None:
        """使缓存客户端失效；下次审批按当前 Profile 重建。"""
        self._client = None
        self._client_fingerprint = None

    async def chat(self, messages: list[BaseMessage]) -> str:
        client = self._get_client()
        response = await client.chat(messages)
        return response.content or ""