"""Agent Loop 抽象基类 + Inbox/InboxMessage 消息队列。

所有 Agent 循环（ParentAgentLoop、SubAgentLoop、GroupChatLoop）继承 ``BaseAgentLoop``。
``BaseAgentLoop`` 只提供所有循环共用的生命周期、收件箱机制和 sink 抽象；
``BasePrivateChatAgentLoop`` 继承它，补充 1-on-1 私聊循环所需的标准历史、
LLM 调用、工具执行、memory 和 hooks 能力。
"""

from __future__ import annotations

import asyncio
import logging
import shutil
import uuid
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Awaitable, Callable, ContextManager, TYPE_CHECKING

from pydantic import BaseModel

from entity.puretype import (
    Role,
    ToolAvailability,
    SessionMessageEntry,
    SessionHistorySkeletonResponse,
    SessionHistoryPageResponse,
    SessionHistoryResourcesResponse,
    TokenUsageRecord,
    MessageContent,
    LLMProfile,
    MessageMetrics,
    QueuedMessage,
    MainSessionInterruptResult,
    MainSessionActivitySource,
    MainSessionActivityPhase,
    MainSessionActivitySnapshot,
)
from entity.messages import (
    History,
    BaseMessage,
    ToolResultMessage,
    CharacterConversationMessage,
    CharacterMessage,
    MessageBlock,
    TextBlock,
)
from entity.constant import (
    USER_CHARACTER_NAME, SYSTEM_CHARACTER_NAME,
    INHERIT_LAST_ROUNDS,
    MAIN_SESSION_INTERRUPT_TIMEOUT,
    MAIN_SESSION_INTERRUPT_FORCE_CANCEL_TIMEOUT,
)
from entry.agent_support.messages import (
    build_full_history_messages,
    collect_all_hooks_context,
    load_message_hooks,
)
from entry.agent_support.multimodal import (
    content_to_text,
    blocks_from_dicts,
    content_to_serializable,
    extract_tool_call_meta,
)
from system.pathutils import find_repo_root
from system.session_store import SessionStore

if TYPE_CHECKING:
    from abstract.llm.client import BaseLLMClient
    from system.context import RuntimeContext
    from system.application import Application
    from entry.agent_sink import AgentSink
    from gateway.session_manager import SessionManager
    from entry.tool_post_dispatch import ResultFieldInjector
    from entry.session_message_queue import SessionMessageQueue

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


