"""跨会话历史查询工具 — ReadSession + RecallSession。

模块导入时通过 ``registry.register()`` 注册两个工具：
  - ReadSession: 精准读取指定会话的区间消息（session_id + index + length）
  - RecallSession: 混合检索全体会话（exact / substring / bm25），RRF 融合排序

混合检索设计：
  - exact / substring: 布尔高置信通道
  - bm25: 词汇排序通道，query 分词（拉丁词元 + CJK 单字/二元），覆盖缩写与多词查询
  - RRF (Reciprocal Rank Fusion, k=60): 按名次融合各通道，规避分数尺度不可比问题
"""

from __future__ import annotations

import logging
import re
from typing import Any

from rank_bm25 import BM25Okapi

from abstract.tools.registry import registry, tool_error, tool_result
from entity.puretype import ToolAvailability, ToolDangerLevel, Role, SessionStatus
from entity.constant import (
    SESSION_SEARCH_MAX_MESSAGE_RESULTS_DEFAULT,
    SESSION_SEARCH_MAX_MESSAGE_RESULTS_LIMIT,
    SESSION_SEARCH_MAX_HISTORY_RESULTS_DEFAULT,
    SESSION_SEARCH_MAX_HISTORY_RESULTS_LIMIT,
    SESSION_SEARCH_READ_LENGTH_DEFAULT,
    SESSION_SEARCH_READ_LENGTH_LIMIT,
    SESSION_SEARCH_PREVIEW_LENGTH,
)

logger = logging.getLogger(__name__)


# ── 混合检索常量 ─────────────────────────────────────────

# RRF 融合参数（Cormack et al. 2009 的常用默认值，跨数据集稳定）
_RRF_K: int = 60

# 各通道在 RRF 中的权重：布尔高置信通道 > 排序通道
_CHANNEL_WEIGHTS: dict[str, float] = {
    "exact": 1.5,
    "substring": 1.2,
    "bm25": 1.0,
}

# 排序通道送入融合的候选深度（粗召回宁多勿少，靠融合精修）
_BM25_TOP_K: int = 50

_VALID_METHODS: set[str] = {"exact", "substring", "bm25"}

# 分词：拉丁词元（含数字/路径片段）+ CJK 连续段
_LATIN_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9._\-/#]*")
_CJK_RUN_RE = re.compile(r"[㐀-䶿一-鿿]+")


def _tokenize(text: str) -> list[str]:
    """混合分词：拉丁词元原样保留；CJK 连续段切单字 + 二元组。

    - 拉丁词元保住 "yolo" "deepseek-v4-flash" "session_search.py" 这类精确标识符；
    - CJK 单字保证召回，二元组保证短语精度（"审批模式" -> 审批/批模/模式）。
    """
    text = text.lower()
    tokens: list[str] = _LATIN_TOKEN_RE.findall(text)
    for run in _CJK_RUN_RE.findall(text):
        tokens.extend(run)
        tokens.extend(run[i:i + 2] for i in range(len(run) - 1))
    return tokens


# ── 辅助函数 ─────────────────────────────────────────────


