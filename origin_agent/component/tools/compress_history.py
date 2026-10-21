"""历史压缩工具 — agent 主动调用，用 agent 撰写的摘要替换旧消息。

工具对象协议：模块导出顶层 ``TOOLSET``（``BaseToolSet``），其中持有
``CompressHistoryTool`` 实例。``handle`` 只做参数边界校验并登记调用态材料，
不含任何历史变更；真正的替换发生在结果写入并保存后的 ``after_handle``——
那时本次调用已经拥有配对结果，重新扫描历史才能正确压缩保留区内的完整工具链。

danger_level 为 critical：操作本身可能安全，但用户必须亲自许可，不可由模型代审批。
"""

from __future__ import annotations

from interface.session_metadata_service import ISessionMetadataService

import asyncio
import logging

from abstract.tools.tool import (
    BaseTool,
    BaseToolSet,
    ToolExecution,
    ToolHandlerResult,
    ToolPostprocessEffect,
    tool_error,
    tool_result,
)
from component.tools._history_compression import (
    collect_tool_call_ids,
    prepare_tool_chain_replacements,
)
from entity.constant import (
    COMPRESS_HISTORY_DEFAULT_KEEP_ROUNDS,
    COMPRESS_HISTORY_MAX_KEEP_ROUNDS,
    COMPRESS_HISTORY_MIN_KEEP_ROUNDS,
    COMPRESS_HISTORY_MIN_MESSAGES,
    SYSTEM_CHARACTER_NAME,
)
from entity.messages import CharacterConversationMessage
from entity.puretype import Role, ToolAvailability, ToolDangerLevel

logger = logging.getLogger(__name__)


class _PendingHistoryCompression:
    """handle 与 after_handle 之间携带的已校验参数。

    单次调用独占的非持久化业务运行时对象：不写回共享工具实例，不进入 easysave，
    也不属于 ``entity.puretype``（不引入消息依赖）。
    """

    def __init__(self, *, summary: str, keep_start_idx: int) -> None:
        self.summary = summary
        self.keep_start_idx = keep_start_idx


# ── schema 常量 ─────────────────────────────────────────────

_COMPRESS_HISTORY_SCHEMA = {
    # 用 agent 撰写的摘要替换旧消息，保留最近 N 轮对话。
    # 前置条件：会话历史至少 COMPRESS_HISTORY_MIN_MESSAGES 条消息。
    # 调用效果：截断旧消息并插入摘要，不可逆。
    # 返回格式：{ success, compressed, remaining, tool_chains_compressed }
    # 典型场景：用户要求压缩历史；agent 感知上下文丢失或响应质量下降时主动压缩。
    # 注意：此操作为 critical 级别，始终需要用户亲自审批，即使在脱手模式下也不走审批模型。
    "description": f"""Compress conversation history: replace older rounds with a summary you write, and repack complete tool call chains inside the kept rounds into single compressed placeholder calls carrying LLM-generated chain summaries.

## Prerequisites
- The session must have at least {COMPRESS_HISTORY_MIN_MESSAGES} messages in history.
- You must write a summary of the conversation that captures key context, decisions, and current state.

## Parameters
- `summary` (required): A structured summary you write covering the conversation being compressed. Include key topics, decisions, user preferences, and current task state.
- `keep_recent_rounds` (optional, default {COMPRESS_HISTORY_DEFAULT_KEEP_ROUNDS}): Number of recent user/assistant conversation rounds to preserve. Must be between {COMPRESS_HISTORY_MIN_KEEP_ROUNDS} and {COMPRESS_HISTORY_MAX_KEEP_ROUNDS}.

## Effect
1. Rounds older than the kept rounds are replaced by your summary.
2. Inside the kept rounds, every complete tool call chain (all calls already have results) above a small size threshold is repacked into one placeholder tool call `CompressedToolChain` (not callable) whose paired tool result carries a model-generated chain summary. Chains from the current, still-running round are never touched.
3. This is irreversible. If any chain summary cannot be generated, the whole operation fails and the history is left unchanged.

## Returns
```json
{{ "success": true, "compressed": <int>, "remaining": <int>, "tool_chains_compressed": <int> }}
```

## When to Use
- When the user asks you to compress/summarize the conversation.
- When responses are getting slow due to long context.
- When you notice you are losing track of earlier conversation details.
- When context length is degrading your response quality.

## Important
- This is a `critical` level operation: it always requires explicit user approval, even in handsfree mode.
- This tool has no execution timeout: generating one summary per compressed tool chain may take a while.
- Do NOT compress the current round (the last user message and your response).

## Summary Quality Requirements
- The summary is your only record of the compressed conversation — you cannot access the original messages after compression.
- Must include: key decisions, file changes, user preferences, current task state, open issues, errors and lessons learned.
- Be information-dense: every sentence should preserve context that would otherwise be lost.""",
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
}


