"""Agent Loop 抽象基类 + Inbox/InboxMessage 消息队列。

所有 Agent 循环（ParentAgentLoop、SubAgentLoop、GroupChatLoop）继承 ``BaseAgentLoop``。
``BaseAgentLoop`` 只提供所有循环共用的生命周期、收件箱机制和 sink 抽象；
``BasePrivateChatAgentLoop`` 继承它，补充 1-on-1 私聊循环所需的标准历史、
LLM 调用、工具执行、memory 和 hooks 能力。
"""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, TYPE_CHECKING

from pydantic import BaseModel

from entity.puretype import Role, ToolDangerLevel, SessionMessageEntry
from entity.messages import (
    History,
    BaseMessage,
    ToolResultMessage,
    CharacterConversationMessage,
    CharacterMessage,
    MessageBlock,
)
from entity.constant import (
    USER_CHARACTER_NAME, SYSTEM_CHARACTER_NAME,
    AUTO_TITLE_CONTENT_MAX, AUTO_TAGS_CONTENT_MAX,
    META_EXTRACTOR_CHARACTER,
)
from entry.agent_support.messages import (
    build_full_history_messages,
    collect_all_hooks_context,
    load_message_hooks,
)
from entry.agent_support.multimodal import tool_result_to_content, content_to_text
from system.pathutils import find_repo_root
from system.session_store import SessionStore

if TYPE_CHECKING:
    from abstract.llm.client import BaseLLMClient
    from system.context import RuntimeContext
    from system.application import Application
    from entry.agent_sink import AgentSink

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Inbox / InboxMessage — 带类型的消息队列
# ---------------------------------------------------------------------------

class InboxMessage(BaseModel):
    """收件箱消息基类。"""
    content: str = ""
    character_name: str = SYSTEM_CHARACTER_NAME

    def to_text(self) -> str:
        """转换为注入 LLM 历史的文本。子类按需重写。"""
        return self.content


class UserMessage(InboxMessage):
    """来自用户/父Agent的文本消息。"""
    character_name: str = USER_CHARACTER_NAME


# TODO: 目前似乎没有被使用到
class ApprovalDecisionMessage(InboxMessage):
    """父Agent对工具审批的决定。"""
    decision: dict[str, Any]

    def to_text(self) -> str:
        return json.dumps(self.decision, ensure_ascii=False)


class CronResultMessage(InboxMessage):
    """Cron 定时任务执行结果。"""
    task_id: str
    name: str
    exit_code: int
    stdout_preview: str

    def to_text(self) -> str:
        status = "completed" if self.exit_code == 0 else f"failed (exit={self.exit_code})"
        return f"[cron-result] {self.name} ({self.task_id}) — {status}\n{self.stdout_preview}"


class ContextLimitMessage(InboxMessage):
    """上下文超限通知。"""
    saved_path: str | None = None

    def to_text(self) -> str:
        return f"[system] Context limit reached. Session saved to: {self.saved_path or 'unknown'}"


class InterruptMessage(InboxMessage):
    """中断请求。"""

    def to_text(self) -> str:
        return "[system] Interrupt requested"


class Inbox:
    """线程安全的收件箱，支持等待新消息。

    BaseAgentLoop._flush_inbox() 在每个 LLM 回合前检查并合并待处理消息。
    """

    def __init__(self) -> None:
        self._queue: asyncio.Queue[InboxMessage] = asyncio.Queue()
        self._wake_event: asyncio.Event = asyncio.Event()
        self._wake_event.set()  # 初始允许首轮 LLM 调用

    def put(self, msg: InboxMessage) -> None:
        """投递消息并唤醒等待中的循环。"""
        self._queue.put_nowait(msg)
        self._wake_event.set()

    def get_pending(self) -> list[InboxMessage]:
        """非阻塞获取所有待处理消息。"""
        msgs: list[InboxMessage] = []
        while not self._queue.empty():
            try:
                msgs.append(self._queue.get_nowait())
            except asyncio.QueueEmpty:
                break
        return msgs

    async def wait(self) -> None:
        """阻塞直到有新消息。"""
        self._wake_event.clear()
        await self._wake_event.wait()

    def wake(self) -> None:
        """立即唤醒等待中的循环。"""
        self._wake_event.set()

    @property
    def has_pending(self) -> bool:
        return not self._queue.empty()


