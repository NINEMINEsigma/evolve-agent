"""聊天 gateway 的消息协议类型和 session 管理。

定义所有 WebSocket 消息类型，包括流式相关消息：
  - ``STREAM_DELTA`` — LLM 响应增量（content / reasoning_content）
  - ``STREAM_DONE`` — 流式结束标记（携带 finish_reason）
"""

from __future__ import annotations

import json
import logging
import threading
import uuid
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

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
    STREAM_DELTA = "stream_delta"
    STREAM_DONE = "stream_done"
    PING = "ping"
    PONG = "pong"
    SUBAGENT_UPDATE = "subagent_update"


class Message(BaseModel):
    type: MessageType
    session_id: str = ""
    content: Optional[Any] = None
    tool: str | None = None
    args: Optional[dict[str, Any]] = None
    result: Optional[Any] = None
    message: str | None = None  # ERROR 类型使用
    request_id: str | None = None  # confirm_request / confirm_response 使用
    action: str | None = None      # confirm_response：allow_once | allow_always | deny
    deny_reason: str | None = None  # confirm_response：拒绝原因
    denied_by: str | None = None    # confirm_response：拒绝来源 (model/user/system)
    filename: str | None = None    # FILE_UPLOAD：原始文件名
    mime_type: str | None = None   # FILE_UPLOAD：MIME 类型
    file_data: str | None = None   # FILE_UPLOAD：base64 编码的文件内容
    local_path: str | None = None  # FILE_UPLOAD：本地文件路径（同盘时优先硬链接）
    # ask_request / ask_response 相关字段
    question: str | None = None    # ASK_REQUEST：问题文本
    options: Optional[list] = None    # ASK_REQUEST：选项列表 [{label, value}]
    allow_custom: Optional[bool] = None  # ASK_REQUEST：是否允许自定义输入
    option: str | None = None      # ASK_RESPONSE：选中的选项值
    custom_text: str | None = None # ASK_RESPONSE：自定义输入文本
    # stream 相关字段
    stream_id: str | None = None   # STREAM_DELTA / STREAM_DONE：流标识
    delta: str | None = None       # STREAM_DELTA：文本增量
    reasoning_delta: str | None = None  # STREAM_DELTA：reasoning 增量
    finish_reason: str | None = None    # STREAM_DONE：结束原因或错误
    target_sessions: Optional[list[str]] = None  # USER_MESSAGE：目标会话列表
    # tool_call / tool_result 相关字段
    tool_call_id: str | None = None  # TOOL_CALL / TOOL_RESULT：工具调用 ID

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
            local_path=data.get("local_path"),
            question=data.get("question"),
            options=data.get("options"),
            allow_custom=data.get("allow_custom"),
            option=data.get("option"),
            custom_text=data.get("custom_text"),
            target_sessions=data.get("target_sessions"),
            tool_call_id=data.get("tool_call_id"),
        )

    def to_json(self) -> str:
        d: dict[str, Any] = {"type": self.type.value}
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
        if self.local_path is not None:
            d["local_path"] = self.local_path
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
        if self.stream_id is not None:
            d["stream_id"] = self.stream_id
        if self.delta is not None:
            d["delta"] = self.delta
        if self.reasoning_delta is not None:
            d["reasoning_delta"] = self.reasoning_delta
        if self.finish_reason is not None:
            d["finish_reason"] = self.finish_reason
        if self.target_sessions is not None:
            d["target_sessions"] = self.target_sessions
        if self.tool_call_id is not None:
            d["tool_call_id"] = self.tool_call_id
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
        self._sessions: dict[str, dict] = {}  # sid -> {status, created_at, title, tags}
        self._store_dir: Path | None = Path(store_path) if store_path else None
        self._index_lock: threading.Lock = threading.Lock()
        self._tags: list[str] = []
        if self._store_dir:
            self._store_dir.mkdir(parents=True, exist_ok=True)
            self.load_from_disk()

    # -- 持久化辅助方法 ------------------------------------------------

    def _index_path(self) -> Path:
        """返回 session 索引 JSON 文件的路径。"""
        assert self._store_dir is not None
        return self._store_dir / "_index.json"

    def _tags_path(self) -> Path:
        """返回全局标签 JSON 文件的路径。"""
        assert self._store_dir is not None
        return self._store_dir / "tags.json"

    def _read_index(self) -> list[dict]:
        """从磁盘读取持久化的 session 索引，损坏时尝试从 .bak 恢复。"""
        if not self._store_dir:
            return []
        idx: Path = self._index_path()
        data: list[dict]
        if not idx.exists():
            # 主文件不存在时尝试从 .bak 恢复（例如前一次写入中途失败）
            backup = idx.with_suffix(".json.bak")
            if backup.exists():
                logger.warning("Primary index missing, recovering from backup")
                import shutil
                try:
                    shutil.copy2(backup, idx)
                    data = json.loads(idx.read_text(encoding="utf-8"))
                    if isinstance(data, list):
                        logger.info("Recovered %d sessions from backup", len(data))
                        return self._upgrade_index_entries(data)
                except Exception:
                    logger.exception("Backup recovery failed")
            return []
        try:
            data = json.loads(idx.read_text(encoding="utf-8"))
            return self._upgrade_index_entries(data if isinstance(data, list) else [])
        except Exception:
            logger.exception("Failed to parse session index, trying backup")
            # 尝试读取 .bak 备份
            backup = idx.with_suffix(".json.bak")
            if backup.exists():
                try:
                    data = json.loads(backup.read_text(encoding="utf-8"))
                    if isinstance(data, list):
                        logger.info("Recovered %d sessions from backup", len(data))
                        return self._upgrade_index_entries(data)
                except Exception:
                    logger.exception("Backup also corrupted")
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
                    "parents": [],
                    "continuation": None,
                    "pinned": False,
                    "last_activity_at": created_at,
                    "tags": [],
                })
            if recovered:
                logger.info("Recovered %d sessions from directory scan", len(recovered))
                return recovered
            logger.critical("Session index lost — no valid backup or directories available")
            return []

    @staticmethod
    def _upgrade_index_entries(entries: list[dict]) -> list[dict]:
        """将旧格式索引中的 parent 升级为 parents 数组，并补齐 tags。"""
        for entry in entries:
            if "parent" in entry and "parents" not in entry:
                p = entry.pop("parent")
                entry["parents"] = [p] if p else []
            elif "parents" not in entry:
                entry["parents"] = []
            if "tags" not in entry:
                entry["tags"] = []
        return entries

    def _write_index(self, entries: list[dict]) -> None:
        """将 session 索引持久化到磁盘（原子写入 + 备份）。"""
        if not self._store_dir:
            return
        try:
            idx = self._index_path()
            # 清理旧格式字段，只保留 parents
            clean_entries: list[dict] = []
            for e in entries:
                clean: dict = dict(e)
                clean.pop("parent", None)
                clean_entries.append(clean)
            # 1. 先写 tmp 文件，不影响 _index.json
            tmp = idx.with_suffix(".json.tmp")
            tmp.write_text(
                json.dumps(clean_entries, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            # 2. 备份当前文件（copy，不 rename，保证失败时 _index.json 仍在）
            if idx.exists():
                import shutil
                try:
                    shutil.copy2(idx, idx.with_suffix(".json.bak"))
                except Exception:
                    logger.warning("Failed to backup session index", exc_info=True)  # 备份失败不阻塞主流程
            # 3. 原子替换
            tmp.replace(idx)
        except Exception as exc:
            logger.exception("Failed to write session index")

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
                candidate: Path = ws / "sessions"
                if candidate.exists():
                    self._store_dir = candidate
            except Exception:
                logger.warning("Failed to resolve workspace sessions directory", exc_info=True)
        if not self._store_dir:
            return
        entries: list[dict] = self._read_index()
        self._tags = self._read_tags()
        for entry in entries:
            sid: str = entry.get("id", "")
            if sid:
                self._sessions[sid] = {
                    "status": entry.get("status", "active"),
                    "created_at": entry.get("created_at", 0),
                    "title": entry.get("title", ""),
                    "parents": entry.get("parents", []),
                    "continuation": entry.get("continuation"),
                    "pinned": entry.get("pinned", False),
                    "last_activity_at": entry.get("last_activity_at", entry.get("created_at", 0)),
                    "tags": entry.get("tags", []),
                }
        if entries:
            logger.info("Loaded %d sessions from disk", len(entries))
            # 双向修复父子会话关系：从磁盘加载后确保 continuation 与 parents 严格一致
            changed = False
            for sid, info in self._sessions.items():
                parents: list[str] = info.get("parents", [])
                continuation: str | None = info.get("continuation")
                # 修复A：如果本会话的 continuation 指向某个子，但该子未以本会话为 parent，则补入
                if continuation and continuation in self._sessions:
                    child = self._sessions[continuation]
                    child_parents: list[str] = child.get("parents", [])
                    if sid not in child_parents:
                        child_parents.insert(0, sid)
                        child["parents"] = child_parents
                        changed = True
                # 修复B：如果本会话的 parents[0] 指向某个父，但该父未以本会话为 continuation，则修正
                if parents:
                    primary_parent: str = parents[0]
                    if primary_parent in self._sessions:
                        if self._sessions[primary_parent].get("continuation") != sid:
                            self._sessions[primary_parent]["continuation"] = sid
                            changed = True
            if changed:
                with self._index_lock:
                    entries = self._read_index()
                    for e in entries:
                        sid = e.get("id", "")
                        if sid in self._sessions:
                            e["parents"] = self._sessions[sid].get("parents", [])
                            e["continuation"] = self._sessions[sid].get("continuation")
                            e["tags"] = self._sessions[sid].get("tags", [])
                    self._write_index(entries)
                logger.info("Fixed session parent-child inconsistencies and synced to disk")

    def set_store_dir(self, path: str) -> None:
        """设置或更新存储目录并重新从磁盘加载。"""
        self._store_dir = Path(path)
        self._store_dir.mkdir(parents=True, exist_ok=True)
        self.load_from_disk()

    # -- CRUD ----------------------------------------------------------------

    def create(
        self,
        parent_sid: str | None = None,
        parents: list[str] | None = None,
    ) -> str:
        import time
        sid: str = uuid.uuid4().hex[:12]
        now: float = time.time()
        # 兼容旧参数：parent_sid 存在时纳入 parents
        effective_parents: list[str] = []
        if parents:
            effective_parents = list(parents)
        if parent_sid and parent_sid not in effective_parents:
            effective_parents.insert(0, parent_sid)
        self._sessions[sid] = {
            "status": "active", "created_at": now, "title": "",
            "parents": effective_parents, "continuation": None,
            "pinned": False, "last_activity_at": now,
            "tags": [],
        }
        # 持久化到磁盘
        if self._store_dir:
            with self._index_lock:
                entries: list[dict] = self._read_index()
                entries.append({
                    "id": sid, "created_at": now, "status": "active", "title": "",
                    "parents": effective_parents, "continuation": None,
                    "pinned": False, "last_activity_at": now,
                    "tags": [],
                })
                self._write_index(entries)
            (self._store_dir / sid).mkdir(parents=True, exist_ok=True)
        logger.debug("Session created | id=%s parents=%s", sid, effective_parents)
        return sid

    def archive(self, sid: str, continuation_sid: str | None = None) -> None:
        """将会话标记为已归档，不可再对话。"""
        if sid in self._sessions:
            self._sessions[sid]["status"] = "archived"
            if continuation_sid is not None:
                self._sessions[sid]["continuation"] = continuation_sid
        if self._store_dir:
            with self._index_lock:
                entries: list[dict] = self._read_index()
                for e in entries:
                    if e.get("id") == sid:
                        e["status"] = "archived"
                        if continuation_sid is not None:
                            e["continuation"] = continuation_sid
                        # 保留 tags 字段
                        if "tags" not in e:
                            e["tags"] = self._sessions.get(sid, {}).get("tags", [])
                        break
                self._write_index(entries)
        logger.info("Session archived | id=%s continuation=%s", sid, continuation_sid)

    def create_with_context(
        self,
        content: str,
        parent_sid: str | None = None,
        parents: list[str] | None = None,
        role: str = "system",
    ) -> str:
        """创建新会话并以指定角色的消息作为初始内容。支持多父合并。"""
        new_sid: str = self.create(parent_sid=parent_sid, parents=parents)
        # 写入初始消息到 JSONL
        sdir: Path | None = self._store_dir / new_sid if self._store_dir else None
        if sdir:
            sdir.mkdir(parents=True, exist_ok=True)
            msg_path: Path = sdir / "messages.jsonl"
            entry: dict = {"role": role, "content": content}
            try:
                with open(msg_path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            except Exception as exc:
                logger.warning("Failed to write context for session %s: %s", new_sid, exc)
        # 更新主父会话的 continuation（仅第一个父节点）
        primary_parent: str | None = None
        if parents:
            primary_parent = parents[0]
        elif parent_sid:
            primary_parent = parent_sid
        if primary_parent and primary_parent in self._sessions:
            self._sessions[primary_parent]["continuation"] = new_sid
            # 同步更新父会话索引持久化，确保重启后 continuation 关系可恢复
            if self._store_dir:
                with self._index_lock:
                    entries = self._read_index()
                    for e in entries:
                        if e.get("id") == primary_parent:
                            e["continuation"] = new_sid
                            break
                    self._write_index(entries)
        logger.info("Session created | new=%s parents=%s role=%s", new_sid, parents or [parent_sid], role)
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
                    info = self._sessions.get(sid, {})
                    entries.append({
                        "id": sid,
                        "created_at": info.get("created_at", 0),
                        "status": "active",
                        "title": title,
                        "parents": info.get("parents", []),
                        "continuation": info.get("continuation"),
                        "pinned": info.get("pinned", False),
                        "last_activity_at": info.get("last_activity_at", info.get("created_at", 0)),
                        "tags": info.get("tags", []),
                    })
                self._write_index(entries)

    def update_last_activity(self, sid: str) -> None:
        """更新 session 的最后活动时间。"""
        import time
        now: float = time.time()
        if sid in self._sessions:
            self._sessions[sid]["last_activity_at"] = now
        if self._store_dir:
            with self._index_lock:
                entries: list[dict] = self._read_index()
                for e in entries:
                    if e.get("id") == sid:
                        e["last_activity_at"] = now
                        break
                self._write_index(entries)

    def toggle_pin(self, sid: str) -> bool:
        """切换 session 的置顶状态，返回新的 pinned 值。"""
        if sid not in self._sessions:
            return False
        new_val: bool = not self._sessions[sid].get("pinned", False)
        self._sessions[sid]["pinned"] = new_val
        if self._store_dir:
            with self._index_lock:
                entries: list[dict] = self._read_index()
                for e in entries:
                    if e.get("id") == sid:
                        e["pinned"] = new_val
                        break
                self._write_index(entries)
        return new_val

    def get(self, sid: str) -> dict | None:
        """返回单个 session 及其完整元数据，不存在时返回 None。"""
        info: dict | None = self._sessions.get(sid)
        if info is None:
            return None
        parents: list[str] = info.get("parents", [])
        return {
            "id": sid,
            "created_at": info.get("created_at", 0),
            "status": info.get("status", "unknown"),
            "title": info.get("title", ""),
            "parents": parents,
            "parent": parents[0] if parents else None,
            "continuation": info.get("continuation"),
            "pinned": info.get("pinned", False),
            "last_activity_at": info.get("last_activity_at", info.get("created_at", 0)),
            "tags": info.get("tags", []),
        }

    def cleanup_expired(self) -> int:
        # 禁用过期清理：会话应永久保留在索引中，避免历史丢失。
        return 0

    def get_all(self) -> list[dict]:
        """返回所有 session 及其元数据的列表。

        排序规则：置顶的 session 排在最前面；
        同一层级内按 last_activity_at 降序（最近的在前）。
        """
        items: list[dict] = []
        for sid, info in self._sessions.items():
            parents: list[str] = info.get("parents", [])
            items.append({
                "id": sid,
                "created_at": info.get("created_at", 0),
                "status": info.get("status", "unknown"),
                "title": info.get("title", ""),
                "parents": parents,
                "parent": parents[0] if parents else None,
                "continuation": info.get("continuation"),
                "pinned": info.get("pinned", False),
                "last_activity_at": info.get("last_activity_at", info.get("created_at", 0)),
                "tags": info.get("tags", []),
            })
        items.sort(key=lambda s: (-int(s["pinned"]), -s["last_activity_at"]))
        return items

    @staticmethod
    def validate_tag(tag: str) -> bool:
        """校验单个标签格式：最多5个汉字或10个英文字母，不含空格。"""
        if not tag:
            return False
        import re
        return bool(re.fullmatch(r"[\u4e00-\u9fa5]{1,5}|[a-zA-Z]{1,10}", tag))

    def get_all_tags(self) -> list[str]:
        """返回全局已有标签列表。"""
        return list(self._tags)

    def _read_tags(self) -> list[str]:
        """从磁盘读取全局标签列表。"""
        if not self._store_dir:
            return []
        path = self._tags_path()
        if not path.exists():
            return []
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, list):
                return [str(t) for t in data if self.validate_tag(str(t))]
        except Exception as exc:
            logger.warning("Failed to read tags file: %s", exc)
        return []

    def _write_tags(self, tags: list[str]) -> None:
        """原子写入全局标签列表。"""
        if not self._store_dir:
            return
        try:
            path = self._tags_path()
            tmp = path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(tags, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(path)
        except Exception as exc:
            logger.warning("Failed to write tags file: %s", exc)

    def add_tags(self, new_tags: list[str]) -> bool:
        """把新标签合并到全局标签列表，返回是否发生变化。"""
        valid = [t for t in new_tags if self.validate_tag(t)]
        if not valid:
            return False
        changed = False
        for t in valid:
            if t not in self._tags:
                self._tags.append(t)
                changed = True
        if changed and self._store_dir:
            with self._index_lock:
                self._write_tags(list(self._tags))
        return changed

    def set_session_tags(self, sid: str, tags: list[str]) -> list[str]:
        """更新会话标签并同步全局标签。返回最终有效的标签列表。"""
        valid = [t for t in tags if self.validate_tag(t)]
        if sid in self._sessions:
            self._sessions[sid]["tags"] = valid
        if self._store_dir:
            with self._index_lock:
                entries: list[dict] = self._read_index()
                for e in entries:
                    if e.get("id") == sid:
                        e["tags"] = valid
                        break
                else:
                    info = self._sessions.get(sid, {})
                    entries.append({
                        "id": sid,
                        "created_at": info.get("created_at", 0),
                        "status": info.get("status", "active"),
                        "title": info.get("title", ""),
                        "parents": info.get("parents", []),
                        "continuation": info.get("continuation"),
                        "pinned": info.get("pinned", False),
                        "last_activity_at": info.get("last_activity_at", info.get("created_at", 0)),
                        "tags": valid,
                    })
                self._write_index(entries)
        self.add_tags(valid)
        return valid

    def validate_merge_sources(self, source_ids: list[str]) -> str | None:
        """校验所有源会话是否已归档。返回错误信息，全部通过则返回 None。"""
        for sid in source_ids:
            info = self._sessions.get(sid)
            if info is None:
                return f"session {sid} not found"
            if info.get("status") != "archived":
                return f"session {sid} is not archived"
        return None

    @property
    def count(self) -> int:
        return len(self._sessions)