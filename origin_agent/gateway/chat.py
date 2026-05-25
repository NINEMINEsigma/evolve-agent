"""Message protocol types and session management for the chat gateway."""

from __future__ import annotations

import json
import logging
import uuid
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Optional

from pydantic import BaseModel

logger = logging.getLogger(__name__)


class MessageType(str, Enum):
    USER_MESSAGE = "user_message"
    AGENT_MESSAGE = "agent_message"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    CONFIRM_REQUEST = "confirm_request"
    CONFIRM_RESPONSE = "confirm_response"
    INTERRUPT = "interrupt"
    ERROR = "error"
    SYSTEM = "system"


class Message(BaseModel):
    type: MessageType
    session_id: str = ""
    content: Optional[str] = None
    tool: Optional[str] = None
    args: Optional[Dict[str, Any]] = None
    result: Optional[Any] = None
    message: Optional[str] = None  # used by ERROR type
    request_id: Optional[str] = None  # for confirm_request / confirm_response
    action: Optional[str] = None      # for confirm_response: allow_once | allow_always | deny

    @classmethod
    def from_json(cls, raw: str) -> Message:
        data = json.loads(raw)
        return cls(
            type=MessageType(data["type"]),
            session_id=data.get("session_id", ""),
            content=data.get("content"),
            tool=data.get("tool"),
            args=data.get("args"),
            result=data.get("result"),
            message=data.get("message"),
            request_id=data.get("request_id"),
            action=data.get("action"),
        )

    def to_json(self) -> str:
        d: Dict[str, Any] = {"type": self.type.value}
        if self.session_id:
            d["session_id"] = self.session_id
        if self.content is not None:
            d["content"] = self.content
        if self.tool is not None:
            d["tool"] = self.tool
        if self.args is not None:
            d["args"] = self.args
        if self.result is not None:
            d["result"] = self.result
        if self.message is not None:
            d["message"] = self.message
        if self.request_id is not None:
            d["request_id"] = self.request_id
        if self.action is not None:
            d["action"] = self.action
        return json.dumps(d, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Session manager
# ---------------------------------------------------------------------------


class SessionManager:
    """Track WebSocket sessions with TTL-based expiry and disk persistence.

    Each connected client gets a unique session_id.
    Sessions expire after 30 minutes of inactivity.
    Session metadata is persisted to a JSON index file so the list survives
    server restarts.
    """

    _SESSION_TTL = 1800  # 30 minutes

    def __init__(self, store_path: str | None = None) -> None:
        import time
        self._sessions: Dict[str, dict] = {}  # sid -> {status, created_at, title}
        self._store_dir: Path | None = Path(store_path) if store_path else None
        if self._store_dir:
            self._store_dir.mkdir(parents=True, exist_ok=True)
            self.load_from_disk()

    # -- persistence helpers ------------------------------------------------

    def _index_path(self) -> Path:
        """Path to the session index JSON file."""
        assert self._store_dir is not None
        return self._store_dir / "_index.json"

    def _read_index(self) -> list[dict]:
        """Read persisted session index from disk."""
        if not self._store_dir:
            return []
        idx = self._index_path()
        if not idx.exists():
            return []
        try:
            data = json.loads(idx.read_text(encoding="utf-8"))
            return data if isinstance(data, list) else []
        except Exception:
            logger.warning("Failed to read session index, starting fresh")
            return []

    def _write_index(self, entries: list[dict]) -> None:
        """Persist session index to disk."""
        if not self._store_dir:
            return
        try:
            self._index_path().write_text(
                json.dumps(entries, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as exc:
            logger.warning("Failed to write session index: %s", exc)

    def load_from_disk(self) -> None:
        """Load persisted sessions from disk into memory."""
        entries = self._read_index()
        for entry in entries:
            sid = entry.get("id", "")
            if sid:
                self._sessions[sid] = {
                    "status": entry.get("status", "active"),
                    "created_at": entry.get("created_at", 0),
                    "title": entry.get("title", ""),
                }
        if entries:
            logger.info("Loaded %d sessions from disk", len(entries))

    def set_store_dir(self, path: str) -> None:
        """Set or update the store directory and reload from disk."""
        self._store_dir = Path(path)
        self._store_dir.mkdir(parents=True, exist_ok=True)
        self.load_from_disk()

    # -- CRUD ----------------------------------------------------------------

    def create(self) -> str:
        import time
        sid = uuid.uuid4().hex[:12]
        now = time.time()
        self._sessions[sid] = {"status": "active", "created_at": now, "title": ""}
        # Persist to disk
        if self._store_dir:
            entries = self._read_index()
            entries.append({"id": sid, "created_at": now, "status": "active", "title": ""})
            self._write_index(entries)
            (self._store_dir / sid).mkdir(parents=True, exist_ok=True)
        logger.debug("Session created | id=%s", sid)
        return sid

    def exists(self, sid: str) -> bool:
        return sid in self._sessions

    def remove(self, sid: str) -> None:
        self._sessions.pop(sid, None)
        # Clean up disk
        if self._store_dir:
            entries = self._read_index()
            entries = [e for e in entries if e.get("id") != sid]
            self._write_index(entries)
            import shutil
            sdir = self._store_dir / sid
            if sdir.exists():
                shutil.rmtree(sdir)
        logger.debug("Session removed | id=%s", sid)

    def update_title(self, sid: str, title: str) -> None:
        """Update the title for a session in memory and on disk."""
        if sid in self._sessions:
            self._sessions[sid]["title"] = title
        if self._store_dir:
            entries = self._read_index()
            for e in entries:
                if e.get("id") == sid:
                    e["title"] = title
                    break
            else:
                entries.append({
                    "id": sid,
                    "created_at": self._sessions.get(sid, {}).get("created_at", 0),
                    "status": "active",
                    "title": title,
                })
            self._write_index(entries)

    def get(self, sid: str) -> dict | None:
        """Return a single session with full metadata, or None."""
        info = self._sessions.get(sid)
        if info is None:
            return None
        return {
            "id": sid,
            "created_at": info.get("created_at", 0),
            "status": info.get("status", "unknown"),
            "title": info.get("title", ""),
        }

    def cleanup_expired(self) -> int:
        import time
        now = time.time()
        expired = [
            sid for sid, info in self._sessions.items()
            if now - info.get("created_at", 0) > self._SESSION_TTL
        ]
        for sid in expired:
            self._sessions.pop(sid, None)
            logger.debug("Session expired | id=%s", sid)
        return len(expired)

    def get_all(self) -> list[dict]:
        """Return list of all sessions with metadata."""
        return [
            {
                "id": sid,
                "created_at": info.get("created_at", 0),
                "status": info.get("status", "unknown"),
                "title": info.get("title", ""),
            }
            for sid, info in self._sessions.items()
        ]

    @property
    def count(self) -> int:
        return len(self._sessions)