# ---------------------------------------------------------------------------
# ToolContext — 传递给工具 handler 的运行时上下文
# ---------------------------------------------------------------------------

class ToolContext(BaseModel):
    """工具执行时注入的运行时上下文。

    替代旧的全局导入模式（如 get_runtime_context()），
    工具 handler 通过此对象访问当前 loop 和会话上下文。
    """
    model_config = {"arbitrary_types_allowed": True}

    loop: Any  # BaseAgentLoop 实例
    session_id: str = ""

    @property
    def app(self) -> Application:
        from system.application import Application
        return Application.current()

    @property
    def runtime_context(self) -> RuntimeContext:
        return self.app.runtime_context

    @property
    def sink(self) -> AgentSink:
        return self.loop.get_sink()

    @property
    def is_interrupted(self) -> bool:
        return self.loop.is_interrupted()


# ---------------------------------------------------------------------------
# _serialize_message_entry — 公共消息序列化函数
# ---------------------------------------------------------------------------

def _serialize_message_entry(
    msg: BaseMessage,
    index: int,
    fallback_character: str = "assistant",
) -> SessionMessageEntry:
    """将单条 History 消息序列化为前端展示用的 SessionMessageEntry。

    统一 BaseAgentLoop / MultiAgentLoop 两处 get_session_messages 的序列化逻辑，
    修复 MultiAgentLoop 中 str(raw_content) 的 bug（应使用 content_to_text）。
    """
    raw_content = msg.content
    if isinstance(raw_content, list):
        content: str | list[dict[str, Any]] = [
            b.as_object() if isinstance(b, MessageBlock) else b
            for b in raw_content
        ]
    else:
        content = content_to_text(raw_content)

    # character_name: CharacterMessage 有角色名，否则回退到 fallback
    character_name = (
        msg.character_name
        if isinstance(msg, CharacterMessage)
        else fallback_character
    )

    # CharacterConversationMessage 专属字段
    visible_characters: list[str] | None = None
    response_characters: list[str] | None = None
    message_suffix: str | None = None
    dynamic_message_suffix: str | None = None
    reasoning_content: str | None = None
    tool_calls: list[dict[str, Any]] | None = None

    if isinstance(msg, CharacterConversationMessage):
        visible_characters = msg.visible_characters or None
        response_characters = msg.response_characters or None
        message_suffix = msg.message_suffix or None
        dynamic_message_suffix = msg.dynamic_message_suffix or None
        reasoning_content = msg.reasoning or None
        if msg.tool_calls:
            tool_calls = [
                {
                    "id": tc.id,
                    "type": tc.type,
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    },
                }
                for tc in msg.tool_calls
            ]

    requires_response = True if msg.role == Role.USER else None

    # ToolResultMessage._meta 提取
    tool_call_meta: dict[str, Any] | None = None
    if isinstance(msg, ToolResultMessage):
        content_str = content_to_text(raw_content)
        try:
            parsed = json.loads(content_str)
            if isinstance(parsed, dict) and "_meta" in parsed:
                tool_call_meta = parsed["_meta"]
        except (json.JSONDecodeError, TypeError):
            pass

    return SessionMessageEntry(
        role=msg.role.value,
        content=content,
        index=index,
        character_name=character_name,
        visible_characters=visible_characters,
        response_characters=response_characters,
        message_suffix=message_suffix,
        dynamic_message_suffix=dynamic_message_suffix,
        reasoning_content=reasoning_content,
        requires_response=requires_response,
        tool_calls=tool_calls,
        tool_call_meta=tool_call_meta,
    )


