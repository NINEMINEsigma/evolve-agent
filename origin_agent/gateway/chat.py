"""Message protocol types and session management for the chat gateway."""

from __future__ import annotations

import json
import logging
import uuid
from enum import Enum
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
    """Track active WebSocket sessions with TTL-based expiry.

    Each connected client gets a unique session_id.
    Sessions expire after 30 minutes of inactivity.
    """

    _SESSION_TTL = 1800  # 30 minutes

    def __init__(self) -> None:
        import time
        self._sessions: Dict[str, dict] = {}  # sid -> {status, created_at}

    def create(self) -> str:
        import time
        sid = uuid.uuid4().hex[:12]
        self._sessions[sid] = {"status": "active", "created_at": time.time()}
        logger.debug("Session created | id=%s", sid)
        return sid

    def exists(self, sid: str) -> bool:
        return sid in self._sessions

    def remove(self, sid: str) -> None:
        self._sessions.pop(sid, None)
        logger.debug("Session removed | id=%s", sid)

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
            {"id": sid, "created_at": info.get("created_at", 0), "status": info.get("status", "unknown")}
            for sid, info in self._sessions.items()
        ]

    @property
    def count(self) -> int:
        return len(self._sessions)