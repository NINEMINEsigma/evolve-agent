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
from abc import ABC, abstractmethod
from typing import Any, TYPE_CHECKING

from pydantic import BaseModel

from entity.puretype import Role, ToolDangerLevel
from entity.messages import History, BaseMessage, ToolResultMessage
from entity.constant import USER_CHARACTER_NAME
from entry.agent_support.messages import build_turn_messages, load_message_hooks
from entry.agent_support.multimodal import tool_result_to_content, content_to_text
from system.pathutils import find_repo_root

if TYPE_CHECKING:
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
    character_name: str

    def to_text(self) -> str:
        """转换为注入 LLM 历史的文本。子类按需重写。"""
        return self.content


class UserMessage(InboxMessage):
    """来自用户/父Agent的文本消息。"""
    character_name: str = USER_CHARACTER_NAME


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
    character_name: str = "system"

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
        return self.loop._get_sink()

    @property
    def is_interrupted(self) -> bool:
        return self.loop._cancel_event.is_set()


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

    @property
    def inbox(self) -> Inbox:
        """公开的收件箱访问器，供 CronRouter 等外部组件投递消息。"""
        return self._inbox

    # -- 抽象方法 ---------------------------------------------------------

    @abstractmethod
    def _get_sink(self) -> AgentSink:
        """返回当前 loop 的 AgentSink 实例。"""
        ...

    @property
    @abstractmethod
    def user_character_name(self) -> str:
        """返回当前 loop 的"用户"角色名：向本 loop 发消息的发出者角色名。

        主会话里是真正的 end-user；子会话里是其"父 Agent"当前角色名。
        """
        ...

    @abstractmethod
    async def append_user_message(self, content: Any, *, display_content: Any | None = None) -> int:
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

    def is_interrupted(self) -> bool:
        """返回 True 表示存在活跃的中断请求。"""
        return self._cancel_event.is_set()

    async def _check_cancel(self) -> bool:
        """检查取消事件，已中断则返回 True。"""
        return self._cancel_event.is_set()


# ---------------------------------------------------------------------------
# BasePrivateChatAgentLoop — 1-on-1 私聊 Agent 循环基类
# ---------------------------------------------------------------------------

class BasePrivateChatAgentLoop(BaseAgentLoop):
    """1-on-1 私聊 Agent 循环的抽象基类。

    继承 ``BaseAgentLoop``，补充标准 OpenAI 格式历史、LLM 调用、工具执行、
    memory 和 custom_hooks 能力。

    子类必须实现以下工厂方法：
    - _get_llm_client() → LLMClient
    - _get_context() → Any
    - _get_tool_definitions() → list[dict]
    - _on_context_over_limit() → None
    - _build_system_prompt() → list[str]
    """

    def __init__(self, app: Application, session_id: str) -> None:
        super().__init__(app, session_id)
        self._history: History = History(messages=[])
        self._message_hooks_cache: list[dict] | None = None

    # -- 抽象方法 ---------------------------------------------------------

    @property
    @abstractmethod
    def current_character_agent(self) -> str:
        """返回当前 loop 对应的 agent 角色名，用于 History 视图过滤。"""
        ...

    @abstractmethod
    def _get_llm_client(self) -> Any:
        """返回当前 loop 的 LLMClient 实例。"""
        ...

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
            from component.approval_allowlist import is_allowed
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

        sink = self._get_sink()
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

    def _load_message_hooks(self) -> list[dict]:
        """加载 custom_hooks 目录中的消息扩展 hook，结果按 loop 实例缓存。"""
        if self._message_hooks_cache is not None:
            return self._message_hooks_cache
        hooks = load_message_hooks(find_repo_root(), logger)
        self._message_hooks_cache = hooks
        return hooks

    def _get_memory_context(self, user_message: str) -> str:
        """返回当前回合的 memory 上下文；子类可重写，默认空。"""
        _ = user_message  # 基类默认不使用，子类重写时消费
        return ""

    def _build_history_messages(
        self, user_message: str = ""
    ) -> tuple[list[dict[str, Any]], str]:
        """构建发送给 LLM 的完整历史消息列表（含 system prompt + hooks + memory）。

        返回 (messages, fixator_context)。fixator_context 由 hook_fixator 产生，
        调用方如需持久化到磁盘可据此判断。
        """
        system_prompts = self._build_system_prompt()
        memory_ctx = self._get_memory_context(user_message)
        hooks = self._load_message_hooks()
        workspace = (
            str(self.app.runtime_context.workspace)
            if self.app.runtime_context is not None
            else str(find_repo_root())
        )
        messages, fixator_context = build_turn_messages(
            system_prompts=system_prompts,
            history=self._history,
            current_character_agent=self.current_character_agent,
            session_id=self.session_id,
            workspace=workspace,
            memory_ctx=memory_ctx,
            hooks=hooks,
            runtime_ctx=self.app.runtime_context,
        )
        return messages, fixator_context