# ---------------------------------------------------------------------------
# BaseAgentLoop — 最基础 Agent 循环抽象基类
# ---------------------------------------------------------------------------

class BaseAgentLoop(ABC):
    """所有 Agent 循环的最基础抽象基类。

    子类必须实现：
    - _get_sink() → AgentSink

    可选覆盖：
    - schedule_inbox_processing() → None
    """

    def __init__(self, app: Application, session_id: str) -> None:
        self.session_id: str = session_id
        self.app: Application = app
        self._inbox: Inbox = Inbox()
        self._cancel_event: asyncio.Event = asyncio.Event()
        self._message_hooks_cache: list[dict] | None = None
        self._history: History = History()
        self._session_store: SessionStore | None = None
        self._token_usage: int = 0
        self._last_prompt_tokens: int = 0

    @property
    def history_store_dir(self) -> Path | None:
        """统一返回当前 loop 的 session 持久化根目录。"""
        return self._session_store.base_dir if self._session_store else None

    @property
    def inbox(self) -> Inbox:
        """公开的收件箱访问器，供 CronRouter 等外部组件投递消息。"""
        return self._inbox

    # -- 抽象方法 ---------------------------------------------------------

    @abstractmethod
    def get_sink(self) -> AgentSink:
        """返回当前 loop 的 AgentSink 实例。"""
        ...

    @property
    @abstractmethod
    def current_character_agent(self) -> str:
        """返回当前 loop 对应的 agent 角色名，用于 History 视图过滤。"""
        ...

    @abstractmethod
    def _get_session_info_llm_client(self) -> BaseLLMClient | None:
        """返回用于生成标题/标签/摘要等会话信息的 LLM 客户端，无可用时返回 None。"""
        ...

    @property
    @abstractmethod
    def user_character_name(self) -> str:
        """返回当前 loop 的"用户"角色名：向本 loop 发消息的发出者角色名。

        主会话里是真正的 end-user；子会话里是其"父 Agent"当前角色名。
        """
        ...

    @abstractmethod
    async def append_user_message(self, content: Any, *, display_content: Any | None = None, **kwargs: Any) -> int:
        """把用户消息加入本 loop 的历史/状态，返回其在持久化历史中的 index。

        Args:
            content: 实际存入历史供 LLM 消费的内容。
            display_content: 回显给前端显示的内容；默认与 content 相同。

        各具体 loop 自行决定存储方式；gateway 在收到 user_message 后调用此方法
        获取 index，再通过 sink 把带 character_name 的消息回显给前端。
        """
        ...

    @abstractmethod
    async def process_message(
        self,
        user_message: str,
        *,
        skip_append: bool = False,
        character_name: str = USER_CHARACTER_NAME,
        **kwargs
    ) -> str:
        """处理一条用户消息，返回助手的回复文本。

        由 gateway 在收到来自前端的 user_message 后调用。
        各具体 loop 自行实现消息处理逻辑（ParentAgentLoop 的 tool loop、
        MultiAgentLoop 的级联对话等）。
        """
        ...

    # -- 收件箱处理 -------------------------------------------------------

    def schedule_inbox_processing(self) -> None:
        """提示 loop 尽快处理 inbox 中的待处理消息。

        默认空实现；需要即时消费 inbox 的 loop（如 ParentAgentLoop）可覆盖。
        """
        pass

    def _flush_inbox(self) -> list[InboxMessage]:
        """取出并返回所有待处理的收件箱消息。

        子类可重写以处理特定类型的消息（如 ApprovalDecisionMessage）。
        """
        return self._inbox.get_pending()

    # -- 取消控制 ---------------------------------------------------------

    def interrupt(self) -> None:
        """请求停止当前循环。"""
        self._cancel_event.set()

    @property
    def cancel_event(self) -> asyncio.Event:
        """只读返回取消事件，供外部流式消费者检查中断状态。"""
        return self._cancel_event

    def is_interrupted(self) -> bool:
        """返回 True 表示存在活跃的中断请求。"""
        return self._cancel_event.is_set()

    async def _check_cancel(self) -> bool:
        """检查取消事件，已中断则返回 True。"""
        return self._cancel_event.is_set()

    # -- token 追踪（所有 loop 共享，可被子类覆盖）-------------------------

    def get_token_usage(self) -> int:
        if self._token_usage:
            return self._token_usage
        if self._session_store is not None:
            try:
                disk_usage = self._session_store.read_token_usage(self.session_id)
            except Exception:
                logger.exception("Failed to load token usage for session=%s", self.session_id)
                disk_usage = 0
            if disk_usage:
                self._token_usage = disk_usage
            return disk_usage
        return 0

    def get_context_tokens(self) -> int:
        return self._last_prompt_tokens

    async def _push_usage_update(self, session_id: str) -> None:
        """推送 token 消耗到前端。"""
        try:
            await self.get_sink().emit_usage_update(
                session_id, self._token_usage, self._last_prompt_tokens,
            )
        except Exception:
            logger.warning("Failed to push usage update for session=%s", session_id, exc_info=True)

    def _persist_token_usage(self, session_id: str) -> None:
        if self._session_store is None:
            return
        try:
            self._session_store.write_token_usage(session_id, self._token_usage)
        except Exception as exc:
            logger.exception("Failed to persist token usage for session %s: %s", session_id, exc)

    # -- 持久化（所有 loop 共享）-------------------------------------------

    @property
    def history(self) -> History:
        """返回当前 loop 的 History 实例（只读访问）。"""
        return self._history

    def set_session_id(self, session_id: str) -> None:
        """设置当前 loop 的 session ID（供 gateway 层旋转/替换 loop 时使用）。"""
        self.session_id = session_id

    # TODO: 以下三个函数完全没有差异
    def persist_history(self, session_id: str) -> None:
        """将当前 History 持久化到磁盘。"""
        self._persist_message(session_id)

    def _persist_message(self, session_id: str) -> None:
        if self._session_store is None:
            return
        try:
            self._session_store.write_history(session_id, self._history)
        except Exception as exc:
            logger.exception("Failed to persist history for session %s: %s", session_id, exc)

    def _overwrite_history_file(self, session_id: str) -> None:
        if self._session_store is None:
            return
        try:
            self._session_store.write_history(session_id, self._history)
        except Exception as exc:
            logger.exception("Failed to overwrite history file for session %s: %s", session_id, exc)

    def _remove_last_user_message(self, session_id: str) -> None:
        """移除 History 中最后一条 user 消息并持久化。"""
        if self._history.count > 0:
            last_msg = self._history.get_message(self._history.count - 1)
            if last_msg.role == Role.USER:
                self._history.remove_last_message()
        self._overwrite_history_file(session_id)

    def clear_session(self) -> None:
        """清理当前 session 的持久化数据。"""
        if self._session_store is None:
            return
        session_path = self._session_store.session_dir(self.session_id)
        if session_path.exists():
            shutil.rmtree(str(session_path), ignore_errors=True)
            logger.info("Cleared persisted data for session %s", self.session_id)

    def get_session_messages(self) -> list[SessionMessageEntry]:
        """返回前端展示所需的消息列表，包含多 agent 元数据。"""
        fallback = self.current_character_agent
        return [
            _serialize_message_entry(msg, index, fallback_character=fallback)
            for index, msg in enumerate(self._history.iter_messages())
        ]

    # TODO: 重编辑缺少多模态支持
    def edit_session_message(self, index: int, content: str | None = None,
                             visible_characters: list[str] | None = None) -> dict:
        if not isinstance(index, int) or index < 0:
            return {"updated": False, "error": "invalid message index"}
        if index >= self._history.count:
            return {"updated": False, "error": "message index out of range"}
        msg = self._history.get_message(index)
        if not isinstance(msg, CharacterConversationMessage):
            return {"updated": False, "error": "message type not editable"}
        updates: dict = {}
        if content is not None:
            updates["content"] = content
        if visible_characters is not None:
            updates["visible_characters"] = visible_characters
        updated_msg = msg.model_copy(update=updates)
        self._history.set_message(index, updated_msg)
        self._overwrite_history_file(self.session_id)
        result: dict = {
            "updated": True,
            "session_id": self.session_id,
            "index": index,
            "role": msg.role.value,
            "content": content_to_text(updated_msg.content),
        }
        if visible_characters is not None:
            result["visible_characters"] = visible_characters
        return result

    def delete_session_messages(self, count: int = 1) -> dict:
        """删除最后 count 个逻辑轮次的消息（从倒数第 count 条 user 起，覆盖其后所有 tool/assistant）。"""
        if count < 1:
            return {"deleted": False, "error": "count must be >= 1"}
        remove_from = self._history.find_last_user_message_index(count=count)
        if remove_from is None:
            return {"deleted": False, "error": "no user messages to delete"}
        self._history.truncate_to(remove_from)
        self._overwrite_history_file(self.session_id)
        return {"deleted": True, "session_id": self.session_id, "remaining_count": self._history.count}

    def regenerate_response(self) -> dict:
        """截断到最后一条 user 消息，返回其内容供重新生成。"""
        last_user_idx = self._history.find_last_user_message_index(count=1)
        if last_user_idx is None:
            return {"regenerate": False, "error": "no user message found"}
        last_user_msg = self._history.get_message(last_user_idx)
        last_user_content = content_to_text(last_user_msg.content)
        self._history.truncate_to(last_user_idx + 1)
        self._overwrite_history_file(self.session_id)
        result: dict = {
            "regenerate": True,
            "session_id": self.session_id,
            "last_user_content": last_user_content,
            "remaining_count": self._history.count,
        }
        if isinstance(last_user_msg, CharacterConversationMessage):
            result["visible_characters"] = last_user_msg.visible_characters
            result["response_characters"] = last_user_msg.response_characters
        return result

    def get_tool_resources(self) -> dict:
        """返回 session 的可恢复工具副作用资源快照。"""
        if self._session_store is None:
            return {"task_progress": {}, "clipboard_display": {}}
        return self._session_store.read_tool_resources(self.session_id)

    # -- IMainSessionLoop 默认实现 ----------------------------------------

    def pop_session_rotated(self) -> str | None:
        """取出并移除 session 旋转通知。默认返回 None。"""
        return None

    def is_processing(self) -> bool:
        """返回当前是否正在处理消息。默认返回 False。"""
        return False

    async def terminate_session(self) -> dict:
        """终结当前会话。默认返回简单确认。子类可覆盖。"""
        logger.info("Terminating session (base): %s", self.session_id)
        return {"terminated": True, "session_id": self.session_id}

    async def merge_sessions(self, sources: list[str]) -> dict:
        """合并多个源会话到一个新会话。默认不支持。"""
        logger.warning("Merge sessions not supported in this loop | session=%s sources=%s",
                       self.session_id, sources)
        return {"error": "merge not supported in this loop", "merged": False}

    # -- 标题 / 标签 / 摘要生成（全量消息，不做可见性过滤）------------------

    async def auto_generate_title(self) -> str:
        """根据会话历史自动生成标题。"""
        from abstract.llm.formats import to_summary_dict
        from system.templates import read_template

        messages = [m for m in self._history.iter_messages() if isinstance(m, CharacterConversationMessage)]
        if not messages:
            return ""
        llm = self._get_session_info_llm_client()
        if llm is None:
            return ""
        system_prompt = read_template("auto_title.txt")
        messages_json = [
            d for m in messages
            if (d := to_summary_dict(m)) is not None
        ]
        user_prompt = read_template("auto_title_input.txt").replace(
            "{{context}}",
            json.dumps(messages_json, ensure_ascii=False)[-AUTO_TITLE_CONTENT_MAX:],
        )
        try:
            resp = await llm.chat([
                BaseMessage(role=Role.SYSTEM, content=system_prompt),
                BaseMessage(role=Role.USER, content=user_prompt),
            ], character=META_EXTRACTOR_CHARACTER)
            return (resp.content or "").strip().strip("\"'")[:50]
        except Exception as exc:
            logger.exception("Failed to auto-generate title: %s", exc)
            return ""

    async def regenerate_session_tags(self) -> list[str]:
        """根据会话历史重新生成标签列表。"""
        from abstract.llm.formats import to_summary_dict
        from system.templates import read_template

        messages = [m for m in self._history.iter_messages() if isinstance(m, CharacterConversationMessage)]
        if not messages:
            logger.warning("No messages to regenerate session tags")
            return []
        llm = self._get_session_info_llm_client()
        if llm is None:
            logger.warning("No LLM client to regenerate session tags")
            return []
        try:
            system_prompt = read_template("session_tags.txt")
            # 获取已有标签池供 LLM 参考，优先复用已有标签
            existing_tags_hint = ""
            try:
                from system.application import Application
                sm = Application.current().session_manager
                if sm is not None:
                    all_tags = sm.get_all_tags()
                    if all_tags:
                        existing_tags_hint = (
                            "\n\nExisting tags in the system (prefer reusing these when applicable): "
                            + ", ".join(all_tags)
                        )
            except Exception:
                pass
            system_prompt = system_prompt.replace("{{existing_tags}}", existing_tags_hint)
            messages_json = [
                d for m in messages
                if (d := to_summary_dict(m)) is not None
            ]
            user_prompt = read_template("session_tags_input.txt").replace(
                "{{old_text}}",
                json.dumps(messages_json, ensure_ascii=False)[-AUTO_TAGS_CONTENT_MAX:],
            )
            resp = await llm.chat([
                BaseMessage(role=Role.SYSTEM, content=system_prompt),
                BaseMessage(role=Role.USER, content=user_prompt),
            ], character=META_EXTRACTOR_CHARACTER, response_format={"type": "json_object"})
            logger.info("Session tags response: %s", str(resp))
            result = json.loads(resp.content)
            if isinstance(result, list) == False:
                raise ValueError("session tags response is not a list")
            return result
        except Exception as exc:
            logger.exception("Failed to regenerate session tags: %s", exc)
        return []

    async def regenerate_summary_for_session(self, session_id: str) -> str:
        """重新生成指定会话的摘要（可为任意 session_id，不要求当前活跃）。"""
        if self._session_store is None:
            return ""
        history = self._session_store.read_history(session_id)
        if history is None or history.count == 0:
            return ""
        llm = self._get_session_info_llm_client()
        if llm is None:
            return ""
        from entry.agent_support.history_summary import summarize_history
        summary = await summarize_history(history, llm)
        if summary:
            self._session_store.write_summary(session_id, summary)
        return summary

    # -- Hook 支持（所有 loop 共享）----------------------------------------

    def _load_message_hooks(self) -> list[dict]:
        """加载 custom_hooks 目录中的消息扩展 hook，结果按 loop 实例缓存。"""
        if self._message_hooks_cache is not None:
            return self._message_hooks_cache
        hooks = load_message_hooks(find_repo_root(), logger)
        self._message_hooks_cache = hooks
        return hooks

    def _get_workspace(self) -> str:
        """返回当前 loop 使用的 workspace 路径。"""
        return (
            str(self.app.runtime_context.workspace)
            if self.app.runtime_context is not None
            else str(find_repo_root())
        )

    def _collect_hooks_context(
        self,
        session_id: str | None = None,
    ) -> tuple[str, str]:
        """收集 custom_hooks 的实时上下文。

        返回 (hooks_context, fixator_context)。hooks_context 只应作非持久化注入；
        fixator_context 应持久化为用户消息的 message_suffix。
        通过 collect_all_hooks_context 只遍历一次 hooks，避免重复调用 tag_fn。
        """
        sid = session_id or self.session_id
        hooks = self._load_message_hooks()
        workspace = self._get_workspace()
        return collect_all_hooks_context(
            hooks=hooks,
            session_id=sid,
            workspace=workspace,
            runtime_ctx=self.app.runtime_context,
        )

    def get_hooks_context(self, session_id: str) -> str:
        """返回 custom_hooks 的实时上下文（非持久化注入）。

        是 ``get_hooks_context`` 的便捷封装，只返回 hooks_context 部分。
        """
        hooks_context, _ = self._collect_hooks_context(session_id=session_id)
        return hooks_context

    def _set_dynamic_suffix(
        self,
        history: History,
        hooks_context: str,
        memory_ctx: str = "",
    ) -> None:
        """把非持久化的 hooks_context / memory_ctx 设置到 History 最后一条 user 消息。

        由 CharacterConversationMessage.as_content 在 is_last_user_message=True 时自动附加。
        """
        if history.last_user_message is None:
            return
        parts: list[str] = []
        if memory_ctx:
            parts.append(f"<|im_memory_context_start|>\n{memory_ctx}\n<|im_memory_context_end|>")
        if hooks_context:
            parts.append(hooks_context)
        history.last_user_message.dynamic_message_suffix = "\n".join(parts) if parts else None


