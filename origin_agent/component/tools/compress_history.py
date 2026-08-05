"""历史压缩工具 — agent 主动调用，用 agent 撰写的摘要替换旧消息。

模块导入时通过 ``registry.register()`` 注册 ``compress_history`` 工具。
danger_level 为 critical：操作本身可能安全，但用户必须亲自许可，不可由模型代审批。
"""

from __future__ import annotations

import logging
from typing import Any, TYPE_CHECKING

from abstract.tools.registry import registry, tool_error, tool_result
from entity.puretype import Role, ToolAvailability, ToolDangerLevel
from entity.messages import CharacterConversationMessage
from entity.constant import (
    SYSTEM_CHARACTER_NAME,
    COMPRESS_HISTORY_DEFAULT_KEEP_ROUNDS,
    COMPRESS_HISTORY_MIN_KEEP_ROUNDS,
    COMPRESS_HISTORY_MAX_KEEP_ROUNDS,
    COMPRESS_HISTORY_MIN_MESSAGES,
)

if TYPE_CHECKING:
    from entry.base_agent_loop import ToolContext

logger = logging.getLogger(__name__)


async def _handle_compress_history(args: dict[str, Any], context: "ToolContext") -> dict:
    """用 agent 撰写的摘要替换旧消息，保留最近 N 轮对话。

    流程：
    1. 提取 summary 和 keep_recent_rounds 参数
    2. 边界保护（summary 为空、rounds 越界、历史过短）
    3. 定位截断位置（保护本轮对话不被压缩）
    4. 通知前端 → 截断 → 清理 → 插入摘要 → 保存 → 通知完成
    """
    loop = context.loop
    session_id = context.session_id
    history = loop.history

    # 1. 提取参数
    summary: str = str(args.get("summary", "")).strip()
    keep_recent_rounds: int = int(args.get("keep_recent_rounds", COMPRESS_HISTORY_DEFAULT_KEEP_ROUNDS))

    # 2. 边界保护
    if not summary:
        return tool_error("'summary' must not be empty")

    if keep_recent_rounds < COMPRESS_HISTORY_MIN_KEEP_ROUNDS or keep_recent_rounds > COMPRESS_HISTORY_MAX_KEEP_ROUNDS:
        return tool_error(
            f"'keep_recent_rounds' must be between {COMPRESS_HISTORY_MIN_KEEP_ROUNDS} and {COMPRESS_HISTORY_MAX_KEEP_ROUNDS}, got {keep_recent_rounds}"
        )

    if history.count < COMPRESS_HISTORY_MIN_MESSAGES:
        return tool_error(f"History is too short to compress (need at least {COMPRESS_HISTORY_MIN_MESSAGES} messages)")

    # 3. 定位保护边界
    last_user_idx = history.find_last_user_message_index(count=1)
    if last_user_idx is None:
        return tool_error("No user message found in history")

    # 4. 计算截断位置
    keep_start_idx = history.find_last_user_message_index(count=keep_recent_rounds)
    if keep_start_idx is None:
        # 不足 keep_recent_rounds 轮时全部保留
        keep_start_idx = 0

    if keep_start_idx >= last_user_idx:
        return tool_error(
            "Cannot compress: keep_recent_rounds covers the entire history. "
            "Try reducing keep_recent_rounds."
        )

    # 5. 通知前端
    await context.sink.emit_system_message(session_id, "正在压缩历史...")

    # 6. 截断（保留尾部）
    # 注意：截断后不调用 remove_unpaired_tool_calls()，
    # 因为当前轮的 assistant tool_calls（即本次 compress_history 调用）
    # 尚未配对 ToolResultMessage，此时清理会错误地移除它，
    # 导致 tool_result 无法配对写入 History，agent 会循环重复调用压缩。
    history.truncate_from(keep_start_idx)

    # 7. 插入摘要消息到头部
    summary_msg = CharacterConversationMessage(
        role=Role.USER,
        character_name=SYSTEM_CHARACTER_NAME,
        content=summary,
        visible_characters=[loop.current_character_agent],
    )
    history.insert_message(summary_msg, 0)

    # 8. 保存历史
    loop.save_history(session_id)

    # 9. 重置 token 计数
    loop._last_prompt_tokens = 0

    # 10. 通知前端
    await context.sink.emit_system_message(session_id, "压缩完成")

    logger.info(
        "History compressed | session=%s compressed=%d remaining=%d",
        session_id, keep_start_idx, history.count,
    )

    return tool_result(
        success=True,
        compressed=keep_start_idx,
        remaining=history.count,
    )


registry.register(
    name="compress_history",
    toolset="core",
    schema={
        # 用 agent 撰写的摘要替换旧消息，保留最近 N 轮对话。
        # 前置条件：会话历史至少 COMPRESS_HISTORY_MIN_MESSAGES 条消息。
        # 调用效果：截断旧消息并插入摘要，不可逆。
        # 返回格式：{ success, compressed, remaining }
        # 典型场景：用户要求压缩历史以提升响应速度。
        # 注意：此操作为 critical 级别，始终需要用户亲自审批，即使在脱手模式下也不走审批模型。
        "description": f"""Compress conversation history by replacing older messages with a summary you write, keeping recent rounds intact.

## Prerequisites
- The session must have at least {COMPRESS_HISTORY_MIN_MESSAGES} messages in history.
- You must write a summary of the conversation that captures key context, decisions, and current state.

## Parameters
- `summary` (required): A structured summary you write covering the conversation being compressed. Include key topics, decisions, user preferences, and current task state.
- `keep_recent_rounds` (optional, default {COMPRESS_HISTORY_DEFAULT_KEEP_ROUNDS}): Number of recent user/assistant conversation rounds to preserve. Must be between {COMPRESS_HISTORY_MIN_KEEP_ROUNDS} and {COMPRESS_HISTORY_MAX_KEEP_ROUNDS}.

## Effect
Replaces all messages before the kept rounds with your summary. This is irreversible.

## Returns
```json
{{ "success": true, "compressed": <int>, "remaining": <int> }}
```

## When to Use
- When the user asks you to compress/summarize the conversation.
- When responses are getting slow due to long context.

## Important
- This is a `critical` level operation: it always requires explicit user approval, even in handsfree mode.
- The summary should be information-dense and preserve all critical context.
- Do NOT compress the current round (the last user message and your response).""",
        "parameters": {
            "type": "object",
            "properties": {
                "summary": {
                    "type": "string",
                    # agent 撰写的历史摘要文本，应包含关键上下文、决策和当前状态。
                    "description": "A structured summary of the conversation being compressed. Cover key topics, decisions, user preferences, and current task state.",
                },
                "keep_recent_rounds": {
                    "type": "integer",
                    "default": COMPRESS_HISTORY_DEFAULT_KEEP_ROUNDS,
                    # 保留最近多少轮原始对话（一轮 = 一条 user 消息及其后的 assistant/tool 消息）。
                    "description": f"Number of recent conversation rounds to preserve. Must be between {COMPRESS_HISTORY_MIN_KEEP_ROUNDS} and {COMPRESS_HISTORY_MAX_KEEP_ROUNDS}. Default is {COMPRESS_HISTORY_DEFAULT_KEEP_ROUNDS}.",
                },
            },
            "required": ["summary"],
        },
    },
    handler=_handle_compress_history,
    is_async=True,
    emoji="🗜️",
    danger_level=ToolDangerLevel.critical,
    availability=ToolAvailability.MAIN,
)