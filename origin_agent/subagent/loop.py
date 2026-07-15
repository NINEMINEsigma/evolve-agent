"""子 Agent 的 LLM 调用 + 工具执行循环。

参考 ``AgentLoop._process_message_locked`` 的结构，但适配子 Agent 的特化需求：
- 工具调用分类处理（readonly 立即执行，其他工具阻塞等审批）
- 独立 LLM 客户端（SubRuntimeContext）
- 收件箱/发件箱机制
"""

from __future__ import annotations

import asyncio
import json
import logging
import time as _time_module
from contextvars import ContextVar
from pathlib import Path
from typing import * # type: ignore

from abstract.tools.registry import ToolEntry, registry as tool_registry
from abstract.llm.client import BaseLLMClient
from abstract.llm.loader import create_llm_client
from entity.puretype import LLMResponse, ToolCall
from entity.constant import MAIN_AGENT_CHARACTER_NAME, USER_CHARACTER_NAME, History_Version as __History_Version__
from entity.messages import (
    History,
    CharacterConversationMessage,
    FunctionCall,
    ToolResultMessage,
    ToolCall as HistoryToolCall,
)
from entity.puretype import Role, ToolDangerLevel
from subagent.context import SubRuntimeContext
from entry.agent_sink import AgentSink, ParentAgentSink
from entry.base_agent_loop import BasePrivateChatAgentLoop, UserMessage, ContextLimitMessage, ToolContext
from entry.agent_support.multimodal import content_to_text, tool_result_to_content

logger = logging.getLogger(__name__)

# 由 SubAgentLoop 在每次工具执行前设置，供沙箱隔离（list_tools）及工具 handler 使用。
# 类型标注为 Any 以避免循环导入；实际类型为 subagent.loop.SubAgentLoop。
current_subagent_loop: ContextVar[Any] = ContextVar("current_subagent_loop")

# 分隔符 — 用于合并多条消息
SUB_MESSAGE_SEPARATOR = "[Sub Session Message]"


def format_user_message(user_name: str, message_type: str, content: str, co_recipients: list[str] | None = None) -> str:
    """包装进入子 Agent 的用户消息，明确标识真实发送者身份。"""
    from system.templates import read_template

    template_map = {
        "direct": "subagent/user_message_direct.txt",
        "overheard": "subagent/user_message_overheard.txt",
        "user_direct": "subagent/user_message_user_direct.txt",
    }
    template_name = template_map.get(message_type)
    if template_name is None:
        raise ValueError(f"Unknown message_type: {message_type}")

    template = read_template(template_name)
    co_str = (
        f"\n\n(This message is also shared with: {', '.join(co_recipients)}.)"
        if co_recipients else ""
    )
    return (
        template
        .replace("{{user_name}}", user_name)
        .replace("{{content}}", content)
        .replace("{{co_recipients_suffix}}", co_str)
    )


class PendingToolCall:
    """挂起的工具调用条目。"""

    def __init__(self, tool_call: ToolCall) -> None:
        self.tool_call_id: str = tool_call.id
        self.name: str = tool_call.name
        self.arguments: dict[str, Any] = dict(tool_call.arguments) if tool_call.arguments else {}
        self.result: asyncio.Future = asyncio.get_event_loop().create_future()


