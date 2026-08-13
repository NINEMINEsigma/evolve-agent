"""跨会话历史查询工具 — ReadSession + RecallSession。

模块导入时通过 ``registry.register()`` 注册两个工具：
  - ReadSession: 精准读取指定会话的区间消息（session_id + index + length）
  - RecallSession: 多路径检索全体会话（exact / substring / semantic），去重合并
"""

from __future__ import annotations

import logging
import math
from typing import Any

from abstract.tools.registry import registry, tool_error, tool_result
from entity.puretype import ToolAvailability, ToolDangerLevel, Role, SessionStatus
from entity.constant import (
    SESSION_SEARCH_MAX_RESULTS_DEFAULT,
    SESSION_SEARCH_MAX_RESULTS_LIMIT,
    SESSION_SEARCH_READ_LENGTH_DEFAULT,
    SESSION_SEARCH_READ_LENGTH_LIMIT,
    SESSION_SEARCH_PREVIEW_LENGTH,
    SESSION_SEARCH_SEMANTIC_THRESHOLD,
)

logger = logging.getLogger(__name__)


# ── 辅助函数 ─────────────────────────────────────────────


def _filter_conversation_messages(history) -> list[tuple[int, Any]]:
    """过滤出 Role.USER 和 Role.ASSISTANT 的 CharacterConversationMessage。

    返回 (conv_index, message) 列表，conv_index 是过滤后的序号（0, 1, 2, ...），
    非 history.messages 的原始全局位置。
    """
    from entity.messages import CharacterConversationMessage

    result: list[tuple[int, Any]] = []
    conv_idx = 0
    for msg in history.iter_messages():
        if not isinstance(msg, CharacterConversationMessage):
            continue
        if msg.role not in (Role.USER, Role.ASSISTANT):
            continue
        result.append((conv_idx, msg))
        conv_idx += 1
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


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """计算两个向量的余弦相似度。"""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def _extract_preview(text: str, max_len: int = SESSION_SEARCH_PREVIEW_LENGTH) -> str:
    """截取文本前 max_len 字符作为预览。"""
    return text[:max_len] if len(text) > max_len else text


# ── ReadSession handler ────────────────────────────────────


def _handle_read_session(args: dict[str, Any]) -> dict:
    """精准读取指定会话的区间消息。"""
    session_id: str = str(args.get("session_id", "")).strip()
    start_index: int = int(args.get("index", 0))
    length: int = int(args.get("length", SESSION_SEARCH_READ_LENGTH_DEFAULT))

    if not session_id:
        return tool_error("'session_id' is required")
    if start_index < 0:
        return tool_error("'index' must be non-negative")
    if length <= 0:
        length = SESSION_SEARCH_READ_LENGTH_DEFAULT
    if length > SESSION_SEARCH_READ_LENGTH_LIMIT:
        length = SESSION_SEARCH_READ_LENGTH_LIMIT

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
    total = len(conv_msgs)

    end = min(start_index + length, total)
    messages: list[dict] = []
    for i in range(start_index, end):
        msg = conv_msgs[i][1]
        content_text = _extract_content_with_suffix(msg)
        messages.append({
            "index": i,
            "role": msg.role.value,
            "character_name": getattr(msg, "character_name", ""),
            "content": content_text,
        })

    return tool_result(
        session_id=session_id,
        start_index=start_index,
        messages=messages,
        total_conversation_messages=total,
    )


# ── RecallSession handler ─────────────────────────────────


