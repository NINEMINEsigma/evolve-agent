"""
MultiAgentWorker — 单 Agent tool loop 执行器。

在多 Agent 协作模式中，每个被指定响应的 Agent 通过本 worker
执行完整的 tool loop：LLM → tool_calls → 工具执行 → 结果追加 → 循环，
最终以 JSON 格式输出（含 visible_characters / response_characters）。
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from collections.abc import AsyncIterator
from typing import Any, TYPE_CHECKING

from pydantic import BaseModel, Field

from entity.puretype import Role
from entity.messages import ToolResultMessage
from entity.constant import (
    MAX_TOOL_TURNS,
    MULTI_AGENT_JSON_RETRIES,
)
from entry.base_agent_loop import BaseAgentLoop

if TYPE_CHECKING:
    from entry.agent_sink import AgentSink
    from component.llm import LLMClient, StreamChunk

logger = logging.getLogger(__name__)


class AgentResponse(BaseModel):
    """多 Agent 模式下单个 Agent 的 JSON 响应结构。"""

    content: str = Field("", description="Agent 的自然语言回复文本")
    visible_characters: list[str] = Field(default_factory=list, description="能看到此消息的角色名列表")
    response_characters: list[str] = Field(default_factory=list, description="需要回复的角色名列表")
    reasoning: str | None = Field(default=None, description="LLM 推理内容（仅在支持 thinking 的 provider 下存在）")


class WorkerResult(BaseModel):
    """Worker 执行结果，包含解析后的 JSON 路由元数据。"""

    character_name: str = Field(..., description="当前 Agent 的角色名")
    parsed_json: AgentResponse = Field(..., description="解析后的 Agent JSON 响应")
    raw_json: str = Field("", description="原始 JSON 文本")
    stream_buffer: list[str] = Field(default_factory=list, description="流式 token 缓冲")
    stream_id: str = Field("", description="Worker 的流式标识，用于前端关联元数据")


class MultiAgentWorker:
    """单个 Agent 的 tool loop 执行器。

    在独立上下文中执行 LLM → tool_calls → 工具执行 → 循环，
    最终输出 JSON 格式响应。

    参数:
        character_name: 当前 Agent 的角色名
        system_prompt: Agent 的系统提示词
        history: 该 Agent 视角的 History 视图（已过滤的 OpenAI 消息列表）
        tools: 该 Agent 可用的工具定义列表
        llm_client: LLM 客户端（需支持 chat_stream + response_format）
        sink: 前端流式输出 sink
        loop: 所属 MultiAgentLoop 实例（用于工具审批和执行）
    """

    def __init__(
        self,
        *,
        character_name: str,
        system_prompt: str,
        history: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        llm_client: LLMClient,
        sink: AgentSink,
        loop: BaseAgentLoop,
    ) -> None:
        self.character_name: str = character_name
        self._system_prompt: str = system_prompt
        self._messages: list[dict[str, Any]] = history
        self._tools: list[dict[str, Any]] = tools
        self._llm: LLMClient = llm_client
        self._sink: AgentSink = sink
        self._loop: BaseAgentLoop = loop
        # 每个 worker 实例使用独立 stream_id，防止级联多轮时前端叠加/覆盖消息
        self._stream_id: str = f"multi_{character_name}_{uuid.uuid4().hex[:8]}"

    async def run(self) -> WorkerResult:
        """执行完整的 tool loop + JSON 输出。

        流程:
        1. 插入 system_prompt 到消息列表头部
        2. 循环: LLM 调用 → 检查 tool_calls → 执行工具 → 追加结果
        3. 当 LLM 返回纯文本时 → 解析 JSON → 推送干净内容到前端 → 返回 WorkerResult
        4. JSON 解析失败或返回空内容时重试（最多 MULTI_AGENT_JSON_RETRIES 次）
        """
        # 在消息列表头部插入 system prompt
        full_messages = [
            {"role": "system", "content": self._system_prompt},
            *self._messages,
        ]

        # 本地重试计数器：空 content / JSON 解析失败共享同一上限
        retries = 0

        for turn in range(MAX_TOOL_TURNS):
            if self._loop.is_interrupted():
                return await self._error_result("Interrupted")

            logger.info(
                "MultiAgentWorker turn start | session=%s character=%s turn=%d messages_len=%d retries=%d",
                self._loop.session_id, self.character_name, turn, len(full_messages), retries,
            )

            # 调用 LLM（流式 + JSON 模式）
            response = await self._call_llm(full_messages)

            if response.get("error"):
                logger.error(
                    "LLM error for agent=%s: %s",
                    self.character_name, response["error"],
                )
                return await self._error_result(f"LLM error: {response['error']}")

            # 有 tool_calls → 执行工具 → 追加到消息列表 → 继续循环
            if response.get("tool_calls"):
                full_messages.append(
                    {
                        "role": "assistant",
                        "content": response.get("content"),
                        "tool_calls": response["tool_calls"],
                    }
                )

                for tc in response["tool_calls"]:
                    tool_msg = await self._execute_tool_call(tc)
                    full_messages.append(tool_msg)

                continue

            # 纯文本响应 → 尝试解析 JSON
            text = response.get("content", "")
            logger.info(
                "MultiAgentWorker raw text | session=%s character=%s turn=%d text_len=%d text=%r",
                self._loop.session_id, self.character_name, turn, len(text), text,
            )

            # 空或全空白 content：可能是 DeepSeek JSON Output 的已知问题，进入重试
            if not text or not text.strip():
                logger.warning(
                    "MultiAgentWorker empty/blank response | session=%s character=%s turn=%d retries=%d max=%d",
                    self._loop.session_id, self.character_name, turn, retries, MULTI_AGENT_JSON_RETRIES,
                )
                if retries < MULTI_AGENT_JSON_RETRIES:
                    retries += 1
                    logger.warning(
                        "Empty/blank response for agent=%s, retrying (%d/%d)",
                        self.character_name, retries, MULTI_AGENT_JSON_RETRIES,
                    )
                    full_messages.append({"role": "assistant", "content": text})
                    full_messages.append(
                        {
                            "role": "user",
                            "content": (
                                "你的上一个回复是空内容。"
                                '请严格按照 {"content": "...", "visible_characters": [...], "response_characters": [...]} 的格式回复，'
                                "不要输出空内容，也不要输出 JSON 之外的任何内容。"
                            ),
                        }
                    )
                    continue
                return await self._error_result(
                    f"Max retries ({MULTI_AGENT_JSON_RETRIES}) exceeded for empty/blank response",
                    raw_text=text,
                )

            parsed = self._parse_json_safe(text)
            if parsed is not None:
                logger.info(
                    "MultiAgentWorker JSON parse success | session=%s character=%s turn=%d parsed=%s",
                    self._loop.session_id, self.character_name, turn, parsed,
                )
                clean_content = parsed.get("content", "")
                if clean_content:
                    await self._emit_text(clean_content)
                else:
                    # 内容为空时至少发送 stream_done，避免前端 streamingMessage 悬空
                    await self._sink.emit_stream_done(
                        self._loop.session_id,
                        self._stream_id,
                    )
                return WorkerResult(
                    character_name=self.character_name,
                    parsed_json=AgentResponse(**parsed),
                    raw_json=text,
                    stream_buffer=response.get("stream_buffer", []),
                    stream_id=self._stream_id,
                )

            # JSON 解析失败，如果还有重试次数则重试
            logger.warning(
                "MultiAgentWorker JSON parse failed | session=%s character=%s turn=%d retries=%d max=%d",
                self._loop.session_id, self.character_name, turn, retries, MULTI_AGENT_JSON_RETRIES,
            )
            if retries < MULTI_AGENT_JSON_RETRIES:
                retries += 1
                logger.warning(
                    "JSON parse failed for agent=%s, retrying (%d/%d)",
                    self.character_name, retries, MULTI_AGENT_JSON_RETRIES,
                )
                full_messages.append({"role": "assistant", "content": text})
                full_messages.append(
                    {
                        "role": "user",
                        "content": (
                            "你的上一个回复不是合法的 JSON 格式。"
                            '请严格按照 {"content": "...", "visible_characters": [...], "response_characters": [...]} 的格式回复，'
                            "不要包含任何 JSON 之外的内容。"
                        ),
                    }
                )
                continue

            # 重试耗尽
            return await self._error_result(
                f"Max retries ({MULTI_AGENT_JSON_RETRIES}) exceeded for JSON parse",
                raw_text=text,
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

        使用 response_format={'type': 'json_object'} 约束 JSON 输出。
        **不在此处推送 content_delta 到前端**——原始内容是 JSON 格式，
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
                response_format={"type": "json_object"},
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

                if chunk.tool_call:
                    tc_dict = {
                        "id": chunk.tool_call.id,
                        "type": "function",
                        "function": {
                            "name": chunk.tool_call.name,
                            "arguments": chunk.tool_call.arguments,
                        },
                    }
                    tool_calls.append(tc_dict)
                    await self._sink.emit_stream_delta(
                        self._loop.session_id,
                        self._stream_id,
                        tool_call={
                            "id": chunk.tool_call.id,
                            "name": chunk.tool_call.name,
                            "arguments": chunk.tool_call.arguments,
                        },
                        character_name=self.character_name,
                    )
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
    ) -> dict[str, Any]:
        """执行单个工具调用，返回 OpenAI 格式的 tool role 消息。"""
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

        content = result_msg.content
        if isinstance(content, list):
            # 多模态内容块 → 转换为纯文本
            from entry.agent_support.multimodal import content_to_text
            content = content_to_text(content)

        return {
            "role": "tool",
            "tool_call_id": tc["id"],
            "content": str(content),
        }

    # -- JSON 解析 --------------------------------------------------------

    @staticmethod
    def _parse_json_safe(text: str) -> dict | None:
        """安全解析 JSON，支持从混杂文本中提取第一个合法 JSON 对象。"""
        if not text:
            return None

        # 先尝试直接解析
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # 尝试提取第一个 { ... } 完整 JSON 块
        start = text.find("{")
        if start == -1:
            return None

        depth = 0
        for i in range(start, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start : i + 1])
                    except json.JSONDecodeError:
                        return None

        return None

    # -- 辅助方法 ---------------------------------------------------------

    async def _error_result(
        self,
        error: str,
        raw_text: str = "",
    ) -> WorkerResult:
        """构造错误占位 JSON 结果，同时推送错误文本到前端。"""
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
        )

    async def _emit_text(self, text: str) -> None:
        """将一段文本以流式方式推送到前端（stream_delta + stream_done）。

        仅在 ``_call_llm`` 未推送 content_delta 的前提下使用——
        ``_call_llm`` 已不再推送原始 JSON，由本方法在 JSON 解析后
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