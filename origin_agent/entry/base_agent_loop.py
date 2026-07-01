"""BaseAgentLoop 抽象基类 + Inbox/InboxMessage 消息队列。

所有 Agent 循环（ParentAgentLoop、SubAgentLoop）继承此基类。
提供统一的 LLM-工具循环、收件箱机制和生命周期管理。
"""

from __future__ import annotations

import asyncio
import json
import logging
from abc import ABC, abstractmethod
from typing import Any, TYPE_CHECKING

from pydantic import BaseModel

from entity.puretype import Role, ToolDangerLevel

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

    def to_text(self) -> str:
        """转换为注入 LLM 历史的文本。子类按需重写。"""
        return self.content


class UserMessage(InboxMessage):
    """来自用户/父Agent的文本消息。"""


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
        return self.loop._get_sink()

    @property
    def is_interrupted(self) -> bool:
        return self.loop._cancel_event.is_set()


# ---------------------------------------------------------------------------
# BaseAgentLoop — 抽象基类
# ---------------------------------------------------------------------------

class BaseAgentLoop(ABC):
    """Agent 循环抽象基类。

    子类必须实现以下工厂方法：
    - _get_llm_client() → LLMClient
    - _get_context() → Any
    - _get_sink() → AgentSink
    - _get_tool_definitions() → list[dict]
    - _on_context_over_limit() → None
    - _build_system_prompt() → list[str]
    """

    def __init__(self, app: Application, session_id: str) -> None:
        self.session_id: str = session_id
        self.app: Application = app
        self._history: list[dict[str, Any]] = []
        self._inbox: Inbox = Inbox()
        self._cancel_event: asyncio.Event = asyncio.Event()
        self._hooks_context: str | None = None

    @property
    def inbox(self) -> Inbox:
        """公开的收件箱访问器，供 CronRouter 等外部组件投递消息。"""
        return self._inbox

    # -- 抽象方法 ---------------------------------------------------------

    @abstractmethod
    def _get_llm_client(self) -> Any:
        """返回当前 loop 的 LLMClient 实例。"""
        ...

    @abstractmethod
    def _get_context(self) -> Any:
        """返回当前 loop 的 RuntimeContext 或 SubRuntimeContext。"""
        ...

    @abstractmethod
    def _get_sink(self) -> AgentSink:
        """返回当前 loop 的 AgentSink 实例。"""
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
                            session_id: str = "") -> dict:
        """执行单个工具调用，处理只读/审批分流。

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
                return {
                    "role": Role.TOOL,
                    "tool_call_id": tool_call_id,
                    "content": f"Tool execution denied: {approval.deny_reason or 'User rejected'}",
                }

        # 执行工具
        from abstract.tools.registry import registry
        from entry.base_agent_loop import ToolContext
        ctx = ToolContext(loop=self, session_id=self.session_id)
        result = await registry.async_dispatch(tool_name, args, context=ctx)
        if isinstance(result, dict) and "error" in result:
            content = json.dumps(result, ensure_ascii=False)
        else:
            content = json.dumps(result, ensure_ascii=False) if not isinstance(result, str) else result

        # 对前端 UI 类工具推送实时状态更新（工具模块自行注册事件类型）
        from abstract.tools.ui_event_router import ui_event_router
        await ui_event_router.emit_for(
            tool_name,
            result,
            sink,
            session_id or self.session_id,
        )

        return {
            "role": Role.TOOL,
            "tool_call_id": tool_call_id,
            "name": tool_name,
            "content": content,
        }

    # -- 收件箱处理 -------------------------------------------------------

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

    # -- 历史管理 ---------------------------------------------------------

    def _get_history(self) -> list[dict[str, Any]]:
        return self._history

    def _append_history(self, entry: dict[str, Any]) -> None:
        self._history.append(entry)

    def _build_history_messages(self) -> list[dict[str, Any]]:
        """构建发送给 LLM 的完整历史消息列表（含 system prompt + hooks）。

        子类可重写以添加 memory 上下文等。
        """
        messages: list[dict[str, Any]] = []
        for sp in self._build_system_prompt():
            messages.append({"role": Role.SYSTEM, "content": sp})
        # 将 hooks 上下文拼接到最后一条 user 消息
        history = list(self._history)
        if self._hooks_context and history:
            last_user_idx = None
            for i in range(len(history) - 1, -1, -1):
                if history[i].get("role") == Role.USER:
                    last_user_idx = i
                    break
            if last_user_idx is not None:
                old_content = history[last_user_idx].get("content", "")
                history[last_user_idx] = {
                    **history[last_user_idx],
                    "content": (old_content if isinstance(old_content, str) else str(old_content)) + "\n\n" + self._hooks_context,
                }
        messages.extend(history)
        return messages