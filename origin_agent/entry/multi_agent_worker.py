"""
MultiAgentWorker — 单 Agent tool loop 执行器。

在多 Agent 协作模式中，每个被指定响应的 Agent 通过本 worker
执行完整的 tool loop：LLM → tool_calls → 工具执行 → 结果追加 → 循环，
最终以自然语言 + DSL 路由标签输出（@visible(...) / @response(...)）。
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from typing import Any, TYPE_CHECKING

from pydantic import BaseModel, Field

from entity.puretype import Role
from entity.messages import ToolResultMessage, CharacterConversationMessage, CharacterSystemMessage, FunctionCall, ToolCall as HistoryToolCall, BaseMessage
from entity.constant import (
    MAX_TOOL_TURNS,
    ALL_AGENTS_CHARACTER_REF_NAME,
    MULTI_AGENT_ROUTING_TAG_VISIBLE,
    MULTI_AGENT_ROUTING_TAG_RESPONSE,
    MULTI_AGENT_ROUTING_RESPONSE_NONE,
    MULTI_AGENT_ROUTING_RESPONSE_NULL,
)
from entry.base_agent_loop import BaseAgentLoop, IMainSessionLoop
from entry.stream_consumer import StreamConsumer
from entry.tool_executor import ToolExecutor

if TYPE_CHECKING:
    from entry.agent_sink import AgentSink
    from abstract.llm.client import BaseLLMClient
    from entity.puretype import LLMResponse

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
    reasoning: str | None = Field(default=None, description="LLM 推理内容（仅在支持 thinking 的 provider 下存在）")


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
        history: list[BaseMessage],
        tools: list[dict[str, Any]],
        llm_client: BaseLLMClient,
        sink: AgentSink,
        loop: IMainSessionLoop,
    ) -> None:
        self.character_name: str = character_name
        self._system_prompts: list[str] = system_prompts
        self._messages: list[BaseMessage] = history
        self._tools: list[dict[str, Any]] = tools
        self._llm: BaseLLMClient = llm_client
        self._sink: AgentSink = sink
        self._loop: IMainSessionLoop = loop
        # 流式消费器：每轮 LLM 调用会生成独立 stream_id，避免多轮文本互相覆盖
        self._stream_consumer = StreamConsumer(
            llm=self._llm,
            sink=self._sink,
            character_name=self.character_name,
            cancel_event=self._loop.loop.cancel_event,
        )
        # 工具执行器：复用 ParentAgentLoop 的统一执行逻辑
        self._tool_executor = ToolExecutor(loop=self._loop, llm=self._llm)
        # 累计 token 消耗与最近一次上下文 token 数
        self._total_token_usage: int = 0
        self._last_prompt_tokens: int = 0

    @property
    def total_token_usage(self) -> int:
        """返回该 worker 累计消耗的 total_tokens。"""
        return self._total_token_usage

    @property
    def last_prompt_tokens(self) -> int:
        """返回该 worker 最近一次 LLM 调用的 prompt_tokens。"""
        return self._last_prompt_tokens

    @staticmethod
    def _parse_routing_tags(text: str) -> AgentResponse:
        """从自然语言文本中旁路解析 DSL 路由标签。

        支持格式：
        - @visible(Noire, 杏)
        - @response(Noire)
        - @response(none)
        - @visible(all) / @visible(all-agents)

        content 保留原始全文（含标签），不剥离、不修改。
        visible_characters / response_characters 作为旁路结构化字段返回。
        若未命中任何标签，二者均为空列表（由外层补全默认值）。
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
            # 保留原文：返回匹配的原始文本，不做替换
            return match.group(0)

        # 旁路提取路由标签值，content 保留原始全文
        tag_pattern.sub(process_match, text)

        return AgentResponse(
            content=text,
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
        full_messages: list[BaseMessage] = [
            CharacterSystemMessage(role=Role.SYSTEM, character_name=self.character_name, content=prompt)
            for prompt in self._system_prompts
        ] + self._messages

        for turn in range(MAX_TOOL_TURNS):
            # 每轮 LLM 调用使用独立 stream_id，确保前端把本轮文本固化为独立消息
            stream_id = f"multi_{self.character_name}_{uuid.uuid4().hex[:8]}_{turn}"
            if self._loop.loop.is_interrupted():
                return await self._error_result("Interrupted", stream_id=stream_id)

            logger.info(
                "MultiAgentWorker turn start | session=%s character=%s turn=%d messages_len=%d",
                self._loop.loop.session_id, self.character_name, turn, len(full_messages),
            )

            try:
                resp = await self._stream_consumer.consume(
                    self._loop.loop.session_id,
                    full_messages,
                    self._tools,
                    stream_id,
                )
            except Exception as exc:
                logger.exception(
                    "LLM error for agent=%s: %s",
                    self.character_name, exc,
                )
                return await self._error_result(
                    f"LLM error: {exc}",
                    stream_id=stream_id,
                )

            # 发送 stream_done，固化本轮自然语言文本到前端
            await self._sink.emit_stream_done(
                self._loop.loop.session_id,
                stream_id,
                resp.finish_reason,
            )

            # 收集 token 消耗
            if resp.usage and resp.usage.total_tokens > 0:
                self._total_token_usage += resp.usage.total_tokens
                self._last_prompt_tokens = resp.usage.prompt_tokens

            # 有 tool_calls → 写入共享 History → 发送标准事件 → 执行工具 → 继续循环
            if resp.tool_calls:
                # 1. 构造 History 格式的 ToolCall 列表
                history_tool_calls: list[HistoryToolCall] = []
                for tc in resp.tool_calls:
                    args_str = json.dumps(tc.arguments, ensure_ascii=False)
                    history_tool_calls.append(HistoryToolCall(
                        id=tc.id,
                        type="function",
                        function=FunctionCall(name=tc.name, arguments=args_str),
                    ))

                # 2. 写入 assistant message（含 tool_calls）到共享 History，并追加到本地 LLM 上下文
                assistant_msg = CharacterConversationMessage(
                    role=Role.ASSISTANT,
                    character_name=self.character_name,
                    content=resp.content or "",
                    tool_calls=history_tool_calls,
                    visible_characters=[self.character_name],
                    reasoning=resp.reasoning_content,
                )
                self._loop.loop.history.add_message(assistant_msg)
                self._loop.loop.save_history(self._loop.loop.session_id)

                full_messages.append(assistant_msg)

                # 3. 执行工具，写入结果到 History
                #    tool_call/tool_result 前端事件由 ToolExecutor 内部统一发送，此处不再重复
                for tc in resp.tool_calls:
                    tool_msg = await self._tool_executor.execute(
                        tc, self._loop.loop.session_id,
                        character_name=self.character_name,
                    )

                    # 写入共享 History
                    self._loop.loop.history.add_message(tool_msg)
                    self._loop.loop.save_history(self._loop.loop.session_id)

                    # 追加 tool 结果到本地 LLM 上下文（跟在 assistant tool_calls 之后）
                    full_messages.append(tool_msg)

                continue

            # 纯文本响应 → 解析 DSL 标签
            text = resp.content or ""
            logger.info(
                "MultiAgentWorker raw text | session=%s character=%s turn=%d text_len=%d text=%r",
                self._loop.loop.session_id, self.character_name, turn, len(text), text,
            )

            if not text or not text.strip():
                return await self._error_result(
                    "Empty response",
                    raw_text=text,
                    reasoning=resp.reasoning_content,
                )

            parsed = self._parse_routing_tags(text)
            parsed.reasoning = resp.reasoning_content
            logger.info(
                "MultiAgentWorker DSL parse | session=%s character=%s turn=%d parsed=%s",
                self._loop.loop.session_id, self.character_name, turn, parsed,
            )

            return WorkerResult(
                character_name=self.character_name,
                parsed_json=parsed,
                raw_json=text,
                stream_buffer=[],
                stream_id=stream_id,
                total_token_usage=self._total_token_usage,
                last_prompt_tokens=self._last_prompt_tokens,
                reasoning=resp.reasoning_content,
            )

        # tool loop 超过最大轮数
        return await self._error_result(
            f"Max tool turns ({MAX_TOOL_TURNS}) exceeded",
            stream_id=stream_id,
        )

    # -- 辅助方法 ---------------------------------------------------------

    async def _error_result(
        self,
        error: str,
        raw_text: str = "",
        reasoning: str | None = None,
        stream_id: str = "",
    ) -> WorkerResult:
        """构造错误占位结果，同时推送错误文本到前端。"""
        text = f"[{self.character_name} 响应失败: {error}]"
        stream_id = stream_id or f"multi_{self.character_name}_{uuid.uuid4().hex[:8]}_error"
        await self._emit_text(text, stream_id=stream_id)
        return WorkerResult(
            character_name=self.character_name,
            parsed_json=AgentResponse(
                content=text,
                visible_characters=[],
                response_characters=[],
                reasoning=reasoning,
            ),
            raw_json=raw_text,
            stream_id=stream_id,
            total_token_usage=self._total_token_usage,
            last_prompt_tokens=self._last_prompt_tokens,
            reasoning=reasoning,
        )

    async def _emit_text(self, text: str, stream_id: str = "") -> None:
        """将一段文本以流式方式推送到前端（stream_delta + stream_done）。

        仅在流式消费器未主动推送 content 的前提下使用，用于错误兜底文本展示。
        """
        stream_id = stream_id or f"multi_{self.character_name}_{uuid.uuid4().hex[:8]}"
        if text:
            await self._sink.emit_stream_delta(
                self._loop.loop.session_id,
                stream_id,
                delta=text,
                character_name=self.character_name,
            )
        await self._sink.emit_stream_done(
            self._loop.loop.session_id,
            stream_id,
        )

