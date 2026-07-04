"""ParentAgentLoop — 主 Agent 循环，继承 BasePrivateChatAgentLoop。

实现流式 LLM 调用、Memory 管理、session 旋转/归档、
工具审批流程和前端事件推送。每个 session 对应一个实例。
"""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, TYPE_CHECKING

from abstract.memory.manager import MemoryManager
from abstract.tools.registry import ToolEntry, registry as tool_registry
from component.approval import ApprovalResult, ask_agent_reason, is_handsfree_mode, request_user_confirm
from component.approval_allowlist import add_allowed as add_tool_allowlist_entry
from component.approval_allowlist import is_allowed as is_tool_allowlisted
from component.llm import LLMClient, LLMResponse, StreamChunk, ToolCall, Usage
from system.session_store import SessionStore
from entity.constant import (
    LOG_PREVIEW_CHARS,
    TOOL_RESULT_PREVIEW_CHARS,
    TOOL_RESULT_SAVE_THRESHOLD_CHARS,
    AUTO_TITLE_CONTENT_MAX,
    MAX_TOOL_TURNS,
    MAIN_AGENT_CHARACTER_NAME,
    USER_CHARACTER_NAME,
)
from entity.messages import History, CharacterConversationMessage, FunctionCall, ImageBlock, TextBlock, ToolResultMessage, ToolCall as HistoryToolCall
from entity.puretype import Role, ToolAvailability, ToolDangerLevel
from entry.base_agent_loop import BasePrivateChatAgentLoop, ToolContext
from entry.agent_sink import AgentSink, FrontendSink
from entry.agent_support.messages import (
    build_agent_system_prompt,
    build_full_history_messages,
    collect_hooks_context,
)
from entry.agent_support.multimodal import (
    build_image_content_blocks,
    content_to_text,
    is_content_block_error,
    sanitize_image_payload,
    strip_image_blocks,
    summarize_message_for_log,
    supports_vision,
    tool_result_to_content,
)


class IncompatibleHistoryError(Exception):
    """会话历史格式不兼容，无法加载。"""
    def __init__(self, session_id: str) -> None:
        self.session_id = session_id
        super().__init__(f"Session {session_id} history format is incompatible")

if TYPE_CHECKING:
    from gateway.session_manager import SessionManager
    from system.application import Application
    from system.context import RuntimeContext

logger = logging.getLogger(__name__)

# 每条消息的最大工具调用循环次数
_MAX_TOOL_TURNS: int = MAX_TOOL_TURNS


async def _close_async_iterator(ait: Any) -> None:
    """安全关闭异步迭代器，避免未读取完成的流留下资源泄漏。"""
    try:
        await ait.aclose()
    except Exception:
        # 迭代器已关闭或不可关闭；清理阶段失败不应中断主流程
        logger.debug("Failed to close async iterator", exc_info=True)


