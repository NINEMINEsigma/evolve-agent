"""EasysaveMemoryProvider — 基于 easysave 的持久化 memory。

将对话历史存储在 ``workspace/logs/memory/`` 中，
使 agent 在页面刷新和重启后仍能记住过去的回合。
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from typing import Any, Dict, List

# 确保 third/ 可导入
from system.pathutils import find_repo_root

_THIRD: Path = find_repo_root() / "third"
for _p in (_THIRD, _THIRD / "easysave"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from easysave import save, load  # type: ignore[import]

from abstract.memory.provider import MemoryProvider

logger = logging.getLogger(__name__)


class EasysaveMemoryProvider(MemoryProvider):
    """通过 easysave 将对话回合持久化到磁盘。

    每个 session 在 ``memory_dir/session_{id}.json`` 下获得一个 JSON 文件。
    provider 还跟踪一个全局 session ID 列表以支持跨 session 回忆。
    """

    def __init__(self, memory_dir: str | Path = "") -> None:
        self._dir: Path = Path(memory_dir) if memory_dir else Path("workspace/logs/memory")
        self._dir.mkdir(parents=True, exist_ok=True)
        self._session_id: str = ""
        self._index: Dict[str, Any] = {}

    # -- MemoryProvider ABC ------------------------------------------------

    @property
    def name(self) -> str:
        return "easysave"

    def is_available(self) -> bool:
        return self._dir.exists()

    def initialize(self, session_id: str, **kwargs: Any) -> None:
        self._session_id = session_id
        # 加载或创建 session 索引
        idx_path: Path = self._dir / "_sessions.json"
        try:
            self._index = load("_sessions", str(idx_path)) or {}
        except Exception:
            self._index = {}
        logger.info("EasysaveMemoryProvider initialized | session=%s dir=%s",
                    session_id, self._dir)

    def system_prompt_block(self) -> str:
        if not self._index:
            return ""
        sessions: list = self._index.get("sessions", [])
        if not sessions:
            return ""
        return (
            "You have persistent memory of {n} previous session(s). "
            "Use the `recall_memory` tool to search past conversations. "
            "The search only supports single keyword matching — always try "
            "one concise keyword at a time (e.g. \"novel\" rather than "
            "\"write a novel story\"). "
            "You can also use `remember` to explicitly store facts."
        ).format(n=len(sessions))

    # TODO: 这里可能可以提供一些分词以其优化和匹配
    def prefetch(self, query: str, *, session_id: str = "") -> str:
        sid: str = session_id or self._session_id
        if not sid:
            return ""
        data: dict | None = self._load_session(sid)
        if not data:
            return ""
        turns: list = data.get("turns", [])
        if not turns:
            return ""
        # 如果提供了查询关键字则过滤
        if query:
            q: str = query.lower()
            turns = [t for t in turns if q in str(t.get('user', '')).lower() or q in str(t.get('assistant', '')).lower()]
            if not turns:
                return ""
        # 返回最后几个回合作为上下文
        recent: list = turns[-6:]  # 最后 6 个回合
        lines: list[str] = ["[Previous conversation — recall context]"]
        for t in recent:
            lines.append(f"User: {t.get('user', '')}")
            assistant_text: str = str(t.get('assistant', ''))
            truncated: str = assistant_text[:500] + ("...[truncated]" if len(assistant_text) > 500 else "")
            lines.append(f"Assistant: {truncated}")
        return "\n".join(lines)

    def sync_turn(
        self,
        user_message: str,
        assistant_response: str,
        *,
        session_id: str = "",
    ) -> None:
        sid: str = session_id or self._session_id
        if not sid:
            return
        data: dict = self._load_session(sid) or {"session_id": sid, "turns": []}
        data["turns"].append({
            "user": user_message,
            "assistant": assistant_response,
        })
        self._save_session(sid, data)

        # 更新索引
        sessions: list = list(set(self._index.get("sessions", []) + [sid]))
        self._index["sessions"] = sessions
        idx_path: Path = self._dir / "_sessions.json"
        try:
            save("_sessions", str(idx_path), self._index)
        except Exception:
            pass

    def get_tool_schemas(self) -> List[Dict[str, Any]]:
        return [
            {
                "name": "recall_memory",
                "description": (
                    "Search past conversation history for relevant context. "
                    "Use this to remember what was discussed in previous sessions. "
                    "IMPORTANT: Pass only a SINGLE keyword — the ENTIRE query string is used as-is "
                    "for substring matching. Spaces are NOT treated as separators; a query like "
                    "'foo bar' searches for the literal text 'foo bar', not 'foo' or 'bar' individually, "
                    "and will almost certainly match nothing. Use the most unique single word you can "
                    "think of, then refine with a different word if needed. "
                    "If session_id is omitted, searches across all sessions."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "session_id": {
                            "type": "string",
                            "description": "Optional: specific session to search.",
                        },
                        "query": {
                            "type": "string",
                            "description": (
                                "A single keyword only. The search uses the ENTIRE input string as a "
                                "literal substring — it does NOT split on spaces. Passing multiple words "
                                "separated by spaces will search for that exact multi-word string and "
                                "almost certainly find nothing. Pick the most distinctive single word."
                            ),
                        },
                    },
                },
            },
            {
                "name": "remember",
                "description": (
                    "Store a fact or piece of information for future recall. "
                    "Use this to persist important findings across sessions."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "content": {
                            "type": "string",
                            "description": "The fact or information to remember.",
                        },
                    },
                    "required": ["content"],
                },
            },
        ]

    def handle_tool_call(self, tool_name: str, args: Dict[str, Any]) -> str:
        if tool_name == "recall_memory":
            return self._handle_recall(args)
        if tool_name == "remember":
            return self._handle_remember(args)
        return json.dumps({"error": f"Unknown memory tool: {tool_name}"})

    def shutdown(self) -> None:
        logger.info("EasysaveMemoryProvider shut down | session=%s", self._session_id)

    # -- 内部方法 -----------------------------------------------------------

    def _session_path(self, session_id: str) -> Path:
        return self._dir / f"session_{session_id}.json"

    def _load_session(self, session_id: str) -> Dict[str, Any] | None:
        try:
            return load(f"session_{session_id}", str(self._session_path(session_id)))
        except Exception:
            return None

    def _save_session(self, session_id: str, data: Dict[str, Any]) -> None:
        try:
            save(f"session_{session_id}", str(self._session_path(session_id)), data)
        except Exception as exc:
            logger.warning("Failed to save session %s: %s", session_id, exc)

    def _handle_recall(self, args: Dict[str, Any]) -> str:
        sid: str = str(args.get("session_id", "")).strip()
        query: str = str(args.get("query", "")).strip().lower()

        results: list[dict]
        if sid:
            data: dict | None = self._load_session(sid)
            results = [{"session_id": sid, "turns": data.get("turns", [])}] if data else []
        else:
            # 搜索所有 session
            results = []
            for s in self._index.get("sessions", []):
                data = self._load_session(s)
                if data:
                    results.append({"session_id": s, "turns": data.get("turns", [])})

        # 如果提供了查询则过滤
        if query:
            filtered: list[dict] = []
            for r in results:
                matching: list[dict] = [
                    t for t in r.get("turns", [])
                    if query in str(t.get("user", "")).lower()
                    or query in str(t.get("assistant", "")).lower()
                ]
                if matching:
                    filtered.append({"session_id": r["session_id"], "turns": matching})
            results = filtered

        # 截断以避免巨大响应
        total: int = 0
        if isinstance(results, list) and len(results) > 0:
            total = sum(len(r.get("turns", [])) for r in results)
        return json.dumps(
            {"found": total, "results": results[:10]},
            ensure_ascii=False,
        )

    def _handle_remember(self, args: Dict[str, Any]) -> str:
        content: str = str(args.get("content", "")).strip()
        if not content:
            return json.dumps({"error": "content is required"})

        sid: str = self._session_id or "global"
        data: dict = self._load_session(sid) or {"session_id": sid, "turns": [], "facts": []}
        if "facts" not in data:
            data["facts"] = []
        data["facts"].append(content)
        self._save_session(sid, data)

        return json.dumps({"stored": True, "session_id": sid})