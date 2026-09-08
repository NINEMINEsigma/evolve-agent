"""ColloquyLoop — "随意聊聊"会话循环，继承 ParentAgentLoop。

与 ParentAgentLoop 的差异：
- 工具集仅限 component/tools 和 component/extools（排除 multiagenttools/automation/MCP）
- 会话永不旋转/过期，不可删除/终结
- 上下文超限时采用滑动窗口压缩最早 30% 消息，而非旋转会话
"""

from __future__ import annotations

import logging
from typing import Any

from abstract.tools.registry import registry as tool_registry
from entity.puretype import Role, ToolAvailability, MessageContent
from entity.constant import (
    COLLOQUY_COMPRESS_RATIO,
    COLLOQUY_TOOLSET_WHITELIST,
    SYSTEM_CHARACTER_NAME,
)
from entity.messages import (
    CharacterConversationMessage,
    History,
)
from entry.parent_agent_loop import ParentAgentLoop

logger = logging.getLogger(__name__)


class ColloquyLoop(ParentAgentLoop):
    """随意聊聊会话循环 — 不旋转、不归档，超限时滑动窗口压缩。

    继承 ParentAgentLoop 的全部工具循环、流式 LLM、memory、hooks 能力，
    仅覆写工具过滤、超限处理和 session 保护逻辑。
    """

    # ========================================================================
    # 工具过滤
    # ========================================================================

    def _get_tool_definitions(self) -> list[dict]:
        """返回白名单范围内且已加载的工具 schema。

        在 `_get_effective_tool_definitions()`（已加载工具集 × MAIN scope）基础上，
        叠加 ColloquyLoop 工具集白名单过滤。
        """
        definitions: list[dict] = self._get_effective_tool_definitions()
        filtered: list[dict] = []
        for d in definitions:
            func = d.get("function") or {}
            name = func.get("name", "")
            entry = tool_registry.get_entry(name)
            if entry and entry.toolset in COLLOQUY_TOOLSET_WHITELIST:
                filtered.append(d)
        return filtered

    # ========================================================================
    # 超限处理 — 滑动窗口压缩
    # ========================================================================

    async def _check_over_limit_before_process(
        self, sid: str, user_message: MessageContent | None,
    ) -> str:
        """process_message 入口处的超限检查：超限时滑动窗口压缩，返回原 sid。

        user_message 为 None 表示队列路径（SP-4），滑窗路径忽略该参数。
        """
        if self._lifecycle.is_context_over_limit():
            await self._compress_sliding_window(sid)
        return sid

    async def _check_over_limit_in_tool_loop(self, sid: str) -> str:
        """_run_tool_loop 内每轮工具调用后的超限检查：超限时滑动窗口压缩，返回原 sid。"""
        if self._lifecycle.is_context_over_limit():
            await self._compress_sliding_window(sid)
        return sid

    async def _compress_sliding_window(self, sid: str) -> None:
        """滑动窗口压缩：将最早 30% 的消息压缩为一条摘要消息。

        保证不压缩本轮对话（最后一条 user 消息及之后的内容）。
        """
        from entry.agent_support.history_summary import summarize_history

        # 1. 通知前端
        await self._frontend_sink.emit_system_message(sid, "正在压缩历史...")

        # 2. 计算压缩范围
        compress_count: int = int(self._history.count * COLLOQUY_COMPRESS_RATIO)

        # 3. 边界保护：无用户消息或压缩量不足时跳过
        last_user_idx = self._history.find_last_user_message_index(count=1)
        if last_user_idx is None:
            logger.info("Colloquy compress skipped: no user message found | session=%s", sid)
            await self._frontend_sink.emit_system_message(sid, "压缩完成（无需压缩）")
            return

        if compress_count >= last_user_idx:
            compress_count = max(last_user_idx - 1, 0)

        if compress_count < 1:
            logger.info("Colloquy compress skipped: compress_count < 1 | session=%s", sid)
            await self._frontend_sink.emit_system_message(sid, "压缩完成（无需压缩）")
            return

        # 4. 构建临时 History（绕过 add_message 校验，避免 ToolResultMessage 配对问题）
        messages_to_compress = list(self._history.messages[:compress_count])
        temp_history = History(messages=messages_to_compress)

        # 5. LLM 生成摘要
        llm = self._llm
        if llm is None:
            raise RuntimeError("No LLM client available for colloquy history summary")
        summary: str = await summarize_history(temp_history, llm)
        if not summary:
            logger.warning("Colloquy compress: summary generation failed | session=%s", sid)
            await self._frontend_sink.emit_system_message(sid, "压缩完成（摘要生成失败）")
            return

        # 6. 替换：truncate → remove_unpaired → insert 摘要
        self._history.truncate_to(compress_count)
        self._history.remove_unpaired_tool_calls()
        self._history.insert_message(
            CharacterConversationMessage(
                role=Role.USER,
                character_name=SYSTEM_CHARACTER_NAME,
                content=summary,
                visible_characters=[self.current_character_agent],
            ),
            0,
        )
        self.save_history(sid)
        self._token_record.prompt_tokens = 0

        # 7. 通知前端
        await self._frontend_sink.emit_system_message(sid, "压缩完成")
        logger.info(
            "Colloquy compress done | session=%s compressed=%d remaining=%d",
            sid, compress_count, self._history.count,
        )

    # ========================================================================
    # Session 保护
    # ========================================================================

    async def terminate_session(self) -> dict:
        """colloquy session 不可终结。"""
        logger.warning("Colloquy session terminate rejected | session=%s", self.session_id)
        return {"terminated": False, "error": "colloquy session cannot be terminated"}

    def pop_session_rotated(self) -> str | None:
        """colloquy session 永不旋转。"""
        return None