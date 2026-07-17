"""LoopSessionManager — 主 Agent 的 session 生命周期管理。

封装 session 初始化、token 超限检查、旋转/归档、摘要/标签生成、
memory provider 迁移和 cron 任务迁移，与 gateway.SessionManager 协作。

注意：为避免与 ``gateway.session_manager.SessionManager`` 混淆，
类名使用 ``LoopSessionManager``，在 ``ParentAgentLoop`` 中以
``self._lifecycle`` 持有。
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, TYPE_CHECKING

from entity.messages import History, CharacterConversationMessage, BaseMessage
from entity.puretype import Role
from entity.constant import USER_CHARACTER_NAME, INHERIT_LAST_ROUNDS
from system.templates import read_template
from system.session_store import SessionStore
from entry.agent_support.history_summary import extract_last_rounds
from abstract.llm.formats import to_openai_message

if TYPE_CHECKING:
    from abstract.llm.client import BaseLLMClient
    from entry.parent_agent_loop import ParentAgentLoop

logger = logging.getLogger(__name__)


class LoopSessionManager:
    """管理单个 ParentAgentLoop 实例的 session 生命周期。

    TODO: 当前仅被 ParentAgentLoop 独享；MultiAgentLoop 明确声明不支持 session 旋转
    和合并（存在 TODO 标记），因此未使用此模块。若未来多 Agent 模式需支持 session
    旋转/归档，需将此模块的类型标注收窄到共享接口。

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
        """判断当前 token 数加上 safety_margin 是否超过配置上限。"""
        current_tokens: int = self._loop.last_prompt_tokens
        if current_tokens == 0:
            return False
        ctx = self._loop.app.runtime_context
        return (
            current_tokens + ctx.llm_max_output_tokens + safety_margin
        ) > ctx.llm_max_context_tokens

    # ------------------------------------------------------------------
    # Session 旋转
    # ------------------------------------------------------------------

    async def rotate_session_for_continuation(
        self,
        session_id: str,
        pending_user_message: str | None = None,
    ) -> str | None:
        """终结旧会话并创建继承会话，返回新 session_id 或 None。"""
        from entity.puretype import Role
        from entity.constant import USER_CHARACTER_NAME

        old_sid: str = session_id
        if pending_user_message is not None:
            self._loop.remove_last_user_message(old_sid)

        new_sid: str | None = await self._terminate_session(old_sid, rotate=True)
        if not new_sid:
            if pending_user_message is not None:
                self._loop.append_history(old_sid, Role.USER, pending_user_message)
            return None

        transfer_result = self._transfer_session_runtime_resources(old_sid, new_sid)
        if transfer_result.get("tool_resources_error"):
            logger.warning(
                "Session runtime resource transfer had issues | old=%s new=%s result=%s",
                old_sid, new_sid, transfer_result,
            )
        if pending_user_message is not None:
            self._loop.append_history(new_sid, Role.USER, pending_user_message)

        logger.info(
            "Session context exceeded limit and continued | old=%s new=%s",
            old_sid, new_sid,
        )
        return new_sid

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
        result["tool_resources_error"] = tool_resources_error

        return result

    def pop_session_rotated(self) -> str | None:
        """取出并移除旋转通知（old_sid → new_sid）。"""
        return self._session_rotated_notify.pop(
            self._loop.session_id, None,
        )

    # ------------------------------------------------------------------
    # Session 归档 / 终结
    # ------------------------------------------------------------------

    async def terminate_session(self) -> dict:
        """终结当前会话：归档 + 摘要，不旋转。"""
        await self._terminate_session(self._loop.session_id, rotate=False)
        return {"terminated": True, "session_id": self._loop.session_id}

    async def _terminate_session(
        self, session_id: str, rotate: bool = False,
    ) -> str | None:
        """终结会话：归档 + 压缩（生成摘要），可选创建继承会话。"""
        sm = self._loop.session_manager
        if sm is None:
            return None

        old_sid: str = session_id

        # 读取已持久化摘要
        summary: str = ""
        if self._history_store_dir:
            summary_path = self._history_store_dir / old_sid / "summary.txt"
            if summary_path.exists():
                try:
                    summary = summary_path.read_text(encoding="utf-8")
                except Exception:
                    logger.exception(
                        "Failed to read persisted summary for session=%s", old_sid,
                    )

        # 若无持久化摘要，则 LLM 压缩生成
        if not summary:
            summary = await self._summarize_session_history(old_sid)

        # 写入摘要
        if self._loop.session_store is not None:
            try:
                self._loop.session_store.write_summary(old_sid, summary)
            except Exception as exc:
                logger.exception(
                    "Failed to write summary for session %s: %s", old_sid, exc,
                )

        # 自动分类标签
        tags: list[str] = await self._generate_session_tags(old_sid)
        if tags and sm is not None:
            sm.set_session_tags(old_sid, tags)
            logger.info("Auto-classified tags for session %s: %s", old_sid, tags)
        sm.archive(old_sid, continuation_sid=None)

        if rotate:
            context: str = self._build_inherited_context(old_sid, summary)

            # 读取当前 session 的 LoopMeta 供旋转继承
            loop_meta = None
            if sm is not None:
                info = sm.get(old_sid)
                if info:
                    from entity.puretype import LoopMeta as _LoopMeta
                    loop_meta = _LoopMeta(
                        loopType=info.loop_type, agents=info.agents,
                    )

            # 提取旧会话尾部轮次文本，追加到 context
            tail_rounds_text = ""
            if self._loop.session_store is not None:
                try:
                    old_history = self._loop.session_store.read_history(old_sid)
                    if old_history is not None and old_history.count > 0:
                        from entry.agent_support.history_summary import messages_to_text
                        tail_msgs = extract_last_rounds(
                            old_history,
                            rounds=INHERIT_LAST_ROUNDS,
                            include_tool_messages=False,
                        )
                        if tail_msgs:
                            tail_text = messages_to_text(tail_msgs)
                            tail_rounds_text = (
                                "\n\n## Recent conversation rounds\n" + tail_text
                            )
                except Exception as exc:
                    logger.exception(
                        "Failed to extract tail rounds for session old=%s: %s",
                        old_sid, exc,
                    )
            if tail_rounds_text:
                context += tail_rounds_text

            new_sid: str = sm.create_with_context(
                context, parent_sid=old_sid, role=Role.USER,
                loop_meta=loop_meta,
            )
            sm.archive(old_sid, continuation_sid=new_sid)

            # 新 session 以 summary 作为 user 消息开始
            self._loop.load_history(History())
            self._loop.last_prompt_tokens = 0
            summary_msg = CharacterConversationMessage(
                role=Role.USER,
                character_name=USER_CHARACTER_NAME,
                content=context,
                visible_characters=[
                    self._loop.current_character_agent,
                ],
            )
            self._loop.history.add_message(summary_msg)
            self._loop.save_history(new_sid)

            # 迁移 cron 定时任务
            try:
                from component.extools import cron_tools
                cron_tools.migrate_session_cron_jobs(old_sid, new_sid)
            except Exception:
                logger.exception(
                    "Failed to migrate cron jobs from %s to %s", old_sid, new_sid,
                )

            self._session_rotated_notify[old_sid] = new_sid
            logger.info(
                "Session terminated and rotated | old=%s new=%s summary=%d chars",
                old_sid, new_sid, len(summary),
            )
            return new_sid

        logger.info(
            "Session terminated | old=%s summary=%d chars", old_sid, len(summary),
        )
        return None

    # ------------------------------------------------------------------
    # 摘要 / 标签生成
    # ------------------------------------------------------------------

    async def _summarize_session_history(self, session_id: str) -> str:
        """用 LLM 对完整历史做压缩生成摘要。"""
        if self._loop.session_store is None:
            return ""
        history = self._loop.session_store.read_history(session_id)
        if history is None or history.count == 0:
            return ""
        from entry.agent_support.history_summary import summarize_history
        return await summarize_history(history, self._loop.llm)

    async def _generate_session_tags(self, session_id: str) -> list[str]:
        """委托 loop.regenerate_session_tags() 生成会话分类标签。"""
        return await self._loop.regenerate_session_tags()

    def _build_inherited_context(self, old_sid: str, summary: str) -> str:
        """为继承会话构建初始上下文消息。"""
        return (
            read_template("session_inherit.txt")
            .replace("{{old_sid}}", old_sid)
            .replace("{{summary}}", summary)
        )