async def _handle_recall_session(args: dict[str, Any]) -> dict:
    """多路径检索全体会话。"""
    query: str = str(args.get("query", "")).strip()
    raw_methods = args.get("match_methods", ["exact", "substring", "semantic"])
    max_results: int = int(args.get("max_results", SESSION_SEARCH_MAX_RESULTS_DEFAULT))
    include_history: bool = bool(args.get("include_history", True))

    if not query:
        return tool_error("'query' is required")

    if max_results <= 0:
        max_results = SESSION_SEARCH_MAX_RESULTS_DEFAULT
    if max_results > SESSION_SEARCH_MAX_RESULTS_LIMIT:
        max_results = SESSION_SEARCH_MAX_RESULTS_LIMIT

    valid_methods = {"exact", "substring", "semantic"}
    if isinstance(raw_methods, list):
        methods = [m for m in raw_methods if m in valid_methods]
    else:
        methods = []
    if not methods:
        methods = ["exact", "substring", "semantic"]

    from system.application import Application

    sm = Application.current().session_manager
    if sm is None:
        return tool_error("SessionManager not available")

    session_store = _get_session_store()
    all_sessions = sm.get_all()

    query_lower = query.lower()

    # ── 语义路径准备 ──
    semantic_available = False
    query_vec: list[float] | None = None
    backend = None
    if "semantic" in methods:
        try:
            backend = await Application.current().embedding_backend_manager.get_backend()
        except Exception:
            logger.debug("Failed to get embedding backend", exc_info=True)
            backend = None
        if backend is not None:
            try:
                resp = await backend.embed([query])
                if resp and resp[0]:
                    query_vec = resp[0]
                    semantic_available = True
            except Exception:
                logger.debug("Failed to compute embedding for query", exc_info=True)

    # ── 遍历会话，三路径并行匹配 ──
    # message 去重: key=(session_id, conv_index) -> dict
    msg_hits: dict[tuple[str, int], dict] = {}
    # history 去重: key=session_id -> dict
    hist_hits: dict[str, dict] = {}

    for info in all_sessions:
        sid = info.id

        # ── history 级匹配 ──
        if include_history:
            hist_matched_methods: list[str] = []

            # exact: query == title 或 query in tags
            if "exact" in methods:
                if info.title and query_lower == info.title.lower():
                    hist_matched_methods.append("exact")
                if info.tags:
                    for tag in info.tags:
                        if query_lower == tag.lower():
                            if "exact" not in hist_matched_methods:
                                hist_matched_methods.append("exact")
                            break

            # substring: query in title 或 query in summary
            summary_text: str | None = None
            if "substring" in methods:
                if info.title and query_lower in info.title.lower():
                    if "substring" not in hist_matched_methods:
                        hist_matched_methods.append("substring")
                if session_store is not None:
                    try:
                        summary_text = session_store.read_summary(sid)
                    except Exception:
                        pass
                if summary_text and query_lower in summary_text.lower():
                    if "substring" not in hist_matched_methods:
                        hist_matched_methods.append("substring")

            if hist_matched_methods:
                hist_entry: dict = {
                    "session_id": sid,
                    "title": info.title,
                    "tags": info.tags if info.tags else [],
                    "status": info.status.value if hasattr(info.status, "value") else str(info.status),
                    "matched_methods": hist_matched_methods,
                }
                # 读取 summary 用于返回（若尚未读取）
                if summary_text is None and session_store is not None:
                    try:
                        summary_text = session_store.read_summary(sid)
                    except Exception:
                        pass
                if summary_text and info.status == SessionStatus.archived:
                    hist_entry["summary"] = _extract_preview(summary_text)
                hist_hits[sid] = hist_entry

        # ── message 级匹配 ──
        if session_store is None:
            continue
        try:
            history = session_store.read_history(sid)
        except Exception:
            logger.exception("Failed to read history for session=%s", sid)
            continue
        if history is None:
            continue

        conv_msgs = _filter_conversation_messages(history)
        for conv_idx, msg in conv_msgs:
            content_text = _extract_content_with_suffix(msg)
            content_lower = content_text.lower()
            matched_methods: list[str] = []
            similarity: float | None = None

            # exact
            if "exact" in methods and query_lower == content_lower:
                matched_methods.append("exact")

            # substring
            if "substring" in methods and query_lower in content_lower:
                matched_methods.append("substring")

            # semantic
            if "semantic" in methods and semantic_available and query_vec is not None:
                stored_vec = msg.get_embedding(backend.model_name)
                if stored_vec is not None:
                    sim = _cosine_similarity(query_vec, stored_vec)
                    if sim >= SESSION_SEARCH_SEMANTIC_THRESHOLD:
                        matched_methods.append("semantic")
                        similarity = round(sim, 6)

            if matched_methods:
                key = (sid, conv_idx)
                if key in msg_hits:
                    for m in matched_methods:
                        if m not in msg_hits[key]["matched_methods"]:
                            msg_hits[key]["matched_methods"].append(m)
                    if similarity is not None:
                        existing = msg_hits[key].get("similarity")
                        if existing is None or similarity > existing:
                            msg_hits[key]["similarity"] = similarity
                else:
                    msg_hits[key] = {
                        "session_id": sid,
                        "session_title": info.title,
                        "message_index": conv_idx,
                        "role": msg.role.value,
                        "character_name": getattr(msg, "character_name", ""),
                        "preview": _extract_preview(content_text),
                        "matched_methods": matched_methods,
                        "similarity": similarity,
                    }

    # ── 排序与截断 ──
    msg_list = list(msg_hits.values())
    msg_list.sort(
        key=lambda x: (x.get("similarity") or 0.0, len(x["matched_methods"])),
        reverse=True,
    )

    hist_list = list(hist_hits.values())
    hist_list.sort(key=lambda x: len(x["matched_methods"]), reverse=True)

    total_matched = len(msg_list) + len(hist_list)
    if len(msg_list) > max_results:
        msg_list = msg_list[:max_results]
    remaining = max_results - len(msg_list)
    if remaining > 0 and len(hist_list) > remaining:
        hist_list = hist_list[:remaining]

    return tool_result(
        success=True,
        semantic_available=semantic_available,
        total_sessions_scanned=len(all_sessions),
        message_matches=msg_list,
        history_matches=hist_list,
        total_matched=total_matched,
    )