class Inbox:
    """线程安全的收件箱，支持等待新消息。

    SubAgentLoop 父→子通道使用（SP-5 D8：主会话已切队列，inbox 仅子 Agent 保留）。
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

    loop: BaseAgentLoop
    session_id: str = ""
    # 当前回复轮次的唯一 ID；所有明确 ws: 文件接触共用该 ID。
    round_id: str
    # 当前执行 agent 的角色名 — 多 agent 模式下由 ToolExecutor/Worker 注入，
    # 空 = 未指定（handler 回退到 loop.current_character_agent）
    character_name: str = ""
    # 当前 agent 的 LLM 配置 — 多 agent 模式下各 agent 配置不同，
    # None = 未指定（modality_capability 等回退到 loop.active_llm_profile）
    llm_profile: LLMProfile | None = None

    @property
    def app(self) -> Application:
        from system.application import Application
        return Application.current()

    @property
    def runtime_context(self) -> RuntimeContext:
        return self.app.runtime_context

    @property
    def resource_session_id(self) -> str:
        """返回长期资源归属的主会话 ID。"""
        parent_session_id = getattr(self.loop, "parent_session_id", "")
        if isinstance(parent_session_id, str) and parent_session_id:
            return parent_session_id
        return self.session_id

    @property
    def sink(self) -> AgentSink:
        return self.loop.get_sink()

    @property
    def is_interrupted(self) -> bool:
        return self.loop.is_interrupted()

    def agentspace_access(
        self,
        paths: list[tuple[str, bool]],
    ) -> ContextManager[None]:
        """登记本轮明确接触的 ws: 路径；失败时由工具 fail-closed。"""
        from entity.puretype import AgentspaceLockOwner

        owner = AgentspaceLockOwner(
            owner_id=self.round_id,
            session_id=self.session_id,
            character_name=self.character_name,
            round_id=self.round_id,
        )
        return self.app.agentspace_service.agent_access(owner, paths)


# ---------------------------------------------------------------------------
# _serialize_message_entry — 公共消息序列化函数
# ---------------------------------------------------------------------------

def _serialize_message_entry(
    msg: BaseMessage,
    index: int,
    fallback_character: str = "assistant",
    metrics: MessageMetrics | None = None,
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

    # SystemStatusMessage 标记（对 LLM 不可见，仅前端展示用）
    from entity.messages import SystemStatusMessage
    is_system_status = isinstance(msg, SystemStatusMessage)

    # ToolResultMessage._meta 提取
    tool_call_meta: dict[str, Any] | None = None
    if isinstance(msg, ToolResultMessage):
        tool_call_meta = extract_tool_call_meta(raw_content)

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
        metrics=metrics,
        is_system_status=is_system_status,
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
        self._disgust_event: asyncio.Event = asyncio.Event()
        self._message_hooks_cache: list[dict] | None = None
        self._history: History = History()
        self._session_store: SessionStore | None = None
        self._token_record: TokenUsageRecord = TokenUsageRecord()
        # gateway SessionManager 引用（由 server 层注入，用于旋转/归档）；
        # 仅主会话 loop 使用，子 Agent loop 保持 None
        self._session_manager: SessionManager | None = None
        # 活跃 LLM 配置覆盖（前端切换后设置，None 表示使用启动配置）
        self._active_llm_profile: LLMProfile | None = None
        # 处理中标志：子类在 process_message 主体内置位/复位；
        # 供 /regenerate 端点做并发防护（is_processing）查询
        self._processing: bool = False
        # 主会话活动快照只描述当前进程内运行状态，不进入 History 或持久化。
        self._main_session_activity: MainSessionActivitySnapshot | None = None
        self._main_session_activity_revision: int = 0
        # SP-4: 轮次互斥锁统一上移（原 ParentAgentLoop 私有）；会话消息队列设施（子类构造赋值）
        self._process_lock: asyncio.Lock = asyncio.Lock()
        self._message_queue: SessionMessageQueue | None = None
        # SP-5 D2：轮次后编排放 loop——由 MessageRouter 在 handle_user_message 注册，
        # run_pending_round 锁外末尾调用，完成 WS 重映射/token 推送/进化触发。
        self._on_round_done: Callable[[Any], Awaitable[None]] | None = None
        # 角色名 → 当前回复轮次 ID；只在 loop 的事件循环中变更。
        self._agentspace_round_ids: dict[str, str] = {}
        # 会话级已加载工具集名称集合
        self._loaded_toolsets: set[str] = set()

    def begin_agentspace_round(self, character_name: str) -> str:
        """开始一个 Agent 回复轮次并返回唯一 round_id。"""
        if character_name in self._agentspace_round_ids:
            raise RuntimeError(
                f"Agentspace round already active for {character_name!r}"
            )
        round_id = uuid.uuid4().hex
        self._agentspace_round_ids[character_name] = round_id
        return round_id

    def current_agentspace_round(self, character_name: str) -> str:
        """返回角色当前回复轮次；无活动轮次时拒绝无锁工具访问。"""
        try:
            return self._agentspace_round_ids[character_name]
        except KeyError as exc:
            raise RuntimeError(
                f"No active Agentspace round for {character_name!r}"
            ) from exc

    def end_agentspace_round(self, character_name: str, round_id: str) -> None:
        """仅释放匹配轮次持有的路径锁；重复调用幂等。"""
        current = self._agentspace_round_ids.get(character_name)
        if current is None:
            return
        if current != round_id:
            logger.warning(
                "Ignored mismatched Agentspace round release | character=%s current=%s requested=%s",
                character_name,
                current,
                round_id,
            )
            return
        try:
            self.app.agentspace_service.release_agent_access(round_id)
        finally:
            if self._agentspace_round_ids.get(character_name) == round_id:
                self._agentspace_round_ids.pop(character_name, None)

    def set_on_round_done(self, cb: Callable[[Any], Awaitable[None]] | None) -> None:
        """注册轮次后回调（幂等覆盖；None 清除）。

        由 MessageRouter.handle_user_message 在每次 WS 消息入队前调用。
        """
        self._on_round_done = cb

    @property
    def history_store_dir(self) -> Path | None:
        """统一返回当前 loop 的 session 持久化根目录。"""
        return self._session_store.base_dir if self._session_store else None

    @property
    def session_store(self) -> "SessionStore | None":
        """返回当前 loop 的 session 持久化存储（未配置时为 None）。"""
        return self._session_store

    @property
    def active_llm_profile(self) -> LLMProfile | None:
        """返回当前活跃的 LLM 配置（前端切换后），未切换时返回 None。"""
        return self._active_llm_profile

    def set_session_manager(self, manager: SessionManager) -> None:
        """注入 gateway SessionManager，用于旋转/归档等操作。"""
        self._session_manager = manager

    @property
    def session_manager(self) -> SessionManager | None:
        """返回当前 loop 关联的 gateway SessionManager（未注入时为 None）。"""
        return self._session_manager

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
        user_message: MessageContent,
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

        子类可重写以处理特定类型的消息。
        """
        return self._inbox.get_pending()

    # -- 取消控制 ---------------------------------------------------------

    def interrupt(self) -> None:
        """请求停止当前循环。"""
        logger.info("Interrupt requested | session=%s", self.session_id)
        self._cancel_event.set()

    @property
    def cancel_event(self) -> asyncio.Event:
        """只读返回取消事件，供外部流式消费者检查中断状态。"""
        return self._cancel_event

    def is_interrupted(self) -> bool:
        """返回 True 表示存在活跃的中断请求。"""
        return self._cancel_event.is_set()

    # -- 厌恶控制 ---------------------------------------------------------

    def disgust(self) -> None:
        """请求厌恶模式：不中断 LLM 生成，但后续所有工具调用返回厌恶错误。"""
        logger.info("Disgust requested | session=%s", self.session_id)
        self._disgust_event.set()

    def is_disgusted(self) -> bool:
        """返回 True 表示存在活跃的厌恶请求。"""
        return self._disgust_event.is_set()

    async def _check_cancel(self) -> bool:
        """检查取消事件，已中断则返回 True。"""
        return self._cancel_event.is_set()

    # -- 工具集加载状态（所有 loop 共享）-----------------------------------

    def get_tool_availability_scope(self) -> ToolAvailability:
        """返回当前 loop 的工具可用性 scope。

        子类覆写此方法返回具体的 ToolAvailability（MAIN / SUBAGENT /
        MULTI_AGENT / TASKAGENT）。默认返回 EVERY。
        """
        return ToolAvailability.EVERY

    def get_loaded_toolsets(self) -> set[str]:
        """返回当前会话已加载的工具集名称集合。"""
        return set(self._loaded_toolsets)

    def is_toolset_loaded(self, toolset_name: str) -> bool:
        """检查工具集是否已加载。"""
        return toolset_name in self._loaded_toolsets

    def load_toolsets(self, toolset_names: list[str]) -> list[str]:
        """加载工具集，持久化并返回新加载的工具集名称列表。

        幂等：已加载的工具集不重复加载。core 始终在集合中。
        """
        newly_loaded: list[str] = []
        for name in toolset_names:
            if name not in self._loaded_toolsets:
                self._loaded_toolsets.add(name)
                newly_loaded.append(name)
        if newly_loaded:
            self._persist_loaded_toolsets()
        return newly_loaded

    def _persist_loaded_toolsets(self) -> None:
        """持久化当前已加载工具集到 SessionStore。"""
        if self._session_store is not None:
            self._session_store.write_loaded_toolsets(
                self.session_id, sorted(self._loaded_toolsets),
            )

    def _restore_loaded_toolsets(self) -> None:
        """从 SessionStore 恢复已加载工具集；无 SessionStore 时仅加载 core。"""
        from abstract.tools.registry import DEFAULT_LOADED_TOOLSET
        if self._session_store is not None:
            names = self._session_store.read_loaded_toolsets(self.session_id)
            self._loaded_toolsets = set(names)
        else:
            self._loaded_toolsets = {DEFAULT_LOADED_TOOLSET}

    def _get_effective_tool_definitions(self) -> list[dict]:
        """根据当前 Loop 的 scope 和会话已加载工具集，计算有效工具 schema 列表。

        子类通过 get_tool_availability_scope() 返回当前 Loop 的 ToolAvailability。
        """
        from abstract.tools.registry import registry as tool_registry
        scope = self.get_tool_availability_scope()
        return tool_registry.get_definitions_for_loaded_toolsets(
            scope=scope,
            loaded_toolsets=self._loaded_toolsets,
        )

    # -- token 追踪（所有 loop 共享，可被子类覆盖）-------------------------

    def _ensure_token_record_loaded(self) -> None:
        """首次访问时从磁盘恢复 token 使用记录（幂等）。"""
        if self._token_record.token_usage or self._token_record.prompt_tokens:
            return
        if self._session_store is None:
            return
        try:
            record = self._session_store.read_token_usage(self.session_id)
        except Exception:
            logger.exception("Failed to load token usage for session=%s", self.session_id)
            return
        if record.token_usage or record.prompt_tokens:
            self._token_record = record

    def get_token_usage(self) -> int:
        self._ensure_token_record_loaded()
        return self._token_record.token_usage

    def get_context_tokens(self) -> int:
        self._ensure_token_record_loaded()
        return self._token_record.prompt_tokens

    async def _push_usage_update(self, session_id: str) -> None:
        """推送 token 消耗到前端。"""
        try:
            await self.get_sink().emit_usage_update(
                session_id, self._token_record.token_usage, self._token_record.prompt_tokens,
            )
        except Exception:
            logger.warning("Failed to push usage update for session=%s", session_id, exc_info=True)

    def _persist_token_usage(self, session_id: str) -> None:
        if self._session_store is None:
            return
        try:
            self._session_store.write_token_usage(session_id, self._token_record)
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

    def save_history(self, session_id: str) -> None:
        """将当前 History 持久化到磁盘。"""
        if self._session_store is None:
            return
        try:
            self._session_store.write_history(session_id, self._history)
        except Exception as exc:
            logger.exception("Failed to save history for session %s: %s", session_id, exc)

    def _remove_last_user_message(self, session_id: str) -> None:
        """移除 History 中最后一条 user 消息并持久化。"""
        if self._history.count > 0:
            last_msg = self._history.get_message(self._history.count - 1)
            if last_msg.role == Role.USER:
                self._history.remove_last_message()
        self.save_history(session_id)

    def append_assistant_text(self, text: str, *, session_id: str | None = None) -> int:
        """将一段 assistant 文本作为 CharacterConversationMessage 追加到历史并持久化。

        供 gateway 层与 loop 内错误/取消/超限等路径统一使用，确保「凡以 assistant
        气泡显示的内容必进历史」（D6 不变量）。返回新消息的索引。
        """
        sid = session_id or self.session_id
        message = CharacterConversationMessage(
            role=Role.ASSISTANT,
            character_name=self.current_character_agent,
            content=text,
        )
        index = self._history.add_message(message)
        self.save_history(sid)
        return index

    def append_system_status(self, text: str, *, session_id: str | None = None) -> int:
        """将系统状态消息作为 SystemStatusMessage 追加到历史并持久化。

        SystemStatusMessage 对 LLM 不可见（is_visible_to 返回 False），
        但存储在 History 中，前端可通过 get_session_messages 看到。
        用于替代中断/错误场景下的 append_assistant_text，避免污染 LLM 上下文。

        返回新消息的索引。
        """
        from entity.messages import SystemStatusMessage
        sid = session_id or self.session_id
        message = SystemStatusMessage(
            role=Role.SYSTEM,
            content=text,
        )
        index = self._history.add_message(message)
        self.save_history(sid)
        return index

    async def report_context_limit_rotation_blocked(
        self,
        session_id: str,
        error: Exception,
    ) -> None:
        """持久化并推送上下文超限旋转失败状态。"""
        from entity.constant import CONTEXT_LIMIT_METADATA_FAILURE_STATUS

        logger.error(
            "Context-limit rotation blocked by metadata failure | session=%s error=%s",
            session_id,
            error,
            exc_info=(type(error), error, error.__traceback__),
        )
        self.append_system_status(
            CONTEXT_LIMIT_METADATA_FAILURE_STATUS,
            session_id=session_id,
        )
        await self.get_sink().emit_system_message(
            session_id,
            CONTEXT_LIMIT_METADATA_FAILURE_STATUS,
        )

    def clear_session(self) -> None:
        """清理当前 session 的持久化数据。"""
        logger.info("Clearing session | session=%s", self.session_id)
        if self._session_store is None:
            return
        session_path = self._session_store.session_dir(self.session_id)
        if session_path.exists():
            shutil.rmtree(str(session_path), ignore_errors=True)
            logger.info("Cleared persisted data for session %s", self.session_id)

    def stop_message_queue(self) -> None:
        """停止本会话的消息队列消费者（gateway 在 loop 消亡时调用）。

        SP-4 D8：旋转复用 loop 不调用（队列随 loop 存活）；仅 terminate/replace 调用。
        """
        if self._message_queue is not None:
            self._message_queue.stop()

    def mark_queue_stopped(self) -> None:
        """标记队列停止但不取消 consumer task（用于 replace_loop 延迟拆卸）。

        与 stop_message_queue() 的区别：不调用 consumer_task.cancel()，
        让当前 run_pending_round 自然完成后再退出 _consume_loop。
        """
        if self._message_queue is not None:
            self._message_queue.mark_stopped()

    def get_session_messages(self) -> list[SessionMessageEntry]:
        """返回前端展示所需的消息列表，包含多 agent 元数据。"""
        fallback = self.current_character_agent
        # 从 SessionStore 读取持久化的 metrics
        metrics_map: dict[str, dict[str, Any]] = {}
        if self._session_store is not None:
            try:
                metrics_map = self._session_store.read_message_metrics(self.session_id)
            except Exception:
                logger.warning(
                    "Failed to read message metrics for session=%s",
                    self.session_id, exc_info=True,
                )
        result: list[SessionMessageEntry] = []
        for index, msg in enumerate(self._history.iter_messages()):
            m_data = metrics_map.get(str(index))
            m = MessageMetrics.model_validate(m_data) if m_data else None
            result.append(
                _serialize_message_entry(msg, index, fallback_character=fallback, metrics=m)
            )
        return result

    def get_session_history_skeleton(
        self, start_index: int = 0,
    ) -> SessionHistorySkeletonResponse:
        """返回从 History 索引开始的全历史骨架后缀。"""
        from entry.history_projection import project_history_skeleton

        messages = list(self._history.iter_messages())
        history_count = len(messages)
        if start_index < 0 or start_index > history_count:
            raise ValueError("start_index out of range")
        rows = project_history_skeleton(
            messages,
            self.current_character_agent,
            start_index=start_index,
        )
        return SessionHistorySkeletonResponse(
            session_id=self.session_id,
            start_index=start_index,
            history_count=history_count,
            row_count=len(rows),
            rows=rows,
        )

    def get_session_history_page(
        self, start_index: int, limit: int,
    ) -> SessionHistoryPageResponse:
        """按 History 索引范围返回完整前端内容行。"""
        from entry.history_projection import project_history_content_rows

        messages = list(self._history.iter_messages())
        history_count = len(messages)
        if start_index < 0:
            raise ValueError("start_index must be >= 0")
        if limit < 1:
            raise ValueError("limit must be >= 1")
        if start_index >= history_count:
            return SessionHistoryPageResponse(
                session_id=self.session_id,
                start_index=start_index,
                end_index=start_index,
                history_count=history_count,
                rows=[],
            )

        end_index = min(history_count, start_index + limit)
        metrics_map: dict[int, MessageMetrics] = {}
        if self._session_store is not None:
            try:
                raw_metrics_map = self._session_store.read_message_metrics(self.session_id)
                for raw_index, raw_metrics in raw_metrics_map.items():
                    try:
                        metrics_map[int(raw_index)] = MessageMetrics.model_validate(raw_metrics)
                    except (TypeError, ValueError):
                        logger.warning(
                            "Invalid message metrics index=%s for session=%s",
                            raw_index, self.session_id,
                        )
            except Exception:
                logger.warning(
                    "Failed to read message metrics for session=%s",
                    self.session_id,
                    exc_info=True,
                )
        rows = project_history_content_rows(
            messages,
            start_index,
            end_index,
            self.current_character_agent,
            metrics_map,
        )
        return SessionHistoryPageResponse(
            session_id=self.session_id,
            start_index=start_index,
            end_index=end_index,
            history_count=history_count,
            rows=rows,
        )

    def get_session_history_resources(self) -> SessionHistoryResourcesResponse:
        """返回完整 History 的图片与下载资源索引。"""
        from entry.history_projection import project_history_resources

        return project_history_resources(
            list(self._history.iter_messages()), self.session_id,
        )

    def edit_session_message(self, index: int, content: str | list[dict[str, Any]] | None = None,
                             visible_characters: list[str] | None = None) -> dict:
        logger.info("Edit message | session=%s index=%d", self.session_id, index)
        if not isinstance(index, int) or index < 0:
            logger.warning("Edit message fail | session=%s error=invalid index", self.session_id)
            return {"updated": False, "error": "invalid message index"}
        if index >= self._history.count:
            logger.warning("Edit message fail | session=%s index=%d error=out of range", self.session_id, index)
            return {"updated": False, "error": "message index out of range"}
        msg = self._history.get_message(index)
        if not isinstance(msg, CharacterConversationMessage):
            logger.warning("Edit message fail | session=%s index=%d error=type not editable", self.session_id, index)
            return {"updated": False, "error": "message type not editable"}
        updates: dict = {}
        if content is not None:
            if isinstance(content, list):
                updates["content"] = blocks_from_dicts(content)
            else:
                updates["content"] = content
        if visible_characters is not None:
            updates["visible_characters"] = visible_characters
        updated_msg = msg.model_copy(update=updates)
        self._history.set_message(index, updated_msg)
        self.save_history(self.session_id)
        result: dict = {
            "updated": True,
            "session_id": self.session_id,
            "index": index,
            "role": msg.role.value,
            "content": content_to_serializable(updated_msg.content),
        }
        if visible_characters is not None:
            result["visible_characters"] = visible_characters
        logger.info("Edit message ok | session=%s index=%d role=%s", self.session_id, index, msg.role.value)
        return result

    def delete_session_messages(self, count: int = 1) -> dict:
        """删除最后 count 个逻辑轮次的消息（从倒数第 count 条 user 起，覆盖其后所有 tool/assistant）。"""
        logger.info("Delete messages | session=%s count=%d", self.session_id, count)
        if count < 1:
            logger.warning("Delete messages fail | session=%s error=count must be >= 1", self.session_id)
            return {"deleted": False, "error": "count must be >= 1"}
        remove_from = self._history.find_last_user_message_index(count=count)
        if remove_from is None:
            logger.warning("Delete messages fail | session=%s error=no user messages to delete", self.session_id)
            return {"deleted": False, "error": "no user messages to delete"}
        self._history.truncate_to(remove_from)
        self.save_history(self.session_id)
        logger.info("Delete messages ok | session=%s removed_from=%d remaining=%d", self.session_id, remove_from, self._history.count)
        return {"deleted": True, "session_id": self.session_id, "remaining_count": self._history.count}

    def delete_single_message(self, index: int) -> dict:
        """删除最后一轮范围内的单条消息（含配对联动清理）。

        校验 index 在最后一条 user 消息之后。
        调用 History.remove_message_with_pairing。
        持久化 save_history。
        """
        logger.info("Delete single message | session=%s index=%d", self.session_id, index)

        # 校验 index 在最后一条 user 消息之后
        last_user_idx = self._history.find_last_user_message_index(count=1)
        if last_user_idx is None:
            logger.warning("Delete single message fail | session=%s error=no user message found", self.session_id)
            return {"deleted": False, "error": "no user message found"}
        if index <= last_user_idx:
            logger.warning("Delete single message fail | session=%s index=%d must be after last user (idx=%d)", self.session_id, index, last_user_idx)
            return {"deleted": False, "error": "can only delete messages after the last user message"}

        # 调用 History 的配对删除
        result = self._history.remove_message_with_pairing(index)
        if not result.get("deleted"):
            return result

        # 持久化
        self.save_history(self.session_id)

        logger.info("Delete single message ok | session=%s removed=%s remaining=%d",
                     self.session_id, result.get("removed_indices"), result.get("remaining_count"))
        return result

    def regenerate_response(self, message_index: int | None = None) -> dict:
        """截断到目标 user 消息，刷新其上下文扩展块，返回内容供重新生成。

        NOTE: 双路径解析目标消息——
          - 显式路径（message_index 非 None）：由前端按钮携带所点消息的索引，
            校验 0 <= idx < count 且该处 role == Role.USER。命中精确、不会
            误取 cron/动态端点等非人类 user 消息。失败返回 400 类错误。
          - 兜底路径（message_index 为 None）：旧式无参调用，取
            find_last_user_message_index(count=1)，可能命中非人类 user 消息，
            仅为兼容保留。后续前端全面携带 message_index 后可移除。
        """
        logger.info("Regenerate response | session=%s message_index=%s", self.session_id, message_index)

        # ── 解析目标 user 消息索引 ──
        if message_index is not None:
            # 显式路径
            if not isinstance(message_index, int) or message_index < 0 or message_index >= self._history.count:
                logger.warning("Regenerate fail | session=%s index=%s out of range", self.session_id, message_index)
                return {"regenerate": False, "error": "message index out of range"}
            target_msg = self._history.get_message(message_index)
            if target_msg.role != Role.USER:
                logger.warning("Regenerate fail | session=%s index=%s not a user message", self.session_id, message_index)
                return {"regenerate": False, "error": "target message is not a user message"}
            last_user_idx = message_index
        else:
            # 兜底路径
            last_user_idx = self._history.find_last_user_message_index(count=1)
            if last_user_idx is None:
                logger.warning("Regenerate fail | session=%s error=no user message found", self.session_id)
                return {"regenerate": False, "error": "no user message found"}

        last_user_msg = self._history.get_message(last_user_idx)
        last_user_content = content_to_text(last_user_msg.content)

        # ── 截断到目标 user 消息（含）之后 ──
        self._history.truncate_to(last_user_idx + 1)
        self.save_history(self.session_id)

        # ── 刷新上下文扩展块（重新生成 ≡ 重新发送）──
        # 重新收集 hooks，同时覆写动态块与固定块并持久化
        hooks_context, fixator_context = self._collect_hooks_context()
        if isinstance(last_user_msg, CharacterConversationMessage):
            updated = last_user_msg.model_copy(update={
                "message_suffix": fixator_context or None,
                "dynamic_message_suffix": hooks_context or None,
            })
            self._history.set_message(last_user_idx, updated)
            self.save_history(self.session_id)
            last_user_msg = updated

        result: dict = {
            "regenerate": True,
            "session_id": self.session_id,
            "last_user_content": last_user_content,
            "remaining_count": self._history.count,
            "message_index": last_user_idx,
            "message_suffix": fixator_context or None,
            "dynamic_message_suffix": hooks_context or None,
        }
        if isinstance(last_user_msg, CharacterConversationMessage):
            result["visible_characters"] = last_user_msg.visible_characters
            result["response_characters"] = last_user_msg.response_characters
        logger.info("Regenerate ok | session=%s index=%d remaining=%d", self.session_id, last_user_idx, self._history.count)
        return result

    def get_tool_resources(self) -> dict:
        """返回 session 的可恢复工具副作用资源快照。"""
        if self._session_store is None:
            return {"task_progress": {}, "clipboard_display": {}}
        return self._session_store.read_tool_resources(self.session_id)

    # -- 主会话活动快照 --------------------------------------------------

    def ensure_main_session_activity(
        self,
        source: MainSessionActivitySource,
        *,
        character_name: str | None = None,
    ) -> str:
        """创建或复用当前主会话活动；只有 queued 阶段允许合并来源。"""
        current = self._main_session_activity
        if current is not None:
            updates: dict[str, Any] = {}
            if (
                current.phase == MainSessionActivityPhase.queued
                and current.source != source
                and current.source != MainSessionActivitySource.mixed
            ):
                updates["source"] = MainSessionActivitySource.mixed
            if character_name and current.character_name != character_name:
                updates["character_name"] = character_name
            if updates:
                self._main_session_activity_revision += 1
                updates["revision"] = self._main_session_activity_revision
                self._main_session_activity = current.model_copy(update=updates)
            return current.activity_id

        self._main_session_activity_revision = 1
        activity_id = uuid.uuid4().hex
        self._main_session_activity = MainSessionActivitySnapshot(
            activity_id=activity_id,
            revision=self._main_session_activity_revision,
            source=source,
            phase=MainSessionActivityPhase.queued,
            character_name=character_name,
        )
        return activity_id

    def set_main_session_activity_phase(
        self,
        activity_id: str,
        phase: MainSessionActivityPhase,
        *,
        stream_id: str | None = None,
        character_name: str | None = None,
    ) -> None:
        """更新匹配活动的阶段；None stream_id 明确解除当前流绑定。"""
        current = self._main_session_activity
        if current is None or current.activity_id != activity_id:
            logger.debug(
                "Ignored stale main-session activity update | session=%s requested=%s current=%s",
                self.session_id,
                activity_id,
                current.activity_id if current else None,
            )
            return
        next_character = character_name if character_name is not None else current.character_name
        if (
            current.phase == phase
            and current.stream_id == stream_id
            and current.character_name == next_character
        ):
            return
        self._main_session_activity_revision += 1
        self._main_session_activity = current.model_copy(update={
            "revision": self._main_session_activity_revision,
            "phase": phase,
            "stream_id": stream_id,
            "character_name": next_character,
        })

    def get_main_session_activity(self) -> MainSessionActivitySnapshot | None:
        """返回当前活动的隔离副本，避免外部修改内部状态。"""
        current = self._main_session_activity
        return current.model_copy(deep=True) if current is not None else None

    def finish_main_session_activity(self, activity_id: str) -> None:
        """仅结束匹配活动；旧轮次收尾不能清除后续活动。"""
        current = self._main_session_activity
        if current is None:
            return
        if current.activity_id != activity_id:
            logger.debug(
                "Ignored stale main-session activity finish | session=%s requested=%s current=%s",
                self.session_id,
                activity_id,
                current.activity_id,
            )
            return
        self._main_session_activity = None

    def is_active(self) -> bool:
        """返回用户可见的主会话活跃状态，包含尚未取得处理锁的排队窗口。"""
        return self._main_session_activity is not None or self._processing

    # -- IMainSessionLoop 默认实现 ----------------------------------------

    def pop_session_rotated(self) -> str | None:
        """取出并移除 session 旋转通知。默认返回 None。"""
        return None

    def is_processing(self) -> bool:
        """返回当前是否正在处理消息。

        基类维护 ``self._processing`` 标志，子类应在 ``process_message``
        主体内置位（True）与复位（False）。基类默认实现返回该标志。
        """
        return self._processing

    async def terminate_session(self) -> dict:
        """终结当前会话。默认返回简单确认。子类可覆盖。"""
        logger.info("Terminating session (base): %s", self.session_id)
        return {"terminated": True, "session_id": self.session_id}

    async def merge_sessions(self, sources: list[str]) -> dict:
        """基于全部父会话摘要创建延续会话；任一摘要失败则整体失败。"""
        sm = self.session_manager
        if sm is None:
            return {"error": "session manager not available", "merged": False}
        if not sources:
            return {"error": "sources list is empty", "merged": False}
        if self._session_store is None:
            return {"error": "session store not available", "merged": False}

        from entry.agent_support.history_summary import (
            messages_to_text,
            extract_last_rounds,
        )
        from system.session_metadata import SessionMetadataError
        from system.templates import read_template

        summaries: list[tuple[str, str]] = []
        for source_id in sources:
            try:
                summary = await self.app.session_metadata_service.ensure_summary(
                    source_id
                )
            except SessionMetadataError as exc:
                logger.warning(
                    "Session merge blocked by missing summary | source=%s error=%s",
                    source_id,
                    exc,
                )
                return {
                    "error": f"无法为父会话 {source_id} 生成摘要：{exc}",
                    "merged": False,
                }
            summaries.append((source_id, summary))

        if len(summaries) == 1:
            source_id, summary = summaries[0]
            context = (
                read_template("session_inherit.txt")
                .replace("{{old_sid}}", source_id)
                .replace("{{summary}}", summary)
            )
        else:
            joined = "\n\n---\n\n".join(
                f"[Session {source_id}]: {summary}"
                for source_id, summary in summaries
            )
            threshold = self.app.runtime_context.merge_concat_threshold
            if threshold > 0 and len(joined) > threshold:
                joined = joined[-threshold:]
            context = (
                "This session merges multiple previous sessions. "
                "Here are their summaries:\n\n"
                f"{joined}"
            )

        tail_blocks: list[str] = []
        for source_id in sources:
            try:
                source_history = self._session_store.read_history(source_id)
                if source_history is None or source_history.count == 0:
                    continue
                tail_messages = extract_last_rounds(
                    source_history,
                    rounds=INHERIT_LAST_ROUNDS,
                    include_tool_messages=False,
                )
                if tail_messages:
                    tail_blocks.append(
                        f"### Source session {source_id}\n"
                        + messages_to_text(tail_messages)
                    )
            except Exception:
                logger.exception(
                    "Failed to append tail rounds for source=%s", source_id
                )
        if tail_blocks:
            context += (
                "\n\n## Recent conversation rounds\n"
                + "\n\n---\n\n".join(tail_blocks)
            )

        new_sid = sm.create_with_context(
            context=context,
            parent_sid=sources[0],
            parents=sources,
            role=Role.USER,
        )
        self._session_store.copy_active_profile_name(sources[0], new_sid)

        summary_history = History()
        summary_history.add_message(CharacterConversationMessage(
            role=Role.USER,
            character_name=SYSTEM_CHARACTER_NAME,
            content=context,
            visible_characters=[self.current_character_agent],
        ))
        self._session_store.write_history(new_sid, summary_history)

        for source_id in sources:
            sm.archive(source_id, continuation_sid=new_sid)

        logger.info(
            "Sessions merged | new=%s sources=%s summaries=%d",
            new_sid,
            sources,
            len(summaries),
        )
        return {"merged": True, "session_id": new_sid, "sources": sources}

    # -- Hook 支持（所有 loop 共享）----------------------------------------

    def _load_message_hooks(self) -> list[dict]:
        """加载 custom_hooks 目录中的消息扩展 hook，结果按 loop 实例缓存。"""
        if self._message_hooks_cache is not None:
            return self._message_hooks_cache
        from entity.constant import Namespace
        hooks_dir: Path = self.app.sandbox.get_base(Namespace.CUSTOM_HOOKS)
        hooks = load_message_hooks(hooks_dir, logger)
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

    # -- 主会话活动任务管理（强制中断基础）---------------------------------

    def _init_round_registry(self) -> None:
        """初始化主会话活动任务注册表。由主会话实现类在 ``super().__init__`` 后调用。"""
        self._interrupt_lock: asyncio.Lock = asyncio.Lock()
        self._active_round_task: asyncio.Task | None = None

    def register_round_task(self, task: asyncio.Task | None) -> None:
        """登记已经取得处理锁的当前主会话回复任务。"""
        if task is None:
            return
        old = self._active_round_task
        if old is task:
            return
        if old is not None and not old.done():
            message = (
                f"Overlapping active round tasks for session={self.loop.session_id}: "
                f"old={old.get_name()} new={task.get_name()}"
            )
            logger.error(message)
            raise RuntimeError(message)
        self._active_round_task = task

    def unregister_round_task(self, task: asyncio.Task | None) -> None:
        """注销主会话回复任务；仅匹配当前登记任务时清除。"""
        if task is not None and self._active_round_task is task:
            self._active_round_task = None

    def has_active_round(self) -> bool:
        """以「是否存在登记的活动任务」判定主会话是否忙碌，而非 _processing。"""
        task = self._active_round_task
        return task is not None and not task.done()

    async def request_interrupt(
        self, *, reason: str = "user",
        timeout: float = MAIN_SESSION_INTERRUPT_TIMEOUT,
    ) -> MainSessionInterruptResult:
        """强制中断当前主会话轮次并等待收尾确认（权威结果）。

        流程：互斥 → 无活动任务直接 idle → 设置轮次取消信号 →
        终止活动子进程 → 协作式等待 → 超时后强制取消轮次 task。
        """
        sid = self.loop.session_id
        started = asyncio.get_running_loop().time()
        async with self._interrupt_lock:
            task = self._active_round_task
            if task is None or task.done():
                return MainSessionInterruptResult(
                    accepted=True, status="idle", session_id=sid, reason=reason,
                )

            self.loop._cancel_event.set()

            # 终止本会话登记的活动子进程树。
            try:
                self.loop.app.sandbox.kill_active(sid)
            except Exception:
                logger.warning(
                    "kill_active failed during interrupt | session=%s", sid, exc_info=True,
                )

            # 先给协作式退出完整窗口；超时后才强制取消轮次 task。
            try:
                await asyncio.wait_for(asyncio.shield(task), timeout=timeout)
            except asyncio.TimeoutError:
                logger.warning(
                    "Interrupt cooperative cleanup timed out; forcing round cancellation | "
                    "session=%s task=%s",
                    sid,
                    task.get_name(),
                )
                task.cancel()
            except asyncio.CancelledError:
                if task.cancelled():
                    logger.info(
                        "Interrupt completed by target task cancellation | session=%s elapsed_ms=%d",
                        sid,
                        int((asyncio.get_running_loop().time() - started) * 1000),
                    )
                    return MainSessionInterruptResult(
                        accepted=True, status="cancelled", session_id=sid, reason=reason,
                    )
                raise
            except Exception as exc:
                logger.exception("Interrupt cooperative cleanup failed | session=%s", sid)
                return MainSessionInterruptResult(
                    accepted=True, status="failed", session_id=sid, reason=reason,
                    error=f"{type(exc).__name__}: {exc}",
                )
            else:
                logger.info(
                    "Interrupt completed cooperatively | session=%s elapsed_ms=%d",
                    sid,
                    int((asyncio.get_running_loop().time() - started) * 1000),
                )
                return MainSessionInterruptResult(
                    accepted=True, status="cancelled", session_id=sid, reason=reason,
                )

            try:
                await asyncio.wait_for(
                    asyncio.shield(task),
                    timeout=MAIN_SESSION_INTERRUPT_FORCE_CANCEL_TIMEOUT,
                )
            except asyncio.TimeoutError:
                total_timeout = timeout + MAIN_SESSION_INTERRUPT_FORCE_CANCEL_TIMEOUT
                logger.error(
                    "Interrupt forced cleanup timed out | session=%s task=%s timeout=%.3f",
                    sid,
                    task.get_name(),
                    total_timeout,
                )
                return MainSessionInterruptResult(
                    accepted=True, status="timeout", session_id=sid, reason=reason,
                    error=f"round cleanup exceeded {total_timeout}s",
                )
            except asyncio.CancelledError:
                if not task.cancelled():
                    raise
            except Exception as exc:
                logger.exception("Interrupt forced cleanup failed | session=%s", sid)
                return MainSessionInterruptResult(
                    accepted=True, status="failed", session_id=sid, reason=reason,
                    error=f"{type(exc).__name__}: {exc}",
                )

            logger.info(
                "Interrupt completed after forced cancellation | session=%s elapsed_ms=%d",
                sid,
                int((asyncio.get_running_loop().time() - started) * 1000),
            )
            return MainSessionInterruptResult(
                accepted=True, status="cancelled", session_id=sid, reason=reason,
            )

    @property
    def loop(self) -> BaseAgentLoop:
        """返回当前 loop 的实例。"""
        if isinstance(self, BaseAgentLoop):
            return self
        raise ValueError("current instance is not a BaseAgentLoop")

    def ensure_main_session_activity(
        self,
        source: MainSessionActivitySource,
        *,
        character_name: str | None = None,
    ) -> str:
        return self.loop.ensure_main_session_activity(
            source,
            character_name=character_name,
        )

    def set_main_session_activity_phase(
        self,
        activity_id: str,
        phase: MainSessionActivityPhase,
        *,
        stream_id: str | None = None,
        character_name: str | None = None,
    ) -> None:
        self.loop.set_main_session_activity_phase(
            activity_id,
            phase,
            stream_id=stream_id,
            character_name=character_name,
        )

    def get_main_session_activity(self) -> MainSessionActivitySnapshot | None:
        return self.loop.get_main_session_activity()

    def finish_main_session_activity(self, activity_id: str) -> None:
        self.loop.finish_main_session_activity(activity_id)

    def is_active(self) -> bool:
        return self.loop.is_active()

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
    def set_profile(self, profile: LLMProfile | None) -> None:
        """切换主会话的活动 Profile；None 表示明确无配置。"""

    @abstractmethod
    def get_tool_availability_scope(self) -> ToolAvailability:
        """返回当前 loop 的工具可用性 scope。

        dispatch 层用 (entry.availability & scope) == 0 拦截不在当前 scope 内的工具。
        """

    def get_result_field_injector(self) -> "ResultFieldInjector | None":
        """返回工具结果字段注入器。默认返回 None（无注入）。

        ToolExecutor.execute 在每次工具调用时查询此方法，
        将返回的注入器传给 finalize_tool_result 的 field_injector 参数。
        SP-4 的 SessionMessageQueue 将通过重写此方法返回队列的 drain 回调，
        使队列在工具链中消费时能向工具结果 dict 注入 queued_messages 字段。
        """
        return None

    def set_on_round_done(self, cb: Callable[[Any], Awaitable[None]] | None) -> None:
        """注册轮次后回调（SP-5 D2）。默认空实现；BaseAgentLoop 提供真实存储。

        MessageRouter.handle_user_message 在 WS 消息入队前调用，run_pending_round
        锁外末尾调用该回调以完成 WS 重映射/token 推送/进化触发。
        """
        pass

    @abstractmethod
    async def run_pending_round(self, items: list[QueuedMessage]) -> str | None:
        """以队列 drained 消息列表为输入驱动一轮会话（SP-4 D3）。

        实现必须：持 _process_lock → 置 _processing → （parent 系）超限检查（旋转随动）
        → sid 变更检测 → cancel 检测 → 注入落历史（无回显、保序、原生块）
        → （非旋转非中断时）跑轮 → finally 复位。
        """

    @abstractmethod
    async def resume(self) -> str:
        """从当前历史状态恢复工具链执行。

        清除中断/厌恶标志，重置工具调用计数器，
        从当前历史构建 messages 并重新进入工具循环。
        不追加任何 user 消息。
        返回助手回复文本（空串表示无回复）。
        """


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
        self, user_message: MessageContent = ""
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
