"""不持久化的会话视觉资源状态；不代表浏览器渲染成功。"""

from enum import Enum
from pydantic import BaseModel


class SessionVisualKind(str, Enum):
    stage = "stage"
    site = "site"
    chat_style = "chat_style"


class SessionVisualStatus(str, Enum):
    ready = "ready"
    missing = "missing"


class SessionVisualSource(BaseModel):
    session_id: str
    kind: SessionVisualKind


class SessionVisualResourceState(BaseModel):
    kind: SessionVisualKind
    status: SessionVisualStatus
    source_path: str
    effective_path: str
    redirected: bool = False
    redirect_error: str | None = None
    entry_name: str
    entry_url: str | None = None
    version: str | None = None


class SessionVisualResources(BaseModel):
    stage: SessionVisualResourceState
    site: SessionVisualResourceState
    chat_style: SessionVisualResourceState