class SubAgentLoop(BasePrivateChatAgentLoop):
    """单个子 Agent 会话的 LLM 循环。

    继承 BasePrivateChatAgentLoop，实现子 Agent 特化的 LLM 客户端、收件箱和工具审批。
    每个子 Agent 在独立的 asyncio.Task 中运行 ``run()``。
    """

    def __init__(
        self,
        ctx: SubRuntimeContext,
        session_id: str,
        tools: list[dict[str, Any]],
        max_turns: int,
        # TODO: 真的可能为空吗
        on_message: Callable[[dict], None]|None = None, 
        parent_session_id: str = "",
        parent_character_agent: str = "",
        name: str = "",
    ) -> None:
        from system.application import Application
        app = Application.current()
        super().__init__(app, session_id)

        self._name: str = name                              # 子 Agent 注册名，用于历史保存路径
        self._ctx: SubRuntimeContext = ctx                   # 子 Agent 的独立运行时上下文（LLM 配置、system prompt）
        self._parent_session_id: str = parent_session_id     # 父 Agent 的 session ID，用于审批回源
        self._parent_character_agent: str = parent_character_agent  # 父 Agent 当前角色名，即子会话的"用户"
        self._tools: list[dict[str, Any]] = tools            # OpenAI function-calling 格式的工具 schema 列表

        # 当前子 Agent 被授权的工具名集合 — 用于运行时强制隔离
        self._allowed_tool_names: set[str] = {
            (t.get("function") or {}).get("name") or t.get("name", "")
            for t in tools
        }
        self._allowed_tool_names.discard("")

        self._llm: BaseLLMClient = self._build_llm_client(ctx)   # 子 Agent 独立的 LLM 客户端
        self._on_message: Callable[[dict], None] | None = on_message  # 每轮 LLM 响应/工具调用即时推送回调

        # 内部状态（_inbox / _cancel_event 由 BaseAgentLoop 提供；_history 由 BasePrivateChatAgentLoop 提供）
        self._outbox: list[str] = []                         # 发件箱：子 Agent 文本回复，父 Agent 通过 get_outbox() 收集
        self._pending_approvals: list[PendingToolCall] = []   # 等待父 Agent 审批的工具调用队列
        self._max_turns: int = max_turns                     # 最大工具调用轮次上限

        self._last_message_from_parent: bool = True          # 上一条消息是否来自父 Agent（用于决定是否入 outbox）

        # 控制事件
        self._paused_event: asyncio.Event = asyncio.Event()  # 暂停信号：设置后 run() 等待恢复
        self._paused_event.set()
        self._wake_event: asyncio.Event = asyncio.Event()    # 唤醒信号：新消息到达时触发
        self._wake_event.set()

        # 生命周期标记
        self._completed: bool = False                        # run() 正常结束（非中断/异常）
        self._terminated: bool = False                       # 被外部请求终止
        self._round_active: bool = True                      # 当前是否正在执行 LLM 推理或工具链

    # ── 构造 LLM 客户端 ────────────────────────────────────────────

    def _build_llm_client(self, ctx: SubRuntimeContext) -> BaseLLMClient:
        """用 SubRuntimeContext 构建独立的 LLM 客户端。

        优先使用子 Agent profile 中的 LLM 配置，缺失时兜底到父 Agent。
        """
        from system.context import get_runtime_context

        parent_ctx = get_runtime_context()
        return create_llm_client(
            ctx.client_type,
            parent_ctx,
            profile=ctx.model_dump(),
        )

    # ── 基类抽象方法实现 ─────────────────────────────────────────────

    @property
    def current_character_agent(self) -> str:
        return self._name

    @property
    def user_character_name(self) -> str:
        return self._parent_character_agent# or MAIN_AGENT_CHARACTER_NAME

    def _get_llm_client(self) -> BaseLLMClient:
        return self._llm

    def _get_session_info_llm_client(self) -> BaseLLMClient | None:
        return self._llm

    def _get_context(self) -> SubRuntimeContext:
        return self._ctx

    def get_sink(self) -> AgentSink:
        return ParentAgentSink(self)

    def _get_tool_definitions(self) -> list[dict[str, Any]]:
        return self._tools

    def _build_system_prompt(self) -> list[str]:
        return list(self._ctx.system_prompts)

    async def _on_context_over_limit(self) -> None:
        """子 Agent 上下文超限时通知父 Agent，不自动旋转。"""
        logger.warning("SubAgent context limit reached | session=%s", self.session_id)
        self._outbox.append("[system] Context limit reached. Sub-agent may lose context.")

    async def append_user_message(self, content: Any, *, display_content: Any | None = None, **kwargs: Any) -> int:
        """把用户消息加入子 Agent 历史并返回索引。"""
        msg = CharacterConversationMessage(
            role=Role.USER,
            character_name=USER_CHARACTER_NAME,
            content=content if isinstance(content, str) else str(content),
        )
        return self._history.add_message(msg)

    async def process_message(
        self,
        user_message: str,
        *,
        skip_append: bool = False,
        character_name: str = USER_CHARACTER_NAME,
        **kwargs
    ) -> str:
        """子 Agent 不通过此路径接收消息；使用 inject_parent_message() + run() 替代。"""
        raise NotImplementedError(
            "SubAgentLoop does not support process_message(). "
            "Use inject_parent_message() + run() instead."
        )

    # ── 公共接口 ─────────────────────────────────────────────────────

    @property
    def parent_session_id(self) -> str:
        """返回父 Agent 的 session ID。"""
        return self._parent_session_id

    def get_outbox(self) -> list[str]:
        """返回并清空当前发件箱内容。"""
        outbox = list(self._outbox)
        self._outbox.clear()
        return outbox

    def set_paused(self) -> None:
        """暂停子 Agent 循环，等待外部审批决策。"""
        self._paused_event.clear()

    def clear_paused(self) -> None:
        """恢复子 Agent 循环。"""
        self._paused_event.set()

    def add_pending_approval(self, pending: PendingToolCall) -> None:
        """将挂起的工具调用加入审批队列并暂停循环。"""
        self._pending_approvals.append(pending)
        self.set_paused()

    def emit_event(self, role: str, **fields: Any) -> None:
        """向前端推送一条结构化事件（公共接口）。"""
        self._emit(role, **fields)

    def _emit(self, role: str, **fields: Any) -> None:
        """向前端推送一条结构化事件。

        ``role`` 取值：``user`` / ``assistant`` / ``reasoning`` / ``tool_call`` /
        ``tool_result`` / ``status`` / ``approval_pending`` / ``approval_decision``。
        其余字段（``content``/``tool_name``/``tool_call_id``/``tool_args``/``reasoning``）
        按需透传。
        """
        if not self._on_message:
            return
        try:
            payload: dict[str, Any] = {"role": role}
            payload.update({k: v for k, v in fields.items() if v is not None})
            self._on_message(payload)
        except Exception:
            logger.warning("Failed to emit subagent event role=%s", role, exc_info=True)

    def _is_readonly_tool(self, name: str) -> bool:
        entry = tool_registry.get_entry(name)
        if entry is None:
            return False
        return entry.danger_level == ToolDangerLevel.readonly

    def _is_auto_approved_tool(self, name: str, args: dict) -> bool:
        """检查工具调用是否在 allowlist 中（始终自动批准）。"""
        try:
            from component.approval.allowlist import is_allowed
            return is_allowed(name, args)
        except Exception:
            logger.warning("Failed to check approval allowlist for subagent tool=%s", name, exc_info=True)
            return False

    async def run(self, initial_prompt: str, user_name: str, message_type: str) -> None:
        """子 Agent 主循环。"""
        # 注册到 CronRouter，使 cron 结果能投递到 inbox
        from system.application import Application
        _cron = Application.current().cron_router
        if _cron is not None:
            _cron.register(self.session_id, self)
        try:
            # 注入初始用户消息（system prompt 由 _build_history_messages 通过 _build_system_prompt 处理）
            initial_character_name = USER_CHARACTER_NAME if message_type == "user_direct" else (self._parent_character_agent or MAIN_AGENT_CHARACTER_NAME)
            self._history.add_message(
                CharacterConversationMessage(
                    role=Role.USER,
                    character_name=initial_character_name,
                    content=format_user_message(user_name, message_type, initial_prompt),
                    visible_characters=[self.current_character_agent],
                )
            )

            turn: int = 0
            while turn < self._max_turns:
                if self._cancel_event.is_set():
                    return
                turn += 1
                self._round_active = True  # 新一轮响应开始

                # 调用 LLM（基类 _build_history_messages 统一处理 system prompt + hooks + memory）
                messages = self._build_history_messages()
                resp: LLMResponse = await self._llm.chat(messages, self._tools, character=self.current_character_agent)

                if self._cancel_event.is_set():
                    return

                reasoning_text = resp.reasoning_content

                if not resp.tool_calls:
                    # 文本回复 — 推入发件箱并发给前端
                    text = resp.content or ""
                    assistant_msg = CharacterConversationMessage(
                        role=Role.ASSISTANT,
                        character_name=self.current_character_agent,
                        content=text,
                        reasoning=reasoning_text,
                        reasoning_field_name=resp.reasoning_field_name,
                    )
                    self._history.add_message(assistant_msg)
                    if self._last_message_from_parent:
                        self._outbox.append(text)
                    self._emit("assistant", content=text, reasoning=reasoning_text,
                               character_name=self.current_character_agent)
                    # LLM 给出纯文本即视作本轮对话结束，等待父 Agent 消息或取消
                    self._round_active = False
                    self._wake_event.clear()
                    await self._wake_event.wait()
                    self._maybe_inject_inbox()
                    continue

                # 推送 assistant 文本（若与 tool_calls 同帧）
                if resp.content:
                    self._emit("assistant", content=resp.content, reasoning=reasoning_text,
                               character_name=self.current_character_agent)

                # 存储带 tool_calls 的 assistant 消息
                tool_calls_data: list[HistoryToolCall] = [
                    HistoryToolCall(
                        id=tc.id,
                        type="function",
                        function=FunctionCall(
                            name=tc.name,
                            arguments=json.dumps(tc.arguments, ensure_ascii=False),
                        ),
                    )
                    for tc in resp.tool_calls
                ]
                assistant_msg = CharacterConversationMessage(
                    role=Role.ASSISTANT,
                    character_name=self.current_character_agent,
                    content=resp.content or "",
                    tool_calls=tool_calls_data,
                    reasoning=reasoning_text,
                    reasoning_field_name=resp.reasoning_field_name,
                )
                self._history.add_message(assistant_msg)

                # 处理工具调用 — readonly 直接执行；其它工具入审批队列阻塞等待
                for tc in resp.tool_calls:
                    if self._cancel_event.is_set():
                        return

                    # 推送 tool_call 事件
                    self._emit(
                        "tool_call",
                        tool_call_id=tc.id,
                        tool_name=tc.name,
                        tool_args=dict(tc.arguments) if tc.arguments else {},
                    )

                    if self._is_readonly_tool(tc.name) or self._is_auto_approved_tool(tc.name, dict(tc.arguments) if tc.arguments else {}):
                        tool_msg = await self._execute_approved_tool(tc)
                    else:
                        tool_msg = await self._queue_for_approval(tc)

                    # 推送 tool_result 事件
                    raw_content = content_to_text(tool_msg.content)
                    self._emit(
                        "tool_result",
                        tool_call_id=tc.id,
                        tool_name=tc.name,
                        content=raw_content,
                    )

                    # 检测工具失败并放入 outbox，让父 Agent 知道（防止默认成功假设）
                    self._maybe_record_tool_failure(tc.name, raw_content)

                    messages.append(tool_msg)
                    self._history.add_message(tool_msg)

                # 工具结果已收集，本轮响应结束；注入收件箱（若有）后立刻进入下一轮 LLM 推理
                self._round_active = False
                self._maybe_inject_inbox()

        except Exception as exc:
            logger.exception("SubAgentLoop error for session=%s: %s", self.session_id, exc)
        finally:
            if _cron is not None:
                _cron.unregister(self.session_id)
            self._terminated = True

    def inject_parent_message(
        self,
        text: str,
        user_name: str,
        message_type: str,
        co_recipients: list[str] | None = None,
        *,
        character_name: str | None = None,
    ) -> None:
        """父 Agent 或用户直接发送来的消息，投递到收件箱。"""
        self._last_message_from_parent = (message_type != "user_direct")
        content = format_user_message(user_name, message_type, text, co_recipients)
        if character_name is None:
            character_name = USER_CHARACTER_NAME if message_type == "user_direct" else MAIN_AGENT_CHARACTER_NAME
        self._inbox.put(UserMessage(content=content, character_name=character_name))
        self._wake_event.set()

    def approve_tools(self, decisions: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """父 Agent 审批结果，触发工具执行并解除阻塞。

        Returns:
            审批处理结果列表，每项包含 tool_call_id, approved, error（如有）。
        """
        results: list[dict[str, Any]] = []
        decision_map: dict[str, dict[str, Any]] = {
            d["tool_call_id"]: d for d in decisions
        }

        for pending in self._pending_approvals:
            decision = decision_map.get(pending.tool_call_id)
            if decision is None:
                # 未匹配 — 跳过（可能已被其他决策处理）
                continue

            if decision["approved"]:
                # 同意：设置 Future 结果
                if not pending.result.done():
                    pending.result.set_result({"approved": True})
                results.append({"tool_call_id": pending.tool_call_id, "approved": True})
            else:
                # 拒绝：设置 Future 异常
                reason = decision.get("reason", "Rejected by parent agent.")
                if not pending.result.done():
                    pending.result.set_exception(RuntimeError(reason))
                results.append({
                    "tool_call_id": pending.tool_call_id,
                    "approved": False,
                    "reason": reason,
                })

        # 清空待审批队列
        self._pending_approvals.clear()

        # 解除阻塞
        self._paused_event.set()

        return results

    def stop(self) -> None:
        """强制终止子 Agent。"""
        self._cancel_event.set()

    def load_history(self, history: History) -> None:
        """加载外部历史到子 Agent 循环中。"""
        self._history = history

    def save_history(self, path: Path) -> None:
        """将 History 实例以 easysave 多态序列化写入磁盘。"""
        from easysave import save
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            save(__History_Version__, str(path), self._history)
        except Exception as exc:
            logger.exception("Failed to save subagent history to %s: %s", path, exc)
            raise

    @property
    def completed(self) -> bool:
        return self._completed

    @property
    def terminated(self) -> bool:
        return self._terminated

    @property
    def round_active(self) -> bool:
        return self._round_active

    @property
    def outbox(self) -> list[str]:
        return list(self._outbox)

    @property
    def pending_approvals_info(self) -> list[dict[str, Any]]:
        return [
            {
                "tool_call_id": p.tool_call_id,
                "tool_name": p.name,
                "arguments": p.arguments,
            }
            for p in self._pending_approvals
        ]

    # ── 内部方法 ─────────────────────────────────────────────────────

    def _maybe_inject_inbox(self) -> bool:
        """若有收件箱消息，注入到历史。"""
        msgs = self._inbox.get_pending()
        if not msgs:
            return False
        for pending_message in msgs:
            self._history.add_message(
                CharacterConversationMessage(
                    role=Role.USER,
                    character_name=pending_message.character_name,
                    content=pending_message.to_text(),
                    visible_characters=[self.current_character_agent],
                )
            )
        return True

    async def _queue_for_approval(self, tc: ToolCall) -> ToolResultMessage:
        """将工具调用加入待审批队列并阻塞等待结果。

        子 Agent 进入暂停状态，直到父 Agent 通过 approve_tools() 审批。
        """
        from component.approval import is_handsfree_mode, request_user_confirm

        if is_handsfree_mode(self._parent_session_id):
            result = await request_user_confirm(
                session_id=self._parent_session_id,
                tool_name=tc.name,
                args=dict(tc.arguments) if tc.arguments else {},
                reason="Sub-agent initiated tool call",
                content=f"Sub-agent {tc.name} tool call",
                ask_agent_callback=None,
            )
            if result.action in ("allow_once", "allow_always"):
                self._emit(
                    "approval_decision",
                    tool_call_id=tc.id,
                    tool_name=tc.name,
                    content="approved",
                )
                return await self._execute_approved_tool(tc)
            self._emit(
                "approval_decision",
                tool_call_id=tc.id,
                tool_name=tc.name,
                content=f"rejected: {result.deny_reason}",
            )
            return self._make_tool_msg(tc.id, f"Tool call denied: {result.deny_reason}")

        pending = PendingToolCall(tc)
        self._pending_approvals.append(pending)

        # 暂停
        self._paused_event.clear()

        # 推送 pending 事件到前端
        self._emit(
            "approval_pending",
            tool_call_id=tc.id,
            tool_name=tc.name,
            tool_args=dict(tc.arguments) if tc.arguments else {},
        )

        try:
            result = await pending.result  # 永不超时，阻塞等待
            if result["approved"]:
                self._emit(
                    "approval_decision",
                    tool_call_id=tc.id,
                    tool_name=tc.name,
                    content="approved",
                )
                return await self._execute_approved_tool(tc)
            else:
                # TODO: 似乎拒绝分支输出错误内容
                self._emit(
                    "approval_decision",
                    tool_call_id=tc.id,
                    tool_name=tc.name,
                    content="approved",
                )
                return self._make_tool_msg(
                    tc.id,
                    json.dumps({"approved": True, "result": result}),
                )
        except RuntimeError as exc:
            self._emit(
                "approval_decision",
                tool_call_id=tc.id,
                tool_name=tc.name,
                content=f"rejected: {exc}",
            )
            return self._make_tool_msg(tc.id, f"Tool call rejected: {exc}")

    async def _execute_approved_tool(self, tc: ToolCall) -> ToolResultMessage:
        """执行已获批准的工具调用。"""
        # 沙箱隔离：拒绝授权清单之外的工具
        if tc.name not in self._allowed_tool_names:
            return self._make_tool_msg(
                tc.id,
                {
                    "success": False,
                    "error": (
                        f"Tool '{tc.name}' is not authorized for this sub-agent. "
                        f"Allowed tools: {sorted(self._allowed_tool_names)}"
                    ),
                },
            )
        timeout: int = self._ctx.tool_timeout
        try:
            if tool_registry.get_entry(tc.name) is None:
                return self._make_tool_msg(tc.id, f"Tool '{tc.name}' not found in registry")

            args: dict[str, Any] = dict(tc.arguments) if tc.arguments else {}
            args["_session_id"] = self.session_id

            current_subagent_loop.set(self)
            entry = tool_registry.get_entry(tc.name)
            if entry and entry.no_timeout:
                timeout = 0

            # 通过 registry.async_dispatch 执行，正确传递 ToolContext
            tool_ctx = ToolContext(loop=self, session_id=self.session_id)
            coro = tool_registry.async_dispatch(tc.name, args, context=tool_ctx)

            if timeout:
                result = await asyncio.wait_for(coro, timeout=timeout)
            else:
                result = await coro

            return self._make_tool_msg(tc.id, tool_result_to_content(result))
        except asyncio.TimeoutError:
            return self._make_tool_msg(
                tc.id,
                {"success": False, "error": f"Tool execution timed out ({timeout}s)"},
            )
        except Exception as exc:
            return self._make_tool_msg(
                tc.id,
                {"success": False, "error": f"Tool execution failed: {exc}"},
            )
        finally:
            current_subagent_loop.set(None)

    @property
    def allowed_tool_names(self) -> set[str]:
        return set(self._allowed_tool_names)

    def _maybe_record_tool_failure(self, tool_name: str, content: str) -> None:
        """检测工具失败并写入 outbox，让父 Agent 在下一次 [subagent-result] 中收到。

        工具结果约定为 JSON ``{"success": bool, ...}``；当 ``success`` 为 false
        或包含明显错误标记时记录为失败。普通文本/异常字符串也按失败处理。
        """
        snippet = content.strip()
        if not snippet:
            return
        is_failure: bool = False
        summary: str = snippet
        try:
            parsed = json.loads(snippet)
            if isinstance(parsed, dict):
                if parsed.get("success") is False:
                    is_failure = True
                    summary = str(
                        parsed.get("error")
                        or parsed.get("message")
                        or parsed
                    )
                elif "error" in parsed and parsed.get("success") is None:
                    is_failure = True
                    summary = str(parsed.get("error"))
        except json.JSONDecodeError:
            lowered = snippet.lower()
            if (
                lowered.startswith("tool execution failed")
                or lowered.startswith("tool call rejected")
                or "traceback" in lowered
            ):
                is_failure = True
                summary = snippet

        if not is_failure:
            return
        max_len = 30000
        if len(summary) > max_len:
            summary = summary[:max_len] + "...(truncated)"
        self._outbox.append(
            f"[tool-failure] {tool_name}: {summary}"
        )

    def _make_tool_msg(self, tool_call_id: str, content: Any) -> ToolResultMessage:
        return ToolResultMessage.from_result(
            tool_call_id=tool_call_id,
            character_name=self.current_character_agent,
            result=content,
        )

