"""Agent 主循环 — 接收用户消息，流式调用 LLM + 工具，边生成边推送回复。

将抽象层的三个子系统串联起来：
  - ``abstract.tools.registry`` — 工具 schema 发现与分发
  - ``abstract.memory.manager`` — memory 预取 / 同步
  - ``component.llm`` — LLM 客户端（chat_stream 流式 + chat 非流式）

每个 session 的消息历史保存在内存中。LLM 响应通过 ``chat_stream``
逐块接收，以 ``stream_delta`` / ``stream_done`` 消息实时推送到前端。
工具在启动时通过 ``abstract.tools.discover.discover_builtin_tools`` 发现。
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List

from abstract.memory.manager import MemoryManager
from abstract.tools.registry import ToolEntry, registry as tool_registry
from component.approval import ApprovalResult, ask_agent_reason, is_handsfree_mode, request_user_confirm
from component.approval_allowlist import add_allowed as add_tool_allowlist_entry
from component.approval_allowlist import is_allowed as is_tool_allowlisted
from component.llm import LLMClient, LLMResponse, StreamChunk, ToolCall, Usage
from system.pathutils import find_repo_root
from system.context import RuntimeContext
from system.session_store import SessionStore
from entity.constant import LOG_PREVIEW_CHARS, TOOL_RESULT_PREVIEW_CHARS, AUTO_TITLE_CONTENT_MAX, MAX_TOOL_TURNS
from entity.puretype import Role
from entry.agent_support.messages import (
    build_agent_system_prompt,
    build_full_history_messages,
    build_turn_messages,
    collect_hooks_context,
    load_message_hooks,
)
from entry.agent_support.multimodal import (
    build_image_content_blocks,
    is_content_block_error,
    sanitize_image_payload,
    strip_image_blocks,
    summarize_message_for_log,
    supports_vision,
)

logger = logging.getLogger(__name__)

# 每条消息的最大工具调用循环次数，防止无限循环。
_MAX_TOOL_TURNS: int = MAX_TOOL_TURNS


async def _close_async_iterator(ait: Any) -> None:
    """安全关闭异步迭代器，避免未读取完成的流留下资源泄漏。"""
    try:
        await ait.aclose()
    except Exception:
        pass


# ---------------------------------------------------------------------------


class AgentLoop:
    """每个进程的单例，编排一次 LLM 会话回合。

    用法::

        loop = AgentLoop(ctx)
        reply = await loop.process_message(session_id, user_message)
    """

    def __init__(self, ctx: RuntimeContext, history_store_path: str | None = None) -> None:
        self._ctx: RuntimeContext = ctx
        self._llm: LLMClient = LLMClient(ctx)
        self._memory: MemoryManager = MemoryManager()
        # 记录哪些 session 已完成 memory provider 初始化
        self._memory_initialized: dict[str, bool] = {}
        # 记录哪些 session 已收到中断请求
        self._interrupted: dict[str, bool] = {}
        # 每个 session 的取消事件 — 由 interrupt() 设置，
        # 由 process_message() 检查，用于立即取消正在进行的 LLM HTTP 请求。
        self._cancel_events: dict[str, asyncio.Event] = {}
        # 每个 session 的会话历史：session_id → OpenAI 格式的消息列表
        self._histories: dict[str, list[dict[str, Any]]] = {}
        # Skill prompt 缓存 — skill 被修改后失效
        self._skill_cache: list[str] = []
        # skill 缓存是否有效
        self._skill_cache_valid: bool = False
        # 累计 token 消耗，仅用于 dashboard 展示。
        self._token_usage: dict[str, int] = {}
        # 最近一次 LLM 调用返回的真实 prompt_tokens（上下文占用锚点）
        self._last_prompt_tokens: dict[str, int] = {}
        # SessionManager 引用（由 server.py 注入），用于归档+旋转会话
        self._session_manager: Any | None = None
        # 会话旋转通知队列：old_sid -> new_sid（server.py 在 process_message 后检查并推送前端）
        self._session_rotated_notify: dict[str, str] = {}
        # 工具调用统计，用于 dashboard 监控。
        # key 为工具名，value 为 {"calls": int, "errors": int}
        self._tool_stats: dict[str, dict[str, int]] = {}
        # 工具调用事件回调，在 tool_call / tool_result 时触发。
        # 签名：async (session_id, event_type, tool_name, payload) -> None
        self._tool_event_callback: Callable[[str, str, str, str], Awaitable[None]] | None = None
        # 消息历史的磁盘持久化目录
        self._history_store_dir: Path | None = Path(history_store_path) if history_store_path else None
        self._session_store: SessionStore | None = SessionStore(self._history_store_dir) if self._history_store_dir else None
        # 自定义消息 hook 缓存（custom_hooks/ 下的扩展上下文脚本）
        self._message_hooks_cache: list[dict] | None = None
        # 每个 session 的排他锁，防止并发 process_message 破坏消息序列
        # （如 cron 定时任务回调与主流程同时写入同一 session）
        self._session_locks: dict[str, asyncio.Lock] = {}
        # 记录哪些 session 正在处理消息（process_message 未返回）
        self._processing_sessions: dict[str, bool] = {}

        # 父 Agent 最后一次消息处理结束的时间戳（供 SubAgentOrchestrator 空闲检测）
        self._last_idle_time: float = time.monotonic()

    # -- 公开 API ----------------------------------------------------------

    def set_tool_event_callback(
        self,
        cb: Callable[[str, str, str, str], Awaitable[None]],
    ) -> None:
        """注册工具执行事件的异步回调。

        *cb* 调用参数为 ``(session_id, event_type, tool_name, payload)``，
        其中 *event_type* 为 ``"tool_call"`` 或 ``"tool_result"``，
        *payload* 为 JSON 字符串。
        """
        self._tool_event_callback = cb

    def set_session_manager(self, manager: Any) -> None:
        """注入 SessionManager 引用，用于归档会话。"""
        self._session_manager = manager

    def add_memory_provider(self, provider: Any) -> None:
        """注册 memory provider，避免外部直接访问内部 memory manager。"""
        self._memory.add_provider(provider)

    def pop_session_rotated(self, session_id: str) -> str | None:
        """取出并移除指定 session 的旋转通知。"""
        return self._session_rotated_notify.pop(session_id, None)

    def get_all_token_usage(self) -> dict[str, int]:
        """返回所有已加载 session 的 token 消耗快照。"""
        return dict(self._token_usage)

    def get_all_tool_stats(self) -> dict[str, dict[str, int]]:
        """返回工具调用统计快照。"""
        return {name: dict(stats) for name, stats in self._tool_stats.items()}

    def interrupt(self, session_id: str) -> None:
        """请求停止指定 session 的 agent 循环处理。

        同时拒绝该 session 所有待处理的 shell 命令确认请求，
        使阻塞中的 ``_request_user_confirm()`` 立即解除阻塞。
        """
        self._interrupted[session_id] = True
        # 设置取消事件，使正在进行的 LLM 调用立即中止，
        # 而不是等待 HTTP 响应完成。
        ev = self._cancel_events.get(session_id)
        if ev is not None:
            ev.set()
        try:
            from gateway.server import _deny_session_confirms
            _deny_session_confirms(session_id)
        except Exception:
            pass
        # 暂停子 Agent 周期定时器（子 Agent 本身继续运行）
        try:
            from gateway.server import get_subagent_orchestrator
            get_subagent_orchestrator().interrupt()
        except Exception:
            pass
        logger.info("Interrupt requested for session=%s", session_id)

    def is_interrupted(self, session_id: str) -> bool:
        """返回 True 表示该 session 存在活跃的中断请求。"""
        ev = self._cancel_events.get(session_id)
        return ev is not None and ev.is_set()

    def is_processing(self, session_id: str) -> bool:
        """返回 True 表示该 session 当前正在处理消息。"""
        return self._processing_sessions.get(session_id, False)

    async def process_message(
        self,
        session_id: str,
        user_message: str | list[dict[str, Any]],
    ) -> str:
        """处理一条用户消息，返回助手的回复。

        核心 agent 循环：
          1. 预取 memory 上下文
          2. 构建带 system prompt 的消息历史
          3. 调用 LLM，执行工具调用，重复直到得到文本回复
          4. 将完成的本回合同步到 memory
        """
        # 获取或创建 session 级排他锁，防止并发 process_message
        # 破坏消息序列（如 cron 回调与主流程同时写入同一 session）
        if session_id not in self._session_locks:
            self._session_locks[session_id] = asyncio.Lock()
        async with self._session_locks[session_id]:
            return await self._process_message_locked(session_id, user_message)

    async def _process_message_locked(
        self,
        session_id: str,
        user_message: str | list[dict[str, Any]],
    ) -> str:
        """process_message 的锁内实现。"""
        # 清除上一回合残留的过期中断标记
        self._interrupted.pop(session_id, None)
        # 恢复子 Agent 周期定时器（用户发消息后恢复）
        try:
            from gateway.server import get_subagent_orchestrator
            get_subagent_orchestrator().resume()
        except Exception:
            pass
        # ---- 拒绝已归档会话的新消息 ----
        if self._session_manager is not None:
            info = self._session_manager.get(session_id)
            if info and info.get("status") == "archived":
                return "This session has been archived. Please continue in the new session or start a new one."
        # ---- 持久化用户消息 ----
        logger.info(
            "Received user message | session=%s content=%s",
            session_id, summarize_message_for_log(user_message),
        )
        self._append(session_id, Role.USER, user_message)
        # ---- 延迟初始化 memory provider ----
        if session_id not in self._memory_initialized:
            for provider in self._memory.providers:
                try:
                    provider.initialize(session_id)
                except Exception:
                    pass
            self._memory_initialized[session_id] = True

        # ---- memory 预取 ----
        # memory provider 通常只接受文本摘要，因此传入提取后的文本
        memory_ctx = self._memory.prefetch_all(
            self._extract_text(user_message), session_id=session_id
        )

        # ---- 历史过长时自动终结会话并将当前回合转移到继承会话 ----
        if self._is_context_over_limit(session_id):
            new_sid: str | None = await self._rotate_session_for_continuation(
                session_id,
                pending_user_message=user_message,
            )
            if new_sid:
                session_id = new_sid
                memory_ctx = self._memory.prefetch_all(
                    self._extract_text(user_message), session_id=session_id
                )

        # ---- 构建消息列表 ----
        messages = self._build_messages(session_id, user_message, memory_ctx)

        # ---- 工具调用循环 ----
        # 为每个 session 创建取消事件，使 interrupt() 能够
        # 立即中止正在进行的 LLM HTTP 请求。
        cancel_event: asyncio.Event = asyncio.Event()
        self._cancel_events[session_id] = cancel_event
        # 标记当前 session 正在处理消息
        self._processing_sessions[session_id] = True

        turn: int = 0
        try:
            while turn < _MAX_TOOL_TURNS:
                # ---- 响应中断 ----
                if cancel_event.is_set():
                    return "Cancelled."
                turn += 1

                # ---- 可取消的 LLM 流式调用 ----
                stream_id: str = uuid.uuid4().hex[:12]
                try:
                    resp = await self._stream_llm_response(
                        session_id, messages, self._get_tool_definitions(), cancel_event, stream_id
                    )
                except Exception as llm_exc:
                    # 检查是否因 content blocks（如 image_url）导致 API 拒绝
                    if is_content_block_error(llm_exc):
                        stripped: int = strip_image_blocks(messages, session_id)
                        if stripped > 0:
                            logger.warning(
                                "LLM rejected image content blocks — retrying with text-only "
                                "(stripped %d image(s) from session=%s)",
                                stripped, session_id,
                            )
                            continue  # 重新进入循环，用 text-only 消息重试
                    # 其他异常：记录错误、清理本轮用户消息、返回友好提示，不抛异常
                    logger.exception("LLM call failed for session=%s", session_id)
                    self._remove_last_user_message(session_id)
                    return f"The service provider returned an error, please try again later. Details: {llm_exc}"

                # 处理中断：流式已提前结束
                if cancel_event.is_set():
                    # 仍然发送 stream_done 以便前端刷新流式消息
                    if self._tool_event_callback:
                        await self._tool_event_callback(
                            session_id, "stream_done", "",
                            json.dumps({
                                "stream_id": stream_id,
                                "finish_reason": "cancelled",
                            }),
                        )
                    # 已有内容则保存并返回，否则返回 "Cancelled."
                    if resp.content:
                        self._append(session_id, Role.ASSISTANT, resp.content,
                                     reasoning_content=resp.reasoning_content)
                        return resp.content
                    return "Cancelled."

                # 流式内部已实时累加 token 消耗；这里用最终响应中的
                # prompt_tokens 兜底更新上下文占用锚点，并统一推送。
                if resp.usage.prompt_tokens:
                    self._last_prompt_tokens[session_id] = resp.usage.prompt_tokens
                self._push_usage_update(session_id)

                # 记录 agent 响应日志
                if resp.tool_calls:
                    tool_names = ", ".join(tc.name for tc in resp.tool_calls)
                    logger.info(
                        "Agent response | session=%s tools=[%s] content=%s",
                        session_id, tool_names,
                        (resp.content[:LOG_PREVIEW_CHARS] + "...") if len(resp.content or "") > LOG_PREVIEW_CHARS else (resp.content or ""),
                    )
                else:
                    logger.info(
                        "Agent response | session=%s content=%s",
                        session_id,
                        (resp.content[:LOG_PREVIEW_CHARS] + "...") if len(resp.content or "") > LOG_PREVIEW_CHARS else (resp.content or ""),
                    )

                # 发送流结束标记（必须 await，确保在 agent_message 之前到达前端）
                if self._tool_event_callback:
                    await self._tool_event_callback(
                        session_id, "stream_done", "",
                        json.dumps({
                            "stream_id": stream_id,
                            "finish_reason": resp.finish_reason,
                        }),
                    )

                if not resp.tool_calls:
                    # 纯文本回复 — 存储并返回
                    assistant_text = resp.content or ""
                    self._append(session_id, Role.ASSISTANT, assistant_text,
                                 reasoning_content=resp.reasoning_content)
                    self._memory.sync_all(
                        user_message, assistant_text, session_id=session_id,
                    )
                    return assistant_text

                # 将带 tool_calls 的 assistant 消息存入历史
                self._store_assistant_with_tools(session_id, resp)

                # 执行工具调用并将结果持久化到历史
                history: list[dict[str, Any]] = self._get_history(session_id)
                for tc in resp.tool_calls:
                    tool_msg: dict[str, Any] = await self._execute_tool(tc, session_id)
                    messages.append(tool_msg)
                    history.append(tool_msg)
                    self._persist_message(session_id, tool_msg)

                    self._push_usage_update(session_id)

                    # 如果 evolve_code 执行成功，干净退出循环。
                    # 无需继续 — run.py 编排器会重启我们。
                    if tc.name == "evolve_code":
                        try:
                            parsed: Any = json.loads(tool_msg["content"])
                            if parsed.get("evolved"):
                                self._append(session_id, Role.ASSISTANT, "Evolution complete, restarting to apply new code...")
                                return "Evolution complete, restarting to apply new code..."
                        except (json.JSONDecodeError, KeyError, TypeError):
                            pass

                # Mid-loop 上下文检查：工具结果追加后若接近上限则终结旧会话并转入继承会话
                if self._is_context_over_limit(session_id):
                    new_sid = await self._rotate_session_for_continuation(session_id)
                    if new_sid:
                        session_id = new_sid

                messages = self._get_full_history(session_id)

        finally:
            # 始终清理取消事件，确保下一回合从干净状态开始
            self._cancel_events.pop(session_id, None)
            # 清除处理中标记
            self._processing_sessions.pop(session_id, None)
            # 记录空闲时间戳（供 SubAgentOrchestrator 周期检测）
            self._last_idle_time = time.monotonic()

        logger.warning(
            "Tool-call loop exceeded max turns (%d) for session=%s",
            _MAX_TOOL_TURNS, session_id,
        )
        return "I ran into an issue processing your request. Please try again."

    async def _stream_llm_response(
        self,
        session_id: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        cancel_event: asyncio.Event,
        stream_id: str,
    ) -> LLMResponse:
        """以流式方式调用 LLM，边收边向前端推送增量。

        返回聚合后的完整 LLMResponse。当 cancel_event 被设置时，
        立即停止迭代并返回已收集的内容。
        """
        content: str = ""
        reasoning_content: str = ""
        tool_calls: list[ToolCall] = []
        finish_reason: str = "stop"
        usage: dict[str, int] = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}

        stream = self._llm.chat_stream(messages, tools=tools)
        try:
            async for chunk in stream:
                if cancel_event.is_set():
                    break

                if chunk.error:
                    raise RuntimeError(chunk.error)

                if chunk.content_delta:
                    content += chunk.content_delta
                    if self._tool_event_callback:
                        asyncio.create_task(
                            self._tool_event_callback(
                                session_id, "stream_delta", "",
                                json.dumps({
                                    "stream_id": stream_id,
                                    "delta": chunk.content_delta,
                                }),
                            ),
                            name=f"stream-delta-{session_id}",
                        )

                if chunk.reasoning_delta:
                    reasoning_content += chunk.reasoning_delta
                    if self._tool_event_callback:
                        asyncio.create_task(
                            self._tool_event_callback(
                                session_id, "stream_delta", "",
                                json.dumps({
                                    "stream_id": stream_id,
                                    "reasoning_delta": chunk.reasoning_delta,
                                }),
                            ),
                            name=f"stream-reasoning-{session_id}",
                        )

                if chunk.tool_call:
                    tool_calls.append(chunk.tool_call)
                    if self._tool_event_callback:
                        asyncio.create_task(
                            self._tool_event_callback(
                                session_id, "stream_delta", "",
                                json.dumps({
                                    "stream_id": stream_id,
                                    "tool_call": {
                                        "id": chunk.tool_call.id,
                                        "name": chunk.tool_call.name,
                                        "arguments": chunk.tool_call.arguments,
                                    },
                                }),
                            ),
                            name=f"stream-tool-{session_id}",
                        )

                # usage 可能在 finish_reason chunk 中，也可能在
                # include_usage 模式下的独立尾部 chunk 中到达
                if chunk.usage:
                    usage["prompt_tokens"] = chunk.usage.prompt_tokens
                    usage["completion_tokens"] = chunk.usage.completion_tokens
                    usage["total_tokens"] = chunk.usage.total_tokens
                    # 实时累加并推送最新 usage，让前端立即看到上下文占用
                    self._token_usage[session_id] = self._token_usage.get(session_id, 0) + chunk.usage.total_tokens
                    self._persist_token_usage(session_id)
                    self._last_prompt_tokens[session_id] = chunk.usage.prompt_tokens
                    self._push_usage_update(session_id)

                if chunk.finish_reason:
                    finish_reason = chunk.finish_reason
        finally:
            await _close_async_iterator(stream)

        if cancel_event.is_set():
            finish_reason = "cancelled"

        if not cancel_event.is_set() and usage["total_tokens"] == 0:
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

    def _store_assistant_with_tools(self, session_id: str, resp: LLMResponse) -> None:
        entry: dict[str, Any] = {
            "role": Role.ASSISTANT,
            "content": resp.content or "",
            "tool_calls": [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.name,
                        "arguments": json.dumps(tc.arguments, ensure_ascii=False),
                    },
                }
                for tc in resp.tool_calls
            ],
        }
        if resp.reasoning_content:
            entry["reasoning_content"] = resp.reasoning_content
        self._get_history(session_id).append(entry)
        self._persist_message(session_id, entry)


# -- 内部辅助方法 ----------------------------------------------------

    @staticmethod
    def _extract_text(content: Any) -> str:
        """从消息 content 中提取纯文本（处理 string 和 list 两种格式）。"""
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts: list[str] = []
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    parts.append(str(block.get("text", "")))
            return "\n".join(parts)
        return str(content or "")

    def _supports_vision(self) -> bool:
        """检测当前模型是否支持图像 vision 功能。

        优先查询 probe_vision_capability 工具产生的本地缓存；
        缓存未命中时采用乐观默认（视为支持），让图片进入消息流，
        由下游 is_content_block_error 在 API 拒绝时降级处理。
        """
        model: str = (self._ctx.llm_model or "").lower()
        if not model:
            return False
        return supports_vision(model)

    def _get_history(self, session_id: str) -> list[dict[str, Any]]:
        if session_id not in self._histories:
            # 先尝试从磁盘加载（重启后仍然可用）
            disk: list[dict] = self._load_history_from_disk(session_id)
            self._histories[session_id] = disk
        return self._histories[session_id]

    def _append(
        self, session_id: str, role: str, content: str | list[dict[str, Any]],
        reasoning_content: str | None = None,
    ) -> None:
        entry: dict[str, Any] = {"role": role, "content": content}
        if reasoning_content:
            entry["reasoning_content"] = reasoning_content
        self._get_history(session_id).append(entry)
        self._persist_message(session_id, entry)

    # -- 磁盘持久化辅助方法 -------------------------------------------

    def _history_path(self, session_id: str) -> Path | None:
        """返回 session 消息历史 JSONL 文件的路径。"""
        if self._session_store is None:
            return None
        return self._session_store.messages_path(session_id)

    def _persist_message(self, session_id: str, entry: dict) -> None:
        """向 session 的 JSONL 文件追加一条消息。"""
        if self._session_store is None:
            return
        try:
            self._session_store.append_message(session_id, entry)
        except Exception as exc:
            logger.warning("Failed to persist message for session %s: %s", session_id, exc)

    def _load_history_from_disk(self, session_id: str) -> list[dict]:
        """从 JSONL 文件加载完整消息历史。"""
        if self._session_store is None:
            return []
        try:
            return self._session_store.read_messages(session_id)
        except Exception as exc:
            logger.warning("Failed to load history for session %s: %s", session_id, exc)
            return []

    def _remove_last_user_message(self, session_id: str) -> None:
        """从历史中移除最后一条用户消息（用于 LLM 调用失败时清理上下文）。"""
        history: list[dict[str, Any]] = self._histories.get(session_id, [])
        if history and history[-1].get("role") == Role.USER:
            history.pop()

        if self._session_store is None:
            return
        try:
            self._session_store.remove_last_user_message(session_id)
        except Exception as exc:
            logger.warning("Failed to remove last user message from disk for session %s: %s", session_id, exc)

    def _is_context_over_limit(self, session_id: str, safety_margin: int = 5000) -> bool:
        """判断当前上下文是否已经需要会话终结与延续。

        仅使用 LLM 服务商返回的真实 prompt_tokens 作为判断依据；
        未取得真实值时保守返回 False，避免本地估算导致误判。
        """
        current_tokens: int = self._last_prompt_tokens.get(session_id, 0)
        if current_tokens == 0:
            return False
        return (
            current_tokens + self._ctx.llm_max_output_tokens + safety_margin
        ) > self._ctx.llm_max_context_tokens

    async def _rotate_session_for_continuation(
        self,
        session_id: str,
        pending_user_message: str | None = None,
    ) -> str | None:
        """终结旧会话并创建继承会话，必要时把当前用户消息转移过去。"""
        old_sid: str = session_id
        if pending_user_message is not None:
            self._remove_last_user_message(old_sid)

        new_sid: str | None = await self._terminate_session(old_sid, rotate=True)
        if not new_sid:
            if pending_user_message is not None:
                self._append(old_sid, Role.USER, pending_user_message)
            return None

        cancel_event: asyncio.Event | None = self._cancel_events.pop(old_sid, None)
        if cancel_event is not None:
            self._cancel_events[new_sid] = cancel_event
        if self._interrupted.pop(old_sid, False):
            self._interrupted[new_sid] = True
        if old_sid in self._session_locks:
            self._session_locks[new_sid] = self._session_locks[old_sid]

        self._transfer_session_runtime_resources(old_sid, new_sid)

        if pending_user_message is not None:
            self._append(new_sid, Role.USER, pending_user_message)

        logger.info(
            "Session context exceeded limit and continued in new session | old=%s new=%s",
            old_sid, new_sid,
        )
        return new_sid

    def _transfer_session_runtime_resources(self, old_sid: str, new_sid: str) -> None:
        """将旧会话的运行态资源迁移到继承会话。"""
        self._last_prompt_tokens[new_sid] = 0
        self._token_usage[new_sid] = self._token_usage.get(old_sid, 0)
        self._persist_token_usage(new_sid)
        # 迁移 processing 标志
        if self._processing_sessions.pop(old_sid, False):
            self._processing_sessions[new_sid] = True

        if new_sid not in self._memory_initialized:
            for provider in self._memory.providers:
                try:
                    provider.initialize(new_sid)
                except Exception:
                    pass
            self._memory_initialized[new_sid] = True

        if self._session_store is not None:
            try:
                resources = self._session_store.read_tool_resources(old_sid)
                self._session_store.write_tool_resources(new_sid, resources)
            except Exception as exc:
                logger.warning(
                    "Failed to transfer tool resources from %s to %s: %s",
                    old_sid, new_sid, exc,
                )

    # -- token 消耗持久化 -------------------------------------------

    def _token_usage_path(self, session_id: str) -> Path | None:
        """返回 session token 消耗 JSON 文件的路径。"""
        if self._session_store is None:
            return None
        return self._session_store.token_usage_path(session_id)

    def _persist_token_usage(self, session_id: str) -> None:
        """将 session 当前 token 消耗写入磁盘。"""
        if self._session_store is None:
            return
        try:
            self._session_store.write_token_usage(
                session_id,
                self._token_usage.get(session_id, 0),
            )
        except Exception as exc:
            logger.warning("Failed to persist token usage for session %s: %s", session_id, exc)

    def _load_token_usage_from_disk(self, session_id: str) -> int:
        """从磁盘加载 token 消耗，不存在则返回 0。"""
        if self._session_store is None:
            return 0
        try:
            return self._session_store.read_token_usage(session_id)
        except Exception:
            return 0

    def _push_usage_update(self, session_id: str) -> None:
        """统一推送当前 session 的 token 消耗与上下文占用到前端。

        读取内存中的累计消耗和最近一次 prompt_tokens，通过 usage_update
        事件异步发送。调用方无需关心回调是否注册或发送是否成功。
        """
        if self._tool_event_callback is None:
            return
        payload = json.dumps({
            "token_usage": self._token_usage.get(session_id, 0),
            "context_tokens": self._last_prompt_tokens.get(session_id, 0),
        }, ensure_ascii=False)
        asyncio.create_task(
            self._tool_event_callback(session_id, "usage_update", "", payload),
            name=f"push-usage-update-{session_id}",
        )

    def _load_tool_resources(self, session_id: str) -> dict[str, Any]:
        if self._session_store is None:
            return {"task_progress": {}, "clipboard_display": {}}
        try:
            return self._session_store.read_tool_resources(session_id)
        except Exception as exc:
            logger.warning("Failed to load tool resources for session %s: %s", session_id, exc)
            return {"task_progress": {}, "clipboard_display": {}}

    def _persist_tool_resource_event(self, session_id: str, resource_type: str, tool_name: str, payload: str) -> None:
        if self._session_store is None:
            return
        try:
            data: dict[str, Any] = json.loads(payload)
        except json.JSONDecodeError:
            return

        resources = self._load_tool_resources(session_id)
        bucket = resources.setdefault(resource_type, {})
        if not isinstance(bucket, dict):
            bucket = {}
            resources[resource_type] = bucket

        if resource_type == "task_progress":
            if tool_name == "clear_task_progress":
                cleared = data.get("cleared")
                if isinstance(cleared, list) and cleared:
                    for task_id in cleared:
                        bucket.pop(str(task_id), None)
                else:
                    bucket.clear()
            elif data.get("task_id"):
                bucket[str(data["task_id"])] = {
                    "task_id": str(data["task_id"]),
                    "label": str(data.get("label") or data["task_id"]),
                    "current": data.get("current", 0),
                    "total": data.get("total", 100),
                    "percent": data.get("percent", 0),
                    "status": str(data.get("status") or "running"),
                }
        elif resource_type == "clipboard_display":
            if tool_name == "clear_clipboard_display":
                cleared = data.get("cleared")
                if isinstance(cleared, list) and cleared:
                    for display_id in cleared:
                        bucket.pop(str(display_id), None)
                else:
                    bucket.clear()
            elif data.get("display_id"):
                bucket[str(data["display_id"])] = {
                    "display_id": str(data["display_id"]),
                    "label": str(data.get("label") or data["display_id"]),
                    "content": str(data.get("content") or ""),
                }

        try:
            self._session_store.write_tool_resources(session_id, resources)
        except Exception as exc:
            logger.warning("Failed to persist tool resources for session %s: %s", session_id, exc)

    def get_tool_resources(self, session_id: str) -> dict[str, Any]:
        return self._load_tool_resources(session_id)

    def clear_session(self, session_id: str) -> None:
        """从内存中移除 session，可选择清理磁盘文件。"""
        self._histories.pop(session_id, None)
        self._token_usage.pop(session_id, None)
        # 清理持久化的 token 消耗文件
        path: Path | None = self._token_usage_path(session_id)
        if path and path.exists():
            try:
                path.unlink()
            except Exception:
                pass

    async def auto_generate_title(self, session_id: str) -> str:
        """使用 LLM 从会话历史中生成简短标题。"""
        history: list[dict[str, Any]] = self._get_history(session_id)
        if not history:
            return ""
        # 收集最近的 50 轮 user/assistant 文本（跳过 system 和 tool 条目）
        # 一轮对话按 user + assistant 估算，最多取最近 100 条相关消息
        chat_msgs: list[dict] = [
            msg for msg in history if msg.get("role") in (Role.USER, Role.ASSISTANT)
        ]
        chat_msgs = chat_msgs[-100:]
        lines: list[str] = []
        for msg in chat_msgs:
            role: str = msg.get("role", "")
            content: str = str(msg.get("content", "") or "")
            if not content:
                continue
            if role == Role.USER:
                lines.append(f"User: {content[:AUTO_TITLE_CONTENT_MAX]}")
            elif role == Role.ASSISTANT:
                lines.append(f"Assistant: {content[:AUTO_TITLE_CONTENT_MAX]}")
        if not lines:
            return ""
        context: str = "\n".join(lines)

        # 从模板文件读取自动标题 prompt
        from system.templates import read_template
        prompt_tpl: str = read_template("auto_title.txt")
        if not prompt_tpl:
            # 硬编码回退
            prompt_tpl = (
                "Based on the following conversation, summarize the topic in no more than 20 characters. "
                "Output only the title, no extra content.\n\n{{context}}\n\nTitle: "
            )

        prompt: str = prompt_tpl.replace(r"{{context}}", context)
        try:
            resp: LLMResponse = await self._llm.chat(
                [{"role": Role.USER, "content": prompt}],
                tools=[],
            )
            title: str = resp.content.strip()[:50] if resp.content else ""
            return title
        except Exception:
            return ""

    def _collect_skill_prompts(self) -> list[str]:
        """加载已启用的 skill，返回格式化后的 prompt 列表。"""
        if self._skill_cache_valid:
            return self._skill_cache
        blocks: list[str] = []
        try:
            from pathlib import Path
            from abstract.skills.loader import list_skills, load_skill
            skills: list[dict] = list_skills(skills_dir=Path("skills"))
            for s in skills:
                name: str = s.get("name", "")
                if not name:
                    continue
                try:
                    payload: dict = load_skill(name, skills_dir=Path("skills"))
                    if payload.get("success") and payload.get("content"):
                        blocks.append(
                            f"[Skill: {name}]\n{payload['content']}"
                        )
                except Exception:
                    pass
        except Exception:
            pass
        self._skill_cache = blocks
        self._skill_cache_valid = True
        return blocks

    def invalidate_skill_cache(self) -> None:
        """强制下次调用时重新加载 skill 缓存。"""
        self._skill_cache_valid = False

    def _overwrite_history_file(self, session_id: str) -> None:
        """将内存中的完整历史覆写回磁盘 JSONL（用于压缩后持久化）。"""
        if self._session_store is None:
            return
        try:
            self._session_store.overwrite_messages(
                session_id,
                self._histories.get(session_id, []),
            )
        except Exception as exc:
            logger.warning("Failed to overwrite history file for session %s: %s", session_id, exc)

    def _read_session_summary(self, session_id: str) -> str:
        """读取会话终结时生成的持久化摘要。"""
        if self._session_store is None:
            return ""
        try:
            return self._session_store.read_summary(session_id)
        except Exception:
            return ""

    def _recent_history_text(self, session_id: str, keep_messages: int = 10) -> str:
        """提取最近几条旧历史，作为继承会话的短期上下文。"""
        history: list[dict[str, Any]] = self._get_history(session_id)
        parts: list[str] = []
        for msg in history:
            role: str = msg.get("role", "")
            if role not in (Role.USER, Role.ASSISTANT):
                continue
            text: str = self._extract_text(msg.get("content", "")).strip()
            if not text:
                continue
            parts.append(f"[{role}]: {text[:TOOL_RESULT_PREVIEW_CHARS]}")
        return "\n".join(parts[-keep_messages:])

    def _build_inherited_context(self, session_id: str, summary: str = "") -> str:
        """构造继承会话首条消息：终结摘要 + 最近旧历史。"""
        summary_text: str = summary.strip() or self._read_session_summary(session_id)
        if not summary_text:
            summary_text = "(Session context archived)"

        recent_text: str = self._recent_history_text(session_id)
        sections: list[str] = [
            "[Session continuation summary]",
            "The following is inherited context from a previous session. It is background information, not a new question.",
            "",
            "## Summary",
            summary_text,
        ]
        if recent_text:
            sections.extend([
                "",
                "## Recent history from previous session",
                recent_text,
            ])
        return "\n".join(sections)

    def get_session_tags(self, session_id: str) -> list[str]:
        """返回指定 session 当前的标签列表。"""
        if self._session_manager is None:
            return []
        info = self._session_manager.get(session_id)
        return list(info.get("tags", [])) if info else []

    async def _get_or_create_session_summary(self, session_id: str) -> str:
        """获取会话摘要，优先读取已持久化摘要，否则生成新摘要。"""
        summary: str = ""
        if self._session_store is not None:
            summary = self._session_store.read_summary(session_id)
        if not summary:
            summary = await self._summarize_session_history(session_id)
        return summary

    async def _generate_tags_from_summary(self, summary: str) -> list[str]:
        """基于会话摘要调用 LLM 生成并校验标签。

        LLM 从已有全局标签中选择，若无合适可创建新标签。
        返回校验后的标签列表。
        """
        if self._session_manager is None:
            return []

        summary = summary.strip() or "(Session context archived)"
        all_tags: list[str] = self._session_manager.get_all_tags()
        prompt_lines: list[str] = [
            "You are a session classification assistant.",
            "Based on the following session summary, select the most appropriate tags from the existing tag list.",
            "If no existing tag is suitable, you may create new tags.",
            "Each tag must be either 1-5 Chinese characters OR 1-10 English letters (a-z, A-Z).",
            "Tags must NOT contain spaces, digits, symbols, or mixed Chinese-English characters.",
            "Return ONLY a valid JSON object in this exact format: {\"tags\": [\"tag1\", \"tag2\"]}.",
            "Do not include any explanation, markdown, or extra text.",
            "",
            f"Existing tags: {json.dumps(all_tags, ensure_ascii=False)}",
            "",
            "Session summary:",
            summary[:4000],
            "",
            "Output JSON:",
        ]
        prompt: str = "\n".join(prompt_lines)
        try:
            resp: LLMResponse = await self._llm.chat(
                [{"role": Role.USER, "content": prompt}],
                tools=[],
            )
            raw: str = resp.content.strip()
            # 兼容 markdown 代码块
            if raw.startswith("```"):
                raw = raw.strip("`").strip()
                if raw.lower().startswith("json"):
                    raw = raw[4:].strip()
            data: Any = json.loads(raw)
            if isinstance(data, dict) and isinstance(data.get("tags"), list):
                candidates: list[str] = [str(t).strip() for t in data["tags"]]
                return [t for t in candidates if self._session_manager.validate_tag(t)]
        except Exception:
            logger.warning("Failed to generate tags from summary", exc_info=True)
        return []

    async def _auto_classify_session_tags(self, session_id: str) -> list[str]:
        """终结时自动归类标签。仅当会话无标签时执行。

        保留旧行为的内部包装：先检查现有标签，再获取/生成摘要并生成标签。
        """
        if self._session_manager is None:
            return []
        info = self._session_manager.get(session_id)
        if not info:
            return []
        existing_tags: list[str] = list(info.get("tags", []))
        if existing_tags:
            return []

        summary: str = await self._get_or_create_session_summary(session_id)
        return await self._generate_tags_from_summary(summary)

    async def generate_session_tags(self, session_id: str, force: bool = False) -> list[str]:
        """为指定会话生成标签候选。

        force=False 时遵循"无标签才生成"语义，已有标签直接返回；
        force=True  时无视现有标签，基于会话摘要重新生成。
        返回校验后的标签列表，不写入 session manager。
        """
        if self._session_manager is None:
            return []
        info = self._session_manager.get(session_id)
        if not info:
            return []

        existing_tags: list[str] = list(info.get("tags", []))
        if existing_tags and not force:
            return existing_tags

        summary: str = await self._get_or_create_session_summary(session_id)
        return await self._generate_tags_from_summary(summary)

    async def regenerate_session_tags(self, session_id: str) -> list[str]:
        """手动触发标签完全重新生成并持久化。

        基于会话摘要重新生成标签，覆盖会话已有标签，并同步全局标签。
        返回最终生效的标签列表。
        """
        tags: list[str] = await self.generate_session_tags(session_id, force=True)
        if tags and self._session_manager is not None:
            self._session_manager.set_session_tags(session_id, tags)
            logger.info("Regenerated tags for session %s: %s", session_id, tags)
        return tags

    async def terminate_session(self, session_id: str) -> dict:
        """手动终结会话：归档 + 压缩（生成摘要），不旋转。"""
        await self._terminate_session(session_id, rotate=False)
        return {
            "terminated": True,
            "session_id": session_id,
        }

    async def merge_sessions(self, source_session_ids: list[str]) -> dict:
        """从多个会话创建合并延续。摘要阈值 5w，作为 user message 写入。

        单源调用退化为分支（branch）。
        """
        if self._session_manager is None:
            return {"error": "session manager not ready"}
        if len(source_session_ids) < 1:
            return {"error": "at least one source session required"}

        err = self._session_manager.validate_merge_sources(source_session_ids)
        if err:
            return {"error": err}

        # 收集各源继承上下文：终结摘要 + 最近旧历史
        summaries: list[tuple[str, str, str]] = []  # (sid, title, inherited_context)

        for sid in source_session_ids:
            title: str = ""
            if self._session_manager is not None:
                info = self._session_manager.get(sid)
                title = info.get("title", "") if info else ""

            inherited_context: str = self._build_inherited_context(sid)
            summaries.append((sid, title, inherited_context))

        # 拼接内容（阈值来自配置，默认 5w 字符）
        CONCAT_THRESHOLD: int = self._ctx.merge_concat_threshold

        parts: list[str] = [
            "[The following is inherited context from previous sessions. "
            "It is background information, not a new question.]"
        ]
        for sid, title, text in summaries:
            display: str = title.strip() if title.strip() else sid[:8]
            parts.append(f"\n--- From session {sid[:8]}: {display} ---\n{text}")

        merged_content: str = "\n".join(parts)

        if len(merged_content) > CONCAT_THRESHOLD:
            merged_content = merged_content[:CONCAT_THRESHOLD] + "\n\n[...truncated due to length limit]"

        # 创建新会话，作为 user message 写入
        new_sid: str = self._session_manager.create_with_context(
            merged_content,
            parents=source_session_ids,
            role=Role.USER,
        )

        self._histories[new_sid] = self._load_history_from_disk(new_sid)
        self._last_prompt_tokens[new_sid] = 0

        return {
            "session_id": new_sid,
            "parents": source_session_ids,
        }

    def _compression_prompts(self) -> tuple[str, str, str]:
        """从模板文件返回 (prompt模板, 回退文本, 摘要前缀)。"""
        from system.templates import read_template

        prompt_tpl: str = read_template("compress.txt")
        if not prompt_tpl:
            max_chars: int = self._ctx.merge_concat_threshold
            prompt_tpl = (
                f"Summarize the key content and decisions of the following conversation in no more than {max_chars} characters. Output only the summary.\n\n"
                "Conversation:\n{{old_text}}\n\nSummary: "
            )

        return prompt_tpl, "(History too long, truncated)", "[Context Summary]"

    async def _summarize_session_history(self, session_id: str) -> str:
        """为会话终结生成持久化摘要。"""
        try:
            history: list[dict[str, Any]] = self._get_history(session_id)
            parts: list[str] = []
            for msg in history:
                role: str = msg.get("role", "unknown")
                content: str = self._extract_text(msg.get("content", ""))
                if content:
                    parts.append(f"[{role}]: {content}")
            old_text: str = "\n".join(parts)
            if old_text.strip():
                prompt, fallback, _ = self._compression_prompts()
                summary_prompt: str = prompt.replace(r"{{old_text}}", old_text)
                summary_resp: LLMResponse = await self._llm.chat(
                    [{"role": Role.USER, "content": summary_prompt}],
                    tools=[],
                )
                summary: str = summary_resp.content.strip() if summary_resp.content else ""
                return summary or fallback
        except Exception:
            logger.warning("Failed to summarize session history for %s", session_id, exc_info=True)
        return "(Session context archived)"

    async def _terminate_session(self, session_id: str, rotate: bool = False) -> str | None:
        """终结会话：归档 + 压缩（生成摘要），可选旋转创建继承会话。

        终结 = 归档 + 压缩，统一两种触发方式：
          - 手动终结（rotate=False）：生成摘要、保存 summary.txt、标记 archived
          - 自动终结（rotate=True）：同上 + 创建继承会话并旋转
        返回新 session_id（rotate=True 时），或 None。
        """
        if self._session_manager is None:
            return None

        sm = self._session_manager
        old_sid: str = session_id

        # 1. 优先读取已持久化的摘要（兼容旧会话或测试复用）
        summary: str = ""
        summary_path: Path | None = None
        if self._history_store_dir:
            summary_path = self._history_store_dir / old_sid / "summary.txt"
            if summary_path.exists():
                try:
                    summary = summary_path.read_text(encoding="utf-8")
                except Exception:
                    summary = ""

        # 2. 若无持久化摘要，则对完整历史做 LLM 压缩生成摘要
        if not summary:
            summary = await self._summarize_session_history(old_sid)

        # 3. 将完整摘要写入 summary.txt（供后续继承复用）
        if self._session_store is not None:
            try:
                self._session_store.write_summary(old_sid, summary)
            except Exception as exc:
                logger.warning("Failed to write summary for session %s: %s", old_sid, exc)

        # 4. 同步 memory
        try:
            self._memory.sync_all("", summary, session_id=old_sid)
        except Exception:
            pass

        # 5. 归档旧会话
        tags: list[str] = await self.generate_session_tags(old_sid, force=False)
        if tags and self._session_manager is not None:
            self._session_manager.set_session_tags(old_sid, tags)
            logger.info("Auto-classified tags for session %s: %s", old_sid, tags)
        sm.archive(old_sid, continuation_sid=None)

        if rotate:
            # 6a. 创建继承会话并旋转
            context: str = self._build_inherited_context(old_sid, summary)
            new_sid: str = sm.create_with_context(context, parent_sid=old_sid, role=Role.USER)
            sm.archive(old_sid, continuation_sid=new_sid)

            # 7. 将新会话的历史加载到内存
            self._histories[new_sid] = self._load_history_from_disk(new_sid)
            self._last_prompt_tokens[new_sid] = 0

            # 8. 迁移旧会话的 cron 定时任务到新会话
            try:
                from component.extools import cron_tools
                cron_tools.migrate_session_cron_jobs(old_sid, new_sid)
            except Exception:
                pass

            self._session_rotated_notify[old_sid] = new_sid

            logger.info(
                "Session terminated and rotated | old=%s new=%s summary=%d chars",
                old_sid, new_sid, len(summary),
            )
            return new_sid

        logger.info(
            "Session terminated | old=%s summary=%d chars",
            old_sid, len(summary),
        )
        return None

    def _load_message_hooks(self) -> list[dict]:
        """加载并缓存 custom_hooks 消息扩展。"""
        if self._message_hooks_cache is not None:
            return self._message_hooks_cache
        hooks = load_message_hooks(find_repo_root(), logger)
        self._message_hooks_cache = hooks
        return hooks

    def _get_hooks_context(self, session_id: str) -> str:
        """收集当前所有 custom_hooks 的实时扩展上下文。"""
        return collect_hooks_context(
            self._load_message_hooks(),
            session_id,
            str(self._ctx.workspace),
        )

    def _build_messages(
        self,
        session_id: str,
        user_message: str | list[dict[str, Any]],
        memory_ctx: str,
    ) -> list[dict[str, Any]]:
        """构建当前回合的完整消息列表。"""
        system_prompt: str = build_agent_system_prompt(
            self._ctx,
            self._collect_skill_prompts(),
        )
        return build_turn_messages(
            system_prompt,
            self._get_history(session_id),
            session_id,
            str(self._ctx.workspace),
            memory_ctx,
            self._load_message_hooks(),
        )

    def _get_full_history(self, session_id: str) -> list[dict[str, Any]]:
        """从存储的历史中重建完整消息列表（循环中间使用）。"""
        system_prompt: str = build_agent_system_prompt(
            self._ctx,
            self._collect_skill_prompts(),
        )
        return build_full_history_messages(
            system_prompt,
            self._get_history(session_id),
        )

    def _store_assistant_with_tools(
        self, session_id: str, resp: LLMResponse,
    ) -> None:
        """存储包含工具调用的 assistant 消息。"""
        tool_calls_data: list[dict] = [
            {
                "id": tc.id,
                "type": "function",
                "function": {"name": tc.name, "arguments": json.dumps(tc.arguments, ensure_ascii=False)},
            }
            for tc in resp.tool_calls
        ]
        history: list[dict[str, Any]] = self._get_history(session_id)
        entry: dict[str, Any] = {
            "role": Role.ASSISTANT,
            "content": resp.content or "",
            "tool_calls": tool_calls_data,
        }
        if resp.reasoning_content:
            entry["reasoning_content"] = resp.reasoning_content
        history.append(entry)
        self._persist_message(session_id, entry)

    async def _execute_tool(self, tc: ToolCall, session_id: str = "") -> dict[str, Any]:
        """执行单个工具调用，返回 OpenAI 格式的工具消息。"""
        # 响应中断 — 每次工具执行前检查。
        # 同时检查取消事件，以处理中断在前一个 LLM 调用期间到达的情况。
        cancel_ev: asyncio.Event | None = self._cancel_events.get(session_id)
        if (
            self._interrupted.pop(session_id, False)
            or (cancel_ev is not None and cancel_ev.is_set())
        ):
            return {
                "role": Role.TOOL,
                "tool_call_id": tc.id,
                "content": "Cancelled.",
            }
        # 注入 session 上下文，使 run_command 等工具能够识别
        # 前端 session 以进行用户确认提示。
        args: dict = dict(tc.arguments) if tc.arguments else {}
        args["_session_id"] = session_id

        # 如果工具调用参数解析失败（例如因 max_tokens 太紧导致 JSON
        # 被截断），返回清晰的错误信息，使 LLM 理解原因并调整策略。
        if args.get("_parse_error"):
            logger.warning(
                "Tool call '%s' skipped — arguments JSON parse failed. "
                "Preview: %s", tc.name, args.get("_raw_preview", "")[:LOG_PREVIEW_CHARS],
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
            # Fire-and-forget: 前端推送是尽力而为的副作用，
            # 不能因为 WebSocket 发送失败或阻塞就中断工具执行主链路。
            if self._tool_event_callback:
                asyncio.create_task(
                    self._tool_event_callback(
                        session_id, "tool_result", tc.name, json.dumps(_result, ensure_ascii=False),
                    ),  # type: ignore
                    name=f"push-tool-result-{session_id}",
                )
            return {
                "role": Role.TOOL,
                "tool_call_id": tc.id,
                "content": json.dumps(_result, ensure_ascii=False),
            }

        logger.info("Tool call: %s args=%s", tc.name, tc.arguments)

        # ---- 追踪工具调用统计 ----
        if tc.name not in self._tool_stats:
            self._tool_stats[tc.name] = {"calls": 0, "errors": 0}
        self._tool_stats[tc.name]["calls"] += 1

        # ---- 通知前端：tool_call (fire-and-forget) ----
        # 前端推送是尽力而为的副作用，不阻塞工具执行主链路。
        if self._tool_event_callback:
            asyncio.create_task(
                self._tool_event_callback(
                    session_id, "tool_call", tc.name,
                    json.dumps(tc.arguments, ensure_ascii=False),
                ),  # type: ignore
                name=f"push-tool-call-{session_id}",
            )

        # ---- 统一审批与 allowlist（dangerous 始终审批；write 仅脱手模式审批）----
        _skip_dispatch = False
        result: dict|str = {}
        danger_level: str = tool_registry.get_danger_level(tc.name)
        _handsfree_enabled = is_handsfree_mode(session_id)
        _needs_approval = danger_level == "dangerous" or (
            danger_level == "write" and _handsfree_enabled
        )
        if _needs_approval:
            _approval_args = {k: v for k, v in args.items() if k != "_session_id"}
            if is_tool_allowlisted(tc.name, _approval_args):
                args["_pre_approved"] = True
                args["_approval_action"] = "allow_once"
            else:
                _hooks_ctx = self._get_hooks_context(session_id)
                _ask_agent_callback: Callable[[str], Awaitable[str]] | None = None
                _extra_context: str | None = None
                if _handsfree_enabled:
                    async def _ask_agent_callback_impl(q: str) -> str:
                        return await ask_agent_reason(
                            self._llm, tc.name, _approval_args, q, extra_context=_hooks_ctx,
                        )
                    _ask_agent_callback = _ask_agent_callback_impl
                    _extra_context = _hooks_ctx
                approval = await request_user_confirm(
                    session_id, tc.name, _approval_args,
                    reason=str(args.get("reason", "")),
                    content=f"Tool: {tc.name}\nParameters: {json.dumps(_approval_args, ensure_ascii=False)[:500]}",
                    ask_agent_callback=_ask_agent_callback,
                    extra_context=_extra_context,
                )
                if approval.action == "deny":
                    source_label = {"model": "approval model", "user": "user", "system": "system"}.get(approval.denied_by, "system")
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

        # ---- 实际工具执行（审批耗时与 tool_timeout 相互独立）----
        # request_user_confirm 的审批时间（含模型加载、推理）
        # 不计入下方的 tool_timeout，两者是先后独立的两个阶段。
        if not _skip_dispatch:
            entry: ToolEntry | None = tool_registry.get_entry(tc.name)
            timeout: int = self._ctx.tool_timeout
            # no_timeout 标记使该工具调用不受 tool_timeout 限制
            if entry and entry.no_timeout:
                timeout = 0
            # 如果 memory 管理器拥有该工具，则路由过去
            if self._memory.has_tool(tc.name):
                try:
                    if timeout:
                        result = await asyncio.wait_for(
                            asyncio.to_thread(self._memory.handle_tool_call, tc.name, args),
                            timeout=timeout,
                        )
                    else:
                        result = self._memory.handle_tool_call(tc.name, args)
                except asyncio.TimeoutError:
                    result = {"error": f"Tool execution timed out ({timeout}s)"}
                except Exception as exc:
                    result = {"error": str(exc)}
            else:
                try:
                    if entry and entry.is_async:
                        coro: Any = entry.handler(args)
                    else:
                        coro = asyncio.to_thread(tool_registry.dispatch, tc.name, args)
                    if timeout:
                        result = await asyncio.wait_for(coro, timeout=timeout)
                    else:
                        result = await coro
                except asyncio.TimeoutError:
                    result = {"error": f"Tool execution timed out ({timeout}s)"}
                except Exception as exc:
                    result = {"error": str(exc)}

        # ---- 追踪工具错误统计 ----
        if isinstance(result, dict) and "error" in result:
            if tc.name in self._tool_stats:
                self._tool_stats[tc.name]["errors"] += 1

        # ---- 提取多模态内容（在截断之前） ----
        # read_image 等工具返回 _image 键，含 base64 图片数据，
        # 大小远超 _MAX_RESULT_CHARS，必须在截断前提取并构建 content blocks。
        multimodal_content: Any = None
        if isinstance(result, dict):
            parsed_result: dict = dict(result)
            img: dict | None = parsed_result.pop("_image", None)
            if img and isinstance(img, dict):
                b64: str = str(img.get("base64", ""))
                mime: str = str(img.get("mime_type", "image/png"))
                if b64 and self._supports_vision():
                    text_json: str = json.dumps(parsed_result, ensure_ascii=False)
                    multimodal_content = build_image_content_blocks(img, text_json)
                    # 后续截断/推送只用文本部分
                    result = text_json
                elif b64:
                    fallback: dict = dict(parsed_result)
                    fallback["_vision_unsupported"] = True
                    fallback["_model"] = self._ctx.llm_model
                    fallback["_hint"] = (
                        f"The current model ({self._ctx.llm_model}) does not support image vision analysis. "
                        f"You cannot view the content of this image. Below is the image metadata:\n"
                        f"Path={fallback.get('path', '?')}, "
                        f"Format={mime}, "
                        f"Size={fallback.get('size', '?')} bytes. "
                        f"If you need further processing of the image (e.g. OCR, format conversion), "
                        f"you can use run_command to call external tools "
                        f"(e.g. tesseract, ImageMagick) to extract text or convert formats."
                    )
                    result = json.dumps(fallback, ensure_ascii=False)

        # 防止 base64 以纯文本形式污染上下文。
        if isinstance(result, dict) and "_image" in result:
            result.pop("_image", None)

        # ---- 工具结果大小截断 ----
        _MAX_RESULT_CHARS: int = 50_000
        result_str: str = result if isinstance(result, str) else json.dumps(result, ensure_ascii=False)
        if len(result_str) > _MAX_RESULT_CHARS:
            _ts: str = datetime.now().strftime("%Y%m%d_%H%M%S")
            _rel: str = f"tool_results/{_ts}_{tc.name}.txt"
            _full: Path = self._ctx.agentspace / _rel.replace("/", "\\")
            try:
                _full.parent.mkdir(parents=True, exist_ok=True)
                _full.write_text(result_str, encoding="utf-8")
                _preview: str = result_str[:TOOL_RESULT_PREVIEW_CHARS]
                result_str = (
                    f"[Result too long ({len(result_str)} chars), full content written to ws:{_rel}]\n"
                    f"[First {TOOL_RESULT_PREVIEW_CHARS} chars preview]:\n{_preview}"
                )
            except Exception as _exc:
                logger.warning("Failed to write tool result to file: %s", _exc)

        # ---- 可恢复工具副作用资源：实时持久化并推送前端事件 ----
        if tc.name in ("set_task_progress", "clear_task_progress"):
            _progress_payload: str = result_str
            if isinstance(result, dict) and "_image" in result:
                _progress_payload = json.dumps(sanitize_image_payload(result), ensure_ascii=False)
            self._persist_tool_resource_event(session_id, "task_progress", tc.name, _progress_payload)
            if self._tool_event_callback:
                asyncio.create_task(
                    self._tool_event_callback(
                        session_id, "task_progress", tc.name, _progress_payload,
                    ),  # type: ignore
                    name=f"push-task-progress-{session_id}",
                )

        if tc.name in ("set_clipboard_display", "clear_clipboard_display"):
            _display_payload: str = result_str
            if isinstance(result, dict) and "_image" in result:
                _display_payload = json.dumps(sanitize_image_payload(result), ensure_ascii=False)
            self._persist_tool_resource_event(session_id, "clipboard_display", tc.name, _display_payload)
            if self._tool_event_callback:
                asyncio.create_task(
                    self._tool_event_callback(
                        session_id, "clipboard_display", tc.name, _display_payload,
                    ),  # type: ignore
                    name=f"push-clipboard-display-{session_id}",
                )

        # ---- 通知前端：tool_result (fire-and-forget) ----
        # 前端推送是尽力而为的副作用，不阻塞工具执行主链路。
        if self._tool_event_callback:
            # 对含图片的结果，推送时不包含 base64 数据
            push_result: str = result_str
            if isinstance(result, dict) and "_image" in result:
                push_result = json.dumps(sanitize_image_payload(result), ensure_ascii=False)
            asyncio.create_task(
                self._tool_event_callback(
                    session_id, "tool_result", tc.name, push_result,
                ),  # type: ignore
                name=f"push-tool-result-{session_id}",
            )

        # ---- 构建 OpenAI 格式的工具消息 ----
        # multimodal_content 已在截断前的提取步骤中构建完成（若存在）。
        # 此处直接使用，避免对已截断的 result 二次解析。
        content: Any = multimodal_content if multimodal_content is not None else result_str

        return {
            "role": Role.TOOL,
            "tool_call_id": tc.id,
            "content": content,
        }

    def _get_tool_definitions(self) -> list[dict[str, Any]]:
        """返回 LLM 可用的工具 schema（registry + memory）。"""
        names: set[str] = set(tool_registry.get_all_tool_names())
        definitions: list[dict] = tool_registry.get_definitions(tool_names=names)

        # 合并 memory 工具 schema（包装为 OpenAI 格式）
        for schema in self._memory.get_tool_schemas():
            definitions.append({"type": "function", "function": schema})

        return definitions if definitions else None  # type: ignore[return-value]

    def get_session_messages(self, session_id: str) -> list[dict]:
        """返回格式化后的会话历史，供前端回放。"""
        # 如果尚未加载到内存，先从磁盘加载
        history: list[dict[str, Any]] = self._get_history(session_id)
        messages: list[dict] = []
        for index, entry in enumerate(history):
            role: str = entry.get("role", "")
            content: str = self._extract_text(entry.get("content", ""))
            if role == Role.USER:
                messages.append({"role": Role.USER, "content": content, "index": index})
            elif role == Role.ASSISTANT:
                if not content and not entry.get("reasoning_content"):
                    continue
                msg: dict = {"role": "agent", "content": content, "index": index}
                if entry.get("reasoning_content"):
                    msg["reasoning_content"] = entry["reasoning_content"]
                messages.append(msg)
            elif role == Role.TOOL:
                messages.append({"role": Role.TOOL, "content": content, "index": index})
            elif role == Role.SYSTEM:
                messages.append({"role": Role.SYSTEM, "content": content, "index": index})
        return messages

    def edit_session_message(self, session_id: str, index: int, content: str) -> dict:
        """按历史索引编辑消息正文，并同步内存与 JSONL。"""
        if not isinstance(index, int) or index < 0:
            return {"updated": False, "error": "invalid message index"}
        if not isinstance(content, str):
            return {"updated": False, "error": "content must be a string"}
        history: list[dict[str, Any]] = self._get_history(session_id)
        if index >= len(history):
            return {"updated": False, "error": "message index out of range"}
        entry: dict[str, Any] = dict(history[index])
        entry["content"] = content
        history[index] = entry
        self._histories[session_id] = history
        self._overwrite_history_file(session_id)
        role: str = entry.get("role", "")
        return {
            "updated": True,
            "session_id": session_id,
            "index": index,
            "role": "agent" if role == Role.ASSISTANT else role,
            "content": self._extract_text(entry.get("content", "")),
        }

    def get_token_usage(self, session_id: str) -> int:
        """返回 session 当前的 prompt token 消耗。"""
        if session_id in self._token_usage:
            return self._token_usage[session_id]
        # 内存缺失 — 尝试从磁盘加载（支持重启/进化后恢复）
        disk_usage: int = self._load_token_usage_from_disk(session_id)
        if disk_usage:
            self._token_usage[session_id] = disk_usage
        return disk_usage

    def get_context_tokens(self, session_id: str) -> int:
        """返回 session 最近一次 LLM 调用的 prompt_tokens（已用上下文）。"""
        return self._last_prompt_tokens.get(session_id, 0)