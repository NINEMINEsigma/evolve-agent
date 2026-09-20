"""LoopSessionManager — 主 Agent 的 session 生命周期管理。

封装 session 初始化、token 超限检查、旋转/归档、摘要/标签生成、
memory provider 迁移和 cron 任务迁移，与 gateway.SessionManager 协作。

注意：为避免与 ``gateway.session_manager.SessionManager`` 混淆，
类名使用 ``LoopSessionManager``，在 ``ParentAgentLoop`` 中以
``self._lifecycle`` 持有。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, TYPE_CHECKING

from entity.messages import History, CharacterConversationMessage
from entity.puretype import Role, SessionTerminationResult
from system.templates import read_template
from system.session_store import SessionStore

if TYPE_CHECKING:
    from entry.parent_agent_loop import ParentAgentLoop
    from gateway.session_manager import SessionManager
    from entity.puretype import LoopMeta
    from system.session_metadata import SessionMetadataService

logger = logging.getLogger(__name__)


class LoopSessionManager:
    """管理单个 ParentAgentLoop 实例的 session 生命周期。

    当前实例只由 ParentAgentLoop 持有；MultiAgentLoop 不持有本类，但复用模块级
    ``terminate_and_rotate_session`` 完成相同的摘要保障与旋转提交顺序。

    session 持久化的通用方法（save_history 等）
    已下沉到 BaseAgentLoop，本类只负责 session 旋转/归档/摘要/标签等
    高层级生命周期逻辑。
    """

    def __init__(
        self,
        loop: ParentAgentLoop,
        history_store_dir: Path | None = None,
    ) -> None:
        self._loop = loop
        self._history_store_dir: Path | None = history_store_dir

        # session 旋转通知（由 gateway 层读取并转发前端）
        self._session_rotated_notify: dict[str, str] = {}

    # ------------------------------------------------------------------
    # 初始化
    # ------------------------------------------------------------------

    def initialize(self) -> None:
        """从磁盘加载已有历史并设置到 loop history。

        若历史格式不兼容则抛出 IncompatibleHistoryError。
        """
        if self._loop.session_store is not None:
            try:
                disk_history = self._loop.session_store.read_history(
                    self._loop.session_id,
                )
                if disk_history:
                    self._loop.load_history(disk_history)
            except Exception as exc:
                logger.warning(
                    "Session %s history incompatible or corrupt: %s",
                    self._loop.session_id, exc,
                )
                from entry.parent_agent_loop import IncompatibleHistoryError
                raise IncompatibleHistoryError(self._loop.session_id) from exc

    # ------------------------------------------------------------------
    # 上下文超限
    # ------------------------------------------------------------------

    def is_context_over_limit(self, safety_margin: int = 5000) -> bool:
        """判断当前 token 数加上 safety_margin 是否超过配置上限。

        优先使用活跃 LLM profile 的 token 限制（网页端切换时），
        未切换时回退到 RuntimeContext 启动配置。
        """
        current_tokens: int = self._loop.last_prompt_tokens
        if current_tokens == 0:
            return False
        max_context = self._loop.active_max_context_tokens
        max_output = self._loop.active_max_output_tokens
        return (
            current_tokens + max_output + safety_margin
        ) > max_context

    # ------------------------------------------------------------------
    # Session 旋转
    # ------------------------------------------------------------------

    def _transfer_session_runtime_resources(
        self, old_sid: str, new_sid: str,
    ) -> dict[str, Any]:
        """将旧会话的运行态资源迁移到继承会话。"""
        result: dict[str, Any] = {"old_sid": old_sid, "new_sid": new_sid}
        self._loop.last_prompt_tokens = 0
        self._session_rotated_notify[old_sid] = new_sid

        # 迁移工具副作用资源
        tool_resources_error: str | None = None
        if self._loop.session_store is not None:
            try:
                resources = self._loop.session_store.read_tool_resources(old_sid)
                self._loop.session_store.write_tool_resources(new_sid, resources)
            except Exception as exc:
                tool_resources_error = str(exc)
                logger.exception(
                    "Failed to transfer tool resources from %s to %s: %s",
                    old_sid, new_sid, exc,
                )
        # 迁移加载工具集状态
        if self._loop.session_store is not None:
            try:
                self._loop.session_store.copy_loaded_toolsets(old_sid, new_sid)
            except Exception as exc:
                logger.warning(
                    "Failed to transfer loaded_toolsets from %s to %s: %s",
                    old_sid, new_sid, exc,
                )
        result["tool_resources_error"] = tool_resources_error

        return result

    def pop_session_rotated(self) -> str | None:
        """取出并移除旋转通知（old_sid → new_sid）。"""
        if not self._session_rotated_notify:
            return None
        old_sid = next(iter(self._session_rotated_notify))
        return self._session_rotated_notify.pop(old_sid)

    # ------------------------------------------------------------------
    # Session 归档 / 终结
    # ------------------------------------------------------------------

    async def terminate_session(self) -> SessionTerminationResult:
        """终结当前会话；元数据失败只作为警告，不阻止归档。"""
        session_id = self._loop.session_id
        sm = self._loop.session_manager
        if sm is None:
            return SessionTerminationResult(
                terminated=False,
                session_id=session_id,
                error="session manager not available",
            )

        warnings: list[str] = []
        metadata_service = self._loop.app.session_metadata_service
        try:
            await metadata_service.ensure_summary(session_id)
        except Exception as exc:
            logger.warning(
                "Session summary unavailable during termination | session=%s error=%s",
                session_id,
                exc,
            )
            warnings.append(f"摘要生成失败：{exc}")

        try:
            tags = await metadata_service.generate_tags(
                session_id,
                sm.get_all_tags(),
            )
            sm.set_session_tags(session_id, tags)
        except Exception as exc:
            logger.warning(
                "Session tags unavailable during termination | session=%s error=%s",
                session_id,
                exc,
            )
            warnings.append(f"标签生成失败：{exc}")

        sm.archive(session_id, continuation_sid=None)
        try:
            await self._loop.app.shell_manager.stop_session(session_id)
        except Exception as exc:
            logger.exception(
                "Failed to stop Shell sessions during termination | session=%s",
                session_id,
            )
            warnings.append(f"Shell会话停止失败：{exc}")

        logger.info(
            "Session terminated | session=%s metadata_warnings=%d",
            session_id,
            len(warnings),
        )
        return SessionTerminationResult(
            terminated=True,
            session_id=session_id,
            metadata_warnings=warnings,
        )

    async def rotate_session_for_continuation(
        self,
        session_id: str,
        move_last_user_message: bool = False,
    ) -> str:
        """确保摘要后旋转会话；失败时完整恢复临时分离的用户消息。"""
        sm = self._loop.session_manager
        if sm is None:
            raise RuntimeError("session manager not available")

        moved_message: CharacterConversationMessage | None = None
        if move_last_user_message and self._loop.history.count > 0:
            last_message = self._loop.history.get_message(
                self._loop.history.count - 1
            )
            if (
                isinstance(last_message, CharacterConversationMessage)
                and last_message.role == Role.USER
            ):
                removed = self._loop.history.remove_last_message()
                if isinstance(removed, CharacterConversationMessage):
                    moved_message = removed
                    self._loop.save_history(session_id)

        info = sm.get(session_id)
        loop_meta = None
        if info is not None:
            from entity.puretype import LoopMeta as _LoopMeta

            loop_meta = _LoopMeta(
                loopType=info.loop_type,
                agents=info.agents,
            )

        try:
            new_sid = await terminate_and_rotate_session(
                session_id=session_id,
                session_store=self._loop.session_store,
                session_manager=sm,
                metadata_service=self._loop.app.session_metadata_service,
                loop_meta=loop_meta,
                current_character_agent=self._loop.current_character_agent,
            )
        except Exception:
            if moved_message is not None:
                self._loop.history.add_message(moved_message)
                self._loop.save_history(session_id)
            raise

        new_history = (
            self._loop.session_store.read_history(new_sid)
            if self._loop.session_store is not None
            else None
        ) or History()
        if moved_message is not None:
            new_history.add_message(moved_message)
        self._loop.load_history(new_history)
        self._loop.save_history(new_sid)

        transfer_result = self._transfer_session_runtime_resources(
            session_id,
            new_sid,
        )
        if transfer_result.get("tool_resources_error"):
            logger.warning(
                "Session runtime resource transfer had issues | old=%s new=%s result=%s",
                session_id,
                new_sid,
                transfer_result,
            )

        try:
            tags = await self._loop.app.session_metadata_service.generate_tags(
                session_id,
                sm.get_all_tags(),
            )
            sm.set_session_tags(session_id, tags)
        except Exception:
            logger.warning(
                "Failed to generate tags after successful rotation | session=%s",
                session_id,
                exc_info=True,
            )

        logger.info(
            "Session context exceeded limit and continued | old=%s new=%s",
            session_id,
            new_sid,
        )
        return new_sid

    def _build_inherited_context(self, old_sid: str, summary: str) -> str:
        """为继承会话构建初始上下文消息。"""
        return (
            read_template("session_inherit.txt")
            .replace("{{old_sid}}", old_sid)
            .replace("{{summary}}", summary)
        )


# ---------------------------------------------------------------------------
# 公共旋转函数 — 供 ParentAgentLoop 和 MultiAgentLoop 共用
# ---------------------------------------------------------------------------


async def terminate_and_rotate_session(
    *,
    session_id: str,
    session_store: SessionStore | None,
    session_manager: SessionManager,
    metadata_service: SessionMetadataService,
    loop_meta: LoopMeta | None = None,
    current_character_agent: str = "",
) -> str:
    """确保摘要并完整初始化延续会话后，才归档旧会话。"""
    from entity.constant import INHERIT_LAST_ROUNDS, USER_CHARACTER_NAME
    from entry.agent_support.history_summary import extract_last_rounds, messages_to_text
    from entity.messages import History, CharacterConversationMessage
    from system.session_metadata import MetadataGenerationError

    if session_store is None:
        raise MetadataGenerationError("session store not available")

    old_sid = session_id
    summary = await metadata_service.ensure_summary(old_sid)
    context = (
        read_template("session_inherit.txt")
        .replace("{{old_sid}}", old_sid)
        .replace("{{summary}}", summary)
    )

    try:
        old_history = session_store.read_history(old_sid)
        if old_history is not None and old_history.count > 0:
            tail_messages = extract_last_rounds(
                old_history,
                rounds=INHERIT_LAST_ROUNDS,
                include_tool_messages=False,
            )
            if tail_messages:
                context += (
                    "\n\n## Recent conversation rounds\n"
                    + messages_to_text(tail_messages)
                )
    except Exception:
        logger.exception(
            "Failed to extract tail rounds for session old=%s", old_sid
        )

    new_sid: str | None = None
    try:
        new_sid = session_manager.create_with_context(
            context,
            parent_sid=old_sid,
            role=Role.USER,
            loop_meta=loop_meta,
        )
        session_store.copy_active_profile_name(old_sid, new_sid)
        session_store.copy_loaded_toolsets(old_sid, new_sid)

        summary_history = History()
        summary_history.add_message(CharacterConversationMessage(
            role=Role.USER,
            character_name=USER_CHARACTER_NAME,
            content=context,
            visible_characters=(
                [current_character_agent] if current_character_agent else None
            ),
        ))
        session_store.write_history(new_sid, summary_history)
    except Exception as exc:
        if new_sid is not None:
            try:
                session_manager.remove(new_sid)
            except Exception:
                logger.exception(
                    "Failed to clean incomplete continuation | session=%s",
                    new_sid,
                )
        raise MetadataGenerationError(
            f"延续会话初始化失败：{exc}"
        ) from exc

    session_manager.archive(old_sid, continuation_sid=new_sid)

    try:
        from component.extools import cron_tools

        cron_tools.migrate_session_cron_jobs(old_sid, new_sid)
    except Exception:
        logger.exception(
            "Failed to migrate cron jobs from %s to %s", old_sid, new_sid
        )

    try:
        from component.extools.dynamic_endpoint_tools import migrate_session_endpoints

        migrate_session_endpoints(old_sid, new_sid)
    except Exception:
        logger.exception(
            "Failed to migrate dynamic endpoints from %s to %s", old_sid, new_sid
        )

    try:
        from system.application import Application

        migrated_shells = Application.current().shell_manager.migrate_session(
            old_sid,
            new_sid,
        )
        if migrated_shells:
            logger.info(
                "Migrated %d Shell session(s) | old=%s new=%s",
                migrated_shells,
                old_sid,
                new_sid,
            )
    except Exception:
        logger.exception(
            "Failed to migrate Shell sessions from %s to %s; "
            "they may remain owned by the archived session",
            old_sid,
            new_sid,
        )

    logger.info(
        "Session terminated and rotated | old=%s new=%s summary=%d chars",
        old_sid,
        new_sid,
        len(summary),
    )
    return new_sid