class ParentAgentLoop(BasePrivateChatAgentLoop):
    """主 Agent 循环 — 每个 WebSocket session 一个实例。

    继承 BasePrivateChatAgentLoop，实现：
    - 流式 LLM（通过 LLMClient.chat_stream）
    - Memory 预取与同步
    - 上下文超限时的 session 旋转/归档
    - 工具审批流程（readonly/allowlist/handsfree）
    - 前端事件推送（通过 FrontendSink）
    """

    def __init__(
        self,
        app: Application,
        session_id: str,
        frontend_sink: FrontendSink,
        history_store_dir: Path | None = None,
    ) -> None:
        super().__init__(app, session_id)
        self._frontend_sink: FrontendSink = frontend_sink
        self._llm: LLMClient = LLMClient(app.runtime_context)
        self._memory: MemoryManager = MemoryManager()
        # 记录已成功初始化的 memory provider 的对象 id。
        # 使用集合而非全局布尔值，避免某个 provider 初始化失败后
        # 被永久跳过；成功的 provider 不会重复初始化。
        self._memory_initialized_ids: set[int] = set()

        # -- 工具调用事件回调（供 FrontendSink 推送） --
        self._tool_event_callback: Callable[[str, str, str, str], Awaitable[None]] | None = None

        # -- session 旋转通知 --
        self._session_rotated_notify: dict[str, str] = {}  # old_sid → new_sid

        # -- token 使用追踪 --
        self._token_usage: int = 0
        self._last_prompt_tokens: int = 0

        # -- 工具调用统计 --
        self._tool_stats: dict[str, dict[str, int]] = {}

        # -- 处理状态（process_message 运行时设为 True） --
        self._processing: bool = False

        # -- inbox 处理并发锁和事件循环引用 --
        self._process_lock: asyncio.Lock = asyncio.Lock()
        self._event_loop: asyncio.AbstractEventLoop | None = None

        # -- 取消与中断 --
        self._interrupted: bool = False

        # -- 子 Agent 周期收集器用的空闲时间戳（按 session_id 索引） --
        self._last_idle_time: dict[str, float] = {session_id: time.monotonic()}

        # -- 磁盘持久化 --
        self._history_store_dir: Path | None = history_store_dir
        self._session_store: SessionStore | None = (
            SessionStore(history_store_dir) if history_store_dir else None
        )

        # 从磁盘加载已有历史（resume / 重新连接场景）
        if self._session_store is not None:
            try:
                disk_history = self._session_store.read_history(self.session_id)
                if disk_history:
                    self._history = disk_history
            except Exception as exc:
                logger.warning(
                    "Session %s history incompatible or corrupt: %s",
                    self.session_id, exc,
                )
                raise IncompatibleHistoryError(self.session_id) from exc

        # -- SubAgentOrchestrator（由 server 层注入） --
        self.subagent_orchestrator: Any = None

        # -- session manager 引用（由 server 层注入，用于旋转/归档） --
        self._session_manager: SessionManager | None = None

    # ========================================================================
    # 抽象方法实现
    # ========================================================================

    @property
    def current_character_agent(self) -> str:
        return MAIN_AGENT_CHARACTER_NAME

    @property
    def user_character_name(self) -> str:
        return USER_CHARACTER_NAME

    def _get_llm_client(self) -> LLMClient:
        return self._llm

    def _get_context(self) -> RuntimeContext:
        return self.app.runtime_context

    def _get_sink(self) -> AgentSink:
        return self._frontend_sink

    def _get_tool_definitions(self) -> list[dict]:
        """返回主 Agent 可用的工具 schema（availability 包含 MAIN 或 EVERY + memory 工具）。"""
        definitions: list[dict] = tool_registry.get_definitions_for_availability(
            scope=ToolAvailability.MAIN,
        )
        # 合并 memory 工具 schema
        for schema in self._memory.get_tool_schemas():
            definitions.append({"type": "function", "function": schema})
        return definitions if definitions else []

    async def _on_context_over_limit(self) -> None:
        """上下文超限：触发 session 旋转/归档。"""
        old_sid = self.session_id
        new_sid: str | None = await self._rotate_session_for_continuation(
            self.session_id,
        )
        if new_sid:
            self.session_id = new_sid
            if self._session_manager is not None:
                self._session_manager.rotate_session(old_sid, new_sid)

    def _build_system_prompt(self) -> list[str]:
        """构建系统提示词段落列表（含 skill prompts）。"""
        return build_agent_system_prompt(
            self.app.runtime_context,
            self._collect_skill_prompts(),
        )

    # ========================================================================
    # 公共 API
    # ========================================================================

    def set_tool_event_callback(
        self, cb: Callable[[str, str, str, str], Awaitable[None]]
    ) -> None:
        """注册工具执行事件的异步回调。"""
        self._tool_event_callback = cb

    def set_session_manager(self, manager: Any) -> None:
        """注入 SessionManager 引用。"""
        self._session_manager = manager

    def add_memory_provider(self, provider: Any) -> None:
        self._memory.add_provider(provider)

    def pop_session_rotated(self) -> str | None:
        """取出并移除旋转通知（old_sid → new_sid）。"""
        return self._session_rotated_notify.pop(self.session_id, None)

    def get_token_usage(self) -> int:
        if self._token_usage:
            return self._token_usage
        disk_usage: int = self._load_token_usage_from_disk()
        if disk_usage:
            self._token_usage = disk_usage
        return disk_usage

    def get_context_tokens(self) -> int:
        return self._last_prompt_tokens

    def get_all_tool_stats(self) -> dict[str, dict[str, int]]:
        return {name: dict(stats) for name, stats in self._tool_stats.items()}

    def interrupt(self) -> None:
        """请求停止当前循环。"""
        super().interrupt()
        self._interrupted = True

    # ========================================================================
    # process_message — 主入口
    # ========================================================================

    async def process_message(
        self,
        user_message: str, # | list[dict[str, Any]],
        *,
        skip_append: bool = False,
        character_name: str = USER_CHARACTER_NAME,
    ) -> str:
        """处理一条用户消息，返回助手的回复。

        Args:
            user_message: 用户消息内容。
            skip_append: 为 True 时不追加/广播用户消息（调用方已处理），
                         用于 gateway 在发送给子 agent 前已经自定义过显示内容的情况。
            character_name: 该用户消息的发出者角色名；默认 end-user，
                            子 Agent 反馈回收时传入对应子 Agent 名。
        """
        sid = self.session_id
        self._interrupted = False
        self._processing = True

        self._event_loop = asyncio.get_running_loop()

        logger.info(
            "Received user message | session=%s content=%s",
            sid, summarize_message_for_log(user_message),
        )
        async with self._process_lock:
            # 先消费 inbox 遗留消息（如上回合未被消费的 cron 结果），再追加用户消息
            self._maybe_inject_inbox()
            if not skip_append:
                await self.append_user_message(user_message, character_name=character_name)

            # 延迟初始化 memory provider：按 provider 跟踪成功状态，
            # 失败者在后续消息处理时重试，避免一次失败导致永久跳过。
            for provider in self._memory.providers:
                if id(provider) in self._memory_initialized_ids:
                    continue
                try:
                    provider.initialize(sid)
                    self._memory_initialized_ids.add(id(provider))
                except Exception:
                    logger.exception("Failed to initialize memory provider for session=%s", sid)

            # 历史过长时自动终结会话
            if self._is_context_over_limit():
                new_sid: str | None = await self._rotate_session_for_continuation(
                    sid,
                    pending_user_message=user_message,
                )
                if new_sid:
                    sid = new_sid
                    self.session_id = new_sid

            # 构建消息列表（hook / memory / fixator 由基类统一处理）
            messages, fixator_context = self._build_history_messages(user_message)
            if fixator_context:
                # 将 fixator_context 持久化为 message_suffix，然后重新构建消息，
                # 避免 build_turn_messages 重复追加同一 suffix。
                self._update_last_user_message(sid, fixator_context)
                messages, _ = self._build_history_messages(user_message)

            try:
                return await self._run_tool_loop(sid, messages, user_message)
            finally:
                self._processing = False
                self._last_idle_time[self.session_id] = time.monotonic()

    async def _run_tool_loop(
        self,
        sid: str,
        messages: list[dict[str, Any]],
        user_message: str, # | list[dict[str, Any]],
    ) -> str:
        """执行 LLM 工具调用循环（含 inbox 消息消费）。"""
        self._cancel_event.clear()

        turn: int = 0
        try:
            while turn < _MAX_TOOL_TURNS:
                if self._cancel_event.is_set():
                    return "Cancelled."
                turn += 1

                # 在每次 LLM 调用前消费 inbox（如同时到达的 cron 结果）
                self._maybe_inject_inbox(messages)

                stream_id: str = uuid.uuid4().hex[:12]
                try:
                    resp = await self._stream_llm_response(
                        sid, messages,
                        self._get_tool_definitions(),
                        stream_id,
                    )
                except Exception as llm_exc:
                    if is_content_block_error(llm_exc):
                        stripped: int = strip_image_blocks(messages, sid)
                        if stripped > 0:
                            logger.warning(
                                "LLM rejected image content blocks — retrying with text-only "
                                "(stripped %d image(s) from session=%s)",
                                stripped, sid,
                            )
                            continue
                    logger.exception("LLM call failed for session=%s", sid)
                    self._remove_last_user_message(sid)
                    return f"The service provider returned an error, please try again later. Details: {llm_exc}"

                if self._cancel_event.is_set():
                    await self._emit_stream_done(sid, stream_id, "cancelled")
                    if resp.content:
                        self._append(sid, Role.ASSISTANT, resp.content,
                                     reasoning_content=resp.reasoning_content)
                        return resp.content
                    return "Cancelled."

                if resp.usage.prompt_tokens:
                    self._last_prompt_tokens = resp.usage.prompt_tokens
                self._push_usage_update(sid)

                if resp.tool_calls:
                    tool_names = ", ".join(tc.name for tc in resp.tool_calls)
                    logger.info(
                        "Agent response | session=%s tools=[%s] content=%s",
                        sid, tool_names,
                        (resp.content[:LOG_PREVIEW_CHARS] + "...") if len(resp.content or "") > LOG_PREVIEW_CHARS else (resp.content or ""),
                    )
                else:
                    logger.info(
                        "Agent response | session=%s content=%s",
                        sid,
                        (resp.content[:LOG_PREVIEW_CHARS] + "...") if len(resp.content or "") > LOG_PREVIEW_CHARS else (resp.content or ""),
                    )

                await self._emit_stream_done(sid, stream_id, resp.finish_reason)

                if not resp.tool_calls:
                    assistant_text = resp.content or ""
                    self._append(sid, Role.ASSISTANT, assistant_text,
                                 reasoning_content=resp.reasoning_content)
                    self._memory.sync_all(
                        self._history, session_id=sid,
                    )
                    return assistant_text

                # 存储 assistant 消息（含 tool_calls）
                self._store_assistant_with_tools(sid, resp)

                # 执行工具调用
                for tc in resp.tool_calls:
                    tool_msg = await self._do_execute_tool(tc, sid)
                    openai_tool_msg = tool_msg.as_message(self.current_character_agent)
                    if openai_tool_msg is not None:
                        messages.append(openai_tool_msg)
                    self._history.add_message(tool_msg)
                    self._persist_message(sid)
                    self._push_usage_update(sid)

                    # TODO: 缺乏注释
                    if tc.name == "evolve_code":
                        try:
                            content_text = content_to_text(tool_msg.content)
                            parsed: Any = json.loads(content_text)
                            if parsed.get("evolved"):
                                self._append(sid, Role.ASSISTANT, "Evolution complete, restarting to apply new code...")
                                return "Evolution complete, restarting to apply new code..."
                        except (json.JSONDecodeError, KeyError, TypeError):
                            pass

                if self._is_context_over_limit():
                    new_sid = await self._rotate_session_for_continuation(sid)
                    if new_sid:
                        sid = new_sid
                        self.session_id = new_sid

                messages = self._get_full_history(sid)

        finally:
            pass  # _processing 由 process_message/process_inbox 的 finally 管理

        logger.warning(
            "Tool-call loop exceeded max turns (%d) for session=%s",
            _MAX_TOOL_TURNS, sid,
        )
        return "I ran into an issue processing your request. Please try again."

    # ========================================================================
    # Inbox 消息消费
    # ========================================================================

    def _maybe_inject_inbox(self, target_messages: list[dict[str, Any]] | None = None) -> bool:
        """消费 inbox 中的待处理消息，注入到 _history（和可选的 target_messages）。

        返回 True 表示有新消息注入，False 表示 inbox 为空。
        格式与 subagent/loop.py 一致：多条消息用 \n\n 连接为一条 role=user 消息。
        """
        pending = self._inbox.get_pending()
        if not pending:
            return False
        merged = "\n\n".join(msg.to_text() for msg in pending)
        # TODO: 下方注释有待考虑, 或者不再合并直接多条usermessage插回历史
        # 所有 InboxMessage 子类都已自带 character_name，直接取首条作为合并后的发出者
        character_name = pending[0].character_name if len(pending) == 1 else USER_CHARACTER_NAME
        message = CharacterConversationMessage.from_text(
            role=Role.USER,
            character_name=character_name,
            text=merged,
            visible_characters=[self.current_character_agent],
        )
        self._history.add_message(message)
        self._persist_message(self.session_id)
        if target_messages is not None:
            openai_msg = message.as_message(self.current_character_agent)
            if openai_msg is not None:
                target_messages.append(openai_msg)
        return True

    async def process_inbox(self) -> str | None:
        """消费 inbox 消息并触发一轮 LLM 工具循环，返回 assistant 文本。

        由后台线程通过 schedule_inbox_processing 异步调度，
        使用 _process_lock 保证不与 process_message 并发。
        执行完毕后自动推送 ASSISTANT_MESSAGE 到前端。
        """
        async with self._process_lock:
            if self._cancel_event.is_set():
                return None

            messages = self._get_full_history(self.session_id)
            if not self._maybe_inject_inbox(messages):
                return None

            sid = self.session_id
            self._interrupted = False
            self._processing = True
            self._event_loop = asyncio.get_running_loop()

            try:
                reply = await self._run_tool_loop(sid, messages, "[cron-result]")
            finally:
                self._processing = False
                self._last_idle_time[self.session_id] = time.monotonic()

            # 推送 ASSISTANT_MESSAGE 到前端（server.py 的 process_message 路径会自动做，
            # 但 process_inbox 是异步调度触发的，需要自己推）
            if reply:
                try:
                    await self._frontend_sink.emit_assistant_message(
                        sid, reply, self.current_character_agent,
                    )
                except Exception as exc:
                    logger.exception("Failed to send ASSISTANT_MESSAGE for inbox processing: %s", exc)

            return reply

    def schedule_inbox_processing(self) -> None:
        """从后台线程安全调度 process_inbox 到主事件循环。"""
        loop = self._event_loop
        if loop is None or loop.is_closed():
            return
        try:
            asyncio.run_coroutine_threadsafe(self.process_inbox(), loop)
        except Exception as exc:
            logger.exception("Failed to schedule inbox processing: %s", exc)

    # ========================================================================
    # 流式 LLM
    # ========================================================================

    async def _stream_llm_response(
        self,
        session_id: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        stream_id: str,
        cancel_event: asyncio.Event | None = None,
    ) -> LLMResponse:
        """以流式方式调用 LLM，边收边推送增量到前端。"""
        ev = cancel_event or self._cancel_event

        content: str = ""
        reasoning_content: str = ""
        tool_calls: list[ToolCall] = []
        finish_reason: str = "stop"
        usage: dict[str, int] = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        stream_error: str | None = None

        stream = self._llm.chat_stream(messages, tools=tools)
        try:
            async for chunk in stream:
                if ev.is_set():
                    break

                if chunk.error:
                    stream_error = chunk.error
                    break

                if chunk.content_delta:
                    content += chunk.content_delta
                    await self._frontend_sink.emit_stream_delta(
                        session_id, stream_id,
                        delta=chunk.content_delta,
                        character_name=self.current_character_agent,
                    )

                if chunk.reasoning_delta:
                    reasoning_content += chunk.reasoning_delta
                    await self._frontend_sink.emit_stream_delta(
                        session_id, stream_id,
                        reasoning_delta=chunk.reasoning_delta,
                        character_name=self.current_character_agent,
                    )

                if chunk.tool_call:
                    tool_calls.append(chunk.tool_call)
                    await self._frontend_sink.emit_stream_delta(
                        session_id, stream_id,
                        tool_call={
                            "id": chunk.tool_call.id,
                            "name": chunk.tool_call.name,
                            "arguments": chunk.tool_call.arguments,
                        },
                        character_name=self.current_character_agent,
                    )

                if chunk.usage:
                    usage["prompt_tokens"] = chunk.usage.prompt_tokens
                    usage["completion_tokens"] = chunk.usage.completion_tokens
                    usage["total_tokens"] = chunk.usage.total_tokens
                    self._token_usage += chunk.usage.total_tokens
                    self._persist_token_usage(session_id)
                    self._last_prompt_tokens = chunk.usage.prompt_tokens
                    self._push_usage_update(session_id)

                if chunk.finish_reason:
                    finish_reason = chunk.finish_reason
        finally:
            await _close_async_iterator(stream)

        if ev.is_set():
            finish_reason = "cancelled"

        if stream_error:
            raise RuntimeError(stream_error)

        if not ev.is_set() and usage["total_tokens"] == 0:
            raise RuntimeError(
                "LLM provider did not return token usage for streaming response. "
                "Provider must support stream_options.include_usage."
            )

        return LLMResponse(
            content=content,
            tool_calls=tool_calls,
            finish_reason=finish_reason,
            reasoning_content=reasoning_content or None,
            usage=Usage(
                prompt_tokens=usage["prompt_tokens"],
                completion_tokens=usage["completion_tokens"],
                total_tokens=usage["total_tokens"],
            ),
        )

    # ========================================================================
    # 工具执行
    # ========================================================================

    # TODO: 和下方的_execute_tool, 谁作为impl需要进一步决策
    async def _do_execute_tool(self, tc: ToolCall,
                               session_id: str = "") -> ToolResultMessage:
        """直接通过 ToolCall 实例执行单个工具调用。

        NOTE: 保留 ``_execute_tool`` 的通用参数签名，以便非 LLM 来源或测试
        直接按 name/args/id 调用；LLM 主链路统一走此 wrapper，避免调用点重复拆包。
        """
        return await self._execute_tool(
            tc.name, tc.arguments, tc.id, session_id,
        )

    async def _execute_tool(self, tool_name: str, args: dict,
                            tool_call_id: str = "",
                            session_id: str = "") -> ToolResultMessage:
        """执行单个工具调用，含审批流程。"""
        tc = ToolCall(id=tool_call_id, name=tool_name, arguments=args)
        if self._interrupted or self._cancel_event.is_set():
            return ToolResultMessage(
                role=Role.TOOL,
                character_name=self.current_character_agent,
                tool_call_id=tc.id,
                content="Cancelled.",
            )

        args["_session_id"] = session_id

        if args.get("_parse_error"):
            logger.warning(
                "Tool call '%s' skipped — arguments JSON parse failed. Preview: %s",
                tc.name, args.get("_raw_preview", "")[:LOG_PREVIEW_CHARS],
            )
            _result: dict = {
                "error": (
                    "Tool call parameter parsing failed. Your arguments JSON is incomplete or malformed "
                    "(possibly truncated due to content being too long). Please try: "
                    "1) Split content into multiple writes, "
                    "2) Use edit_file for incremental edits, "
                    "3) Or reduce the amount of data written in a single call."
                ),
                "_parse_failed": True,
            }
            await self._frontend_sink.emit_tool_result(
                session_id, tc.name, tc.id,
                json.dumps(_result, ensure_ascii=False),
            )
            return ToolResultMessage(
                role=Role.TOOL,
                character_name=self.current_character_agent,
                tool_call_id=tc.id,
                content=json.dumps(_result, ensure_ascii=False),
            )

        logger.info("Tool call: %s args=%s", tc.name, tc.arguments)

        # 追踪统计
        if tc.name not in self._tool_stats:
            self._tool_stats[tc.name] = {"calls": 0, "errors": 0}
        self._tool_stats[tc.name]["calls"] += 1

        # 通知前端
        await self._frontend_sink.emit_tool_call(
            session_id, tc.name, tc.id,
            tc.arguments,
        )

        # 审批流程
        _skip_dispatch = False
        result: dict | str = {}
        danger_level: ToolDangerLevel = tool_registry.get_danger_level(tc.name)
        _handsfree_enabled = is_handsfree_mode(session_id)
        _needs_approval = danger_level == ToolDangerLevel.dangerous or (
            danger_level == ToolDangerLevel.write and _handsfree_enabled
        )

        if _needs_approval:
            _approval_args = {k: v for k, v in args.items() if k != "_session_id"}
            if is_tool_allowlisted(tc.name, _approval_args):
                args["_pre_approved"] = True
                args["_approval_action"] = "allow_once"
            else:
                if _handsfree_enabled:
                    # 脱手模式：通过 approval 模型自动审批（仍走 request_user_confirm）
                    _hooks_ctx = self._get_hooks_context(session_id)
                    async def _ask_agent_callback_impl(q: str) -> str:
                        return await ask_agent_reason(
                            self._llm, tc.name, _approval_args, q,
                            extra_context=_hooks_ctx,
                        )
                    approval = await request_user_confirm(
                        session_id, tc.name, _approval_args,
                        reason=str(args.get("reason", "")),
                        content=f"Tool: {tc.name}\nParameters: {json.dumps(_approval_args, ensure_ascii=False)[:500]}",
                        ask_agent_callback=_ask_agent_callback_impl,
                        extra_context=_hooks_ctx,
                    )
                else:
                    # 正常模式：通过 AgentSink 请求审批（干净路径）
                    approval = await self._get_sink().request_approval(
                        tool_name=tc.name,
                        args=_approval_args,
                        reason=str(args.get("reason", "")),
                        content=f"Tool: {tc.name}\nParameters: {json.dumps(_approval_args, ensure_ascii=False)[:500]}",
                        session_id=session_id,
                    )
                if approval.action == "deny":
                    source_label = {"model": "approval model", "user": "user", "system": "system"}.get(
                        approval.denied_by, "system"
                    )
                    result = {
                        "error": f"[{source_label} denied] {approval.deny_reason or 'unknown reason'}",
                        "denied": True,
                        "denied_by": approval.denied_by,
                    }
                    _skip_dispatch = True
                else:
                    if approval.action == "allow_always" and not _handsfree_enabled:
                        add_tool_allowlist_entry(tc.name, _approval_args)
                    args["_pre_approved"] = True
                    args["_approval_action"] = approval.action

        if not _skip_dispatch:
            entry: ToolEntry | None = tool_registry.get_entry(tc.name)
            timeout: int = self.app.runtime_context.tool_timeout
            try:
                ctx = ToolContext(loop=self, session_id=self.session_id)
                result = await tool_registry.async_dispatch(tc.name, args, context=ctx)
            except Exception as exc:
                logger.exception("Tool %s dispatch error: %s", tc.name, exc)
                self._tool_stats[tc.name]["errors"] += 1
                result = {"error": f"Tool execution failed: {type(exc).__name__}: {exc}"}

        # 统一转换为可保存到 History 的 content（支持 _image blocks）
        content = tool_result_to_content(result)

        # 通知前端结果时使用文本摘要，避免 base64 撑爆前端事件
        await self._frontend_sink.emit_tool_result(
            session_id, tc.name, tc.id, content_to_text(content),
        )

        # 对前端 UI 类工具推送实时状态更新
        from abstract.tools.ui_event_router import ui_event_router
        await ui_event_router.emit_for(
            tc.name,
            result,
            self._get_sink(),
            session_id or self.session_id,
        )

        return ToolResultMessage(
            role=Role.TOOL,
            character_name=self.current_character_agent,
            tool_call_id=tc.id,
            content=content,
        )

    # ========================================================================
    # 历史 / 消息构建
    # ========================================================================

    async def append_user_message(
        self, content: Any, *,
        display_content: Any | None = None,
        character_name: str = USER_CHARACTER_NAME,
    ) -> int:
        """把用户消息加入 History 并回显到前端，返回消息索引。

        Args:
            content: 实际存入历史供 LLM 消费的内容。
            display_content: 回显给前端显示的内容；默认与 content 相同。
            character_name: 该用户消息的发出者角色名；默认 end-user。
        """
        index = self._append(self.session_id, Role.USER, content, character_name=character_name)
        await self._frontend_sink.emit_user_message(
            self.session_id, display_content if display_content is not None else content,
            character_name, index,
        )
        return index

    def _append(
        self, session_id: str, role: Role,
        content: str | list[dict[str, Any]],
        reasoning_content: str | None = None,
        character_name: str | None = None,
    ) -> int:
        """追加一条用户/assistant 消息到 History 并持久化，返回消息索引。"""
        if character_name is None:
            character_name = self.current_character_agent if role == Role.ASSISTANT else USER_CHARACTER_NAME
        if isinstance(content, str):
            message_content: str | list[ImageBlock | TextBlock] = content
        else:
            message_content = self._blocks_from_dicts(content)
        if isinstance(message_content, str):
            message = CharacterConversationMessage.from_text(
                role=role,
                character_name=character_name,
                text=message_content,
                visible_characters=[self.current_character_agent] if role == Role.USER else None,
                reasoning=reasoning_content,
            )
        else:
            message = CharacterConversationMessage(
                role=role,
                character_name=character_name,
                content=message_content,
                visible_characters=[self.current_character_agent] if role == Role.USER else None,
                reasoning=reasoning_content,
                reasoning_field_name="reasoning_content",
                message_suffix=None,
                tool_calls=None,
            )
        index = self._history.add_message(message)
        self._persist_message(session_id)
        return index

    @staticmethod
    def _blocks_from_dicts(blocks: list[dict[str, Any]]) -> list[ImageBlock | TextBlock]:
        """把 OpenAI 格式的 content block dict 列表转换为 MessageBlock 对象列表。"""
        result: list[ImageBlock | TextBlock] = []
        for block in blocks:
            if not isinstance(block, dict):
                continue
            btype = block.get("type")
            if btype == "text":
                result.append(TextBlock(text=str(block.get("text", ""))))
            elif btype == "image_url":
                image_url_block = block.get("image_url")
                if isinstance(image_url_block, dict):
                    result.append(ImageBlock(image_url=str(image_url_block.get("url", ""))))
                else:
                    result.append(ImageBlock(image_url=str(image_url_block or "")))
        return result

    def _get_memory_context(self, user_message: str) -> str:
        """主会话：通过 MemoryManager 预取当前回合的 memory 上下文。"""
        return self._memory.prefetch_all(
            self._extract_text(user_message),
            session_id=self.session_id,
        )

    def _get_full_history(self, session_id: str) -> list[dict[str, Any]]:
        system_prompts: list[str] = build_agent_system_prompt(
            self.app.runtime_context,
            self._collect_skill_prompts(),
        )
        return build_full_history_messages(
            system_prompts, self._history, self.current_character_agent
        )

    def _store_assistant_with_tools(
        self, session_id: str, resp: LLMResponse,
    ) -> None:
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
        message = CharacterConversationMessage.from_tool_calls(
            role=Role.ASSISTANT,
            character_name=self.current_character_agent,
            content=resp.content or "",
            tool_calls=tool_calls_data,
            reasoning=resp.reasoning_content,
        )
        self._history.add_message(message)
        self._persist_message(session_id)

    @staticmethod
    def _extract_text(content: Any) -> str:
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts: list[str] = []
            for block in content:
                if isinstance(block, TextBlock):
                    parts.append(block.text)
                elif isinstance(block, ImageBlock):
                    parts.append("[image_url]")
                elif isinstance(block, dict) and block.get("type") == "text":
                    parts.append(str(block.get("text", "")))
            return "\n".join(parts)
        return str(content or "")

    # ========================================================================
    # 上下文超限 / session 旋转
    # ========================================================================

    def _is_context_over_limit(self, safety_margin: int = 5000) -> bool:
        current_tokens: int = self._last_prompt_tokens
        if current_tokens == 0:
            return False
        ctx = self.app.runtime_context
        return (
            current_tokens + ctx.llm_max_output_tokens + safety_margin
        ) > ctx.llm_max_context_tokens

    async def _rotate_session_for_continuation(
        self,
        session_id: str,
        pending_user_message: str | None = None,
    ) -> str | None:
        """终结旧会话并创建继承会话。"""
        old_sid: str = session_id
        if pending_user_message is not None:
            self._remove_last_user_message(old_sid)

        new_sid: str | None = await self._terminate_session(old_sid, rotate=True)
        if not new_sid:
            if pending_user_message is not None:
                self._append(old_sid, Role.USER, pending_user_message)
            return None

        transfer_result = self._transfer_session_runtime_resources(old_sid, new_sid)
        if transfer_result.get("tool_resources_error") or transfer_result.get("memory_init_failed"):
            logger.warning(
                "Session runtime resource transfer had issues | old=%s new=%s result=%s",
                old_sid, new_sid, transfer_result,
            )
        if pending_user_message is not None:
            self._append(new_sid, Role.USER, pending_user_message)

        logger.info(
            "Session context exceeded limit and continued | old=%s new=%s",
            old_sid, new_sid,
        )
        return new_sid

    def _transfer_session_runtime_resources(self, old_sid: str, new_sid: str) -> dict[str, Any]:
        """将旧会话的运行态资源迁移到继承会话。

        返回迁移结果字典，供调用方记录或报告。
        """
        result: dict[str, Any] = {"old_sid": old_sid, "new_sid": new_sid}
        self._last_prompt_tokens = 0
        self._session_rotated_notify[old_sid] = new_sid

        # 迁移子 Agent 周期收集器使用的空闲时间戳
        idle_ts = self._last_idle_time.pop(old_sid, None)
        self._last_idle_time[new_sid] = idle_ts if idle_ts is not None else time.monotonic()

        # 初始化尚未成功的 memory provider
        memory_init_failed: list[str] = []
        for provider in self._memory.providers:
            if id(provider) in self._memory_initialized_ids:
                continue
            try:
                provider.initialize(new_sid)
                self._memory_initialized_ids.add(id(provider))
            except Exception as exc:
                logger.exception("Failed to initialize memory provider for session=%s", new_sid)
                memory_init_failed.append(str(exc))
        result["memory_init_failed"] = memory_init_failed

        # 迁移工具副作用资源
        tool_resources_error: str | None = None
        if self._session_store is not None:
            try:
                resources = self._session_store.read_tool_resources(old_sid)
                self._session_store.write_tool_resources(new_sid, resources)
            except Exception as exc:
                tool_resources_error = str(exc)
                logger.exception(
                    "Failed to transfer tool resources from %s to %s: %s",
                    old_sid, new_sid, exc,
                )
        result["tool_resources_error"] = tool_resources_error

        return result

    # ========================================================================
    # 磁盘持久化
    # ========================================================================

    def _history_path(self, session_id: str) -> Path | None:
        if self._session_store is None:
            return None
        return self._session_store.history_path(session_id)

    def _persist_message(self, session_id: str) -> None:
        if self._session_store is None:
            return
        try:
            self._session_store.write_history(session_id, self._history)
        except Exception as exc:
            logger.exception("Failed to persist history for session %s: %s", session_id, exc)

    def _persist_token_usage(self, session_id: str) -> None:
        if self._session_store is None:
            return
        try:
            self._session_store.write_token_usage(session_id, self._token_usage)
        except Exception as exc:
            logger.exception("Failed to persist token usage for session %s: %s", session_id, exc)

    def _load_token_usage_from_disk(self) -> int:
        if self._session_store is None:
            return 0
        try:
            return self._session_store.read_token_usage(self.session_id)
        except Exception as exc:
            logger.exception("Failed to load token usage for session %s: %s", self.session_id, exc)
            return 0

    def _remove_last_user_message(self, session_id: str) -> None:
        """移除 History 中最后一条 user 消息并持久化。"""
        messages = self._history.messages
        if messages and messages[-1].role == Role.USER:
            messages.pop()
        self._overwrite_history_file(session_id)

    def _update_last_user_message(self, session_id: str, fixator_context: str) -> None:
        """将 fixator_context 设为 History 中最后一条 user 消息的持久化 suffix。"""
        for i in range(len(self._history.messages) - 1, -1, -1):
            msg = self._history.messages[i]
            if msg.role == Role.USER and isinstance(msg, CharacterConversationMessage):
                self._history.messages[i] = msg.with_suffix(fixator_context)
                break
        self._overwrite_history_file(session_id)

    # ========================================================================
    # Session 终止 / 归档
    # ========================================================================

    async def _terminate_session(self, session_id: str, rotate: bool = False) -> str | None:
        """终结会话：归档 + 压缩（生成摘要），可选创建继承会话。"""
        if self._session_manager is None:
            return None

        sm = self._session_manager
        old_sid: str = session_id

        # 读取已持久化摘要
        summary: str = ""
        if self._history_store_dir:
            summary_path = self._history_store_dir / old_sid / "summary.txt"
            if summary_path.exists():
                try:
                    summary = summary_path.read_text(encoding="utf-8")
                except Exception:
                    # 摘要文件读取失败时回退为空，由 LLM 重新生成
                    logger.exception("Failed to read persisted summary for session=%s", old_sid)

        # 若无持久化摘要，则 LLM 压缩生成
        if not summary:
            summary = await self._summarize_session_history(old_sid)

        # 写入摘要
        if self._session_store is not None:
            try:
                self._session_store.write_summary(old_sid, summary)
            except Exception as exc:
                logger.exception("Failed to write summary for session %s: %s", old_sid, exc)

        # 同步 memory：传入旧 session 的完整 History
        try:
            self._memory.sync_all(self._history, session_id=old_sid)
        except Exception:
            logger.exception("Failed to sync memory for session=%s", old_sid)

        # 归档旧会话
        tags: list[str] = await self._generate_session_tags(old_sid)
        if tags and self._session_manager is not None:
            self._session_manager.set_session_tags(old_sid, tags)
            logger.info("Auto-classified tags for session %s: %s", old_sid, tags)
        sm.archive(old_sid, continuation_sid=None)

        if rotate:
            context: str = self._build_inherited_context(old_sid, summary)
            new_sid: str = sm.create_with_context(context, parent_sid=old_sid, role=Role.USER)
            sm.archive(old_sid, continuation_sid=new_sid)

            # 新 session 以 summary 作为 user 消息开始
            self._history = History(messages=[])
            self._last_prompt_tokens = 0
            summary_msg = CharacterConversationMessage.from_text(
                role=Role.USER,
                character_name=USER_CHARACTER_NAME,
                text=context,
                visible_characters=[self.current_character_agent],
            )
            self._history.add_message(summary_msg)
            self._persist_message(new_sid)

            # 迁移 cron 定时任务
            try:
                from component.extools import cron_tools
                cron_tools.migrate_session_cron_jobs(old_sid, new_sid)
            except Exception:
                logger.exception("Failed to migrate cron jobs from %s to %s", old_sid, new_sid)

            self._session_rotated_notify[old_sid] = new_sid
            logger.info(
                "Session terminated and rotated | old=%s new=%s summary=%d chars",
                old_sid, new_sid, len(summary),
            )
            return new_sid

        logger.info("Session terminated | old=%s summary=%d chars", old_sid, len(summary))
        return None

    def _load_history_from_disk(self, session_id: str) -> History:
        if self._session_store is None:
            return History(messages=[])
        try:
            history = self._session_store.read_history(session_id)
            return history if history is not None else History(messages=[])
        except Exception as exc:
            logger.exception("Failed to load history for session %s: %s", session_id, exc)
            return History(messages=[])

    async def _summarize_session_history(self, session_id: str) -> str:
        """用 LLM 对完整历史做压缩生成摘要。"""
        messages = self._get_full_history(session_id)
        if not messages:
            return ""
        # TODO: 总结过短, 截断剩余文本过少, 提示词模板没有分离
        summary_prompt = (
            "Summarize the following conversation history into a concise summary "
            "that captures the key context, actions taken, and decisions made. "
            "Keep it under 2000 characters."
        )
        try:
            resp = await self._llm.chat([
                {"role": "user", "content": summary_prompt},
                {"role": "user", "content": json.dumps(messages, ensure_ascii=False)[:30000]},
            ])
            return resp.content or ""
        except Exception as exc:
            logger.exception("Failed to generate session summary: %s", exc)
            return ""

    async def _generate_session_tags(self, session_id: str) -> list[str]:
        """用 LLM 生成会话分类标签。"""
        messages = self._get_full_history(session_id)
        if not messages:
            return []
        try:
            # TODO: 提示词模板没有分离, 截断剩余文本过少
            tag_prompt = (
                "Based on the conversation, generate 3-5 concise tags (single words or short phrases) "
                "that best categorize the session's topics. Return them as a JSON array of strings."
            )
            resp = await self._llm.chat([
                {"role": "user", "content": tag_prompt},
                {"role": "user", "content": json.dumps(messages, ensure_ascii=False)[:20000]},
            ])
            content = resp.content or ""
            try:
                tags = json.loads(content)
                if isinstance(tags, list):
                    return [str(t) for t in tags[:5]]
            except json.JSONDecodeError:
                pass
        except Exception as exc:
            logger.exception("Failed to generate session tags: %s", exc)
        return []

    def _build_inherited_context(self, old_sid: str, summary: str) -> str:
        """为继承会话构建初始上下文消息。"""
        return (
            f"This session continues from a previous session ({old_sid}). "
            f"Here is a summary of what was done previously:\n\n{summary}\n\n"
            f"Please continue based on this context."
        )

    # ========================================================================
    # Hooks / Skill prompts
    # ========================================================================

    def _get_hooks_context(self, session_id: str) -> str:
        return collect_hooks_context(
            self._load_message_hooks(),
            session_id,
            str(self.app.runtime_context.workspace),
            self.app.runtime_context,
        )

    def _collect_skill_prompts(self) -> list[str]:
        """生成 skill 名称和描述清单，避免全量内容注入 system prompt。

        Skill 的完整内容通过 ``list_skills`` 和 ``recall_skill`` 工具按需加载。
        """
        blocks: list[str] = []
        try:
            from pathlib import Path
            from abstract.skills.loader import list_skills
            skills: list[dict] = list_skills(skills_dir=Path("skills"))
            if skills:
                lines: list[str] = [
                    "Available skills (use list_skills to see details, use recall_skill to load one):",
                    "",
                ]
                for s in skills:
                    name: str = s.get("name", "")
                    description: str = s.get("description", "")
                    line = f"- {name}"
                    if description:
                        line += f": {description}"
                    lines.append(line)
                blocks.append("\n".join(lines))
            return blocks
        except Exception as e:
            logger.exception("Failed to collect skill prompts: %s", e)
            return []

    # ========================================================================
    # Usage 推送
    # ========================================================================

    def _push_usage_update(self, session_id: str) -> None:
        """推送 token 消耗到前端。"""
        try:
            asyncio.create_task(
                self._frontend_sink.emit_usage_update(
                    session_id, self._token_usage,
                    self._last_prompt_tokens,
                ),
                name=f"usage-push-{session_id}",
            )
        except Exception:
            logger.warning("Failed to schedule usage update for session=%s", session_id, exc_info=True)

    async def _emit_stream_done(
        self, session_id: str, stream_id: str, finish_reason: str
    ) -> None:
        """推送流结束事件。"""
        try:
            await self._frontend_sink.emit_stream_done(
                session_id, stream_id, finish_reason,
            )
        except Exception:
            logger.warning(
                "Failed to emit stream_done for session=%s stream=%s",
                session_id, stream_id, exc_info=True,
            )

    # ========================================================================
    # 会话消息管理（供 server API 调用）
    # ========================================================================

    def get_session_messages(self) -> list[dict]:
        """返回前端展示所需的消息列表，包含多 agent 元数据。"""
        messages: list[dict] = []
        for index, msg in enumerate(self._history.messages):
            raw_content = msg.content
            if isinstance(raw_content, list):
                content: str | list[dict[str, Any]] = [b.as_object() for b in raw_content]
            else:
                content = self._extract_text(raw_content)
            entry: dict[str, Any] = {
                "role": msg.role.value,
                "content": content,
                "index": index,
                "character_name": msg.character_name if isinstance(msg, CharacterConversationMessage) else self.current_character_agent,
                "visible_characters": msg.visible_characters if isinstance(msg, CharacterConversationMessage) else None,
                "requires_response": msg.role == Role.USER,
            }
            if isinstance(msg, CharacterConversationMessage) and msg.reasoning:
                entry["reasoning_content"] = msg.reasoning
            if msg.role == Role.SYSTEM:
                entry["role"] = Role.SYSTEM.value
            messages.append(entry)
        return messages

    def edit_session_message(self, index: int, content: str) -> dict:
        if not isinstance(index, int) or index < 0:
            return {"updated": False, "error": "invalid message index"}
        if index >= self._history.count:
            return {"updated": False, "error": "message index out of range"}
        msg = self._history.get_message(index)
        if not isinstance(msg, CharacterConversationMessage):
            return {"updated": False, "error": "message type not editable"}
        self._history.messages[index] = msg.model_copy(update={"content": content})
        self._overwrite_history_file(self.session_id)
        return {
            "updated": True,
            "session_id": self.session_id,
            "index": index,
            "role": msg.role.value,
            "content": self._extract_text(content),
        }

    def _overwrite_history_file(self, session_id: str) -> None:
        if self._session_store is None:
            return
        try:
            self._session_store.write_history(session_id, self._history)
        except Exception as exc:
            logger.exception("Failed to overwrite history file for session %s: %s", session_id, exc)

    def is_processing(self) -> bool:
        """返回当前是否正在处理消息。"""
        return self._processing

    def clear_session(self) -> None:
        """清理当前 session 的持久化数据。"""
        if self._session_store is None:
            return
        session_path = self._session_store.session_dir(self.session_id)
        if session_path.exists():
            shutil.rmtree(str(session_path), ignore_errors=True)
            logger.info("Cleared persisted data for session %s", self.session_id)

    def delete_session_messages(self, count: int = 1) -> dict:
        """删除最后 count 个逻辑轮次的消息（从倒数第 count 条 user 起，覆盖其后所有 tool/assistant）。"""
        if count < 1:
            return {"deleted": False, "error": "count must be >= 1"}
        user_indices = [i for i, m in enumerate(self._history.messages) if m.role == Role.USER]
        if not user_indices:
            return {"deleted": False, "error": "no user messages to delete"}
        if count > len(user_indices):
            return {"deleted": False, "error": f"only {len(user_indices)} user messages available"}
        remove_from = user_indices[-count]
        self._history.messages = self._history.messages[:remove_from]
        self._overwrite_history_file(self.session_id)
        return {"deleted": True, "session_id": self.session_id, "remaining_count": self._history.count}

    def regenerate_response(self) -> dict:
        """截断到最后一条 user 消息，返回其内容供重新生成。"""
        user_indices = [i for i, m in enumerate(self._history.messages) if m.role == Role.USER]
        if not user_indices:
            return {"regenerate": False, "error": "no user message found"}
        last_user_idx = user_indices[-1]
        last_user_content = self._extract_text(self._history.messages[last_user_idx].content)
        # 截断到 user 消息处（保留 user 本身，删除其后所有 assistant/tool）
        self._history.messages = self._history.messages[:last_user_idx + 1]
        self._overwrite_history_file(self.session_id)
        return {
            "regenerate": True,
            "session_id": self.session_id,
            "last_user_content": last_user_content,
            "remaining_count": self._history.count,
        }

    def get_tool_resources(self) -> dict:
        """返回 session 的可恢复工具副作用资源快照。"""
        if self._session_store is None:
            return {"task_progress": {}, "clipboard_display": {}}
        return self._session_store.read_tool_resources(self.session_id)

    async def terminate_session(self) -> dict:
        """终结当前会话：归档 + 压缩（生成摘要），不旋转。"""
        await self._terminate_session(self.session_id, rotate=False)
        return {"terminated": True, "session_id": self.session_id}

    async def merge_sessions(self, sources: list[str]) -> dict:
        """合并多个源会话到一个新会话。"""
        if self._session_manager is None:
            return {"error": "session manager not available", "merged": False}
        if not sources:
            return {"error": "sources list is empty", "merged": False}
        # 收集各源 session 的历史消息
        combined = History(messages=[])
        for sid in sources:
            history = self._load_history_from_disk(sid)
            if history:
                combined.messages.extend(history.messages)
        # 创建新 session
        new_sid = self._session_manager.create_with_context(
            context="Merged session",
            parent_sid=sources[0],
            role=Role.SYSTEM,
        )
        # 写入合并后的历史
        if self._session_store is not None:
            self._session_store.write_history(new_sid, combined)
        # 归档源 sessions
        for sid in sources:
            self._session_manager.archive(sid, continuation_sid=new_sid)
        logger.info(
            "Sessions merged | new=%s sources=%s total_messages=%d",
            new_sid, sources, combined.count,
        )
        return {"merged": True, "session_id": new_sid, "sources": sources}

    async def auto_generate_title(self) -> str:
        """使用 LLM 根据会话消息自动生成标题。"""
        messages = self._get_full_history(self.session_id)
        if not messages:
            return ""
        title_prompt = (
            "Generate a concise title (max 50 characters) for this conversation. "
            "Return only the title text, no quotes or formatting."
        )
        try:
            resp = await self._llm.chat([
                {"role": "user", "content": title_prompt},
                {"role": "user", "content": json.dumps(messages, ensure_ascii=False)[:AUTO_TITLE_CONTENT_MAX]},
            ])
            title = (resp.content or "").strip().strip("\"'")[:50]
            return title
        except Exception as exc:
            logger.exception("Failed to auto-generate title: %s", exc)
            return ""

    async def regenerate_session_tags(self) -> list[str]:
        """根据会话摘要重新生成标签。"""
        return await self._generate_session_tags(self.session_id)