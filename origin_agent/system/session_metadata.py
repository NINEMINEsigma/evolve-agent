"""全局元数据 Profile 驱动的会话标题、标签与摘要服务。"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Iterator
from contextlib import contextmanager
from typing import TYPE_CHECKING

from framework import AsyncSystem
from abstract.llm.formats import to_summary_dict
from abstract.llm.loader import create_llm_client
from entity.constant import (
    AUTO_TAGS_CONTENT_MAX,
    AUTO_TITLE_CONTENT_MAX,
    META_EXTRACTOR_CHARACTER,
    SESSIONS_DIR_NAME,
    SESSION_TITLE_UPDATED_ACTION,
    SYSTEM_QUIESCE_TIMEOUT_SECONDS,
)
from entity.messages import BaseMessage, CharacterConversationMessage, History
from entity.puretype import LLMProfile, MetadataProfileState, Role, ToolchainSummaryProfileState
from entry.agent_support.history_summary import summarize_history
from system.lifecycle import (
    ApplicationStoppingError,
    LifecycleFailure,
    TaskOwner,
    contains_lifecycle_failure,
)
from interface.frontend_sink import IFrontendSink
from interface.llm_profile_store import ILLMProfileStore
from interface.runtime_system import IRuntimeSystem
from interface.session_manager import ISessionManager
from interface.session_metadata_service import ISessionMetadataService
from system.session_store import SessionStore
from system.templates import read_template

if TYPE_CHECKING:
    from abstract.llm.client import BaseLLMClient

logger = logging.getLogger(__name__)


class SessionMetadataError(RuntimeError):
    """可预期的会话元数据业务失败。"""


class MetadataProfileUnavailableError(SessionMetadataError):
    """没有可用的全局或目标会话 Profile。"""


class MetadataGenerationError(SessionMetadataError):
    """元数据模型调用或输出解析失败。"""


class SessionMetadataService(ISessionMetadataService):
    """解析目标会话的元数据 Profile，并生成标题、标签与摘要。

    注册为 framework AsyncSystem，依赖 RuntimeSystem 与 LLMProfileStore；
    不创建独立的 Profile 事务锁，所有 ``_profile_lock`` 语义统一通过
    ``LLMProfileStore.locked()`` 访问同一把共享 RLock。
    """

    def __init__(self) -> None:
        super().__init__(dependencies=(IRuntimeSystem, ILLMProfileStore))
        self._runtime: IRuntimeSystem | None = None
        self._llm_profile_store: ILLMProfileStore | None = None
        self._session_store: SessionStore | None = None
        self._task_owner: TaskOwner | None = None
        self._admission_closed = False
        # 进程内 per-session 首条标题防重集合：检查与登记必须在同一同步代码段完成
        self._first_title_pending: set[str] = set()

    async def virtual_awake(self) -> None:
        self._runtime = self.get_system(IRuntimeSystem)
        self._llm_profile_store = self.get_system(ILLMProfileStore)
        ctx = self._runtime.context
        self._session_store = SessionStore(ctx.workspace / SESSIONS_DIR_NAME)
        self._task_owner = TaskOwner(
            "SessionMetadataService",
            self._runtime.record_failure,
        )

    @property
    def runtime(self) -> IRuntimeSystem:
        if self._runtime is None:
            raise LifecycleFailure("SessionMetadataService has not been awakened")
        return self._runtime

    @property
    def llm_profile_store(self) -> ILLMProfileStore:
        if self._llm_profile_store is None:
            raise LifecycleFailure("SessionMetadataService has not been awakened")
        return self._llm_profile_store

    @property
    def session_store(self) -> SessionStore:
        if self._session_store is None:
            raise LifecycleFailure("SessionMetadataService has not been awakened")
        return self._session_store

    @property
    def task_owner(self) -> TaskOwner:
        if self._task_owner is None:
            raise LifecycleFailure("SessionMetadataService has not been awakened")
        return self._task_owner

    def close_admission(self) -> None:
        """关闭接收：停止后不再开始新的元数据生成调用。"""
        self._admission_closed = True

    @contextmanager
    def _admit_generation(self) -> Iterator[None]:
        """只登记操作；同步区间内不得读取文件或请求模型。"""
        with self.runtime.admission():
            if self._admission_closed:
                raise ApplicationStoppingError("Metadata generation admission is closed")
            yield

    async def cancel_pending(self) -> None:
        """封闭接收，等待完整请求结束以及请求方的取消/结果交接。"""
        self.close_admission()
        await self.task_owner.cancel_and_wait(timeout=SYSTEM_QUIESCE_TIMEOUT_SECONDS)

    async def virtual_shotdown(self) -> None:
        """解绑后仍通过已持有的 Owner 核对失败及结果交接，不仅检查活任务。"""
        await self.cancel_pending()

    @staticmethod
    def _preserve_lifecycle_error(error: BaseException) -> None:
        """业务错误转换不能掩盖生命周期失败或异常组内的取消。"""
        if isinstance(error, (ApplicationStoppingError, asyncio.CancelledError)):
            raise error
        if contains_lifecycle_failure(error):
            raise error
        if isinstance(error, BaseExceptionGroup):
            interrupted = error.subgroup((asyncio.CancelledError, ApplicationStoppingError))
            if interrupted is not None:
                raise error

    @staticmethod
    def _missing_connection_fields(profile: LLMProfile) -> list[str]:
        return [
            name
            for name, value in (
                ("llm_client_name", profile.llm_client_name),
                ("base_url", profile.base_url),
                ("model", profile.model),
            )
            if not value.strip()
        ]

    def get_state(self) -> MetadataProfileState:
        """返回全局元数据 Profile 的服务端权威状态。"""
        store = self.llm_profile_store
        with store.locked():
            profile = store.get_metadata_profile()
            if profile is None:
                return MetadataProfileState()
            return MetadataProfileState(
                profile_name=profile.name,
                model=profile.model or None,
                available=not self._missing_connection_fields(profile),
            )

    def select_profile(self, profile: LLMProfile | None) -> MetadataProfileState:
        """设置或清空全局元数据 Profile。"""
        store = self.llm_profile_store
        with store.locked():
            if profile is not None:
                missing = self._missing_connection_fields(profile)
                if missing:
                    raise MetadataProfileUnavailableError(
                        f"全局元数据 Profile {profile.name!r} 缺少必需字段："
                        + ", ".join(missing)
                    )
            store.set_metadata_profile(profile)
            return self.get_state()

    def is_selected_profile(self, profile: LLMProfile) -> bool:
        """返回目标是否为当前全局元数据 Profile。"""
        return self.llm_profile_store.is_metadata_profile(profile)

    def get_toolchain_summary_state(self) -> ToolchainSummaryProfileState:
        """返回工具链摘要 Profile 的服务端权威状态。"""
        store = self.llm_profile_store
        with store.locked():
            profile = store.get_toolchain_summary_profile()
            if profile is None:
                return ToolchainSummaryProfileState()
            return ToolchainSummaryProfileState(
                profile_name=profile.name,
                model=profile.model or None,
                available=not self._missing_connection_fields(profile),
            )

    def select_toolchain_summary_profile(
        self, profile: LLMProfile | None
    ) -> ToolchainSummaryProfileState:
        """设置或清空工具链摘要 Profile。"""
        store = self.llm_profile_store
        with store.locked():
            if profile is not None:
                missing = self._missing_connection_fields(profile)
                if missing:
                    raise MetadataProfileUnavailableError(
                        f"工具链摘要 Profile {profile.name!r} 缺少必需字段："
                        + ", ".join(missing)
                    )
            store.set_toolchain_summary_profile(profile)
            return self.get_toolchain_summary_state()

    def is_selected_toolchain_summary_profile(self, profile: LLMProfile) -> bool:
        """返回目标是否为当前工具链摘要 Profile。"""
        return self.llm_profile_store.is_toolchain_summary_profile(profile)

    def _resolve_toolchain_summary_profile_snapshot(self, session_id: str) -> LLMProfile:
        """工具链摘要 Profile 优先，未配置时回退到目标会话活动 Profile。"""
        store = self.llm_profile_store
        with store.locked():
            profile = store.get_toolchain_summary_profile()
            if profile is None:
                profile = self._resolve_session_profile_fallback(
                    session_id, purpose="工具链摘要 Profile"
                )
            self._assert_profile_usable(profile, purpose="工具链摘要 Profile")
            return profile.model_copy()

    def _create_toolchain_summary_client(self, session_id: str) -> BaseLLMClient:
        return self._create_client_for_profile(
            self._resolve_toolchain_summary_profile_snapshot(session_id),
            purpose="工具链摘要 Profile",
        )

    def _resolve_session_profile_fallback(
        self,
        session_id: str,
        *,
        purpose: str
        ) -> LLMProfile:
        """读取目标会话活动 Profile 作为全局引用缺失时的回退。

        调用方必须持有 ``LLMProfileStore.locked()`` 事务边界。
        """
        try:
            profile_name = self.session_store.read_active_profile_name(session_id)
        except Exception as exc:
            self._preserve_lifecycle_error(exc)
            raise MetadataProfileUnavailableError(
                f"无法读取会话 {session_id!r} 的活动 Profile"
            ) from exc
        if not profile_name:
            raise MetadataProfileUnavailableError(
                f"未配置{purpose}，目标会话也没有活动 Profile"
            )
        try:
            return self.llm_profile_store.get_profile(profile_name)
        except LookupError as exc:
            raise MetadataProfileUnavailableError(
                f"目标会话活动 Profile {profile_name!r} 不存在"
            ) from exc

    def _assert_profile_usable(
        self,
        profile: LLMProfile,
        *,
        purpose: str
        ) -> None:
        """校验 Profile 连接字段完整，缺失时按用途报错。"""
        missing = self._missing_connection_fields(profile)
        if missing:
            raise MetadataProfileUnavailableError(
                f"{purpose} {profile.name!r} 缺少必需字段：" + ", ".join(missing)
            )

    def _resolve_profile_snapshot(self, session_id: str) -> LLMProfile:
        """按全局优先、目标会话回退规则取得单次任务 Profile 快照。"""
        store = self.llm_profile_store
        with store.locked():
            profile = store.get_metadata_profile()
            if profile is None:
                profile = self._resolve_session_profile_fallback(
                    session_id, purpose="全局元数据 Profile"
                )
            self._assert_profile_usable(profile, purpose="元数据 Profile")
            return profile.model_copy()

    def _create_client_for_profile(
        self,
        profile: LLMProfile,
        *,
        purpose: str
        ) -> BaseLLMClient:
        # 已停机后不再创建 LLM 客户端，避免在关闭期间发起新的模型请求。
        if self._admission_closed:
            raise ApplicationStoppingError(
                "Application is no longer accepting metadata generation work"
            )
        self.runtime.require_running()
        try:
            return create_llm_client(
                profile.llm_client_name,
                self.runtime.context,
                profile,
            )
        except Exception as exc:
            self._preserve_lifecycle_error(exc)
            raise MetadataProfileUnavailableError(
                f"无法创建{purpose} {profile.name!r} 的 LLM 客户端：{exc}"
            ) from exc

    def _create_client(self, session_id: str) -> BaseLLMClient:
        return self._create_client_for_profile(
            self._resolve_profile_snapshot(session_id), purpose="元数据 Profile"
        )

    def _read_history(self, session_id: str) -> History:
        try:
            history = self.session_store.read_history(session_id)
        except Exception as exc:
            self._preserve_lifecycle_error(exc)
            raise MetadataGenerationError(
                f"无法读取会话 {session_id!r} 的历史：{exc}"
            ) from exc
        if history is None or history.count == 0:
            raise MetadataGenerationError("会话历史为空，无法生成元数据")
        return history

    async def generate_title(self, session_id: str) -> str:
        return await self.task_owner.run_request(
            lambda: self._generate_title(session_id),
            name=f"metadata-title-{session_id}",
            admission=self._admit_generation,
        )

    async def generate_tags(
        self,
        session_id: str,
        existing_tags: list[str]
        ) -> list[str]:
        return await self.task_owner.run_request(
            lambda: self._generate_tags(session_id, existing_tags),
            name=f"metadata-tags-{session_id}",
            admission=self._admit_generation,
        )

    async def generate_summary(
        self,
        session_id: str,
        history: History | None = None
        ) -> str:
        return await self.task_owner.run_request(
            lambda: self._generate_summary(session_id, history),
            name=f"metadata-summary-{session_id}",
            admission=self._admit_generation,
        )

    async def regenerate_summary(self, session_id: str) -> str:
        return await self.task_owner.run_request(
            lambda: self._regenerate_summary(session_id),
            name=f"metadata-regenerate-summary-{session_id}",
            admission=self._admit_generation,
        )

    async def ensure_summary(self, session_id: str) -> str:
        return await self.task_owner.run_request(
            lambda: self._ensure_summary(session_id),
            name=f"metadata-ensure-summary-{session_id}",
            admission=self._admit_generation,
        )

    async def generate_tool_chain_summary(
        self,
        session_id: str,
        chain_text: str
        ) -> str:
        return await self.task_owner.run_request(
            lambda: self._generate_tool_chain_summary(session_id, chain_text),
            name=f"metadata-toolchain-summary-{session_id}",
            admission=self._admit_generation,
        )

    async def _generate_title(self, session_id: str) -> str:
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
        client = self._create_client(session_id)
        try:
            response = await client.chat(
                [
                    BaseMessage(role=Role.SYSTEM, content=read_template("auto_title.txt")),
                    BaseMessage(role=Role.USER, content=user_prompt),
                ],
                character=META_EXTRACTOR_CHARACTER,
            )
        except (SessionMetadataError, ApplicationStoppingError):
            raise
        except Exception as exc:
            self._preserve_lifecycle_error(exc)
            raise MetadataGenerationError(f"自动标题生成失败：{exc}") from exc
        title = (response.content or "").strip().strip("\"'")[:50]
        if not title:
            raise MetadataGenerationError("元数据模型返回了空标题")
        return title

    async def _generate_title_from_text(
        self,
        session_id: str,
        text: str
        ) -> str:
        """根据单条用户消息文本生成标题（不读 History）。

        与 ``_generate_title`` 同构：仅上下文来源不同，避免在首条消息
        尚未提交 History 的准备阶段读取会话历史。
        """
        user_prompt = read_template("auto_title_input.txt").replace(
            "{{context}}",
            json.dumps(
                [{"role": "user", "content": text}],
                ensure_ascii=False,
            )[-AUTO_TITLE_CONTENT_MAX:],
        )
        client = self._create_client(session_id)
        try:
            response = await client.chat(
                [
                    BaseMessage(role=Role.SYSTEM, content=read_template("auto_title.txt")),
                    BaseMessage(role=Role.USER, content=user_prompt),
                ],
                character=META_EXTRACTOR_CHARACTER,
            )
        except (SessionMetadataError, ApplicationStoppingError):
            raise
        except Exception as exc:
            self._preserve_lifecycle_error(exc)
            raise MetadataGenerationError(f"自动标题生成失败：{exc}") from exc
        title = (response.content or "").strip().strip("\"'")[:50]
        if not title:
            raise MetadataGenerationError("元数据模型返回了空标题")
        return title

    async def _generate_tags(
        self,
        session_id: str,
        existing_tags: list[str]
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
        client = self._create_client(session_id)
        try:
            response = await client.chat(
                [
                    BaseMessage(role=Role.SYSTEM, content=system_prompt),
                    BaseMessage(role=Role.USER, content=user_prompt),
                ],
                character=META_EXTRACTOR_CHARACTER,
                response_format={"type": "json_object"},
            )
            result = json.loads(response.content or "")
        except (SessionMetadataError, ApplicationStoppingError):
            raise
        except Exception as exc:
            self._preserve_lifecycle_error(exc)
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

    async def _generate_summary(
        self,
        session_id: str,
        history: History | None = None
        ) -> str:
        """生成摘要但不写入磁盘，供临时压缩等调用方使用。"""
        target_history = history if history is not None else self._read_history(session_id)
        if target_history.count == 0:
            raise MetadataGenerationError("会话历史为空，无法生成摘要")
        client = self._create_client(session_id)
        try:
            summary = await summarize_history(target_history, client)
        except (SessionMetadataError, ApplicationStoppingError):
            raise
        except Exception as exc:
            self._preserve_lifecycle_error(exc)
            raise MetadataGenerationError(f"会话摘要生成失败：{exc}") from exc
        if not summary:
            raise MetadataGenerationError("元数据模型返回了空摘要")
        return summary

    async def _regenerate_summary(self, session_id: str) -> str:
        """强制重生成摘要，仅成功后覆盖旧摘要。"""
        summary = await self._generate_summary(session_id)
        try:
            self.session_store.write_summary(session_id, summary)
        except Exception as exc:
            self._preserve_lifecycle_error(exc)
            raise MetadataGenerationError(f"会话摘要保存失败：{exc}") from exc
        return summary

    async def _ensure_summary(self, session_id: str) -> str:
        """返回已有摘要，缺失时保底生成并持久化。"""
        try:
            summary = self.session_store.read_summary(session_id)
        except Exception as exc:
            self._preserve_lifecycle_error(exc)
            raise MetadataGenerationError(f"会话摘要读取失败：{exc}") from exc
        if summary:
            return summary
        return await self._regenerate_summary(session_id)

    async def _generate_tool_chain_summary(
        self,
        session_id: str,
        chain_text: str
        ) -> str:
        """用工具链摘要 Profile 对单条工具链文本生成紧凑摘要（不落盘）。"""
        if not chain_text.strip():
            raise MetadataGenerationError("工具链文本为空，无法生成摘要")
        user_prompt = read_template("toolchain_summary_input.txt").replace(
            "{{chain_text}}", chain_text
        )
        client = self._create_toolchain_summary_client(session_id)
        try:
            response = await client.chat(
                [
                    BaseMessage(role=Role.SYSTEM, content=read_template("toolchain_summary.txt")),
                    BaseMessage(role=Role.USER, content=user_prompt),
                ],
                character=META_EXTRACTOR_CHARACTER,
            )
        except (SessionMetadataError, ApplicationStoppingError):
            raise
        except Exception as exc:
            self._preserve_lifecycle_error(exc)
            raise MetadataGenerationError(f"工具链摘要生成失败：{exc}") from exc
        summary = (response.content or "").strip()
        if not summary:
            raise MetadataGenerationError("元数据模型返回了空工具链摘要")
        return summary

    # -- 首条用户消息自动标题 ----------------------------------------------

    @staticmethod
    def _fallback_title(text: str) -> str:
        """LLM 失败时的旧截取回退：前 30 字符 + 省略号。"""
        stripped = text.strip()
        # 30 字符上限与 "..." 后缀为单处使用的字面量（自原路由层截取逻辑移植）
        title = stripped[:30]
        if len(stripped) > 30:
            title += "..."
        return title

    async def _apply_first_title(
        self,
        session_id: str,
        title: str,
        source: str
        ) -> None:
        """写入标题（内存+磁盘）并尽力推送前端；失败仅记日志。

        update_title 磁盘失败不掩盖内存成功，继续推送（crash-only：
        不回滚已完成写入）；推送失败仅降级日志，下次连接 fetchSessions 补齐。
        """
        from system.application import Application
        application = Application.current()
        try:
            application.get_system(ISessionManager).update_title(session_id, title)
        except Exception:
            logger.warning(
                "First title persistence failed | session=%s", session_id, exc_info=True
            )
        try:
            await application.get_system(IFrontendSink).emit_system_message(
                session_id,
                json.dumps(
                    {"action": SESSION_TITLE_UPDATED_ACTION, "title": title},
                    ensure_ascii=False,
                ),
            )
        except Exception:
            logger.warning(
                "First title push failed | session=%s", session_id, exc_info=True
            )
        logger.info("First title applied | session=%s source=%s", session_id, source)

    async def _first_title_task(
        self,
        session_id: str,
        text: str
        ) -> None:
        """后台任务体：LLM 生成 → 写入标题 → 推送前端；业务失败回退截取。"""
        try:
            title = await self._generate_title_from_text(session_id, text)
        except asyncio.CancelledError:
            raise
        except ApplicationStoppingError:
            # 停机竞态：不传播、不回退、不写标题，与 session_message_queue
            # 停机期过滤先例同向（避免把正常停止翻转为失败关闭）。
            logger.info(
                "First title generation skipped during shutdown | session=%s", session_id
            )
        except SessionMetadataError:
            await self._apply_first_title(
                session_id, self._fallback_title(text), "llm-failed"
            )
        except BaseException as error:
            # 未知异常不得泄漏进 record_failure（后台任务异常=应用失败关闭）；
            # 先放行生命周期失败（LifecycleFailure / 含取消的异常组）。
            self._preserve_lifecycle_error(error)
            logger.warning(
                "First title generation failed unexpectedly | session=%s",
                session_id,
                exc_info=error,
            )
            await self._apply_first_title(
                session_id, self._fallback_title(text), "llm-error"
            )
        else:
            await self._apply_first_title(session_id, title, "llm-ok")
        finally:
            self._first_title_pending.discard(session_id)

    def maybe_generate_first_title(
        self,
        session_id: str,
        text: str
        ) -> None:
        """首条用户消息触发的一次性异步标题生成入口（fire-and-forget）。

        前置判定（会话存在、标题为空、文本非空）由调用方完成；本方法只做
        防重与派发。检查与登记在同一同步代码段内完成，中间不得出现 await。
        """
        if session_id in self._first_title_pending:
            return
        self._first_title_pending.add(session_id)
        try:
            self.task_owner.create(
                self._first_title_task(session_id, text),
                name=f"metadata-first-title-{session_id}",
            )
        except LifecycleFailure:
            # 停机窗口内 Owner closing：静默放弃，不沿准备任务触发失败关闭。
            self._first_title_pending.discard(session_id)
            logger.info(
                "First title generation skipped at shutdown | session=%s", session_id
            )