# ---------------------------------------------------------------------------
# IMainSessionLoop — 主会话 loop 接口
# ---------------------------------------------------------------------------

class IMainSessionLoop(ABC):
    """主会话 loop 接口（C#-style interface）。

    只声明主会话（ParentAgentLoop / MultiAgentLoop）特有的能力，
    不继承 BaseAgentLoop，以避免与 BasePrivateChatAgentLoop 形成菱形继承。
    子 Agent 的 loop 不应继承此类。
    """
    @property
    def loop(self) -> BaseAgentLoop:
        """返回当前 loop 的实例。"""
        if isinstance(self, BaseAgentLoop):
            return self
        raise ValueError("current instance is not a BaseAgentLoop")

    @property
    @abstractmethod
    def current_character_agent(self) -> str:
        """返回当前 loop 对应的 agent 角色名，用于 History 视图过滤。"""

    @abstractmethod
    def pop_session_rotated(self) -> str | None:
        """取出并移除 session 旋转通知（old_sid → new_sid）。"""

    @abstractmethod
    def get_token_usage(self) -> int:
        """返回当前会话累计 token 消耗。"""

    @abstractmethod
    def get_context_tokens(self) -> int:
        """返回当前上下文 token 数。"""

    @abstractmethod
    async def auto_generate_title(self) -> str:
        """根据会话历史自动生成标题。"""

    @abstractmethod
    async def regenerate_session_tags(self) -> list[str]:
        """根据会话历史重新生成标签列表。"""

    @abstractmethod
    async def regenerate_summary_for_session(self, session_id: str) -> str:
        """重新生成指定会话的摘要（可为任意 session_id，不要求当前活跃）。"""