class CompressHistoryTool(BaseTool):
    def __init__(self) -> None:
        super().__init__(
            name="CompressHistory",
            toolset="core",
            schema=_COMPRESS_HISTORY_SCHEMA,
            is_async=True,
            danger_level=ToolDangerLevel.critical,
            availability=ToolAvailability.MAIN,
            no_timeout=True,
            accepts_following_calls=False,
        )

    def handle(self, execution: ToolExecution) -> ToolHandlerResult:
        args = execution.arguments
        summary = str(args.get("summary", "")).strip()
        keep_recent_rounds = int(
            args.get("keep_recent_rounds", COMPRESS_HISTORY_DEFAULT_KEEP_ROUNDS)
        )
        history = execution.context.loop.history

        # 边界保护（summary 为空、rounds 越界、历史过短）
        if not summary:
            return ToolHandlerResult(result=tool_error("'summary' must not be empty"))
        if not COMPRESS_HISTORY_MIN_KEEP_ROUNDS <= keep_recent_rounds <= COMPRESS_HISTORY_MAX_KEEP_ROUNDS:
            return ToolHandlerResult(result=tool_error(
                f"'keep_recent_rounds' must be between {COMPRESS_HISTORY_MIN_KEEP_ROUNDS} and {COMPRESS_HISTORY_MAX_KEEP_ROUNDS}, got {keep_recent_rounds}"
            ))
        if history.count < COMPRESS_HISTORY_MIN_MESSAGES:
            return ToolHandlerResult(result=tool_error(
                f"History is too short to compress (need at least {COMPRESS_HISTORY_MIN_MESSAGES} messages)"
            ))

        # 定位截断位置（保护本轮对话不被压缩）。
        if history.find_last_user_message_index(count=1) is None:
            return ToolHandlerResult(result=tool_error("No user message found in history"))
        keep_start_idx = history.find_last_user_message_index(count=keep_recent_rounds)
        if keep_start_idx is None:
            # 不足 keep_recent_rounds 轮时全部保留。
            keep_start_idx = 0

        # keep_start_idx == 0 表示保留区从历史最开头开始，前面没有任何消息可压缩。
        # 注意：不能用 keep_start_idx >= last_user_idx 判断——
        # 当 keep_recent_rounds=1 时 keep_start_idx 恰好等于 last_user_idx，
        # 但此时 last_user_idx 之前仍有更早的消息可以压缩，属于合法场景。
        if keep_start_idx == 0:
            return ToolHandlerResult(result=tool_error(
                "Cannot compress: keep_recent_rounds covers the entire history. "
                "Try reducing keep_recent_rounds."
            ))

        # 只登记调用态材料；本次调用的配对结果写入并保存后才执行替换。
        return ToolHandlerResult(
            result=tool_result(success=True, _compression_pending=True),
            state=_PendingHistoryCompression(summary=summary, keep_start_idx=keep_start_idx),
        )

    async def after_handle(self, execution: ToolExecution) -> ToolPostprocessEffect:
        state = execution.state
        # handle 返回业务错误时没有调用态材料：空 after，不扫描、不调用模型、不保存。
        if state is None:
            return ToolPostprocessEffect()

        context = execution.context
        loop = context.loop
        session_id = context.session_id
        history = loop.history

        # 摘要模型调用前先通知前端；完成通知在替换与保存成功后发送。
        await context.sink.emit_system_message(session_id, "正在压缩历史...")

        # 重新取得提交后的完整历史快照：本次调用此时已有配对结果。
        # 排除集合包含当前 tool_call_id，使当前调用所在整条链不参与压缩。
        snapshot = list(history.iter_messages())

        metadata_service = context.app.get_system(ISessionMetadataService)
        replacements = await prepare_tool_chain_replacements(
            snapshot,
            session_id=session_id,
            metadata_service=metadata_service,
            start_index=state.keep_start_idx,
            excluded_tool_call_ids={execution.tool_call_id},
        )

        # 生成期间收到的协作式中断也必须在提交前生效；取消不转换为成功。
        if context.is_interrupted:
            raise asyncio.CancelledError

        # 被替换链与被截断轮次里的真实调用都要从前端移除。
        # 本次调用位于保留轮次且其链被排除，因此不在该集合中，不会 suppress。
        discarded_ids = collect_tool_call_ids(
            snapshot,
            [(replacement.start, replacement.end) for replacement in replacements]
            + [(0, state.keep_start_idx)],
        )

        # 应用链重打包（从后往前，避免索引位移）；链完全位于保留区内。
        for replacement in reversed(replacements):
            history.replace_range(replacement.start, replacement.end, replacement.messages)

        # 截断边界是 user 消息索引，按轮次整体丢弃，不切断 tool_calls/结果配对，
        # 因此不需要额外的未配对清理。
        history.truncate_from(state.keep_start_idx)

        # 插入摘要消息到头部。
        summary_message = CharacterConversationMessage(
            role=Role.USER,
            character_name=SYSTEM_CHARACTER_NAME,
            content=state.summary,
            visible_characters=[loop.current_character_agent],
        )
        history.insert_message(summary_message, 0)

        # 保存成功后重置 token 计数并通知完成；任一步失败直接传播。
        loop.save_history(session_id)
        execution.mark_history_updated()
        loop.reset_context_tokens()

        logger.info(
            "History compressed | session=%s compressed=%d remaining=%d tool_chains=%d",
            session_id, state.keep_start_idx, history.count, len(replacements),
        )

        return ToolPostprocessEffect(
            replacement_result=tool_result(
                success=True,
                compressed=state.keep_start_idx,
                remaining=history.count,
                tool_chains_compressed=len(replacements),
            ),
            discarded_tool_call_ids=discarded_ids,
            system_message="压缩完成",
        )


TOOLSET = BaseToolSet(
    name="core",
    tools=(CompressHistoryTool(),),
)
