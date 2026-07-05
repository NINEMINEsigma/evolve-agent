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

    async def run(self) -> WorkerResult:
        """执行完整的 tool loop + JSON 输出。

        流程:
        1. 插入 system_prompt 到消息列表头部
        2. 循环: LLM 调用 → 检查 tool_calls → 执行工具 → 追加结果
        3. 当 LLM 返回纯文本时 → 解析 JSON → 返回 WorkerResult
        4. JSON 解析失败时重试（最多 2 次）
        """
        # 在消息列表头部插入 system prompt
        full_messages = [
            {"role": "system", "content": self._system_prompt},
            *self._messages,
        ]

        for turn in range(MAX_TOOL_TURNS):
            if self._loop.is_interrupted():
                return self._error_result("Interrupted")

            # 调用 LLM（流式 + JSON 模式）
            response = await self._call_llm(full_messages)

            if response.get("error"):
                logger.error(
                    "LLM error for agent=%s: %s",
                    self.character_name, response["error"],
                )
                return self._error_result(f"LLM error: {response['error']}")

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
            if not text:
                return self._error_result("Empty response")

            parsed = self._parse_json_safe(text)
            if parsed is not None:
                return WorkerResult(
                    character_name=self.character_name,
                    parsed_json=AgentResponse(**parsed),
                    raw_json=text,
                    stream_buffer=response.get("stream_buffer", []),
                )

            # JSON 解析失败，如果还有重试次数则重试
            retries_used = response.get("json_retries", 0)
            if retries_used < MULTI_AGENT_JSON_RETRIES:
                logger.warning(
                    "JSON parse failed for agent=%s, retrying (%d/%d)",
                    self.character_name, retries_used + 1, MULTI_AGENT_JSON_RETRIES,
                )
                full_messages.append(
                    {
                        "role": "assistant",
                        "content": text,
                    }
                )
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
                response["json_retries"] = retries_used + 1
                continue

            # 重试耗尽
            return self._error_result(
                f"JSON parse failed after {MULTI_AGENT_JSON_RETRIES} retries",
                raw_text=text,
            )

        # tool loop 超过最大轮数
        return self._error_result(
            f"Max tool turns ({MAX_TOOL_TURNS}) exceeded"
        )

    # -- LLM 调用 ---------------------------------------------------------

    async def _call_llm(
        self, messages: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """流式调用 LLM，收集 content / tool_calls / reasoning。

        使用 response_format={'type': 'json_object'} 约束 JSON 输出。
        同时通过 sink 将 token 流式推送到前端。
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
                    await self._sink.emit_stream_delta(
                        self._loop.session_id,
                        f"multi_{self.character_name}",
                        delta=chunk.content_delta,
                        character_name=self.character_name,
                    )

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
                        f"multi_{self.character_name}",
                        tool_call={
                            "id": chunk.tool_call.id,
                            "name": chunk.tool_call.name,
                            "arguments": chunk.tool_call.arguments,
                        },
                        character_name=self.character_name,
                    )
        finally:
            await self._close_stream(stream)

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

        try:
            args = json.loads(func["arguments"])
        except json.JSONDecodeError:
            args = {}

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

    def _error_result(
        self,
        error: str,
        raw_text: str = "",
    ) -> WorkerResult:
        """构造错误占位 JSON 结果。"""
        return WorkerResult(
            character_name=self.character_name,
            parsed_json=AgentResponse(
                content=f"[{self.character_name} 响应失败: {error}]",
                visible_characters=[],
                response_characters=[],
                reasoning=None,
            ),
            raw_json=raw_text,
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