def _rrf_fuse(channel_ranks: dict[str, dict[Any, int]]) -> dict[Any, float]:
    """Reciprocal Rank Fusion: score(d) = Σ_channel weight / (k + rank + 1)。

    channel_ranks: 通道名 -> {条目 key: 名次(0-based)}。
    只看名次不看原始分数，规避 BM25 / 布尔匹配的尺度不可比问题。
    """
    fused: dict[Any, float] = {}
    for channel, ranks in channel_ranks.items():
        w = _CHANNEL_WEIGHTS.get(channel, 1.0)
        for key, rank in ranks.items():
            fused[key] = fused.get(key, 0.0) + w / (_RRF_K + rank + 1)
    return fused


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
    """混合检索全体会话：三通道召回 + RRF 融合排序。"""
    query: str = str(args.get("query", "")).strip()
    raw_methods = args.get("match_methods", ["exact", "substring", "bm25"])
    max_message_results: int = int(args.get("max_message_results", SESSION_SEARCH_MAX_MESSAGE_RESULTS_DEFAULT))
    max_history_results: int = int(args.get("max_history_results", SESSION_SEARCH_MAX_HISTORY_RESULTS_DEFAULT))
    include_history: bool = bool(args.get("include_history", True))

    if not query:
        return tool_error("'query' is required")

    if max_message_results <= 0:
        max_message_results = SESSION_SEARCH_MAX_MESSAGE_RESULTS_DEFAULT
    if max_message_results > SESSION_SEARCH_MAX_MESSAGE_RESULTS_LIMIT:
        max_message_results = SESSION_SEARCH_MAX_MESSAGE_RESULTS_LIMIT

    if max_history_results <= 0:
        max_history_results = SESSION_SEARCH_MAX_HISTORY_RESULTS_DEFAULT
    if max_history_results > SESSION_SEARCH_MAX_HISTORY_RESULTS_LIMIT:
        max_history_results = SESSION_SEARCH_MAX_HISTORY_RESULTS_LIMIT

    if isinstance(raw_methods, list):
        methods = [m for m in raw_methods if m in _VALID_METHODS]
    else:
        methods = []
    if not methods:
        methods = ["exact", "substring", "bm25"]

    from system.application import Application

    sm = Application.current().session_manager
    if sm is None:
        return tool_error("SessionManager not available")

    session_store = _get_session_store()
    all_sessions = sm.get_all()

    # ── 第一遍：收集检索单元 ──
    # message 级单元
    msg_units: list[dict[str, Any]] = []
    # history 级单元（title + tags + summary 拼接为一个文档）
    hist_units: list[dict[str, Any]] = []

    for info in all_sessions:
        sid = info.id

        summary_text: str | None = None
        if include_history and session_store is not None:
            try:
                summary_text = session_store.read_summary(sid)
            except Exception:
                pass

        if include_history:
            hist_text = " ".join(
                x for x in [
                    info.title or "",
                    " ".join(info.tags) if info.tags else "",
                    summary_text or "",
                ] if x
            )
            hist_units.append({
                "sid": sid,
                "info": info,
                "summary": summary_text,
                "text": hist_text,
            })

        if session_store is None:
            continue
        try:
            history = session_store.read_history(sid)
        except Exception:
            logger.exception("Failed to read history for session=%s", sid)
            continue
        if history is None:
            continue

        for conv_idx, msg in _filter_conversation_messages(history):
            text = _extract_content_with_suffix(msg)
            if not text:
                continue
            msg_units.append({
                "sid": sid,
                "conv_idx": conv_idx,
                "msg": msg,
                "title": info.title,
                "text": text,
            })

    # ── 第二遍：各通道独立产出名次表 ──
    query_lower = query.lower()

    def _boolean_ranks(units: list[dict], key_fn, pred) -> dict[Any, int]:
        """布尔通道：命中即名次 0（共享头部）。"""
        return {key_fn(u): 0 for u in units if pred(u)}

    def _bm25_ranks(units: list[dict], key_fn) -> dict[Any, int]:
        if not units:
            return {}
        corpus = [_tokenize(u["text"]) for u in units]
        bm = BM25Okapi(corpus)
        scores = bm.get_scores(_tokenize(query))
        order = sorted(range(len(units)), key=lambda i: scores[i], reverse=True)
        ranks: dict[Any, int] = {}
        for rank, i in enumerate(order):
            if scores[i] <= 0.0 or rank >= _BM25_TOP_K:
                break
            ranks[key_fn(units[i])] = rank
        return ranks

    # message 级通道
    msg_key = lambda u: (u["sid"], u["conv_idx"])  # noqa: E731
    msg_channel_ranks: dict[str, dict[Any, int]] = {}
    if "exact" in methods:
        msg_channel_ranks["exact"] = _boolean_ranks(
            msg_units, msg_key, lambda u: query_lower == u["text"].lower())
    if "substring" in methods:
        msg_channel_ranks["substring"] = _boolean_ranks(
            msg_units, msg_key, lambda u: query_lower in u["text"].lower())
    if "bm25" in methods:
        msg_channel_ranks["bm25"] = _bm25_ranks(msg_units, msg_key)

    # history 级通道
    hist_key = lambda u: u["sid"]  # noqa: E731
    hist_channel_ranks: dict[str, dict[Any, int]] = {}
    if include_history:
        if "exact" in methods:
            def _hist_exact(u: dict) -> bool:
                info = u["info"]
                if info.title and query_lower == info.title.lower():
                    return True
                return bool(info.tags) and any(query_lower == t.lower() for t in info.tags)
            hist_channel_ranks["exact"] = _boolean_ranks(hist_units, hist_key, _hist_exact)
        if "substring" in methods:
            def _hist_sub(u: dict) -> bool:
                info = u["info"]
                if info.title and query_lower in info.title.lower():
                    return True
                return bool(u["summary"]) and query_lower in u["summary"].lower()
            hist_channel_ranks["substring"] = _boolean_ranks(hist_units, hist_key, _hist_sub)
        if "bm25" in methods:
            hist_channel_ranks["bm25"] = _bm25_ranks(hist_units, hist_key)

    # ── RRF 融合与结果装配 ──
    msg_fused = _rrf_fuse(msg_channel_ranks)
    unit_by_key = {msg_key(u): u for u in msg_units}

    msg_list: list[dict] = []
    for key, score in sorted(msg_fused.items(), key=lambda kv: kv[1], reverse=True):
        u = unit_by_key[key]
        msg = u["msg"]
        matched = [c for c, ranks in msg_channel_ranks.items() if key in ranks]
        msg_list.append({
            "session_id": u["sid"],
            "session_title": u["title"],
            "message_index": u["conv_idx"],
            "role": msg.role.value,
            "character_name": getattr(msg, "character_name", ""),
            "preview": _extract_preview(u["text"]),
            "matched_methods": matched,
            "fusion_score": round(score, 6),
        })
    if len(msg_list) > max_message_results:
        msg_list = msg_list[:max_message_results]

    hist_fused = _rrf_fuse(hist_channel_ranks)
    hist_unit_by_key = {hist_key(u): u for u in hist_units}

    hist_list: list[dict] = []
    for sid, score in sorted(hist_fused.items(), key=lambda kv: kv[1], reverse=True):
        u = hist_unit_by_key[sid]
        info = u["info"]
        entry: dict = {
            "session_id": sid,
            "title": info.title,
            "tags": info.tags if info.tags else [],
            "status": info.status.value if hasattr(info.status, "value") else str(info.status),
            "matched_methods": [c for c, ranks in hist_channel_ranks.items() if sid in ranks],
            "fusion_score": round(score, 6),
        }
        if u["summary"] and info.status == SessionStatus.archived:
            entry["summary"] = _extract_preview(u["summary"])
        hist_list.append(entry)
    if len(hist_list) > max_history_results:
        hist_list = hist_list[:max_history_results]

    return tool_result(
        success=True,
        total_sessions_scanned=len(all_sessions),
        message_matches=msg_list,
        history_matches=hist_list,
        total_matched=len(msg_fused) + len(hist_fused),
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
# 提醒：index 是过滤后的对话消息序号（0-based），不是原始消息序列位置；length 上限受 SESSION_SEARCH_READ_LENGTH_LIMIT 约束。
registry.register(
    name="ReadSession",
    toolset="core",
    schema={
        "description": (
            """Read a range of messages from a specific session by index.

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
"""
            f"- `length` is capped at {SESSION_SEARCH_READ_LENGTH_LIMIT} to limit response size.\n"
            """- Out-of-range indices are silently clipped."""
        ),
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
                    # 从 index 开始读取的消息条数。
                    "description": f"""Number of messages to read starting from index. Default {SESSION_SEARCH_READ_LENGTH_DEFAULT}, max {SESSION_SEARCH_READ_LENGTH_LIMIT}.""",
                    "default": SESSION_SEARCH_READ_LENGTH_DEFAULT,
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

# 混合检索全体会话历史：exact / substring / bm25 三通道召回，RRF 按名次融合排序。
# 前置条件：会话管理子系统已初始化。
# 调用效果：对全体会话执行指定的匹配通道，message 级和 history 级结果按融合分数降序返回。
# 返回格式：{ success, total_sessions_scanned, message_matches: [...], history_matches: [...], total_matched }
# exact: query 完全匹配消息内容、会话标题或标签；substring: query 是消息内容、标题或摘要的子串；
# bm25: 词汇排序（query 分词：拉丁词元 + CJK 单字/二元），覆盖缩写与多词查询。
# 所有通道经 RRF (k=60) 按名次融合，规避分数尺度不可比问题；结果含 fusion_score 与 matched_methods。
# message_matches 每条含 session_id, session_title, message_index, role, character_name, preview(受 SESSION_SEARCH_PREVIEW_LENGTH 截断), matched_methods, fusion_score。
# history_matches 每条含 session_id, title, tags, status, matched_methods, fusion_score, summary(归档会话, 受 SESSION_SEARCH_PREVIEW_LENGTH 截断)。
# 典型场景：按关键词、缩写检索历史讨论，定位相关会话。
# 副作用：无。
# 提醒：message 级结果截断到 max_message_results（受 SESSION_SEARCH_MAX_MESSAGE_RESULTS_DEFAULT/LIMIT 约束），history 级结果截断到 max_history_results（受 SESSION_SEARCH_MAX_HISTORY_RESULTS_DEFAULT/LIMIT 约束），两个上限独立；使用 ReadSession 拉取完整消息内容。
registry.register(
    name="RecallSession",
    toolset="core",
    schema={
        "description": (
            """Hybrid search across all session histories: three recall channels fused by Reciprocal Rank Fusion (RRF).

## Prerequisites
The session management system must be initialized.

## Effect
Runs the specified matching channels (exact, substring, bm25) across all sessions, then fuses their rankings with RRF (k=60) so results are ordered by rank consensus rather than incomparable raw scores.
- `exact`: The query equals a message's content, a session's title, or a session's tag.
- `substring`: The query is a substring of a message's content, a session's title, or a session's summary.
- `bm25`: Lexical ranking over tokenized text (Latin tokens kept verbatim; CJK text split into unigrams + bigrams). Best for abbreviations, identifiers, error codes, and multi-word keyword queries.

## Returns
```json
{
  "success": true,
  "total_sessions_scanned": 15,
  "message_matches": [
    {
      "session_id": "<id>",
      "session_title": "<title>",
      "message_index": 7,
      "role": "user",
      "character_name": "User",
      "preview": "...",
      "matched_methods": ["bm25", "exact"],
      "fusion_score": 0.032
    }
  ],
  "history_matches": [
    {
      "session_id": "<id>",
      "title": "<title>",
      "tags": ["bug"],
      "status": "archived",
      "matched_methods": ["substring"],
      "fusion_score": 0.019,
      "summary": "..."
    }
  ],
  "total_matched": 12
}
```
`fusion_score` is the RRF score used for ordering (higher is better).
`summary` is only included for archived sessions.
"""
            f"Message `preview` and history `summary` are truncated to {SESSION_SEARCH_PREVIEW_LENGTH} characters.\n\n"
            """## When to Use
- Locating sessions by abbreviations, identifiers, or multi-word keywords (bm25 channel).
- Precise lookups by title, tag, or exact phrase (exact/substring channels).

## Side Effects
None.

## Notes
- Only user and assistant messages are searched; tool calls and system prompts are excluded.
"""
            f"- Message matches are capped at `max_message_results` (default {SESSION_SEARCH_MAX_MESSAGE_RESULTS_DEFAULT}, max {SESSION_SEARCH_MAX_MESSAGE_RESULTS_LIMIT}); "
            f"history matches are capped at `max_history_results` (default {SESSION_SEARCH_MAX_HISTORY_RESULTS_DEFAULT}, max {SESSION_SEARCH_MAX_HISTORY_RESULTS_LIMIT}). "
            """The two limits are independent.
- Use `ReadSession` to fetch full message content for any matched index."""
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    # 查询文本，可以是关键词、缩写或描述性句子。必需。
                    "description": """The query text to search for. Can be a keyword, an abbreviation/identifier, or a descriptive sentence. Required.""",
                },
                "match_methods": {
                    "type": "array",
                    "items": {"type": "string", "enum": ["exact", "substring", "bm25"]},
                    # 使用的匹配通道列表。默认全部三种，经 RRF 融合排序。
                    "description": """Matching channels to use. Default: all three (exact, substring, bm25), fused by RRF.""",
                },
                "max_message_results": {
                    "type": "integer",
                    # message 级匹配结果上限。
                    "description": f"""Maximum number of message-level matches to return. Default {SESSION_SEARCH_MAX_MESSAGE_RESULTS_DEFAULT}, max {SESSION_SEARCH_MAX_MESSAGE_RESULTS_LIMIT}.""",
                    "default": SESSION_SEARCH_MAX_MESSAGE_RESULTS_DEFAULT,
                },
                "max_history_results": {
                    "type": "integer",
                    # history 级匹配结果上限。
                    "description": f"""Maximum number of history-level matches to return. Default {SESSION_SEARCH_MAX_HISTORY_RESULTS_DEFAULT}, max {SESSION_SEARCH_MAX_HISTORY_RESULTS_LIMIT}.""",
                    "default": SESSION_SEARCH_MAX_HISTORY_RESULTS_DEFAULT,
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