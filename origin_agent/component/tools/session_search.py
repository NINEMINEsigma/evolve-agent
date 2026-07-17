"""跨会话历史查询工具 — search_sessions + get_session_messages。

模块导入时通过 ``registry.register()`` 注册两个工具：
  - search_sessions: 按关键词搜索所有会话（轻量/全文两档）
  - get_session_messages: 按会话ID获取消息内容或消息总数
"""

from __future__ import annotations

import logging
from typing import Any

from abstract.tools.registry import registry, tool_error, tool_result
from entity.puretype import ToolAvailability, ToolDangerLevel, Role, SessionStatus

logger = logging.getLogger(__name__)

_MAX_MATCHED_SESSIONS = 20
_MAX_MATCHED_INDICES_PER_SESSION = 50


# ── 辅助函数 ─────────────────────────────────────────────


def _filter_conversation_messages(history) -> list[tuple[int, Any]]:
    """过滤出 Role.USER 和 Role.ASSISTANT 的 CharacterConversationMessage。

    返回 (原始index, message) 列表，index 是 messages 列表中的全局位置。
    """
    from entity.messages import CharacterConversationMessage

    result: list[tuple[int, Any]] = []
    for idx, msg in enumerate(history.iter_messages()):
        if not isinstance(msg, CharacterConversationMessage):
            continue
        if msg.role not in (Role.USER, Role.ASSISTANT):
            continue
        result.append((idx, msg))
    return result


def _extract_content_with_suffix(msg) -> str:
    """提取消息的纯文本内容，附加固着器后缀。

    使用与摘要生成相同的 _content_to_text 方法提取纯文本，
    然后追加 message_suffix 和 dynamic_message_suffix（如有）。
    """
    from entry.agent_support.history_summary import _content_to_text

    text = _content_to_text(msg.content)
    suffix = getattr(msg, "message_suffix", None)
    if suffix:
        text += suffix
    dynamic_suffix = getattr(msg, "dynamic_message_suffix", None)
    if dynamic_suffix:
        text += dynamic_suffix
    return text


def _get_session_store():
    """通过 Application 单例获取 SessionStore 实例。

    返回 SessionStore 或 None（store_path 未配置时）。
    """
    from system.application import Application
    from system.session_store import SessionStore

    sm = Application.current().session_manager
    if sm is None:
        return None
    store_path = sm._store_path
    if not store_path:
        return None
    return SessionStore(store_path)


# ── 工具 handler ─────────────────────────────────────────────


def _handle_search_sessions(args: dict[str, Any]) -> dict:
    """搜索所有会话，返回匹配的会话列表。"""
    keyword: str = str(args.get("keyword", "")).strip()
    deep: bool = bool(args.get("deep", False))
    current_session_id: str = str(args.get("_session_id", ""))

    if not keyword:
        return tool_error("'keyword' is required")

    from system.application import Application

    sm = Application.current().session_manager
    if sm is None:
        return tool_error("SessionManager not available")

    session_store = _get_session_store()
    all_sessions = sm.get_all()

    kw_lower = keyword.lower()
    matches: list[dict] = []

    for info in all_sessions:
        sid = info.id
        is_current = sid == current_session_id
        is_archived = info.status == SessionStatus.archived

        # 轻量匹配：title + tags
        matched = False
        if info.title and kw_lower in info.title.lower():
            matched = True
        if not matched and info.tags:
            for tag in info.tags:
                if kw_lower in tag.lower():
                    matched = True
                    break

        # 归档会话的 summary 匹配
        summary_text: str | None = None
        if session_store is not None:
            try:
                summary_text = session_store.read_summary(sid)
            except Exception:
                pass
        if not matched and summary_text and kw_lower in summary_text.lower():
            matched = True

        matched_indices: list[int] | None = None

        # 全文搜索：遍历 history.es
        if deep and session_store is not None:
            try:
                history = session_store.read_history(sid)
            except Exception:
                logger.exception("Failed to read history for session=%s", sid)
                history = None

            if history is not None:
                conv_msgs = _filter_conversation_messages(history)
                indices: list[int] = []
                for idx, msg in conv_msgs:
                    content_text = _extract_content_with_suffix(msg)
                    if kw_lower in content_text.lower():
                        indices.append(idx)
                        if len(indices) >= _MAX_MATCHED_INDICES_PER_SESSION:
                            break
                if indices:
                    matched = True
                    matched_indices = indices

        if not matched:
            continue

        entry: dict = {
            "session_id": sid,
            "title": info.title,
            "is_current": is_current,
            "is_archived": is_archived,
        }
        if is_archived and summary_text:
            entry["summary"] = summary_text
        if matched_indices is not None:
            entry["matched_indices"] = matched_indices

        matches.append(entry)
        if len(matches) >= _MAX_MATCHED_SESSIONS:
            break

    return tool_result(
        matches=matches,
        total_sessions_scanned=len(all_sessions),
        total_matched=len(matches),
    )


