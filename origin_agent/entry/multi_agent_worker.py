"""
MultiAgentWorker — 单 Agent tool loop 执行器。

在多 Agent 协作模式中，每个被指定响应的 Agent 通过本 worker
执行完整的 tool loop：LLM → tool_calls → 工具执行 → 结果追加 → 循环，
最终以自然语言 + DSL 路由标签输出（@visible(...) / @response(...)）。
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import uuid
from collections.abc import AsyncIterator
from typing import Any, TYPE_CHECKING

from pydantic import BaseModel, Field

from entity.puretype import Role
from entity.messages import ToolResultMessage, CharacterConversationMessage, FunctionCall, ToolCall as HistoryToolCall
from entity.constant import (
    MAX_TOOL_TURNS,
    ALL_AGENTS_CHARACTER_REF_NAME,
    MULTI_AGENT_ROUTING_TAG_VISIBLE,
    MULTI_AGENT_ROUTING_TAG_RESPONSE,
    MULTI_AGENT_ROUTING_RESPONSE_NONE,
    MULTI_AGENT_ROUTING_RESPONSE_NULL,
)
from entry.base_agent_loop import BaseAgentLoop

if TYPE_CHECKING:
    from entry.agent_sink import AgentSink
    from component.llm import LLMClient, StreamChunk

logger = logging.getLogger(__name__)


class AgentResponse(BaseModel):
    """多 Agent 模式下单个 Agent 的解析后响应结构。"""

    content: str = Field("", description="Agent 的自然语言回复文本（已剥离路由标签）")
    visible_characters: list[str] = Field(default_factory=list, description="能看到此消息的角色名列表")
    response_characters: list[str] = Field(default_factory=list, description="需要回复的角色名列表")
    reasoning: str | None = Field(default=None, description="LLM 推理内容（仅在支持 thinking 的 provider 下存在）")


class WorkerResult(BaseModel):
    """Worker 执行结果，包含解析后的 DSL 路由元数据。"""

    character_name: str = Field(..., description="当前 Agent 的角色名")
    parsed_json: AgentResponse = Field(..., description="解析后的 Agent 响应")
    raw_json: str = Field("", description="原始 LLM 文本")
    stream_buffer: list[str] = Field(default_factory=list, description="流式 token 缓冲")
    stream_id: str = Field("", description="Worker 的流式标识，用于前端关联元数据")
    total_token_usage: int = Field(0, description="该 worker 本次执行累计消耗的 total_tokens")
    last_prompt_tokens: int = Field(0, description="该 worker 最后一次 LLM 调用的 prompt_tokens")


class MultiAgentWorker:
    """单个 Agent 的 tool loop 执行器。

    在独立上下文中执行 LLM → tool_calls → 工具执行 → 循环，
    最终输出自然语言 + DSL 路由标签。

    参数:
        character_name: 当前 Agent 的角色名
        system_prompt: Agent 的系统提示词
        history: 该 Agent 视角的 History 视图（已过滤的 OpenAI 消息列表）
        tools: 该 Agent 可用的工具定义列表
        llm_client: LLM 客户端（需支持 chat_stream）
        sink: 前端流式输出 sink
        loop: 所属 MultiAgentLoop 实例（用于工具审批和执行）
    """

    def __init__(
        self,
        *,
        character_name: str,
        system_prompts: list[str],
        history: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        llm_client: LLMClient,
        sink: AgentSink,
        loop: BaseAgentLoop,
    ) -> None:
        self.character_name: str = character_name
        self._system_prompts: list[str] = system_prompts
        self._messages: list[dict[str, Any]] = history
        self._tools: list[dict[str, Any]] = tools
        self._llm: LLMClient = llm_client
        self._sink: AgentSink = sink
        self._loop: BaseAgentLoop = loop
        # 每个 worker 实例使用独立 stream_id，防止级联多轮时前端叠加/覆盖消息
        self._stream_id: str = f"multi_{character_name}_{uuid.uuid4().hex[:8]}"
        # 累计 token 消耗与最近一次上下文 token 数
        self._total_token_usage: int = 0
        self._last_prompt_tokens: int = 0

    @staticmethod
    def _parse_routing_tags(text: str) -> AgentResponse:
        """从自然语言文本中解析 DSL 路由标签。

        支持格式：
        - @visible(Noire, 杏)
        - @response(Noire)
        - @response(none)
        - @visible(all) / @visible(all-agents)

        返回的 AgentResponse.content 已剥离所有路由标签。
        若未命中任何标签，visible_characters 与 response_characters 均为空列表
        （由外层补全默认值）。
        """
        if not text:
            return AgentResponse(content="", visible_characters=[], response_characters=[])

        # 匹配 @visible(...) 或 @response(...)
        tag_pattern = re.compile(r"@(\w+)\((.*?)\)")
        visible_characters: list[str] = []
        response_characters: list[str] = []

        def split_names(payload: str) -> list[str]:
            return [n.strip() for n in payload.split(",") if n.strip()]

        def process_match(match: re.Match) -> str:
            nonlocal visible_characters, response_characters
            key = match.group(1).lower()
            payload = match.group(2).strip()
            if key == MULTI_AGENT_ROUTING_TAG_VISIBLE:
                if payload.lower() == ALL_AGENTS_CHARACTER_REF_NAME:
                    visible_characters = [ALL_AGENTS_CHARACTER_REF_NAME]
                else:
                    visible_characters = split_names(payload)
            elif key == MULTI_AGENT_ROUTING_TAG_RESPONSE:
                if payload.lower() in (MULTI_AGENT_ROUTING_RESPONSE_NONE, MULTI_AGENT_ROUTING_RESPONSE_NULL, ""):
                    response_characters = []
                else:
                    response_characters = split_names(payload)
            return ""

        clean_text = tag_pattern.sub(process_match, text)
        clean_text = clean_text.strip()
        clean_text = re.sub(r"\n{3,}", "\n\n", clean_text)

        return AgentResponse(
            content=clean_text,
            visible_characters=visible_characters,
            response_characters=response_characters,
        )

    async def run(self) -> WorkerResult:
        """执行完整的 tool loop + DSL 路由标签输出。

        流程:
        1. 插入 system_prompt 到消息列表头部
        2. 循环: LLM 调用 → 检查 tool_calls → 执行工具 → 追加结果
        3. 当 LLM 返回纯文本时 → 解析 DSL 标签 → 推送干净内容到前端 → 返回 WorkerResult
        """
        # 在消息列表头部插入多条 system prompt
        full_messages = [
            {"role": Role.SYSTEM.value, "content": prompt}
            for prompt in self._system_prompts
        ] + self._messages

        for turn in range(MAX_TOOL_TURNS):
            if self._loop.is_interrupted():
                return await self._error_result("Interrupted")

            logger.info(
                "MultiAgentWorker turn start | session=%s character=%s turn=%d messages_len=%d",
                self._loop.session_id, self.character_name, turn, len(full_messages),
            )

            # 调用 LLM（流式，自然语言输出）
            response = await self._call_llm(full_messages)

            if response.get("error"):
                logger.error(
                    "LLM error for agent=%s: %s",
                    self.character_name, response["error"],
                )
                return await self._error_result(f"LLM error: {response['error']}")

            # 有 tool_calls → 写入共享 History → 发送标准事件 → 执行工具 → 继续循环
            if response.get("tool_calls"):
                raw_tc_list = response["tool_calls"]

                # 1. 构造 History 格式的 ToolCall 列表
                history_tool_calls: list[HistoryToolCall] = []
                for tc in raw_tc_list:
                    func = tc["function"]
                    args_str = func["arguments"] if isinstance(func["arguments"], str) else json.dumps(func["arguments"], ensure_ascii=False)
                    history_tool_calls.append(HistoryToolCall(
                        id=tc["id"],
                        type="function",
                        function=FunctionCall(name=func["name"], arguments=args_str),
                    ))

                # 2. 发送标准 tool_call 事件到前端
                for tc in raw_tc_list:
                    func = tc["function"]
                    raw_args = func["arguments"]
                    if isinstance(raw_args, str):
                        try:
                            raw_args = json.loads(raw_args)
                        except json.JSONDecodeError:
                            raw_args = {}
                    await self._sink.emit_tool_call(
                        self._loop.session_id,
                        func["name"],
                        tc["id"],
                        raw_args,
                        character_name=self.character_name,
                    )

                # 3. 写入 assistant message（含 tool_calls）到共享 History，并追加到本地 LLM 上下文
                msg_content = response.get("content") or ""
                assistant_msg = CharacterConversationMessage(
                    role=Role.ASSISTANT,
                    character_name=self.character_name,
                    content=msg_content,
                    tool_calls=history_tool_calls,
                    visible_characters=[self.character_name],
                )
                self._loop._history.add_message(assistant_msg)
                self._loop._persist_message(self._loop.session_id)

                # assistant 消息（含 tool_calls）必须在 tool 结果之前追加到本地 LLM 上下文
                full_messages.append({
                    "role": "assistant",
                    "content": response.get("content"),
                    "tool_calls": raw_tc_list,
                })

                # 4. 执行工具，写入结果到 History，发送 tool_result 到前端
                for tc in raw_tc_list:
                    result_msg = await self._execute_tool_call(tc)

                    # 设置 character_name 为仅调用方可见
                    if result_msg.character_name != self.character_name:
                        result_msg = result_msg.model_copy(update={"character_name": self.character_name})

                    # 写入共享 History
                    self._loop._history.add_message(result_msg)
                    self._loop._persist_message(self._loop.session_id)

                    # 发送标准 tool_result 事件到前端
                    content_text = result_msg.content
                    if isinstance(content_text, list):
                        from entry.agent_support.multimodal import content_to_text
                        content_text = content_to_text(content_text)
                    await self._sink.emit_tool_result(
                        self._loop.session_id,
                        tc["function"]["name"],
                        tc["id"],
                        str(content_text),
                        character_name=self.character_name,
                    )

                    # 追加 tool 结果到本地 LLM 上下文（跟在 assistant tool_calls 之后）
                    full_messages.append({
                        "role": "tool",
                        "tool_call_id": result_msg.tool_call_id,
                        "content": str(content_text),
                    })

                continue

            # 纯文本响应 → 解析 DSL 标签
            text = response.get("content", "")
            logger.info(
                "MultiAgentWorker raw text | session=%s character=%s turn=%d text_len=%d text=%r",
                self._loop.session_id, self.character_name, turn, len(text), text,
            )

            if not text or not text.strip():
                return await self._error_result(
                    "Empty response",
                    raw_text=text,
                )

            parsed = self._parse_routing_tags(text)
            logger.info(
                "MultiAgentWorker DSL parse | session=%s character=%s turn=%d parsed=%s",
                self._loop.session_id, self.character_name, turn, parsed,
            )

            # DSL 解析后 content 为空/仅空白：兜底提示
            if not parsed.content or not parsed.content.strip():
                return await self._error_result(
                    "Empty content after stripping routing tags",
                    raw_text=text,
                )

            await self._emit_text(parsed.content)
            return WorkerResult(
                character_name=self.character_name,
                parsed_json=parsed,
                raw_json=text,
                stream_buffer=response.get("stream_buffer", []),
                stream_id=self._stream_id,
                total_token_usage=self._total_token_usage,
                last_prompt_tokens=self._last_prompt_tokens,
            )

        # tool loop 超过最大轮数
        return await self._error_result(
            f"Max tool turns ({MAX_TOOL_TURNS}) exceeded"
        )

    # -- LLM 调用 ---------------------------------------------------------

    async def _call_llm(
        self, messages: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """流式调用 LLM，收集 content / tool_calls / reasoning。

        多 Agent 模式下不再使用 response_format 强制 JSON，
        由模型在自然语言中嵌入 DSL 路由标签。
        **不在此处推送 content_delta 到前端**——原始内容可能含 DSL 标签，
        由上层 ``run()`` 在解析后推送干净的 content 字段。
        """
        content: str = ""
        reasoning: str = ""
        tool_calls: list[dict[str, Any]] = []
        stream_buffer: list[str] = []
        error: str | None = None
        stream = None

        try:
            stream = self._llm.chat_stream(
                messages,
                tools=self._tools,
            )

            async for chunk in stream:
                if self._loop.is_interrupted():
                    break

                if chunk.error:
                    error = chunk.error
                    break

                if chunk.content_delta:
                    content += chunk.content_delta
                    stream_buffer.append(chunk.content_delta)

                if chunk.reasoning_delta:
                    reasoning += chunk.reasoning_delta

                # 收集 LLM 返回的 token 消耗；过滤零值避免 finish chunk 覆盖真实 usage
                if chunk.usage and chunk.usage.total_tokens > 0:
                    self._total_token_usage += chunk.usage.total_tokens
                    self._last_prompt_tokens = chunk.usage.prompt_tokens

                if chunk.tool_call:
                    tc_dict = {
                        "id": chunk.tool_call.id,
                        "type": "function",
                        "function": {
                            "name": chunk.tool_call.name,
                            "arguments": json.dumps(chunk.tool_call.arguments, ensure_ascii=False),
                        },
                    }
                    tool_calls.append(tc_dict)
        finally:
            await self._close_stream(stream)

        logger.info(
            "MultiAgentWorker LLM response | session=%s character=%s content_len=%d reasoning_len=%d tool_calls=%d error=%s stream_buffer_len=%d content_preview=%r",
            self._loop.session_id,
            self.character_name,
            len(content),
            len(reasoning),
            len(tool_calls),
            error,
            len(stream_buffer),
            content[:500],
        )

        result: dict[str, Any] = {
            "content": content.strip() if content else None,
            "reasoning": reasoning.strip() if reasoning else None,
            "tool_calls": tool_calls if tool_calls else None,
            "stream_buffer": stream_buffer,
            "json_retries": 0,
        }

        if error:
            result["error"] = error

        return result

    # -- 工具执行 ---------------------------------------------------------

    async def _execute_tool_call(
        self, tc: dict[str, Any]
    ) -> ToolResultMessage:
        """执行单个工具调用，返回 ToolResultMessage。"""
        func = tc["function"]
        tool_name = func["name"]

        # TODO: 防御性编程
        arguments = func["arguments"]
        if isinstance(arguments, str):
            try:
                args = json.loads(arguments)
            except json.JSONDecodeError:
                args = {}
        else:
            args = arguments if isinstance(arguments, dict) else {}

        # 委托给所属 loop 的 _execute_tool（包含审批逻辑）
        # pyright: ignore[reportPrivateUsage] — 合法使用 protected 方法，Worker 与 Loop 紧密协作
        result_msg: ToolResultMessage = await self._loop._execute_tool(
            tool_name=tool_name,
            args=args,
            tool_call_id=tc["id"],
            session_id=self._loop.session_id,
        )

        # 确保 character_name 指向调用的 agent（_loop._execute_tool 使用 current_character_agent 可能不准确）
        if result_msg.character_name != self.character_name:
            result_msg = result_msg.model_copy(update={"character_name": self.character_name})

        content = result_msg.content
        if isinstance(content, list):
            # 多模态内容块 → 转换为纯文本
            from entry.agent_support.multimodal import content_to_text
            content = content_to_text(content)
            result_msg = result_msg.model_copy(update={"content": content})

        return result_msg

    # -- 辅助方法 ---------------------------------------------------------

    async def _error_result(
        self,
        error: str,
        raw_text: str = "",
    ) -> WorkerResult:
        """构造错误占位结果，同时推送错误文本到前端。"""
        text = f"[{self.character_name} 响应失败: {error}]"
        await self._emit_text(text)
        return WorkerResult(
            character_name=self.character_name,
            parsed_json=AgentResponse(
                content=text,
                visible_characters=[],
                response_characters=[],
                reasoning=None,
            ),
            raw_json=raw_text,
            stream_id=self._stream_id,
            total_token_usage=self._total_token_usage,
            last_prompt_tokens=self._last_prompt_tokens,
        )

    async def _emit_text(self, text: str) -> None:
        """将一段文本以流式方式推送到前端（stream_delta + stream_done）。

        仅在 ``_call_llm`` 未推送 content_delta 的前提下使用——
        ``_call_llm`` 已不再推送原始内容，由本方法在 DSL 解析后
        推送干净的 content 字段，确保前端显示的是可读文本。
        """
        stream_id = self._stream_id
        if text:
            await self._sink.emit_stream_delta(
                self._loop.session_id,
                stream_id,
                delta=text,
                character_name=self.character_name,
            )
        await self._sink.emit_stream_done(
            self._loop.session_id,
            stream_id,
        )

    @staticmethod
    async def _close_stream(stream: AsyncIterator[StreamChunk] | None) -> None:
        """安全关闭异步流迭代器。"""
        if stream is None:
            return
        try:
            if hasattr(stream, "aclose"):
                await stream.aclose()
            elif hasattr(stream, "close"):
                stream.close()
        except Exception:
            pass