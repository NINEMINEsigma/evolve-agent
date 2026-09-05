"""ParentAgentLoop — 主 Agent 循环，继承 BasePrivateChatAgentLoop。

实现流式 LLM 调用、Memory 管理、session 旋转/归档、
工具审批流程和前端事件推送。每个 session 对应一个实例。

高层编排保留于此；具体职责委托给：
  - LoopSessionManager（session 生命周期）
  - ToolExecutor（工具审批/分发/事件）
  - StreamConsumer（LLM 流消费）
"""
# TODO: 大量在Messages格式化解构中没有对齐类型的问题
from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, TYPE_CHECKING

from abstract.tools.registry import registry as tool_registry
from abstract.llm.client import BaseLLMClient
from abstract.llm.loader import create_llm_client
from entity.puretype import LLMResponse, ToolCallRequest, Role, ToolAvailability, TokenUsageRecord, MessageContent, LLMProfile, MessageMetrics, QueuedMessage
from entity.gentype import RefWrapper
from system.session_store import SessionStore
from entity.constant import (
    LOG_PREVIEW_CHARS,
    MAX_TOOL_TURNS,
    MAIN_AGENT_CHARACTER_NAME,
    USER_CHARACTER_NAME,
)
from entity.messages import (
    History,
    BaseMessage,
    CharacterConversationMessage,
    FunctionCall,
    AudioBlock,
    ImageBlock,
    TextBlock,
    MessageBlock,
    ToolResultMessage,
    ToolCall as HistoryToolCall,
)
from entry.base_agent_loop import BasePrivateChatAgentLoop, IMainSessionLoop, ToolContext
from entry.agent_sink import AgentSink, FrontendSink
from entry.agent_support.messages import (
    build_agent_system_prompt,
    build_full_history_messages,
)
from system.prompt import build_session_site_block
from entry.agent_support.multimodal import (
    blocks_from_dicts,
    content_to_text,
    summarize_message_for_log,
    preprocess_multimodal_blocks,
)
from system.modality_capability import (
    ensure_modality_capability,
)
from entry.session_manager import LoopSessionManager
from entry.tool_executor import ToolExecutor, _interrupted_result
from entry.stream_consumer import StreamConsumer
from entry.session_message_queue import SessionMessageQueue

if TYPE_CHECKING:
    from gateway.session_manager import SessionManager
    from system.application import Application
    from system.context import RuntimeContext
    from entry.tool_post_dispatch import ResultFieldInjector

logger = logging.getLogger(__name__)

# 每条消息的最大工具调用循环次数
_MAX_TOOL_TURNS: int = MAX_TOOL_TURNS


class IncompatibleHistoryError(Exception):
    """会话历史格式不兼容，无法加载。"""
    def __init__(self, session_id: str) -> None:
        self.session_id = session_id
        super().__init__(f"Session {session_id} history format is incompatible")