def _handle_get_session_messages(args: dict[str, Any]) -> dict:
    """获取指定会话的消息内容或消息总数。"""
    session_id: str = str(args.get("session_id", "")).strip()
    raw_indices = args.get("indices")

    if not session_id:
        return tool_error("'session_id' is required")

    session_store = _get_session_store()
    if session_store is None:
        return tool_error("SessionStore not available")

    try:
        history = session_store.read_history(session_id)
    except Exception as exc:
        logger.exception("Failed to read history for session=%s", session_id)
        return tool_error(f"Failed to load history: {exc}")

    if history is None:
        return tool_error(f"Session not found: {session_id}")

    conv_msgs = _filter_conversation_messages(history)

    # 无 indices：返回消息总数
    if raw_indices is None:
        return tool_result(
            session_id=session_id,
            message_count=len(conv_msgs),
        )

    # 有 indices：返回指定消息
    if not isinstance(raw_indices, list):
        return tool_error("'indices' must be a list of integers")

    indices_set: set[int] = set()
    for i in raw_indices:
        try:
            indices_set.add(int(i))
        except (ValueError, TypeError):
            pass

    if not indices_set:
        return tool_error("'indices' must contain at least one valid integer")

    # 构建索引到消息的映射
    conv_map: dict[int, Any] = {idx: msg for idx, msg in conv_msgs}

    messages: list[dict] = []
    for idx in sorted(indices_set):
        msg = conv_map.get(idx)
        if msg is None:
            logger.warning(
                "Index %d not found in conversation messages for session=%s",
                idx, session_id,
            )
            continue
        content_text = _extract_content_with_suffix(msg)
        messages.append({
            "index": idx,
            "character_name": getattr(msg, "character_name", ""),
            "content": content_text,
        })

    return tool_result(
        session_id=session_id,
        messages=messages,
    )


# ── 注册 ─────────────────────────────────────────────────────

# 搜索所有会话历史，支持轻量和全文两种搜索深度。
# 前置条件：会话管理子系统已初始化。
# 调用效果：轻量模式仅匹配会话标题、标签和摘要；全文模式额外搜索每条对话消息的内容。
# 返回格式：{ matches: [{session_id, title, is_current, is_archived, summary?, matched_indices?}], total_sessions_scanned, total_matched }
# 轻量模式不返回 matched_indices；全文模式返回匹配消息的索引列表。
# 归档会话额外返回摘要文本。
# 典型场景：回顾其他会话的讨论内容、定位包含特定关键词的历史会话。
# 副作用：全文搜索模式下当会话数量较多时可能有秒级延迟。
# 提醒：全文模式最多返回 20 个匹配会话、每会话 50 个匹配索引。
registry.register(
    name="search_sessions",
    toolset="core",
    schema={
        "description": """Search across all session histories by keyword.

## Prerequisites
The session management system must be initialized.

## Effect
In lightweight mode (`deep=false`), matches session titles, tags, and summaries only.
In full-text mode (`deep=true`), additionally searches the content of every conversation message across all sessions.

## Returns
```json
{
  "matches": [
    {
      "session_id": "<id>",
      "title": "<title>",
      "is_current": false,
      "is_archived": true,
      "summary": "<archived sessions only>",
      "matched_indices": [3, 7]
    }
  ],
  "total_sessions_scanned": 15,
  "total_matched": 3
}
```
`summary` is only included for archived sessions.
`matched_indices` is only included when `deep=true`.

## When to Use
- Looking for past discussions on a specific topic.
- Finding which session contains a particular keyword.
- Reviewing conversation history from other sessions.

## Side Effects
Full-text mode may take several seconds when many sessions exist.

## Notes
- Only user and assistant messages are searched; tool calls and system prompts are excluded.
- Results are capped at 20 matched sessions with 50 matched indices per session.""",
        "parameters": {
            "type": "object",
            "properties": {
                "keyword": {
                    "type": "string",
                    # 搜索关键词，不区分大小写。必需。
                    "description": """The keyword to search for. Case-insensitive. Required.""",
                },
                "deep": {
                    "type": "boolean",
                    # 搜索深度。false（默认）= 轻量模式，仅匹配标题/标签/摘要；
                    # true = 全文模式，额外搜索每条对话消息的内容。
                    "description": """Search depth. `false` (default) matches session titles, tags, and summaries only. `true` additionally searches the content of every conversation message.""",
                    "default": False,
                },
            },
            "required": ["keyword"],
        },
    },
    handler=_handle_search_sessions,
    is_async=False,
    emoji="🔍",
    danger_level=ToolDangerLevel.readonly,
    availability=ToolAvailability.MAIN | ToolAvailability.MULTI_AGENT,
)

