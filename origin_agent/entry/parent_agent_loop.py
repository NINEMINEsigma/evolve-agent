"""ParentAgentLoop — 主 Agent 循环，继承 BasePrivateChatAgentLoop。

实现流式 LLM 调用、Memory 管理、session 旋转/归档、
工具审批流程和前端事件推送。每个 session 对应一个实例。

高层编排保留于此；具体职责委托给：
  - LoopSessionManager（session 生命周期）
  - ToolExecutor（工具审批/分发/事件）
  - StreamConsumer（LLM 流消费）
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, TYPE_CHECKING

from abstract.memory.manager import MemoryManager
from abstract.tools.registry import registry as tool_registry
from component.approval import ask_agent_reason
from component.llm import LLMClient, LLMResponse, ToolCall
from system.session_store import SessionStore
from entity.constant import (
    LOG_PREVIEW_CHARS,
    AUTO_TITLE_CONTENT_MAX,
    AUTO_TAGS_CONTENT_MAX,
    MAX_TOOL_TURNS,
    MAIN_AGENT_CHARACTER_NAME,
    USER_CHARACTER_NAME,
)
from entity.messages import (
    History,
    CharacterConversationMessage,
    FunctionCall,
    ImageBlock,
    TextBlock,
    ToolCall as HistoryToolCall,
)
from entity.puretype import Role, ToolAvailability
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
        self._llm: LLMClient = LLMClient(app.runtime_context)
        self._memory: MemoryManager = MemoryManager()
        self._memory_initialized_ids: set[int] = set()

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
        for schema in self._memory.get_tool_schemas():
            definitions.append({"type": "function", "function": schema})
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

    def add_memory_provider(self, provider: Any) -> None:
        self._memory.add_provider(provider)

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

            # 延迟初始化 memory provider
            for provider in self._memory.providers:
                if id(provider) in self._memory_initialized_ids:
                    continue
                try:
                    provider.initialize(sid)
                    self._memory_initialized_ids.add(id(provider))
                except Exception:
                    logger.exception(
                        "Failed to initialize memory provider for session=%s", sid,
                    )

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
                    self._memory.sync_all(self._history, session_id=sid)
                    return assistant_text

                # 存储 assistant 消息（含 tool_calls）
                self._store_assistant_with_tools(sid, resp)

                # 委托给 ToolExecutor 执行工具调用
                for tc in resp.tool_calls:
                    tool_msg = await self._tool_executor.execute(tc, sid)
                    openai_tool_msg = tool_msg.as_message(self.current_character_agent)
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
        merged = "\n\n".join(msg.to_text() for msg in pending)
        character_name = (
            pending[0].character_name
            if len(pending) == 1
            else USER_CHARACTER_NAME
        )
        message = CharacterConversationMessage(
            role=Role.USER,
            character_name=character_name,
            content=merged,
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
        memory_ctx = self._get_memory_context(str(content))

        dynamic_parts: list[str] = []
        if memory_ctx:
            dynamic_parts.append(
                f"<|im_memory_context_start|>\n{memory_ctx}\n<|im_memory_context_end|>",
            )
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
        if isinstance(content, str):
            message_content: str | list[ImageBlock | TextBlock] = content
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
    ) -> list[ImageBlock | TextBlock]:
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
                    result.append(
                        ImageBlock(image_url=str(image_url_block.get("url", ""))),
                    )
                else:
                    result.append(ImageBlock(image_url=str(image_url_block or "")))
        return result

    def _get_memory_context(self, user_message: str) -> str:
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
            system_prompts, self._history, self.current_character_agent,
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
        messages = self._get_full_history(self.session_id)
        if not messages:
            return ""
        from system.templates import read_template
        system_prompt = read_template("auto_title.txt")
        user_prompt = read_template("auto_title_input.txt").replace(
            "{{context}}",
            json.dumps(messages, ensure_ascii=False)[:AUTO_TITLE_CONTENT_MAX],
        )
        try:
            resp = await self._llm.chat([
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ])
            title = (resp.content or "").strip().strip("\"'")[:50]
            return title
        except Exception as exc:
            logger.exception("Failed to auto-generate title: %s", exc)
            return ""

    async def regenerate_session_tags(self) -> list[str]:
        messages = self._get_full_history(self.session_id)
        if not messages:
            return []
        from system.templates import read_template
        try:
            system_prompt = read_template("session_tags.txt")
            user_prompt = read_template("session_tags_input.txt").replace(
                "{{old_text}}",
                json.dumps(messages, ensure_ascii=False)[:AUTO_TAGS_CONTENT_MAX],
            )
            resp = await self._llm.chat([
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
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

    # ========================================================================
    # 会话管理（业务级）
    # ========================================================================

    async def terminate_session(self) -> dict:
        await self._lifecycle.terminate_session()
        return {"terminated": True, "session_id": self.session_id}

    async def merge_sessions(self, sources: list[str]) -> dict:
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

    def _load_history_from_disk(self, session_id: str) -> History:
        if self._session_store is None:
            return History(messages=[])
        try:
            history = self._session_store.read_history(session_id)
            return history if history is not None else History(messages=[])
        except Exception as exc:
            logger.exception(
                "Failed to load history for session %s: %s", session_id, exc,
            )
            return History(messages=[])

    def is_processing(self) -> bool:
        return self._processing