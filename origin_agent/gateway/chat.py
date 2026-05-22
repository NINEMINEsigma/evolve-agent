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
        return json.dumps(d, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Session manager
# ---------------------------------------------------------------------------


class SessionManager:
    """Track active WebSocket sessions.

    Each connected client gets a unique session_id.  This will be used
    later by the agent loop to isolate conversation history per session.
    """

    def __init__(self) -> None:
        self._sessions: Dict[str, str] = {}  # session_id -> status

    def create(self) -> str:
        sid = uuid.uuid4().hex[:12]
        self._sessions[sid] = "active"
        logger.debug("Session created | id=%s", sid)
        return sid

    def exists(self, sid: str) -> bool:
        return sid in self._sessions

    def remove(self, sid: str) -> None:
        self._sessions.pop(sid, None)
        logger.debug("Session removed | id=%s", sid)

    @property
    def count(self) -> int:
        return len(self._sessions)