# ── 注册 ─────────────────────────────────────────────────────

# 精准读取指定会话的区间消息（类比 Read）。
# 前置条件：会话管理子系统已初始化，目标会话存在。
# 调用效果：加载目标会话的对话历史，从 index 开始返回 length 条连续消息的完整内容。
# 返回格式：{ session_id, start_index, messages: [{index, role, character_name, content}], total_conversation_messages }
# 仅返回用户和助手的对话消息，排除工具调用和系统提示。
# 消息内容为纯文本形式，包含消息附带的固定后缀和动态后缀。
# 典型场景：配合 RecallSession 定位后拉取完整消息内容，或按窗口顺序浏览会话历史。
# 副作用：加载会话历史时可能有短暂延迟。
# 提醒：index 是过滤后的对话消息序号（0-based），不是原始消息序列位置；length 上限 100。
registry.register(
    name="ReadSession",
    toolset="core",
    schema={
        "description": """Read a range of messages from a specific session by index.

## Prerequisites
The session management system must be initialized. The target session must exist.

## Effect
Loads the target session's conversation history and returns a contiguous range of user and assistant messages starting from the given index.

## Returns
```json
{
  "session_id": "<id>",
  "start_index": 5,
  "messages": [
    {"index": 5, "role": "user", "character_name": "User", "content": "..."},
    {"index": 6, "role": "assistant", "character_name": "Agent", "content": "..."}
  ],
  "total_conversation_messages": 42
}
```
Only user and assistant messages are included. Tool calls and system prompts are excluded.
`total_conversation_messages` is the total count of conversation messages in the session.

## When to Use
- Reading a specific portion of a session's conversation after `RecallSession` returned a matching index.
- Browsing a session's history sequentially by sliding the index window.
- Getting the full message count of a session by checking `total_conversation_messages`.

## Side Effects
Loading a session's history may cause a brief delay.

## Notes
- Index is 0-based, referring to the position in the filtered conversation message sequence (user + assistant only).
- `length` is capped at 100 to limit response size.
- Out-of-range indices are silently clipped.""",
        "parameters": {
            "type": "object",
            "properties": {
                "session_id": {
                    "type": "string",
                    # 目标会话 ID。必需。
                    "description": """The target session ID. Required.""",
                },
                "index": {
                    "type": "integer",
                    # 起始消息索引（0-based），对话消息序号。必需。
                    "description": """The starting index in the conversation message sequence (0-based). Required.""",
                },
                "length": {
                    "type": "integer",
                    # 从 index 开始读取的消息条数。默认 10，上限 100。
                    "description": """Number of messages to read starting from index. Default 10, max 100.""",
                    "default": 10,
                },
            },
            "required": ["session_id", "index"],
        },
    },
    handler=_handle_read_session,
    is_async=False,
    emoji="📖",
    danger_level=ToolDangerLevel.safe,
    availability=ToolAvailability.MAIN | ToolAvailability.MULTI_AGENT,
)