# 获取指定会话的消息内容或消息总数。
# 前置条件：会话管理子系统已初始化。
# 调用效果：加载目标会话的对话历史，按索引返回具体消息或返回消息总数。
# 返回格式（有 indices）：{ session_id, messages: [{index, character_name, content}] }
# 返回格式（无 indices）：{ session_id, message_count: int }
# 仅返回用户和助手的对话消息，排除工具调用和系统提示。
# 消息内容为纯文本形式，包含消息附带的固定后缀和动态后缀。
# 典型场景：配合 search_sessions 定位后拉取具体消息内容，或查询某会话的消息规模。
# 副作用：加载会话历史时可能有短暂延迟。
# 提醒：越界索引会被静默跳过；索引是会话完整消息序列中的位置，不是过滤后的序号。
registry.register(
    name="get_session_messages",
    toolset="core",
    schema={
        "description": """Retrieve messages from a specific session by ID, or get the total message count.

## Prerequisites
The session management system must be initialized. The target session must exist.

## Effect
Loads the target session's conversation history and returns either specific messages (when `indices` provided) or the total count of user and assistant messages (when `indices` omitted).

## Returns
When `indices` is provided:
```json
{
  "session_id": "<id>",
  "messages": [
    {"index": 3, "character_name": "<name>", "content": "<plain text>"}
  ]
}
```
When `indices` is omitted:
```json
{
  "session_id": "<id>",
  "message_count": 42
}
```
Only user and assistant messages are included. Tool calls and system prompts are excluded.

## When to Use
- Fetching specific messages after `search_sessions` returned matched indices.
- Checking how many conversation messages a session contains.
- Reviewing full message content from another session.

## Side Effects
Loading a session's history may cause a brief delay. Out-of-range indices are silently skipped.

## Notes
- Index refers to the position in the session's full message sequence, not a filtered sequence number.
- Message content is in plain text, including any fixed or dynamic suffixes attached to the original message.""",
        "parameters": {
            "type": "object",
            "properties": {
                "session_id": {
                    "type": "string",
                    # 目标会话 ID。必需。
                    "description": """The target session ID. Required.""",
                },
                "indices": {
                    "type": "array",
                    "items": {"type": "integer"},
                    # 要获取的消息索引列表。索引是会话完整消息序列中的位置。
                    # 省略时返回该会话的用户和助手消息总数。
                    "description": """List of message indices to retrieve. Each index refers to the position in the session's full message sequence. When omitted, returns the total count of user and assistant messages instead.""",
                },
            },
            "required": ["session_id"],
        },
    },
    handler=_handle_get_session_messages,
    is_async=False,
    emoji="📜",
    danger_level=ToolDangerLevel.readonly,
    availability=ToolAvailability.MAIN | ToolAvailability.MULTI_AGENT,
)