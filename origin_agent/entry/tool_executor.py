"""ToolExecutor — 统一工具调用执行器。

封装单个工具调用的完整流程：取消检查、parse error 处理、审批、
registry 分发、异常转换、前端事件推送和 UI 事件路由。

审批流程直接复用 ``component.approval.executor.execute_with_approval``。
"""

from __future__ import annotations

import json
import logging
from typing import Any, Awaitable, Callable, TYPE_CHECKING

from entity.puretype import Role
from entity.messages import ToolResultMessage
from entry.base_agent_loop import BaseAgentLoop, ToolContext, IMainSessionLoop

if TYPE_CHECKING:
    from component.llm import ToolCall, LLMClient

logger = logging.getLogger(__name__)


class ToolExecutor:
    """执行单个工具调用，处理审批、分发和事件推送。

    由 IMainSessionLoop 持有，每个 tool_call 调用一次 ``execute()``。
    """

    def __init__(self, loop: IMainSessionLoop, llm: LLMClient) -> None:
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
    ) -> ToolResultMessage:
        """执行单个工具调用，返回 ToolResultMessage。"""
        from entity.constant import LOG_PREVIEW_CHARS
        from component.approval import execute_with_approval, ask_agent_reason as _ask_agent_reason
        from abstract.tools.registry import registry as tool_registry
        from abstract.tools.ui_event_router import ui_event_router

        args = dict(tc.arguments)

        # 取消检查
        if self._loop.is_interrupted() or self._loop._cancel_event.is_set():
            return ToolResultMessage(
                role=Role.TOOL,
                character_name=self._loop.current_character_agent,
                tool_call_id=tc.id,
                content="Cancelled.",
            )

        args["_session_id"] = session_id

        # parse error
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
            await self._loop._get_sink().emit_tool_result(
                session_id, tc.name, tc.id,
                json.dumps(_result, ensure_ascii=False),
            )
            return ToolResultMessage(
                role=Role.TOOL,
                character_name=self._loop.current_character_agent,
                tool_call_id=tc.id,
                content=json.dumps(_result, ensure_ascii=False),
            )

        logger.info("Tool call: %s args=%s", tc.name, tc.arguments)

        # 统计
        if tc.name not in self._tool_stats:
            self._tool_stats[tc.name] = {"calls": 0, "errors": 0}
        self._tool_stats[tc.name]["calls"] += 1

        # 通知前端 tool_call 事件
        await self._loop.loop._get_sink().emit_tool_call(
            session_id, tc.name, tc.id, args,
        )

        # 审批流程
        _approval_args = {k: v for k, v in args.items() if k != "_session_id"}
        _hooks_ctx = self._loop.loop._get_hooks_context(session_id)

        ask_agent_callback: Callable[[str], Awaitable[str]] | None = None
        if self._llm is not None:
            async def _ask_agent_callback_impl(q: str) -> str:
                return await _ask_agent_reason(
                    self._llm, tc.name, _approval_args, q,
                    extra_context=_hooks_ctx,
                )
            ask_agent_callback = _ask_agent_callback_impl

        outcome = await execute_with_approval(
            tool_name=tc.name,
            args=args,
            session_id=session_id,
            sink=self._loop.loop._get_sink(),
            ask_agent_callback=ask_agent_callback,
            hooks_context=_hooks_ctx,
        )

        _skip_dispatch = False
        result: dict | str | None = {}
        if outcome.denied:
            result = outcome.deny_result
            _skip_dispatch = True

        if not _skip_dispatch:
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

        # 统一转换为可保存到 History 的 content
        from entry.agent_support.multimodal import tool_result_to_content, content_to_text
        content = tool_result_to_content(result)

        # 通知前端结果（使用文本摘要，避免 base64 撑爆前端事件）
        await self._loop.loop._get_sink().emit_tool_result(
            session_id, tc.name, tc.id, content_to_text(content),
        )

        # 对前端 UI 类工具推送实时状态更新
        await ui_event_router.emit_for(
            tc.name,
            result,
            self._loop.loop._get_sink(),
            session_id,
        )

        return ToolResultMessage(
            role=Role.TOOL,
            character_name=self._loop.current_character_agent,
            tool_call_id=tc.id,
            content=content,
        )