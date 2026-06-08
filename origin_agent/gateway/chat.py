"""聊天 gateway 的消息协议类型和 session 管理。"""

from __future__ import annotations

import json
import logging
import threading
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
    ASK_REQUEST = "ask_request"
    ASK_RESPONSE = "ask_response"
    INTERRUPT = "interrupt"
    ERROR = "error"
    SYSTEM = "system"
    FILE_UPLOAD = "file_upload"
    HANDSFREE_MODE = "handsfree_mode"
    TASK_PROGRESS = "task_progress"
    CLIPBOARD_DISPLAY = "clipboard_display"


class Message(BaseModel):
    type: MessageType
    session_id: str = ""
    content: Optional[str] = None
    tool: Optional[str] = None
    args: Optional[Dict[str, Any]] = None
    result: Optional[Any] = None
    message: Optional[str] = None  # ERROR 类型使用
    request_id: Optional[str] = None  # confirm_request / confirm_response 使用
    action: Optional[str] = None      # confirm_response：allow_once | allow_always | deny
    deny_reason: Optional[str] = None  # confirm_response：拒绝原因
    denied_by: Optional[str] = None    # confirm_response：拒绝来源 (model/user/system)
    filename: Optional[str] = None    # FILE_UPLOAD：原始文件名
    mime_type: Optional[str] = None   # FILE_UPLOAD：MIME 类型
    file_data: Optional[str] = None   # FILE_UPLOAD：base64 编码的文件内容
    # ask_request / ask_response 相关字段
    question: Optional[str] = None    # ASK_REQUEST：问题文本
    options: Optional[list] = None    # ASK_REQUEST：选项列表 [{label, value}]
    allow_custom: Optional[bool] = None  # ASK_REQUEST：是否允许自定义输入
    option: Optional[str] = None      # ASK_RESPONSE：选中的选项值
    custom_text: Optional[str] = None # ASK_RESPONSE：自定义输入文本

    @classmethod
    def from_json(cls, raw: str) -> Message:
        data: dict = json.loads(raw)
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
            deny_reason=data.get("deny_reason"),
            denied_by=data.get("denied_by"),
            filename=data.get("filename"),
            mime_type=data.get("mime_type"),
            file_data=data.get("file_data"),
            question=data.get("question"),
            options=data.get("options"),
            allow_custom=data.get("allow_custom"),
            option=data.get("option"),
            custom_text=data.get("custom_text"),
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
        if self.deny_reason is not None:
            d["deny_reason"] = self.deny_reason
        if self.denied_by is not None:
            d["denied_by"] = self.denied_by
        if self.filename is not None:
            d["filename"] = self.filename
        if self.mime_type is not None:
            d["mime_type"] = self.mime_type
        if self.file_data is not None:
            d["file_data"] = self.file_data
        if self.question is not None:
            d["question"] = self.question
        if self.options is not None:
            d["options"] = self.options
        if self.allow_custom is not None:
            d["allow_custom"] = self.allow_custom
        if self.option is not None:
            d["option"] = self.option
        if self.custom_text is not None:
            d["custom_text"] = self.custom_text
        return json.dumps(d, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Session 管理器
# ---------------------------------------------------------------------------



class SessionManager:
    """使用 TTL 过期和磁盘持久化跟踪 WebSocket session。

    每个连接的客户端获得唯一 session_id。
    Session 在 30 分钟不活动后过期。
    Session 元数据持久化到 JSON 索引文件，使列表在 server 重启后仍然存在。
    """

    _SESSION_TTL: int = 1800  # 30 分钟

    def __init__(self, store_path: str | None = None) -> None:
        import time
        self._sessions: Dict[str, dict] = {}  # sid -> {status, created_at, title}
        self._store_dir: Path | None = Path(store_path) if store_path else None
        self._index_lock: threading.Lock = threading.Lock()
        if self._store_dir:
            self._store_dir.mkdir(parents=True, exist_ok=True)
            self.load_from_disk()

    # -- 持久化辅助方法 ------------------------------------------------

    def _index_path(self) -> Path:
        """返回 session 索引 JSON 文件的路径。"""
        assert self._store_dir is not None
        return self._store_dir / "_index.json"

    def _read_index(self) -> list[dict]:
        """从磁盘读取持久化的 session 索引，损坏时尝试从 .bak 恢复。"""
        if not self._store_dir:
            return []
        idx: Path = self._index_path()
        if not idx.exists():
            # 主文件不存在时尝试从 .bak 恢复（例如前一次写入中途失败）
            backup = idx.with_suffix(".json.bak")
            if backup.exists():
                logger.warning("Primary index missing, recovering from backup")
                import shutil
                try:
                    shutil.copy2(backup, idx)
                    data: list = json.loads(idx.read_text(encoding="utf-8"))
                    if isinstance(data, list):
                        logger.info("Recovered %d sessions from backup", len(data))
                        return data
                except Exception:
                    logger.warning("Backup recovery failed")
            return []
        try:
            data: list = json.loads(idx.read_text(encoding="utf-8"))
            return data if isinstance(data, list) else []
        except Exception:
            logger.exception("Failed to parse session index, trying backup")
            # 尝试读取 .bak 备份
            backup = idx.with_suffix(".json.bak")
            if backup.exists():
                try:
                    data = json.loads(backup.read_text(encoding="utf-8"))
                    if isinstance(data, list):
                        logger.info("Recovered %d sessions from backup", len(data))
                        return data
                except Exception:
                    logger.warning("Backup also corrupted")
            # 最终兜底：从会话目录重建索引
            logger.info("Rebuilding session index from directory scan")
            import time as _time
            recovered: list[dict] = []
            for entry in sorted(self._store_dir.iterdir()):
                if not entry.is_dir():
                    continue
                sid: str = entry.name
                if len(sid) != 12 or not all(c in "0123456789abcdef" for c in sid):
                    continue
                created_at: float = 0.0
                try:
                    created_at = entry.stat().st_ctime
                except OSError:
                    created_at = _time.time()
                recovered.append({
                    "id": sid,
                    "created_at": created_at,
                    "status": "active",
                    "title": "",
                    "parent": None,
                    "continuation": None,
                })
            if recovered:
                logger.info("Recovered %d sessions from directory scan", len(recovered))
                return recovered
            logger.critical("Session index lost — no valid backup or directories available")
            return []

    def _write_index(self, entries: list[dict]) -> None:
        """将 session 索引持久化到磁盘（原子写入 + 备份）。"""
        if not self._store_dir:
            return
        try:
            idx = self._index_path()
            # 1. 先写 tmp 文件，不影响 _index.json
            tmp = idx.with_suffix(".json.tmp")
            tmp.write_text(
                json.dumps(entries, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            # 2. 备份当前文件（copy，不 rename，保证失败时 _index.json 仍在）
            if idx.exists():
                import shutil
                try:
                    shutil.copy2(idx, idx.with_suffix(".json.bak"))
                except Exception:
                    pass  # 备份失败不阻塞主流程
            # 3. 原子替换
            tmp.replace(idx)
        except Exception as exc:
            logger.warning("Failed to write session index: %s", exc)

    def _write_index_locked(self, entries: list[dict]) -> None:
        """线程安全的 _write_index 包装。"""
        with self._index_lock:
            self._write_index(entries)

    def load_from_disk(self) -> None:
        """从磁盘加载持久化的 session 到内存。"""
        # 如果 configure_sessions 从未被调用（例如在代码进化期间丢失），
        # 从 RuntimeContext 获取 workspace 路径。
        if self._store_dir is None:
            try:
                from system.context import get_runtime_context
                ws: Path = get_runtime_context().workspace
                candidate: Path = ws / "logs" / "sessions"
                if candidate.exists():
                    self._store_dir = candidate
            except Exception:
                pass
        if not self._store_dir:
            return
        entries: list[dict] = self._read_index()
        for entry in entries:
            sid: str = entry.get("id", "")
            if sid:
                self._sessions[sid] = {
                    "status": entry.get("status", "active"),
                    "created_at": entry.get("created_at", 0),
                    "title": entry.get("title", ""),
                    "parent": entry.get("parent"),
                    "continuation": entry.get("continuation"),
                }
        if entries:
            logger.info("Loaded %d sessions from disk", len(entries))

    def set_store_dir(self, path: str) -> None:
        """设置或更新存储目录并重新从磁盘加载。"""
        self._store_dir = Path(path)
        self._store_dir.mkdir(parents=True, exist_ok=True)
        self.load_from_disk()

    # -- CRUD ----------------------------------------------------------------

    def create(self, parent_sid: str | None = None) -> str:
        import time
        sid: str = uuid.uuid4().hex[:12]
        now: float = time.time()
        self._sessions[sid] = {
            "status": "active", "created_at": now, "title": "",
            "parent": parent_sid, "continuation": None,
        }
        # 持久化到磁盘
        if self._store_dir:
            with self._index_lock:
                entries: list[dict] = self._read_index()
                entries.append({
                    "id": sid, "created_at": now, "status": "active", "title": "",
                    "parent": parent_sid, "continuation": None,
                })
                self._write_index(entries)
            (self._store_dir / sid).mkdir(parents=True, exist_ok=True)
        logger.debug("Session created | id=%s parent=%s", sid, parent_sid)
        return sid

    def archive(self, sid: str, continuation_sid: str | None = None) -> None:
        """将会话标记为已归档，不可再对话。"""
        if sid in self._sessions:
            self._sessions[sid]["status"] = "archived"
            self._sessions[sid]["continuation"] = continuation_sid
        if self._store_dir:
            with self._index_lock:
                entries: list[dict] = self._read_index()
                for e in entries:
                    if e.get("id") == sid:
                        e["status"] = "archived"
                        if continuation_sid:
                            e["continuation"] = continuation_sid
                        break
                self._write_index(entries)
        logger.info("Session archived | id=%s continuation=%s", sid, continuation_sid)

    def create_with_context(self, summary: str, parent_sid: str) -> str:
        """创建新会话并以摘要作为初始 system 消息。"""
        new_sid: str = self.create(parent_sid=parent_sid)
        # 写入初始 system 摘要消息到 JSONL
        sdir: Path | None = self._store_dir / new_sid if self._store_dir else None
        if sdir:
            sdir.mkdir(parents=True, exist_ok=True)
            msg_path: Path = sdir / "messages.jsonl"
            entry: dict = {"role": "system", "content": f"[Session continuation summary]\n{summary}"}
            try:
                with open(msg_path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            except Exception as exc:
                logger.warning("Failed to write context for session %s: %s", new_sid, exc)
        # 更新父会话指向延续
        if parent_sid in self._sessions:
            self._sessions[parent_sid]["continuation"] = new_sid
        logger.info("Session created from archive | new=%s parent=%s", new_sid, parent_sid)
        return new_sid

    def exists(self, sid: str) -> bool:
        return sid in self._sessions

    def remove(self, sid: str) -> None:
        self._sessions.pop(sid, None)
        # 清理磁盘
        if self._store_dir:
            with self._index_lock:
                entries: list[dict] = self._read_index()
                entries = [e for e in entries if e.get("id") != sid]
                self._write_index(entries)
            import shutil
            sdir: Path = self._store_dir / sid
            if sdir.exists():
                shutil.rmtree(sdir)
        logger.debug("Session removed | id=%s", sid)

    def update_title(self, sid: str, title: str) -> None:
        """更新内存和磁盘中 session 的标题。"""
        if sid in self._sessions:
            self._sessions[sid]["title"] = title
        if self._store_dir:
            with self._index_lock:
                entries: list[dict] = self._read_index()
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
        """返回单个 session 及其完整元数据，不存在时返回 None。"""
        info: dict | None = self._sessions.get(sid)
        if info is None:
            return None
        return {
            "id": sid,
            "created_at": info.get("created_at", 0),
            "status": info.get("status", "unknown"),
            "title": info.get("title", ""),
            "parent": info.get("parent"),
            "continuation": info.get("continuation"),
        }

    def cleanup_expired(self) -> int:
        # 禁用过期清理：会话应永久保留在索引中，避免历史丢失。
        return 0

    def get_all(self) -> list[dict]:
        """返回所有 session 及其元数据的列表。"""
        return [
            {
                "id": sid,
                "created_at": info.get("created_at", 0),
                "status": info.get("status", "unknown"),
                "title": info.get("title", ""),
                "parent": info.get("parent"),
                "continuation": info.get("continuation"),
            }
            for sid, info in self._sessions.items()
        ]

    @property
    def count(self) -> int:
        return len(self._sessions)