# ---------------------------------------------------------------------------
# BasePrivateChatAgentLoop — 1-on-1 私聊 Agent 循环基类
# ---------------------------------------------------------------------------

class BasePrivateChatAgentLoop(BaseAgentLoop):
    """1-on-1 私聊 Agent 循环的抽象基类。

    继承 ``BaseAgentLoop``，补充标准 OpenAI 格式历史、LLM 调用、工具执行、
    memory 和 custom_hooks 能力。

    子类必须实现以下工厂方法：
    - _get_context() → Any
    - _get_tool_definitions() → list[dict]
    - _on_context_over_limit() → None
    - _build_system_prompt() → list[str]
    """

    def __init__(self, app: Application, session_id: str) -> None:
        super().__init__(app, session_id)

    # -- 抽象方法 ---------------------------------------------------------

    @abstractmethod
    def _get_context(self) -> Any:
        """返回当前 loop 的 RuntimeContext 或 SubRuntimeContext。"""
        ...

    @abstractmethod
    def _get_tool_definitions(self) -> list[dict]:
        """返回当前 loop 可用的工具 schema 列表。"""
        ...

    @abstractmethod
    async def _on_context_over_limit(self) -> None:
        """上下文超限时的处理策略。"""
        ...

    @abstractmethod
    def _build_system_prompt(self) -> list[str]:
        """构建系统提示词段落列表。"""
        ...

    # -- 工具执行 ---------------------------------------------------------

    def _is_readonly_tool(self, name: str) -> bool:
        """检查工具是否为 readOnly（无需审批直接执行）。"""
        from abstract.tools.registry import registry
        entry = registry.get_entry(name)
        if entry is None:
            return False
        return entry.danger_level == ToolDangerLevel.readonly

    def _is_auto_approved_tool(self, name: str, args: dict) -> bool:
        """检查工具是否在自动批准白名单中。"""
        try:
            from component.approval.allowlist import is_allowed
            return is_allowed(name, args)
        except Exception:
            logger.exception("Failed to check approval allowlist for tool=%s", name)
            return False

    async def _execute_tool(self, tool_name: str, args: dict,
                            tool_call_id: str = "",
                            session_id: str = "") -> ToolResultMessage:
        """执行单个工具调用，处理只读/审批分流，返回 ToolResultMessage。

        1. readonly 或白名单工具：直接执行
        2. 非 readonly：调用 sink.request_approval 等待审批
        3. 审批通过：执行工具
        4. 审批拒绝：返回拒绝信息
        """
        # 注入 session_id 到 args 中（兼容旧工具 handler）
        args["_session_id"] = session_id or self.session_id

        sink = self.get_sink()
        is_readonly = self._is_readonly_tool(tool_name)
        is_auto = self._is_auto_approved_tool(tool_name, args)

        if not is_readonly and not is_auto:
            # 需要审批
            approval = await sink.request_approval(
                tool_name=tool_name,
                args=args,
                session_id=session_id or self.session_id,
            )
            if approval.action == "deny":
                return ToolResultMessage(
                    role=Role.TOOL,
                    character_name=self.current_character_agent,
                    tool_call_id=tool_call_id,
                    content=f"Tool execution denied: {approval.deny_reason or 'User rejected'}",
                )

        # 执行工具
        from abstract.tools.registry import registry
        from entry.base_agent_loop import ToolContext
        ctx = ToolContext(loop=self, session_id=self.session_id)
        result = await registry.async_dispatch(tool_name, args, context=ctx)
        content = tool_result_to_content(result)

        # 对前端 UI 类工具推送实时状态更新（工具模块自行注册事件类型）
        from abstract.tools.ui_event_router import ui_event_router
        await ui_event_router.emit_for(
            tool_name,
            result,
            sink,
            session_id or self.session_id,
        )

        return ToolResultMessage(
            role=Role.TOOL,
            character_name=self.current_character_agent,
            tool_call_id=tool_call_id,
            content=content,
        )

    # -- 历史管理 ---------------------------------------------------------

    def _get_history(self) -> History:
        return self._history

    def _append_history(self, message: BaseMessage) -> None:
        self._history.add_message(message)

    def _get_memory_context(self, user_message: str) -> str:
        """返回当前回合的 memory 上下文；子类可重写，默认空。"""
        _ = user_message  # 基类默认不使用，子类重写时消费
        return ""

    def _build_history_messages(
        self, user_message: str = ""
    ) -> list[BaseMessage]:
        """构建发送给 LLM 的完整历史消息列表（含 system prompt）。

        hooks_context / memory_ctx 已在追加用户消息时通过
        History.last_user_message.dynamic_message_suffix 注入，本函数不再处理。
        """
        system_prompts = self._build_system_prompt()
        return build_full_history_messages(
            system_prompts=system_prompts,
            history=self._history,
            current_character_agent=self.current_character_agent,
        )
