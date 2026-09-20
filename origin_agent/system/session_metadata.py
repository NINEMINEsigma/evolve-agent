"""全局元数据 Profile 驱动的会话标题、标签与摘要服务。"""

from __future__ import annotations

import json
import logging
import threading
from typing import TYPE_CHECKING

from abstract.llm.formats import to_summary_dict
from abstract.llm.loader import create_llm_client
from entity.constant import (
    AUTO_TAGS_CONTENT_MAX,
    AUTO_TITLE_CONTENT_MAX,
    META_EXTRACTOR_CHARACTER,
    SESSIONS_DIR_NAME,
)
from entity.messages import BaseMessage, CharacterConversationMessage, History
from entity.puretype import LLMProfile, MetadataProfileState, Role
from entry.agent_support.history_summary import summarize_history
from system.session_store import SessionStore
from system.templates import read_template

if TYPE_CHECKING:
    from abstract.llm.client import BaseLLMClient
    from system.context import RuntimeContext
    from system.llm_profile_store import LLMProfileStore

logger = logging.getLogger(__name__)


class SessionMetadataError(RuntimeError):
    """可预期的会话元数据业务失败。"""


class MetadataProfileUnavailableError(SessionMetadataError):
    """没有可用的全局或目标会话 Profile。"""


class MetadataGenerationError(SessionMetadataError):
    """元数据模型调用或输出解析失败。"""


