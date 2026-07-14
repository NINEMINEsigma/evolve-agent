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
from component.approval import ask_agent_reason
from abstract.llm.client import BaseLLMClient
from abstract.llm.loader import create_llm_client
from abstract.llm.formats import to_openai_message, to_summary_dict
from entity.puretype import LLMResponse, ToolCall, Role, ToolAvailability
from system.session_store import SessionStore
from entity.constant import (
    LOG_PREVIEW_CHARS,
    AUTO_TITLE_CONTENT_MAX,
    AUTO_TAGS_CONTENT_MAX,
    MAX_TOOL_TURNS,
    MAIN_AGENT_CHARACTER_NAME,
    USER_CHARACTER_NAME,
    SYSTEM_CHARACTER_NAME,
    INHERIT_LAST_ROUNDS,
)
from entity.messages import (
    History,
    BaseMessage,
    CharacterConversationMessage,
    FunctionCall,
    ImageBlock,
    TextBlock,
    MessageBlock,
    ToolCall as HistoryToolCall,
)
from entry.base_agent_loop import BasePrivateChatAgentLoop, IMainSessionLoop
from entry.agent_sink import AgentSink, FrontendSink
from entry.agent_support.messages import (
    build_agent_system_prompt,
    build_full_history_messages,
)
from entry.agent_support.multimodal import (
    content_to_text,
    is_content_block_error,
    strip_image_blocks,
    summarize_message_for_log,
)
from entry.session_manager import LoopSessionManager
from entry.tool_executor import ToolExecutor
from entry.stream_consumer import StreamConsumer

