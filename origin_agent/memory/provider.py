"""EasysaveMemoryProvider — persistent memory backed by easysave.

Stores conversation history in ``workspace/logs/memory/`` so the agent
remembers past turns across page refreshes and restarts.
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from typing import Any, Dict, List

# Ensure third/ is importable
from system.pathutils import find_repo_root

_THIRD = find_repo_root() / "third"
for _p in (_THIRD, _THIRD / "easysave"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from easysave import save, load  # type: ignore[import]

from abstract.memory.provider import MemoryProvider

logger = logging.getLogger(__name__)


class EasysaveMemoryProvider(MemoryProvider):
    """Persists conversation turns to disk via easysave.

    Each session gets a JSON file under ``memory_dir/session_{id}.json``.
    The provider also tracks a global list of session IDs to support
    cross-session recall.
    """

    def __init__(self, memory_dir: str | Path = "") -> None:
        self._dir = Path(memory_dir) if memory_dir else Path("workspace/logs/memory")
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
        # Load or create the session index
        idx_path = self._dir / "_sessions.json"
        try:
            self._index = load("_sessions", str(idx_path)) or {}
        except Exception:
            self._index = {}
        logger.info("EasysaveMemoryProvider initialized | session=%s dir=%s",
                    session_id, self._dir)

    def system_prompt_block(self) -> str:
        if not self._index:
            return ""
        sessions = self._index.get("sessions", [])
        if not sessions:
            return ""
        return (
            "You have persistent memory of {n} previous session(s). "
            "Use the `recall_memory` tool to search past conversations. "
            "You can also use `remember` to explicitly store facts."
        ).format(n=len(sessions))

    def prefetch(self, query: str, *, session_id: str = "") -> str:
        sid = session_id or self._session_id
        if not sid:
            return ""
        data = self._load_session(sid)
        if not data:
            return ""
        turns = data.get("turns", [])
        if not turns:
            return ""
        # Filter by query keywords if provided
        if query:
            q = query.lower()
            turns = [t for t in turns if q in str(t.get('user', '')).lower() or q in str(t.get('assistant', '')).lower()]
            if not turns:
                return ""
        # Return the last few turns as context
        recent = turns[-6:]  # last 6 turns
        lines = ["[Previous conversation — recall context]"]
        for t in recent:
            lines.append(f"User: {t.get('user', '')}")
            assistant_text = str(t.get('assistant', ''))
            truncated = assistant_text[:500] + ("...[truncated]" if len(assistant_text) > 500 else "")
            lines.append(f"Assistant: {truncated}")
        return "\n".join(lines)

    def sync_turn(
        self,
        user_message: str,
        assistant_response: str,
        *,
        session_id: str = "",
    ) -> None:
        sid = session_id or self._session_id
        if not sid:
            return
        data = self._load_session(sid) or {"session_id": sid, "turns": []}
        data["turns"].append({
            "user": user_message,
            "assistant": assistant_response,
        })
        self._save_session(sid, data)

        # Update index
        sessions = list(set(self._index.get("sessions", []) + [sid]))
        self._index["sessions"] = sessions
        idx_path = self._dir / "_sessions.json"
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
                            "description": "Keywords to search for in past conversations.",
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

    # -- internal -----------------------------------------------------------

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
        sid = str(args.get("session_id", "")).strip()
        query = str(args.get("query", "")).strip().lower()

        if sid:
            data = self._load_session(sid)
            results = [{"session_id": sid, "turns": data.get("turns", [])}] if data else []
        else:
            # Search all sessions
            results = []
            for s in self._index.get("sessions", []):
                data = self._load_session(s)
                if data:
                    results.append({"session_id": s, "turns": data.get("turns", [])})

        # Filter by query if provided
        if query:
            filtered = []
            for r in results:
                matching = [
                    t for t in r.get("turns", [])
                    if query in str(t.get("user", "")).lower()
                    or query in str(t.get("assistant", "")).lower()
                ]
                if matching:
                    filtered.append({"session_id": r["session_id"], "turns": matching})
            results = filtered

        # Truncate to avoid huge responses
        if isinstance(results, list) and len(results) > 0:
            total = sum(len(r.get("turns", [])) for r in results)
        else:
            total = 0
        return json.dumps(
            {"found": total, "results": results[:10]},
            ensure_ascii=False,
        )

    def _handle_remember(self, args: Dict[str, Any]) -> str:
        content = str(args.get("content", "")).strip()
        if not content:
            return json.dumps({"error": "content is required"})

        sid = self._session_id or "global"
        data = self._load_session(sid) or {"session_id": sid, "turns": [], "facts": []}
        if "facts" not in data:
            data["facts"] = []
        data["facts"].append(content)
        self._save_session(sid, data)

        return json.dumps({"stored": True, "session_id": sid})