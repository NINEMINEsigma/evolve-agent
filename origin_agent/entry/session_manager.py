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
from entity.constant import USER_CHARACTER_NAME
from system.templates import read_template
from system.session_store import SessionStore

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

        if rotate:
            # 读取当前 session 的 LoopMeta 供旋转继承
            loop_meta = None
            info = sm.get(old_sid)
            if info:
                from entity.puretype import LoopMeta as _LoopMeta
                loop_meta = _LoopMeta(
                    loopType=info.loop_type, agents=info.agents,
                )

            new_sid = await terminate_and_rotate_session(
                session_id=old_sid,
                session_store=self._loop.session_store,
                session_manager=sm,
                llm=self._loop.llm,
                loop_meta=loop_meta,
                current_character_agent=self._loop.current_character_agent,
                history_store_dir=self._history_store_dir,
            )

            if new_sid:
                # 自动分类标签（在公共函数归档前补充）
                tags: list[str] = await self._generate_session_tags(old_sid)
                if tags:
                    sm.set_session_tags(old_sid, tags)
                    logger.info("Auto-classified tags for session %s: %s", old_sid, tags)

                # ParentAgentLoop 特有的后置操作：重置内存历史
                self._loop.load_history(History())
                self._loop.last_prompt_tokens = 0
                summary_msg = CharacterConversationMessage(
                    role=Role.USER,
                    character_name=USER_CHARACTER_NAME,
                    content=self._build_inherited_context(old_sid, self._loop.session_store.read_summary(old_sid) if self._loop.session_store else ""),
                    visible_characters=[
                        self._loop.current_character_agent,
                    ],
                )
                self._loop.history.add_message(summary_msg)
                self._loop.save_history(new_sid)

                self._session_rotated_notify[old_sid] = new_sid

            return new_sid

        # rotate=False：仅归档 + 摘要，不创建继承会话
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
        tags = await self._generate_session_tags(old_sid)
        if tags and sm is not None:
            sm.set_session_tags(old_sid, tags)
            logger.info("Auto-classified tags for session %s: %s", old_sid, tags)
        sm.archive(old_sid, continuation_sid=None)

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


# ---------------------------------------------------------------------------
# 公共旋转函数 — 供 ParentAgentLoop 和 MultiAgentLoop 共用
# ---------------------------------------------------------------------------


async def terminate_and_rotate_session(
    *,
    session_id: str,
    session_store: SessionStore | None,
    session_manager: Any,
    llm: BaseLLMClient | None,
    loop_meta: Any | None = None,
    current_character_agent: str = "",
    history_store_dir: Path | None = None,
) -> str | None:
    """终结会话：生成摘要、归档、创建继承会话（可选传入 LoopMeta）。

    Args:
        session_id: 要终结的会话 ID。
        session_store: 会话持久化存储。
        session_manager: gateway 层 SessionManager（create_with_context / archive / set_session_tags）。
        llm: 用于生成摘要的 LLM 客户端。
        loop_meta: 旋转后新会话的 LoopMeta（普通模式为 None，多 Agent 模式为 Loop.multi）。
        current_character_agent: 当前角色名，用于构造继承会话的初始消息。
        history_store_dir: 历史存储目录，用于读取已持久化摘要。

    Returns:
        新 session_id 或 None（失败时）。
    """
    from entity.puretype import Role, LoopMeta as _LoopMeta
    from entity.constant import USER_CHARACTER_NAME, INHERIT_LAST_ROUNDS
    from entity.messages import History, CharacterConversationMessage
    from system.templates import read_template
    from entry.agent_support.history_summary import summarize_history, extract_last_rounds, messages_to_text

    old_sid: str = session_id

    # 1. 读取已持久化摘要
    summary: str = ""
    if history_store_dir:
        summary_path = history_store_dir / old_sid / "summary.txt"
        if summary_path.exists():
            try:
                summary = summary_path.read_text(encoding="utf-8")
            except Exception:
                logger.exception(
                    "Failed to read persisted summary for session=%s", old_sid,
                )

    # 2. 若无持久化摘要，则 LLM 压缩生成
    if not summary and session_store is not None and llm is not None:
        history = session_store.read_history(old_sid)
        if history is not None and history.count > 0:
            summary = await summarize_history(history, llm)

    # 3. 写入摘要
    if session_store is not None:
        try:
            session_store.write_summary(old_sid, summary)
        except Exception as exc:
            logger.exception(
                "Failed to write summary for session %s: %s", old_sid, exc,
            )

    # 4. 归档
    session_manager.archive(old_sid, continuation_sid=None)

    if not summary:
        logger.info(
            "Session terminated (no rotation, no summary) | old=%s", old_sid,
        )
        return None

    # 5. 构建继承上下文
    context: str = (
        read_template("session_inherit.txt")
        .replace("{{old_sid}}", old_sid)
        .replace("{{summary}}", summary)
    )

    # 6. 提取旧会话尾部轮次文本
    tail_rounds_text = ""
    if session_store is not None:
        try:
            old_history = session_store.read_history(old_sid)
            if old_history is not None and old_history.count > 0:
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

    # 7. 创建继承会话（传入 LoopMeta 保持模式继承）
    new_sid: str = session_manager.create_with_context(
        context, parent_sid=old_sid, role=Role.USER,
        loop_meta=loop_meta,
    )
    session_manager.archive(old_sid, continuation_sid=new_sid)

    # 8. 写入仅含 summary 消息的历史到新会话
    summary_history = History()
    summary_history.add_message(CharacterConversationMessage(
        role=Role.USER,
        character_name=USER_CHARACTER_NAME,
        content=context,
        visible_characters=[current_character_agent] if current_character_agent else None,
    ))
    if session_store is not None:
        session_store.write_history(new_sid, summary_history)

    # 9. 迁移 cron 定时任务
    try:
        from component.extools import cron_tools
        cron_tools.migrate_session_cron_jobs(old_sid, new_sid)
    except Exception:
        logger.exception(
            "Failed to migrate cron jobs from %s to %s", old_sid, new_sid,
        )

    logger.info(
        "Session terminated and rotated | old=%s new=%s summary=%d chars",
        old_sid, new_sid, len(summary),
    )
    return new_sid