if TYPE_CHECKING:
    from gateway.session_manager import SessionManager
    from system.application import Application
    from system.context import RuntimeContext

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
        self._llm: BaseLLMClient = create_llm_client(
            app.runtime_context.llm_client_name,
            app.runtime_context,
        )

        self._session_store = (
            SessionStore(history_store_dir)
            if history_store_dir else None
        )

        # -- 生命周期管理（委托给 LoopSessionManager） --
        self._lifecycle: LoopSessionManager = LoopSessionManager(
            loop=self, history_store_dir=history_store_dir,
        )
        self._lifecycle.initialize()

        # -- 工具执行器 --
        self._tool_executor: ToolExecutor = ToolExecutor(loop=self, llm=self._llm)

        # -- LLM 流消费器 --
        self._stream_consumer: StreamConsumer = StreamConsumer(
            llm=self._llm,
            sink=self._frontend_sink,
            character_name=MAIN_AGENT_CHARACTER_NAME,
            cancel_event=self._cancel_event,
        )

        # -- 工具调用事件回调 --
        self._tool_event_callback: Callable[[str, str, str, str], Awaitable[None]] | None = None

        # -- 处理状态 --
        self._processing: bool = False
        self._process_lock: asyncio.Lock = asyncio.Lock()
        self._event_loop: asyncio.AbstractEventLoop | None = None

        # -- 子 Agent 周期收集器用的空闲时间戳 --
        self._last_idle_time: dict[str, float] = {session_id: time.monotonic()}

    def get_last_idle_time(self, session_id: str) -> float | None:
        """返回指定 session 上次进入空闲的时间戳，不存在时返回 None。"""
        return self._last_idle_time.get(session_id)

    # TODO: 未被使用
    def update_last_idle_time(self, session_id: str) -> None:
        """更新指定 session 的空闲时间戳。"""
        self._last_idle_time[session_id] = time.monotonic()

        # -- 子 Agent 编排器（由 server 层注入） --
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

    def _get_llm_client(self) -> BaseLLMClient:
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
        self._tool_event_callback = cb

    def set_session_manager(self, manager: Any) -> None:
        self._session_manager = manager

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
        user_message: str,
        *,
        skip_append: bool = False,
        character_name: str = USER_CHARACTER_NAME,
        **kwargs,
    ) -> str:
        sid = self.session_id
        self._cancel_event.clear()
        self._processing = True
        self._event_loop = asyncio.get_running_loop()

        logger.info(
            "Received user message | session=%s content=%s",
            sid, summarize_message_for_log(user_message),
        )
        async with self._process_lock:
            self._maybe_inject_inbox()
            if not skip_append:
                await self.append_user_message(user_message, character_name=character_name)

            # 历史过长时自动终结会话
            if self._lifecycle.is_context_over_limit():
                new_sid: str | None = await self._lifecycle.rotate_session_for_continuation(
                    sid, pending_user_message=user_message,
                )
                if new_sid:
                    sid = new_sid
                    self.session_id = new_sid

            messages = self._build_history_messages(user_message)

            try:
                return await self._run_tool_loop(sid, messages, user_message)
            finally:
                self._processing = False
                self._last_idle_time[self.session_id] = time.monotonic()

    async def _run_tool_loop(
        self,
        sid: str,
        messages: list[dict[str, Any]],
        user_message: str,
    ) -> str:
        """执行 LLM 工具调用循环（含 inbox 消息消费）。"""
        self._cancel_event.clear()

        turn: int = 0
        try:
            while turn < _MAX_TOOL_TURNS:
                if self._cancel_event.is_set():
                    return "Cancelled."
                turn += 1

                self._maybe_inject_inbox(messages)

                stream_id: str = uuid.uuid4().hex[:12]
                try:
                    resp = await self._stream_consumer.consume(
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
                    return (
                        f"The service provider returned an error, please try again later. "
                        f"Details: {llm_exc}"
                    )

                if self._cancel_event.is_set():
                    await self._emit_stream_done(sid, stream_id, "cancelled")
                    if resp.content:
                        self._append(
                            sid, Role.ASSISTANT, resp.content,
                            reasoning_content=resp.reasoning_content,
                            reasoning_field_name=resp.reasoning_field_name,
                        )
                        return resp.content
                    return "Cancelled."

                if resp.usage.prompt_tokens:
                    self._last_prompt_tokens = resp.usage.prompt_tokens
                    self._token_usage += resp.usage.total_tokens
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

                await self._emit_stream_done(sid, stream_id, resp.finish_reason)

                if not resp.tool_calls:
                    assistant_text = resp.content or ""
                    self._append(
                        sid, Role.ASSISTANT, assistant_text,
                        reasoning_content=resp.reasoning_content,
                        reasoning_field_name=resp.reasoning_field_name,
                    )
                    return assistant_text

                # 存储 assistant 消息（含 tool_calls）
                self._store_assistant_with_tools(sid, resp)

                # 委托给 ToolExecutor 执行工具调用
                for tc in resp.tool_calls:
                    tool_msg = await self._tool_executor.execute(tc, sid)
                    openai_tool_msg = to_openai_message(tool_msg, current_character_agent=self.current_character_agent)
                    if openai_tool_msg is not None:
                        messages.append(openai_tool_msg)
                    self._history.add_message(tool_msg)
                    self._persist_message(sid)
                    await self._push_usage_update(sid)

                    if tc.name == "evolve_code":
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

                if self._lifecycle.is_context_over_limit():
                    new_sid = await self._lifecycle.rotate_session_for_continuation(sid)
                    if new_sid:
                        sid = new_sid
                        self.session_id = new_sid

                messages = self._get_full_history(sid)

        finally:
            pass

        logger.warning(
            "Tool-call loop exceeded max turns (%d) for session=%s",
            _MAX_TOOL_TURNS, sid,
        )
        return "I ran into an issue processing your request. Please try again."

    # ========================================================================
    # Inbox 消息消费
    # ========================================================================

    def _maybe_inject_inbox(
        self, target_messages: list[dict[str, Any]] | None = None,
    ) -> bool:
        pending = self._inbox.get_pending()
        if not pending:
            return False
        for pending_message in pending:
            message = CharacterConversationMessage(
                role=Role.USER,
                character_name=pending_message.character_name,
                content=pending_message.to_text(),
                visible_characters=[self.current_character_agent],
            )
            self._history.add_message(message)
            self._persist_message(self.session_id)
            if target_messages is not None:
                openai_msg = to_openai_message(message, current_character_agent=self.current_character_agent)
                if openai_msg is not None:
                    target_messages.append(openai_msg)
        return True

    async def process_inbox(self) -> str | None:
        async with self._process_lock:
            if self._cancel_event.is_set():
                return None

            messages = self._get_full_history(self.session_id)
            if not self._maybe_inject_inbox(messages):
                return None

            sid = self.session_id
            self._cancel_event.clear()
            self._processing = True
            self._event_loop = asyncio.get_running_loop()

            try:
                reply = await self._run_tool_loop(sid, messages, "[cron-result]")
            finally:
                self._processing = False
                self._last_idle_time[self.session_id] = time.monotonic()

            if reply:
                try:
                    await self._frontend_sink.emit_assistant_message(
                        sid, reply, self.current_character_agent,
                    )
                except Exception as exc:
                    logger.exception(
                        "Failed to send ASSISTANT_MESSAGE for inbox processing: %s", exc,
                    )

            return reply

    def schedule_inbox_processing(self) -> None:
        loop = self._event_loop
        if loop is None or loop.is_closed():
            return
        try:
            asyncio.run_coroutine_threadsafe(self.process_inbox(), loop)
        except Exception as exc:
            logger.exception("Failed to schedule inbox processing: %s", exc)

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
            message_content = self._blocks_from_dicts(content)
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
        self._persist_message(session_id)
        return index

    @staticmethod
    def _blocks_from_dicts(
        blocks: list[dict[str, Any]],
    ) -> list[MessageBlock]:
        result: list[MessageBlock] = []
        for block in blocks:
            if not isinstance(block, dict):
                continue
            btype = block.get("type")
            if btype == "text":
                result.append(TextBlock(text=str(block.get("text", ""))))
            elif btype == "image_url":
                image_url_block = block.get("image_url")
                if isinstance(image_url_block, dict):
                    result.append(
                        ImageBlock(image_url=str(image_url_block.get("url", ""))),
                    )
                else:
                    result.append(ImageBlock(image_url=str(image_url_block or "")))
        return result

    def _get_full_history(self, session_id: str) -> list[BaseMessage]:
        system_prompts: list[str] = build_agent_system_prompt(
            self.app.runtime_context,
            self._collect_skill_prompts(),
        )
        return build_full_history_messages(
            system_prompts, self._history, self.current_character_agent,
        )

    # ------------------------------------------------------------------
    # 公共生命周期/状态访问接口（供 LoopSessionManager 等外部调用）
    # ------------------------------------------------------------------

    @property
    def session_store(self) -> SessionStore | None:
        """返回当前 loop 的 session 持久化存储。"""
        return self._session_store

    @property
    def session_manager(self) -> SessionManager | None:
        """返回当前 loop 关联的 gateway SessionManager。"""
        return self._session_manager

    @property
    def llm(self) -> BaseLLMClient:
        """返回当前 loop 的 LLM 客户端。"""
        return self._llm

    @property
    def last_prompt_tokens(self) -> int:
        """返回最近一次 prompt 的 token 数。"""
        return self._last_prompt_tokens

    @last_prompt_tokens.setter
    def last_prompt_tokens(self, value: int) -> None:
        """设置最近一次 prompt 的 token 数。"""
        self._last_prompt_tokens = value

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
        self._last_prompt_tokens = 0
        if session_id is not None:
            self._persist_message(session_id)

    def load_history(self, history: History) -> None:
        """从外部加载历史到当前 loop。"""
        self._history = history

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
        message = CharacterConversationMessage(
            role=Role.ASSISTANT,
            character_name=self.current_character_agent,
            content=resp.content or "",
            tool_calls=tool_calls_data,
            reasoning=resp.reasoning_content,
            reasoning_field_name=resp.reasoning_field_name,
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
    ) -> None:
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
    # 自动生成标题 / 标签
    # ========================================================================

    async def auto_generate_title(self) -> str:
        raw_messages = self._get_full_history(self.session_id)
        if not raw_messages:
            return ""
        from system.templates import read_template
        system_prompt = read_template("auto_title.txt")
        # 将 BaseMessage 列表转为 JSON 可序列化的 dict 列表（供模板使用）
        messages_json = [
            d for m in raw_messages
            if (d := to_summary_dict(m, current_character_agent=self.current_character_agent)) is not None
        ]
        user_prompt = read_template("auto_title_input.txt").replace(
            "{{context}}",
            json.dumps(messages_json, ensure_ascii=False)[:AUTO_TITLE_CONTENT_MAX],
        )
        try:
            resp = await self._llm.chat([
                BaseMessage(role=Role.SYSTEM, content=system_prompt),
                BaseMessage(role=Role.USER, content=user_prompt),
            ], character=self.current_character_agent)
            title = (resp.content or "").strip().strip("\"'")[:50]
            return title
        except Exception as exc:
            logger.exception("Failed to auto-generate title: %s", exc)
            return ""

    async def regenerate_session_tags(self) -> list[str]:
        raw_messages = self._get_full_history(self.session_id)
        if not raw_messages:
            return []
        from system.templates import read_template
        try:
            system_prompt = read_template("session_tags.txt")
            # 将 BaseMessage 列表转为 JSON 可序列化的 dict 列表（供模板使用）
            messages_json = [
                d for m in raw_messages
                if (d := to_summary_dict(m, current_character_agent=self.current_character_agent)) is not None
            ]
            user_prompt = read_template("session_tags_input.txt").replace(
                "{{old_text}}",
                json.dumps(messages_json, ensure_ascii=False)[:AUTO_TAGS_CONTENT_MAX],
            )
            resp = await self._llm.chat([
                BaseMessage(role=Role.SYSTEM, content=system_prompt),
                BaseMessage(role=Role.USER, content=user_prompt),
            ], character=self.current_character_agent)
            content = resp.content or ""
            try:
                tags = json.loads(content)
                if isinstance(tags, list):
                    return [str(t) for t in tags[:5]]
                elif content:
                    return [str(content)]
            except json.JSONDecodeError:
                pass
        except Exception as exc:
            logger.exception("Failed to generate session tags: %s", exc)
        return []

    # ========================================================================
    # 会话管理（业务级）
    # ========================================================================

    async def terminate_session(self) -> dict:
        await self._lifecycle.terminate_session()
        return {"terminated": True, "session_id": self.session_id}

    async def regenerate_summary_for_session(self, session_id: str) -> str:
        """重新生成指定会话的摘要（可为任意 session_id，不要求当前活跃）。"""
        if self._session_store is None:
            return ""
        history = self._session_store.read_history(session_id)
        if history is None or history.count == 0:
            return ""
        from entry.agent_support.history_summary import summarize_history
        summary = await summarize_history(history, self._llm)
        if summary:
            self._session_store.write_summary(session_id, summary)
        return summary

    async def merge_sessions(self, sources: list[str]) -> dict:
        """合并多个已归档会话到一个新会话，基于摘要而非完整历史。

        单源分支：读取源 session 的 summary.txt，使用 session_inherit 模板构建初始消息。
        多源合并：拼接各源 session 的摘要，按阈值截断。
        新 session 只包含 summary 消息，源 sessions 归档并标记 continuation_sid。
        """
        if self._session_manager is None:
            return {"error": "session manager not available", "merged": False}
        if not sources:
            return {"error": "sources list is empty", "merged": False}
        if self._session_store is None:
            return {"error": "session store not available", "merged": False}

        # 收集各源 session 的摘要，缺失时自动生成
        from entity.constant import MERGE_SUMMARY_CONCAT_MAX_CHARS
        from entry.agent_support.history_summary import summarize_history
        summaries: list[str] = []
        for sid in sources:
            summary = self._session_store.read_summary(sid)
            logger.info(
                "merge_sessions: source=%s summary_len=%d",
                sid, len(summary),
            )
            if not summary:
                # 摘要缺失时自动生成（可能是旧 session 未归档生成过）
                history = self._session_store.read_history(sid)
                if history and history.count > 0:
                    summary = await summarize_history(history, self._llm)
                    if summary:
                        self._session_store.write_summary(sid, summary)
            if summary:
                summaries.append(
                    f"[Session {sid}]: {summary}"
                )

        logger.info(
            "merge_sessions: collected %d summaries from %d sources",
            len(summaries), len(sources),
        )
        if not summaries:
            return {"error": "no summaries found for source sessions", "merged": False}

        # 拼接摘要
        context: str
        if len(summaries) == 1:
            # 单源分支：使用 session_inherit 模板
            from system.templates import read_template
            context = (
                read_template("session_inherit.txt")
                .replace("{{old_sid}}", sources[0])
                .replace("{{summary}}", summaries[0])
            )
        else:
            # 多源合并：按顺序拼接，阈值截断
            joined = "\n\n---\n\n".join(summaries)
            if len(joined) > MERGE_SUMMARY_CONCAT_MAX_CHARS:
                joined = joined[:MERGE_SUMMARY_CONCAT_MAX_CHARS] + "\n\n... [truncated]"
            context = (
                f"This session merges multiple previous sessions. "
                f"Here are their summaries:\n\n"
                f"{joined}"
            )

        # 创建新 session
        new_sid = self._session_manager.create_with_context(
            context=context,
            parent_sid=sources[0],
            parents=sources,
            role=Role.USER,
        )

        # 从各源会话附加尾部轮次文本到 context
        from entry.agent_support.history_summary import messages_to_text, extract_last_rounds
        tail_blocks: list[str] = []
        for sid in sources:
            try:
                src_history = self._session_store.read_history(sid)
                if src_history is None or src_history.count == 0:
                    continue
                tail_msgs = extract_last_rounds(
                    src_history,
                    rounds=INHERIT_LAST_ROUNDS,
                    include_tool_messages=False,
                )
                if tail_msgs:
                    tail_blocks.append(
                        f"### Source session {sid}\n" + messages_to_text(tail_msgs)
                    )
            except Exception as exc:
                logger.exception("Failed to append tail rounds for source=%s: %s", sid, exc)
        if tail_blocks:
            context += "\n\n## Recent conversation rounds\n" + "\n\n---\n\n".join(tail_blocks)

        # 写入仅含 summary 消息的历史
        summary_history = History()
        summary_history.add_message(CharacterConversationMessage(
                role=Role.USER,
                character_name=SYSTEM_CHARACTER_NAME,
                content=context,
                visible_characters=[self.current_character_agent],
            ))
        self._session_store.write_history(new_sid, summary_history)

        # 归档源 sessions
        for sid in sources:
            self._session_manager.archive(sid, continuation_sid=new_sid)

        logger.info(
            "Sessions merged | new=%s sources=%s summaries=%d",
            new_sid, sources, len(summaries),
        )
        return {"merged": True, "session_id": new_sid, "sources": sources}

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

    def is_processing(self) -> bool:
        return self._processing