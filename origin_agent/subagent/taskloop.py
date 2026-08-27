"""一次性任务 Agent 的 LLM 调用 + 工具执行循环。

继承 ``SubAgentLoop``，覆写终止行为：
- LLM 产出纯文本回复时立即终止（不等待 ``_wake_event``）
- 达到 ``MAX_TOOL_TURNS`` 上限时终止并通知 outbox
- 无系统提示词
- 无持久化、无历史保存
"""

from __future__ import annotations

import json
import logging
from typing import * # type: ignore

from entity.puretype import LLMResponse
from entity.constant import MAIN_AGENT_CHARACTER_NAME, USER_CHARACTER_NAME
from entity.messages import (
    CharacterConversationMessage,
    FunctionCall,
    ToolResultMessage,
    ToolCall as HistoryToolCall,
)
from entity.puretype import Role
from subagent.context import SubRuntimeContext
from subagent.loop import SubAgentLoop, format_user_message
from entry.tool_executor import _interrupted_result

logger = logging.getLogger(__name__)


class TaskAgentLoop(SubAgentLoop):
    """一次性任务 Agent — 完成即终止，不等待唤醒。

    与 ``SubAgentLoop`` 的核心差异：
    - 无系统提示词（``_build_system_prompt`` 返回空列表）
    - LLM 产出纯文本时设 ``_completed=True`` 并 return（不 await ``_wake_event``）
    - 达到 ``MAX_TOOL_TURNS`` 时设 ``_completed=True`` 并通知 outbox
    """

    def _build_system_prompt(self) -> list[str]:
        """taskagent 无系统提示词。"""
        return []

    async def run(self, initial_prompt: str, user_name: str, message_type: str) -> None:
        """taskagent 主循环 — 纯文本回复即终止。"""
        from system.application import Application
        _cron = Application.current().cron_router
        if _cron is not None:
            _cron.register(self.session_id, self)
        try:
            # 注入初始用户消息
            initial_character_name = (
                USER_CHARACTER_NAME if message_type == "user_direct"
                else (self._parent_character_agent or MAIN_AGENT_CHARACTER_NAME)
            )
            self._history.add_message(
                CharacterConversationMessage(
                    role=Role.USER,
                    character_name=initial_character_name,
                    content=format_user_message(user_name, message_type, initial_prompt),
                    visible_characters=[self.current_character_agent],
                )
            )

            turn: int = 0
            while turn < self._max_turns:
                if self._cancel_event.is_set():
                    return
                turn += 1
                self._round_active = True

                messages = self._build_history_messages()
                resp: LLMResponse = await self._llm.chat(
                    messages, self._tools, character=self.current_character_agent,
                    last_user_message=self._history.last_user_message,
                )

                if self._cancel_event.is_set():
                    return

                reasoning_text = resp.reasoning_content

                if not resp.tool_calls:
                    # 纯文本回复 — taskagent 终止
                    text = resp.content or ""
                    assistant_msg = CharacterConversationMessage(
                        role=Role.ASSISTANT,
                        character_name=self.current_character_agent,
                        content=text,
                        reasoning=reasoning_text,
                        reasoning_field_name=resp.reasoning_field_name,
                    )
                    self._history.add_message(assistant_msg)
                    self._outbox.append(text)
                    self._outbox_event.set()
                    self._emit("assistant", content=text, reasoning=reasoning_text,
                               character_name=self.current_character_agent)
                    self._completed = True
                    self._round_active = False
                    return

                # 推送 assistant 文本（若与 tool_calls 同帧）
                if resp.content:
                    self._emit("assistant", content=resp.content, reasoning=reasoning_text,
                               character_name=self.current_character_agent)

                # 存储带 tool_calls 的 assistant 消息
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
                assistant_msg = CharacterConversationMessage(
                    role=Role.ASSISTANT,
                    character_name=self.current_character_agent,
                    content=resp.content or "",
                    tool_calls=tool_calls_data,
                    reasoning=reasoning_text,
                    reasoning_field_name=resp.reasoning_field_name,
                )
                self._history.add_message(assistant_msg)

                # 处理工具调用 — safe 直接执行；理论上非 safe 不在工具集中
                try:
                    _executed_tool_msgs: list[ToolResultMessage] = []
                    for i, tc in enumerate(resp.tool_calls):
                        if self._cancel_event.is_set():
                            for remaining in resp.tool_calls[i:]:
                                self._history.add_message(_interrupted_result(
                                    remaining, self.current_character_agent, "pending",
                                ))
                            return

                        self._emit(
                            "tool_call",
                            tool_call_id=tc.id,
                            tool_name=tc.name,
                            tool_args=dict(tc.arguments) if tc.arguments else {},
                        )

                        if self._is_auto_executable(tc.name) or self._is_auto_approved_tool(
                            tc.name, dict(tc.arguments) if tc.arguments else {}
                        ):
                            tool_msg = await self._execute_approved_tool(tc)
                        else:
                            tool_msg = await self._queue_for_approval(tc)

                        from entry.agent_support.multimodal import content_to_text
                        raw_content = content_to_text(tool_msg.content)
                        self._maybe_record_tool_failure(tc.name, raw_content)

                        messages.append(tool_msg)
                        self._history.add_message(tool_msg)
                        _executed_tool_msgs.append(tool_msg)

                    # 延迟注入 follow_up 消息
                    for tm in _executed_tool_msgs:
                        if tm._follow_up_messages:
                            for fu_msg in tm._follow_up_messages:
                                self._history.add_message(fu_msg)
                except BaseException:
                    logger.exception(
                        "TaskAgent tool loop failed | session=%s", self.session_id,
                    )
                    _assistant_ids = {t.id for t in resp.tool_calls}
                    _executed_ids = {
                        m.tool_call_id
                        for m in self._history.iter_messages()
                        if isinstance(m, ToolResultMessage) and m.tool_call_id in _assistant_ids
                    }
                    for tc in resp.tool_calls:
                        if tc.id in _executed_ids:
                            continue
                        self._history.add_message(_interrupted_result(
                            tc, self.current_character_agent, "unexpected",
                        ))
                    return

                self._round_active = False
                self._maybe_inject_inbox()

            # 达到 MAX_TOOL_TURNS 上限
            self._outbox.append("[taskagent] Max tool turns reached.")
            self._outbox_event.set()
            self._completed = True
            self._round_active = False
            logger.warning(
                "TaskAgent reached max tool turns | session=%s turns=%d",
                self.session_id, self._max_turns,
            )

        except Exception as exc:
            logger.exception("TaskAgentLoop error for session=%s: %s", self.session_id, exc)
        finally:
            if _cron is not None:
                _cron.unregister(self.session_id)
            self._terminated = True
            # SP-5 D4 R1：唤醒 waiter 做终结检查并 break（防永久悬挂）
            self._outbox_event.set()