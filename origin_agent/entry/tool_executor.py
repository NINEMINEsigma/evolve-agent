"""ToolExecutor — 统一工具调用执行器。

封装单个工具调用的完整流程：取消检查、parse error 处理、审批、
registry 分发、异常转换、前端事件推送和 UI 事件路由。

审批流程直接复用 ``component.approval.executor.execute_with_approval``。
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime
from typing import Any, Awaitable, Callable, TYPE_CHECKING

from entity.puretype import Role, ToolCallMeta, ToolCall
from entity.messages import ToolResultMessage
from entry.base_agent_loop import BaseAgentLoop, ToolContext, IMainSessionLoop

if TYPE_CHECKING:
    from abstract.llm.client import BaseLLMClient

logger = logging.getLogger(__name__)


class ToolExecutor:
    """执行单个工具调用，处理审批、分发和事件推送。

    由 IMainSessionLoop 持有，每个 tool_call 调用一次 ``execute()``。
    """

    def __init__(self, loop: IMainSessionLoop, llm: BaseLLMClient) -> None:
        self._loop = loop
        self._llm = llm
        self._tool_stats: dict[str, dict[str, int]] = {}

    # -- 公开 API ----------------------------------------------------------

    def get_tool_stats(self) -> dict[str, dict[str, int]]:
        return {name: dict(stats) for name, stats in self._tool_stats.items()}

    async def execute(
        self,
        tc: ToolCall,
        session_id: str,
        *,
        character_name: str | None = None,
    ) -> ToolResultMessage:
        """执行单个工具调用，返回 ToolResultMessage。

        Args:
            tc: 工具调用描述。
            session_id: 当前会话 ID。
            character_name: 发起此工具调用的角色名；
                MultiAgent 模式下由 worker 传入对应 Agent 名称，
                默认回退到 loop.current_character_agent。
        """
        from entity.constant import LOG_PREVIEW_CHARS
        from component.approval import execute_with_approval, ask_agent_reason as _ask_agent_reason
        from abstract.tools.registry import registry as tool_registry
        from abstract.tools.ui_event_router import ui_event_router

        char_name = character_name or self._loop.current_character_agent

        # -- 记录申请时间（审批流程之前） --
        start_mono: float = time.monotonic()
        application_time_ms: int = int(time.time() * 1000)
        application_time: str = datetime.fromtimestamp(
            time.time()
        ).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]

        args = dict(tc.arguments)

        # 取消检查
        if self._loop.loop.is_interrupted() or self._loop.loop.is_interrupted():
            _meta = ToolCallMeta(
                application_time=application_time,
                application_time_ms=application_time_ms,
                approval_duration_ms=0,
                invocation_start_offset_ms=0,
                invocation_duration_ms=0,
                end_time_offset_ms=0,
            )
            _cancelled_result: dict = {"error": "Cancelled.", "_meta": _meta.model_dump()}
            return ToolResultMessage(
                role=Role.TOOL,
                character_name=char_name,
                tool_call_id=tc.id,
                content=json.dumps(_cancelled_result, ensure_ascii=False),
            )

        args["_session_id"] = session_id

        # parse error
        if args.get("_parse_error"):
            logger.warning(
                "Tool call '%s' skipped — arguments JSON parse failed. Preview: %s",
                tc.name, args.get("_raw_preview", "")[:LOG_PREVIEW_CHARS],
            )
            _meta = ToolCallMeta(
                application_time=application_time,
                application_time_ms=application_time_ms,
                approval_duration_ms=0,
                invocation_start_offset_ms=0,
                invocation_duration_ms=0,
                end_time_offset_ms=0,
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
                "_meta": _meta.model_dump(),
            }
            await self._loop.loop.get_sink().emit_tool_result(
                session_id, tc.name, tc.id,
                json.dumps(_result, ensure_ascii=False),
                character_name=char_name,
                tool_call_meta=_meta.model_dump(),
            )
            return ToolResultMessage(
                role=Role.TOOL,
                character_name=char_name,
                tool_call_id=tc.id,
                content=json.dumps(_result, ensure_ascii=False),
            )

        logger.info("Tool call: %s args=%s", tc.name, tc.arguments)

        # 统计
        if tc.name not in self._tool_stats:
            self._tool_stats[tc.name] = {"calls": 0, "errors": 0}
        self._tool_stats[tc.name]["calls"] += 1

        # 通知前端 tool_call 事件
        await self._loop.loop.get_sink().emit_tool_call(
            session_id, tc.name, tc.id, args,
            character_name=char_name,
        )

        # 审批流程
        _approval_args = {k: v for k, v in args.items() if k != "_session_id"}
        _hooks_ctx = self._loop.loop.get_hooks_context(session_id)

        ask_agent_callback: Callable[[str], Awaitable[str]] | None = None
        if self._llm is not None:
            async def _ask_agent_callback_impl(q: str) -> str:
                return await _ask_agent_reason(
                    self._llm, tc.name, _approval_args, q,
                    extra_context=_hooks_ctx,
                )
            ask_agent_callback = _ask_agent_callback_impl

        approval_start: float = time.monotonic()
        outcome = await execute_with_approval(
            tool_name=tc.name,
            args=args,
            session_id=session_id,
            sink=self._loop.loop.get_sink(),
            ask_agent_callback=ask_agent_callback,
            hooks_context=_hooks_ctx,
        )
        approval_duration_ms: int = int((time.monotonic() - approval_start) * 1000)

        _skip_dispatch = False
        result: dict | str | None = {}
        if outcome.denied:
            result = outcome.deny_result
            _skip_dispatch = True

        if not _skip_dispatch:
            invocation_start: float = time.monotonic()
            invocation_start_offset_ms: int = int((invocation_start - start_mono) * 1000)
            try:
                ctx = ToolContext(loop=self._loop, session_id=self._loop.loop.session_id)
                result = await tool_registry.async_dispatch(
                    tc.name, args, context=ctx,
                )
            except Exception as exc:
                logger.exception("Tool %s dispatch error: %s", tc.name, exc)
                self._tool_stats[tc.name]["errors"] += 1
                result = {
                    "error": f"Tool execution failed: {type(exc).__name__}: {exc}",
                }
            invocation_duration_ms: int = int((time.monotonic() - invocation_start) * 1000)
            end_time_offset_ms: int = int((time.monotonic() - start_mono) * 1000)
        else:
            # 审批拒绝：没有实际调用
            invocation_start_offset_ms = 0
            invocation_duration_ms = 0
            end_time_offset_ms = approval_duration_ms

        # 构建 _meta
        _meta = ToolCallMeta(
            application_time=application_time,
            application_time_ms=application_time_ms,
            approval_duration_ms=approval_duration_ms,
            invocation_start_offset_ms=invocation_start_offset_ms,
            invocation_duration_ms=invocation_duration_ms,
            end_time_offset_ms=end_time_offset_ms,
        )

        # 注入 _meta 到结果
        if isinstance(result, dict):
            result["_meta"] = _meta.model_dump()
        else:
            result = {"result": result, "_meta": _meta.model_dump()}

        # 统一转换为可保存到 History 的 content
        from entry.agent_support.multimodal import tool_result_to_content, content_to_text
        content = tool_result_to_content(result)

        # 通知前端结果（使用文本摘要，避免 base64 撑爆前端事件）
        await self._loop.loop.get_sink().emit_tool_result(
            session_id, tc.name, tc.id, content_to_text(content),
            character_name=char_name,
            tool_call_meta=_meta.model_dump(),
        )

        # 对前端 UI 类工具推送实时状态更新
        await ui_event_router.emit_for(
            tc.name,
            result,
            self._loop.loop.get_sink(),
            session_id,
        )

        return ToolResultMessage(
            role=Role.TOOL,
            character_name=char_name,
            tool_call_id=tc.id,
            content=content,
        )