class SessionMetadataService:
    """解析目标会话的元数据 Profile，并生成标题、标签与摘要。"""

    def __init__(
        self,
        runtime_context: RuntimeContext,
        llm_profile_store: LLMProfileStore,
        profile_lock: threading.RLock,
    ) -> None:
        self._runtime_context = runtime_context
        self._llm_profile_store = llm_profile_store
        self._profile_lock = profile_lock
        self._session_store = SessionStore(
            runtime_context.workspace / SESSIONS_DIR_NAME
        )

    @staticmethod
    def _missing_connection_fields(profile: LLMProfile) -> list[str]:
        return [
            field
            for field in ("llm_client_name", "base_url", "model")
            if not str(getattr(profile, field, "")).strip()
        ]

    def get_state(self) -> MetadataProfileState:
        """返回全局元数据 Profile 的服务端权威状态。"""
        with self._profile_lock:
            profile = self._llm_profile_store.get_metadata_profile()
            if profile is None:
                return MetadataProfileState()
            return MetadataProfileState(
                profile_name=profile.name,
                model=profile.model or None,
                available=not self._missing_connection_fields(profile),
            )

    def select_profile(self, profile: LLMProfile | None) -> MetadataProfileState:
        """设置或清空全局元数据 Profile。"""
        with self._profile_lock:
            if profile is not None:
                missing = self._missing_connection_fields(profile)
                if missing:
                    raise MetadataProfileUnavailableError(
                        f"全局元数据 Profile {profile.name!r} 缺少必需字段："
                        + ", ".join(missing)
                    )
            self._llm_profile_store.set_metadata_profile(profile)
            return self.get_state()

    def is_selected_profile(self, profile: LLMProfile) -> bool:
        """返回目标是否为当前全局元数据 Profile。"""
        return self._llm_profile_store.is_metadata_profile(profile)

    def _resolve_profile_snapshot(self, session_id: str) -> LLMProfile:
        """按全局优先、目标会话回退规则取得单次任务 Profile 快照。"""
        with self._profile_lock:
            profile = self._llm_profile_store.get_metadata_profile()
            if profile is None:
                try:
                    profile_name = self._session_store.read_active_profile_name(
                        session_id
                    )
                except Exception as exc:
                    raise MetadataProfileUnavailableError(
                        f"无法读取会话 {session_id!r} 的活动 Profile"
                    ) from exc
                if not profile_name:
                    raise MetadataProfileUnavailableError(
                        "未配置全局元数据 Profile，目标会话也没有活动 Profile"
                    )
                try:
                    profile = self._llm_profile_store.get_profile(profile_name)
                except LookupError as exc:
                    raise MetadataProfileUnavailableError(
                        f"目标会话活动 Profile {profile_name!r} 不存在"
                    ) from exc

            missing = self._missing_connection_fields(profile)
            if missing:
                raise MetadataProfileUnavailableError(
                    f"元数据 Profile {profile.name!r} 缺少必需字段："
                    + ", ".join(missing)
                )
            return profile.model_copy()

    def _create_client(self, session_id: str) -> BaseLLMClient:
        profile = self._resolve_profile_snapshot(session_id)
        try:
            return create_llm_client(
                profile.llm_client_name,
                self._runtime_context,
                profile,
            )
        except Exception as exc:
            raise MetadataProfileUnavailableError(
                f"无法创建元数据 Profile {profile.name!r} 的 LLM 客户端：{exc}"
            ) from exc

    def _read_history(self, session_id: str) -> History:
        try:
            history = self._session_store.read_history(session_id)
        except Exception as exc:
            raise MetadataGenerationError(
                f"无法读取会话 {session_id!r} 的历史：{exc}"
            ) from exc
        if history is None or history.count == 0:
            raise MetadataGenerationError("会话历史为空，无法生成元数据")
        return history

    async def generate_title(self, session_id: str) -> str:
        """根据目标会话完整对话历史生成标题。"""
        history = self._read_history(session_id)
        messages = [
            message
            for message in history.iter_messages()
            if isinstance(message, CharacterConversationMessage)
        ]
        if not messages:
            raise MetadataGenerationError("会话没有可用于生成标题的对话消息")
        messages_json = [
            item
            for message in messages
            if (item := to_summary_dict(message)) is not None
        ]
        user_prompt = read_template("auto_title_input.txt").replace(
            "{{context}}",
            json.dumps(messages_json, ensure_ascii=False)[-AUTO_TITLE_CONTENT_MAX:],
        )
        try:
            response = await self._create_client(session_id).chat(
                [
                    BaseMessage(
                        role=Role.SYSTEM,
                        content=read_template("auto_title.txt"),
                    ),
                    BaseMessage(role=Role.USER, content=user_prompt),
                ],
                character=META_EXTRACTOR_CHARACTER,
            )
        except SessionMetadataError:
            raise
        except Exception as exc:
            raise MetadataGenerationError(f"自动标题生成失败：{exc}") from exc
        title = (response.content or "").strip().strip("\"'")[:50]
        if not title:
            raise MetadataGenerationError("元数据模型返回了空标题")
        return title

    async def generate_tags(
        self,
        session_id: str,
        existing_tags: list[str],
    ) -> list[str]:
        """根据目标会话完整对话历史生成标签。"""
        history = self._read_history(session_id)
        messages = [
            message
            for message in history.iter_messages()
            if isinstance(message, CharacterConversationMessage)
        ]
        if not messages:
            raise MetadataGenerationError("会话没有可用于生成标签的对话消息")

        existing_tags_hint = ""
        if existing_tags:
            existing_tags_hint = (
                "\n\nExisting tags in the system (prefer reusing these when applicable): "
                + ", ".join(existing_tags)
            )
        system_prompt = read_template("session_tags.txt").replace(
            "{{existing_tags}}", existing_tags_hint
        )
        messages_json = [
            item
            for message in messages
            if (item := to_summary_dict(message)) is not None
        ]
        user_prompt = read_template("session_tags_input.txt").replace(
            "{{old_text}}",
            json.dumps(messages_json, ensure_ascii=False)[-AUTO_TAGS_CONTENT_MAX:],
        )
        try:
            response = await self._create_client(session_id).chat(
                [
                    BaseMessage(role=Role.SYSTEM, content=system_prompt),
                    BaseMessage(role=Role.USER, content=user_prompt),
                ],
                character=META_EXTRACTOR_CHARACTER,
                response_format={"type": "json_object"},
            )
            result = json.loads(response.content or "")
        except SessionMetadataError:
            raise
        except Exception as exc:
            raise MetadataGenerationError(f"自动标签生成失败：{exc}") from exc

        if isinstance(result, dict):
            if "tags" in result:
                result = result["tags"]
            elif "tag" in result:
                result = result["tag"]
            else:
                result = next(
                    (
                        value
                        for value in result.values()
                        if isinstance(value, list)
                        and all(isinstance(item, str) for item in value)
                    ),
                    None,
                )
        if not isinstance(result, list) or not result or not all(
            isinstance(item, str) and item.strip() for item in result
        ):
            raise MetadataGenerationError("元数据模型返回了无效的标签列表")
        return [item.strip() for item in result]

    async def generate_summary(
        self,
        session_id: str,
        history: History | None = None,
    ) -> str:
        """生成摘要但不写入磁盘，供临时压缩等调用方使用。"""
        target_history = history if history is not None else self._read_history(session_id)
        if target_history.count == 0:
            raise MetadataGenerationError("会话历史为空，无法生成摘要")
        try:
            summary = await summarize_history(
                target_history,
                self._create_client(session_id),
            )
        except SessionMetadataError:
            raise
        except Exception as exc:
            raise MetadataGenerationError(f"会话摘要生成失败：{exc}") from exc
        if not summary:
            raise MetadataGenerationError("元数据模型返回了空摘要")
        return summary

    async def regenerate_summary(self, session_id: str) -> str:
        """强制重生成摘要，仅成功后覆盖旧摘要。"""
        summary = await self.generate_summary(session_id)
        try:
            self._session_store.write_summary(session_id, summary)
        except Exception as exc:
            raise MetadataGenerationError(f"会话摘要保存失败：{exc}") from exc
        return summary

    async def ensure_summary(self, session_id: str) -> str:
        """返回已有摘要，缺失时保底生成并持久化。"""
        try:
            summary = self._session_store.read_summary(session_id)
        except Exception as exc:
            raise MetadataGenerationError(f"会话摘要读取失败：{exc}") from exc
        if summary:
            return summary
        return await self.regenerate_summary(session_id)