class ParentAgentLoop(BasePrivateChatAgentLoop, IMainSessionLoop):
    """主 Agent 循环 — 每个 WebSocket session 一个实例。

    继承 BasePrivateChatAgentLoop，实现：
    - 流式 LLM（委托给 StreamConsumer）
    - Memory 预取与同步
    - 上下文超限时的 session 旋转/归档（委托给 LoopSessionManager）
    - 工具审批流程（委托给 ToolExecutor）
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

        self._session_store = (
            SessionStore(history_store_dir)
            if history_store_dir else None
        )

        # -- 从会话级/全局名称指针恢复根对象中的 LLM Profile --
        self._llm: BaseLLMClient | None = None
        if self._session_store is not None:
            restored_name = self._session_store.read_active_profile_name(session_id)
            if restored_name is not None:
                restored_profile = app.llm_profile_store.resolve_profile_name(restored_name)
                if restored_profile is not None:
                    self._llm = create_llm_client(
                        restored_profile.llm_client_name,
                        app.runtime_context,
                        restored_profile,
                    )
                    self._active_llm_profile = restored_profile

        # -- 生命周期管理（委托给 LoopSessionManager） --
        self._lifecycle: LoopSessionManager = LoopSessionManager(
            loop=self, history_store_dir=history_store_dir,
        )
        self._lifecycle.initialize()

        # -- 工具执行器 --
        self._tool_executor: ToolExecutor = ToolExecutor(loop=self)

        # -- LLM 流消费器 --
        self._stream_consumer: StreamConsumer = StreamConsumer(
            llm=self._llm,
            sink=self._frontend_sink,
            character_name=MAIN_AGENT_CHARACTER_NAME,
            cancel_event=self._cancel_event,
        )

        # -- 工具调用事件回调 --
        self._tool_event_callback: Callable[[str, str, str, str], Awaitable[None]] | None = None

        # SP-4: 会话级消息队列（_process_lock 已上移至 BaseAgentLoop.__init__）
        self._message_queue = SessionMessageQueue(self)

        # -- 处理状态 --
        # NOTE: _processing 已上移至 BaseAgentLoop.__init__，is_processing() 由基类提供
        self._event_loop: asyncio.AbstractEventLoop | None = None

        # -- 子 Agent 周期收集器用的空闲时间戳 --
        self._last_idle_time: dict[str, float] = {session_id: time.monotonic()}

        # -- 子 Agent 编排器（由 server 层注入） --
        self.subagent_orchestrator: Any = None

    def get_last_idle_time(self, session_id: str) -> float | None:
        """返回指定 session 上次进入空闲的时间戳，不存在时返回 None。"""
        return self._last_idle_time.get(session_id)

    # TODO: 未被使用
    def update_last_idle_time(self, session_id: str) -> None:
        """更新指定 session 的空闲时间戳。"""
        self._last_idle_time[session_id] = time.monotonic()

    # ========================================================================
    # 抽象方法实现
    # ========================================================================

    @property
    def current_character_agent(self) -> str:
        return MAIN_AGENT_CHARACTER_NAME

    @property
    def user_character_name(self) -> str:
        return USER_CHARACTER_NAME

    def _get_llm_client(self) -> BaseLLMClient | None:
        return self._llm

    def _get_session_info_llm_client(self) -> BaseLLMClient | None:
        return self._llm

    def _get_context(self) -> RuntimeContext:
        return self.app.runtime_context

    def get_sink(self) -> AgentSink:
        return self._frontend_sink

    def _get_tool_definitions(self) -> list[dict]:
        """返回主 Agent 可用的工具 schema（availability 包含 MAIN 或 EVERY）。"""
        definitions: list[dict] = tool_registry.get_definitions_for_availability(
            scope=ToolAvailability.MAIN,
        )
        return definitions if definitions else []

    async def _on_context_over_limit(self) -> None:
        """上下文超限：触发 session 旋转/归档。"""
        old_sid = self.session_id
        new_sid: str | None = await self._lifecycle.rotate_session_for_continuation(
            self.session_id,
        )
        if new_sid:
            self.session_id = new_sid
            if self._session_manager is not None:
                self._session_manager.rotate_session(old_sid, new_sid)

    def _build_system_prompt(self) -> list[str]:
        prompts = build_agent_system_prompt(
            self.app.runtime_context,
            self._collect_skill_prompts(),
            profile=self._active_llm_profile,
            session_id=self.session_id,
        )
        site_block = build_session_site_block(self.session_id, owner="self")
        if site_block:
            prompts.append(site_block)
        return prompts

    def get_tool_availability_scope(self) -> ToolAvailability:
        return ToolAvailability.MAIN

    # -- 超限检查步骤（可被子类覆写）-------------------------------------------

    async def _check_over_limit_before_process(
        self, sid: str, user_message: MessageContent | None,
    ) -> str:
        """process_message 入口处的超限检查：超限时旋转会话，返回可能更新后的 sid。

        user_message 为 None 表示队列路径（SP-4），无 pending 搬运。
        """
        if self._lifecycle.is_context_over_limit():
            new_sid: str | None = await self._lifecycle.rotate_session_for_continuation(
                sid, pending_user_message=user_message,
            )
            if new_sid:
                return new_sid
        return sid

    async def _check_over_limit_in_tool_loop(self, sid: str) -> str:
        """_run_tool_loop 内每轮工具调用后的超限检查：超限时旋转会话，返回可能更新后的 sid。"""
        if self._lifecycle.is_context_over_limit():
            new_sid: str | None = await self._lifecycle.rotate_session_for_continuation(sid)
            if new_sid:
                self.session_id = new_sid
                return new_sid
        return sid

    # ========================================================================
    # 公共 API
    # ========================================================================

    def set_tool_event_callback(
        self, cb: Callable[[str, str, str, str], Awaitable[None]]
    ) -> None:
        self._tool_event_callback = cb

    def pop_session_rotated(self) -> str | None:
        return self._lifecycle.pop_session_rotated()

    def get_all_tool_stats(self) -> dict[str, dict[str, int]]:
        return self._tool_executor.get_tool_stats()

    def interrupt(self) -> None:
        super().interrupt()

    # ========================================================================
    # process_message — 主入口
    # ========================================================================

    async def process_message(
        self,
        user_message: MessageContent,
        *,
        skip_append: bool = False,
        character_name: str = USER_CHARACTER_NAME,
        **kwargs,
    ) -> str:
        sid = self.session_id
        self._cancel_event.clear()
        self._disgust_event.clear()
        self._event_loop = asyncio.get_running_loop()

        # 无 LLM client 时返回错误（不进工具循环）
        if self._llm is None:
            logger.warning("No LLM client available | session=%s", sid)
            err_text = "尚未配置 LLM 模型。请在前端「模型配置」中新建或选择一个配置后重试。"
            # NOTE: 错误文本以系统状态消息显示（对 LLM 不可见），持久化进历史。
            # 此处在锁外返回，_processing 未置位，不影响并发防护。
            self.append_system_status(err_text, session_id=sid)
            return err_text

        logger.info(
            "Received user message | session=%s content=%s",
            sid, summarize_message_for_log(user_message),
        )
        async with self._process_lock:
            self._processing = True
            try:
                if not skip_append:
                    await self.append_user_message(user_message, character_name=character_name)

                # 历史过长时自动终结会话
                sid = await self._check_over_limit_before_process(sid, user_message)
                self.session_id = sid

                messages = self._build_history_messages(user_message)

                reply = await self._run_tool_loop(sid, messages, user_message)
                logger.info("Reply sent | session=%s reply=%s", sid, summarize_message_for_log(reply))
                return reply
            finally:
                self._processing = False
                self._last_idle_time[self.session_id] = time.monotonic()

    async def resume(self) -> str:
        """从当前历史状态恢复工具链执行。

        清除中断/厌恶标志，重置工具调用计数器（_run_tool_loop 内部自动重置），
        从当前历史构建 messages 并重新进入工具循环。
        不追加任何 user 消息。SystemStatusMessage 对 LLM 不可见，自动被过滤。
        返回助手回复文本（空串表示无回复）。
        """
        sid = self.session_id
        self._cancel_event.clear()
        self._disgust_event.clear()
        self._event_loop = asyncio.get_running_loop()

        if self._llm is None:
            err_text = "尚未配置 LLM 模型。请在前端「模型配置」中新建或选择一个配置后重试。"
            self.append_system_status(err_text, session_id=sid)
            return err_text

        async with self._process_lock:
            self._processing = True
            try:
                sid = await self._check_over_limit_before_process(sid, None)
                self.session_id = sid

                messages = self._get_full_history(sid)
                reply = await self._run_tool_loop(sid, messages, "[resume]")
                if reply:
                    await self._frontend_sink.emit_assistant_message(
                        sid, reply, self.current_character_agent,
                    )
                return reply
            finally:
                self._processing = False
                self._last_idle_time[self.session_id] = time.monotonic()

    async def _run_tool_loop(
        self,
        sid: str,
        messages: list[BaseMessage],
        user_message: MessageContent,
    ) -> str:
        """执行 LLM 工具调用循环。"""
        self._cancel_event.clear()
        self._disgust_event.clear()
        round_id = self.begin_agentspace_round(self.current_character_agent)

        turn: RefWrapper[int] = RefWrapper(value=0)
        self._tool_executor.set_turn_counter(turn)

        # 计时数据累积器（三元组：session_id, msg_index, metrics）
        collected_metrics: list[tuple[str, int, MessageMetrics]] = []

        # 预初始化：while 循环内每轮重新赋值，但循环退出后的超限路径仍需引用，
        # 静态检查无法证明循环至少执行一次（_MAX_TOOL_TURNS=90 保证之）。
        stream_id: str = ""

        try:
            while turn.value < _MAX_TOOL_TURNS:
                if self._cancel_event.is_set():
                    self.append_system_status("已中断", session_id=sid)
                    return ""
                turn.value += 1

                # 多模态块预检：检测 messages 中的 ImageBlock/AudioBlock，
                # 自动探查能力，不支持时转发借用并替换为描述文本
                messages = await self._preprocess_multimodal_blocks(
                    sid, messages, round_id,
                )

                stream_id = uuid.uuid4().hex[:12]
                try:
                    resp = await self._stream_consumer.consume(
                        sid, messages,
                        self._get_tool_definitions(),
                        stream_id,
                        last_user_message=self._history.last_user_message,
                    )
                except Exception as llm_exc:
                    logger.exception("LLM call failed for session=%s", sid)
                    # NOTE: D1——失败时保留 user 消息（不再移除），错误回复持久化为
                    # assistant 消息。前后端状态一致，重新生成自然命中刚失败的消息。
                    err_text = (
                        f"The service provider returned an error, please try again later. "
                        f"Details: {llm_exc}"
                    )
                    self.append_system_status(err_text, session_id=sid)
                    await self._emit_stream_done(sid, stream_id, "error", content="", metrics=None)
                    await self._frontend_sink.emit_system_message(sid, err_text)
                    return ""

                if self._cancel_event.is_set():
                    await self._emit_stream_done(sid, stream_id, "cancelled", content=resp.content or "", metrics=resp.metrics)
                    if resp.content:
                        msg_index = self._append(
                            sid, Role.ASSISTANT, resp.content,
                            reasoning_content=resp.reasoning_content,
                            reasoning_field_name=resp.reasoning_field_name,
                        )
                        if resp.metrics:
                            collected_metrics.append((sid, msg_index, resp.metrics))
                        return resp.content
                    self.append_system_status("已中断", session_id=sid)
                    return ""

                if resp.usage.prompt_tokens:
                    self._token_record.prompt_tokens = resp.usage.prompt_tokens
                    self._token_record.token_usage += resp.usage.total_tokens
                    self._persist_token_usage(sid)
                await self._push_usage_update(sid)

                if resp.tool_calls:
                    tool_names = ", ".join(tc.name for tc in resp.tool_calls)
                    logger.info(
                        "Agent response | session=%s tools=[%s] content=%s",
                        sid, tool_names,
                        (resp.content[:LOG_PREVIEW_CHARS] + "...")
                        if len(resp.content or "") > LOG_PREVIEW_CHARS
                        else (resp.content or ""),
                    )
                else:
                    logger.info(
                        "Agent response | session=%s content=%s",
                        sid,
                        (resp.content[:LOG_PREVIEW_CHARS] + "...")
                        if len(resp.content or "") > LOG_PREVIEW_CHARS
                        else (resp.content or ""),
                    )

                await self._emit_stream_done(sid, stream_id, resp.finish_reason, content=resp.content or "", metrics=resp.metrics)

                if not resp.tool_calls:
                    assistant_text = resp.content or ""
                    msg_index = self._append(
                        sid, Role.ASSISTANT, assistant_text,
                        reasoning_content=resp.reasoning_content,
                        reasoning_field_name=resp.reasoning_field_name,
                    )
                    if resp.metrics:
                        collected_metrics.append((sid, msg_index, resp.metrics))
                    return assistant_text

                # 存储 assistant 消息（含 tool_calls）
                msg_index = self._store_assistant_with_tools(sid, resp)
                if resp.metrics:
                    collected_metrics.append((sid, msg_index, resp.metrics))

                # 委托给 ToolExecutor 执行工具调用
                try:
                    _executed_tool_msgs: list[ToolResultMessage] = []
                    for tc in resp.tool_calls:
                        tool_msg = await self._tool_executor.execute(
                            tc, sid,
                            round_id=round_id,
                            character_name=self.current_character_agent,
                            llm_profile=self.active_llm_profile,
                        )
                        messages.append(tool_msg)
                        self._history.add_message(tool_msg)
                        self.save_history(sid)
                        await self._push_usage_update(sid)
                        _executed_tool_msgs.append(tool_msg)

                        if tc.name == "EvolveCode":
                            try:
                                content_text = content_to_text(tool_msg.content)
                                parsed: Any = json.loads(content_text)
                                if parsed.get("evolved"):
                                    self._append(
                                        sid, Role.ASSISTANT,
                                        "Evolution complete, restarting to apply new code...",
                                    )
                                    return "Evolution complete, restarting to apply new code..."
                            except (json.JSONDecodeError, KeyError, TypeError):
                                pass

                    # 延迟注入 follow_up 消息（当前轮所有工具调用完成后）
                    for tm in _executed_tool_msgs:
                        if tm._follow_up_messages:
                            for fu_msg in tm._follow_up_messages:
                                self._history.add_message(fu_msg)
                                self.save_history(sid)
                except BaseException:
                    # 兜底：execute 内部审批/dispatch/finalize 已保护，但
                    # execute 协程被外部取消（asyncio task cancel）或 get_hooks_context
                    # 等未保护 await 点抛异常时仍会穿透。此处为未执行的 tool_calls
                    # 补中断结果，保证 History 配对后停止响应
                    logger.exception("Tool loop failed for session=%s", sid)
                    _assistant_ids = {t.id for t in resp.tool_calls}
                    _executed_ids = {
                        m.tool_call_id
                        for m in self._history.iter_messages()
                        if isinstance(m, ToolResultMessage) and m.tool_call_id in _assistant_ids
                    }
                    for tc in resp.tool_calls:
                        if tc.id in _executed_ids:
                            continue
                        tool_msg = _interrupted_result(
                            tc, self.current_character_agent, "unexpected",
                        )
                        messages.append(tool_msg)
                        self._history.add_message(tool_msg)
                        self.save_history(sid)
                    self.append_system_status("工具链异常中断", session_id=sid)
                    await self._emit_stream_done(sid, stream_id, "error", content="", metrics=None)
                    await self._frontend_sink.emit_system_message(sid, "工具链异常中断")
                    return ""

                sid = await self._check_over_limit_in_tool_loop(sid)

                messages = self._get_full_history(sid)

        finally:
            # 所有退出路径汇聚于此：一次性持久化计时数据，再释放回复轮次文件锁。
            try:
                if collected_metrics and self._session_store is not None:
                    self._session_store.merge_message_metrics(collected_metrics)
            finally:
                self.end_agentspace_round(self.current_character_agent, round_id)

        logger.warning(
            "Tool-call loop exceeded max turns (%d) for session=%s",
            _MAX_TOOL_TURNS, sid,
        )
        await self._emit_stream_done(sid, stream_id, "error", content="", metrics=None)
        await self._frontend_sink.emit_system_message(
            sid,
            f"工具调用已达 {_MAX_TOOL_TURNS} 轮上限，已自动终止。",
        )
        over_limit_text = "I ran into an issue processing your request. Please try again."
        self.append_system_status(f"工具调用已达 {_MAX_TOOL_TURNS} 轮上限", session_id=sid)
        return ""

    # ========================================================================
    # 多模态块预检（委托给 multimodal.preprocess_multimodal_blocks）
    # ========================================================================

    async def _preprocess_multimodal_blocks(
        self,
        sid: str,
        messages: list[BaseMessage],
        round_id: str,
    ) -> list[BaseMessage]:
        """预检多模态块：委托给 multimodal.preprocess_multimodal_blocks 公共函数。"""
        context = ToolContext(
            loop=self,
            session_id=sid,
            round_id=round_id,
            character_name=self.current_character_agent,
            llm_profile=self.active_llm_profile,
        )
        return await preprocess_multimodal_blocks(messages, context, self.save_history)

    # ========================================================================
    # 历史 / 消息构建
    # ========================================================================

    async def append_user_message(
        self, content: Any, *,
        display_content: Any | None = None,
        character_name: str = USER_CHARACTER_NAME,
        client_message_id: str | None = None,
        **kwargs: Any,
    ) -> int:
        hooks_context, fixator_context = self._collect_hooks_context()

        dynamic_parts: list[str] = []
        if hooks_context:
            dynamic_parts.append(hooks_context)
        dynamic_suffix = "\n".join(dynamic_parts) if dynamic_parts else None

        index = self._append(
            self.session_id, Role.USER, content,
            character_name=character_name,
            message_suffix=fixator_context or None,
            dynamic_message_suffix=dynamic_suffix,
        )
        await self._frontend_sink.emit_user_message(
            self.session_id,
            display_content if display_content is not None else content,
            character_name, index,
            client_message_id=client_message_id,
            message_suffix=fixator_context or None,
            dynamic_message_suffix=dynamic_suffix,
        )
        return index

    # -- SP-4 会话消息队列接入 ------------------------------------------------

    def get_result_field_injector(self) -> "ResultFieldInjector | None":
        """SP-4：返回队列的链中注入回调。"""
        return self._message_queue.drain_injected

    async def _append_queued_messages(self, items: list[QueuedMessage]) -> None:
        """队列消息落历史 + 回显：保序、原生块。

        SP-5 bugfix：回显从 push 移到此处（空闲消费时回显，链中注入不回显）。
        SP-5 D1/R7：仅 source == "ws" 时收集 hooks 上下文（message_suffix /
        dynamic_message_suffix），与 append_user_message 同源；其余来源
        （cron/dynamic-endpoint/subagent）不设 suffix——属切队列后的有意行为变更。
        """
        for item in items:
            content = blocks_from_dicts(item.content) if isinstance(item.content, list) else item.content
            message_suffix: str | None = None
            dynamic_message_suffix: str | None = None
            if item.source == "ws":
                hooks_context, fixator_context = self._collect_hooks_context()
                dynamic_parts: list[str] = []
                if hooks_context:
                    dynamic_parts.append(hooks_context)
                dynamic_message_suffix = "\n".join(dynamic_parts) if dynamic_parts else None
                message_suffix = fixator_context or None
            message = CharacterConversationMessage(
                role=Role.USER,
                character_name=item.character_name,
                content=content,
                visible_characters=[self.current_character_agent],
                message_suffix=message_suffix,
                dynamic_message_suffix=dynamic_message_suffix,
            )
            index = self._history.add_message(message)
            self.save_history(self.session_id)
            # SP-5 bugfix：空闲消费时回显（push 不再回显）
            await self._frontend_sink.emit_user_message(
                self.session_id,
                item.content,
                item.character_name,
                index,
                client_message_id=item.client_message_id,
                message_suffix=message_suffix,
                dynamic_message_suffix=dynamic_message_suffix,
            )

    async def run_pending_round(self, items: list[QueuedMessage]) -> str | None:
        """SP-4：队列空闲消费驱动的轮次（S1 分支序）。

        持锁 → 置 _processing → 超限检查（旋转随动）→ sid 变更检测 →
        cancel 检测 → 注入落历史 → 无 LLM 闸 → llm_profile_name 应用 →
        非旋转非中断时跑轮 → finally 复位 → 锁外 on_round_done 回调。
        """
        if not items:
            return None
        async with self._process_lock:
            self._processing = True
            self._event_loop = asyncio.get_running_loop()
            reply: str | None = None
            try:
                sid = await self._check_over_limit_before_process(self.session_id, None)
                self.session_id = sid
                queue = self._message_queue
                rotated: bool = queue.last_known_sid != sid
                interrupted: bool = self._cancel_event.is_set()
                self._cancel_event.clear()
                self._disgust_event.clear()
                await self._append_queued_messages(items)
                should_run: bool = not rotated and not interrupted
                # 取最后一条非 None 的 llm_profile_name；None 表示沿用当前配置（内部消息）。
                selected_name = next(
                    (m.llm_profile_name for m in reversed(items) if m.llm_profile_name is not None), None,
                )
                if should_run and self._llm is None and selected_name is None:
                    err_text = "尚未配置 LLM 模型。请在前端「模型配置」中新建或选择一个配置后重试。"
                    self.append_system_status(err_text, session_id=sid)
                    await self._frontend_sink.emit_system_message(sid, err_text)
                    should_run = False
                if should_run and selected_name is not None:
                    try:
                        profile = self.app.llm_profile_store.resolve_profile_name(
                            selected_name,
                        )
                        self.set_profile(profile)
                    except (LookupError, ValueError, RuntimeError) as exc:
                        err_text = f"LLM Profile 切换失败：{exc}"
                        logger.warning(
                            "Queued message Profile selection failed | session=%s name=%r error=%s",
                            sid, selected_name, exc,
                        )
                        self.append_system_status(err_text, session_id=sid)
                        await self._frontend_sink.emit_system_message(sid, err_text)
                        should_run = False
                if should_run:
                    messages = self._get_full_history(sid)
                    reply = await self._run_tool_loop(sid, messages, "[queued-messages]")
                if reply:
                    await self._frontend_sink.emit_assistant_message(
                        sid, reply, self.current_character_agent,
                    )
                queue.last_known_sid = sid
            finally:
                self._processing = False
                self._last_idle_time[self.session_id] = time.monotonic()

        if self._on_round_done is not None:
            await self._on_round_done(self)
        return reply

    def _append(
        self, session_id: str, role: Role,
        content: str | list[dict[str, Any]],
        reasoning_content: str | None = None,
        reasoning_field_name: str | None = None,
        character_name: str | None = None,
        message_suffix: str | None = None,
        dynamic_message_suffix: str | None = None,
    ) -> int:
        if character_name is None:
            character_name = (
                self.current_character_agent
                if role == Role.ASSISTANT
                else USER_CHARACTER_NAME
            )
        message_content: str | list[MessageBlock]
        if isinstance(content, str):
            message_content = content
        else:
            message_content = blocks_from_dicts(content)
        if isinstance(message_content, str):
            message = CharacterConversationMessage(
                role=role,
                character_name=character_name,
                content=message_content,
                visible_characters=(
                    [self.current_character_agent] if role == Role.USER else None
                ),
                reasoning=reasoning_content,
                reasoning_field_name=reasoning_field_name,
                message_suffix=message_suffix,
                dynamic_message_suffix=dynamic_message_suffix,
            )
        else:
            message = CharacterConversationMessage(
                role=role,
                character_name=character_name,
                content=message_content,
                visible_characters=(
                    [self.current_character_agent] if role == Role.USER else None
                ),
                reasoning=reasoning_content,
                reasoning_field_name=reasoning_field_name,
                message_suffix=message_suffix,
                dynamic_message_suffix=dynamic_message_suffix,
                tool_calls=None,
            )
        index = self._history.add_message(message)
        self.save_history(session_id)
        return index

    def _get_full_history(self, session_id: str) -> list[BaseMessage]:
        system_prompts = self._build_system_prompt()
        return build_full_history_messages(
            system_prompts, self._history, self.current_character_agent,
        )

    # ------------------------------------------------------------------
    # 公共生命周期/状态访问接口（供 LoopSessionManager 等外部调用）
    # ------------------------------------------------------------------

    @property
    def llm(self) -> BaseLLMClient | None:
        """返回当前 loop 的 LLM 客户端。"""
        return self._llm

    @property
    def active_max_context_tokens(self) -> int:
        """返回活跃配置的上下文窗口大小。无 active profile 时用 LlmProfile 字段默认值。"""
        if self._active_llm_profile:
            return self._active_llm_profile.max_context_tokens or LLMProfile().max_context_tokens
        return LLMProfile().max_context_tokens

    @property
    def active_max_output_tokens(self) -> int:
        """返回活跃配置的最大输出 token 数。无 active profile 时用 LlmProfile 字段默认值。"""
        if self._active_llm_profile:
            return self._active_llm_profile.max_output_tokens or LLMProfile().max_output_tokens
        return LLMProfile().max_output_tokens

    def set_profile(self, profile: LLMProfile | None) -> None:
        """同步安装根对象中的 Profile；None 表示明确清空配置。"""
        if profile is None:
            client = None
        else:
            client = create_llm_client(
                profile.llm_client_name,
                self.app.runtime_context,
                profile,
            )
        self._llm = client
        self._stream_consumer.llm = client
        self._active_llm_profile = profile
        if self._session_store is not None:
            self._session_store.write_active_profile_name(
                self.session_id,
                profile.name if profile is not None else "",
            )
        logger.info(
            "LLM Profile selected | session=%s name=%s model=%s",
            self.session_id,
            profile.name if profile is not None else "(none)",
            profile.model if profile is not None else "(none)",
        )

    def switch_llm_profile(self, profile: LLMProfile) -> None:
        """兼容内部旧调用名称；委托给 ``set_profile``。"""
        self.set_profile(profile)

    @property
    def last_prompt_tokens(self) -> int:
        """返回最近一次 prompt 的 token 数。"""
        return self._token_record.prompt_tokens

    @last_prompt_tokens.setter
    def last_prompt_tokens(self, value: int) -> None:
        """设置最近一次 prompt 的 token 数。"""
        self._token_record.prompt_tokens = value

    def get_full_history(self, session_id: str) -> list[BaseMessage]:
        """返回完整历史消息（供外部生命周期管理使用）。"""
        return self._get_full_history(session_id)

    def append_history(
        self, session_id: str, role: Role,
        content: str | list[dict[str, Any]],
        **kwargs: Any,
    ) -> int:
        """追加一条消息到历史并持久化。"""
        return self._append(session_id, role, content, **kwargs)

    def remove_last_user_message(self, session_id: str) -> None:
        """移除 History 中最后一条 user 消息并持久化。"""
        self._remove_last_user_message(session_id)

    def build_inherited_context(self, old_sid: str, summary: str) -> str:
        """为继承会话构建初始上下文消息。"""
        from system.templates import read_template
        return (
            read_template("session_inherit.txt")
            .replace("{{old_sid}}", old_sid)
            .replace("{{summary}}", summary)
        )

    def reset_history(self, session_id: str | None = None) -> None:
        """清空当前历史并可选持久化。"""
        self._history = History()
        self._token_record = TokenUsageRecord()
        if session_id is not None:
            self.save_history(session_id)

    def load_history(self, history: History) -> None:
        """从外部加载历史到当前 loop。"""
        self._history = history

    def _store_assistant_with_tools(
        self, session_id: str, resp: LLMResponse,
    ) -> int:
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
        message = CharacterConversationMessage(
            role=Role.ASSISTANT,
            character_name=self.current_character_agent,
            content=resp.content or "",
            tool_calls=tool_calls_data,
            reasoning=resp.reasoning_content,
            reasoning_field_name=resp.reasoning_field_name,
        )
        index = self._history.add_message(message)
        self.save_history(session_id)
        return index

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
                elif isinstance(block, AudioBlock):
                    parts.append("[input_audio]")
                elif isinstance(block, dict) and block.get("type") == "text":
                    parts.append(str(block.get("text", "")))
            return "\n".join(parts)
        return str(content or "")

    # ========================================================================
    # Hooks / Skill prompts
    # ========================================================================

    def _collect_skill_prompts(self) -> list[str]:
        from entry.agent_support.messages import collect_skill_prompts
        return collect_skill_prompts()

    # ========================================================================
    # Usage / Stream 推送
    # ========================================================================

    async def _emit_stream_done(
        self, session_id: str, stream_id: str, finish_reason: str,
        content: str = "",
        metrics: MessageMetrics | None = None,
    ) -> None:
        try:
            await self._frontend_sink.emit_stream_done(
                session_id, stream_id, finish_reason,
                content=content,
                metrics=metrics,
            )
        except Exception:
            logger.warning(
                "Failed to emit stream_done for session=%s stream=%s",
                session_id, stream_id, exc_info=True,
            )

    # ========================================================================
    # 会话管理（业务级）
    # ========================================================================

    async def terminate_session(self) -> dict:
        logger.info("Terminating session (parent) | session=%s", self.session_id)
        await self._lifecycle.terminate_session()
        logger.info("Terminate session ok (parent) | session=%s", self.session_id)
        return {"terminated": True, "session_id": self.session_id}

    def _load_history_from_disk(self, session_id: str) -> History:
        if self._session_store is None:
            return History()
        try:
            history = self._session_store.read_history(session_id)
            return history if history is not None else History()
        except Exception as exc:
            logger.exception(
                "Failed to load history for session %s: %s", session_id, exc,
            )
            return History()