# 多路径检索全体会话历史，支持精准匹配、字串匹配和语义匹配。
# 前置条件：会话管理子系统已初始化。语义匹配需要 embedding 模型已配置且可用。
# 调用效果：对全体会话执行指定的匹配方式，message 级和 history 级结果去重合并后返回。
# 返回格式：{ success, semantic_available, total_sessions_scanned, message_matches: [...], history_matches: [...], total_matched }
# exact: query 完全匹配消息内容、会话标题或标签；substring: query 是消息内容、标题或摘要的子串；
# semantic: 消息嵌入向量与查询向量的余弦相似度 >= 0.5。
# message_matches 每条含 session_id, session_title, message_index, role, character_name, preview(200字截断), matched_methods, similarity(仅语义)。
# history_matches 每条含 session_id, title, tags, status, matched_methods, summary(归档会话, 200字截断)。
# 典型场景：按关键词或语义概念检索历史讨论，定位相关会话。
# 副作用：语义匹配在会话数量多时可能有秒级延迟。嵌入后端不可用时自动跳过语义路径。
# 提醒：结果总量截断到 max_results（默认 30）；使用 ReadSession 拉取完整消息内容。
registry.register(
    name="RecallSession",
    toolset="core",
    schema={
        "description": """Search across all session histories using multiple matching strategies.

## Prerequisites
The session management system must be initialized.
For semantic matching, an embedding model must be configured and available.

## Effect
Runs the specified matching methods (exact, substring, semantic) across all sessions.
- `exact`: Matches when the query equals a message's content, a session's title, or a session's tag.
- `substring`: Matches when the query is a substring of a message's content, a session's title, or a session's summary.
- `semantic`: Matches messages whose embedding vectors are semantically similar to the query (cosine similarity >= 0.5).

Results from all methods are deduplicated and merged.

## Returns
```json
{
  "success": true,
  "semantic_available": true,
  "total_sessions_scanned": 15,
  "message_matches": [
    {
      "session_id": "<id>",
      "session_title": "<title>",
      "message_index": 7,
      "role": "user",
      "character_name": "User",
      "preview": "...",
      "matched_methods": ["exact", "semantic"],
      "similarity": 0.87
    }
  ],
  "history_matches": [
    {
      "session_id": "<id>",
      "title": "<title>",
      "tags": ["bug"],
      "status": "archived",
      "matched_methods": ["substring"],
      "summary": "..."
    }
  ],
  "total_matched": 12
}
```
`similarity` is only present for messages matched by the semantic method.
`summary` is only included for archived sessions.
Message `preview` and history `summary` are truncated to 200 characters.

## When to Use
- Finding past discussions on a topic, even when exact keywords differ.
- Recalling conversations that relate to a concept or idea.
- Locating sessions by title, tag, or content.

## Side Effects
Semantic matching may take several seconds when many sessions exist.
If the embedding backend is unavailable, semantic matching is skipped and `semantic_available` is set to false.

## Notes
- Only user and assistant messages are searched; tool calls and system prompts are excluded.
- Results are capped at `max_results` (default 30) total across messages and histories.
- Use `ReadSession` to fetch full message content for any matched index.""",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    # 查询文本，可以是关键词或描述性句子。必需。
                    "description": """The query text to search for. Can be a keyword or a descriptive sentence. Required.""",
                },
                "match_methods": {
                    "type": "array",
                    "items": {"type": "string", "enum": ["exact", "substring", "semantic"]},
                    # 使用的匹配方式列表。默认全部三种。
                    "description": """Matching methods to use. Default: all three (exact, substring, semantic).""",
                },
                "max_results": {
                    "type": "integer",
                    # 最终返回结果上限（message + history 合计）。默认 30。
                    "description": """Maximum total results (messages + histories). Default 30.""",
                    "default": 30,
                },
                "include_history": {
                    "type": "boolean",
                    # 是否同时匹配会话级元信息（title/tags/summary）。默认 true。
                    "description": """Whether to also match session-level metadata (title, tags, summary). Default true.""",
                    "default": True,
                },
            },
            "required": ["query"],
        },
    },
    handler=_handle_recall_session,
    is_async=True,
    emoji="🔎",
    danger_level=ToolDangerLevel.safe,
    availability=ToolAvailability.MAIN | ToolAvailability.MULTI_AGENT,
)