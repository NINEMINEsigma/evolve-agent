"""独立于 History 的成功文件目标操作聚合；无后台任务或全局实例。"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path, PurePosixPath
import threading

from easysave import load, save

from entity.constant import (
    SESSION_FILE_CHANGE_KINDS, SESSION_FILE_CHANGE_TOOL_OPERATIONS,
    SESSION_FILE_CHANGES_DEFAULT_LIMIT, SESSION_FILE_CHANGES_MAX_LIMIT,
    SESSION_FILE_CHANGES_DELETE_LOCK_TIMEOUT_SECONDS,
    SESSION_FILE_CHANGES_ES_FILENAME, SESSION_FILE_CHANGES_ES_KEY,
)
from entity.puretype import (
    SessionFileChangeActor, SessionFileChangeOperation, SessionFileChangeEntry,
    SessionFileChangesData, SessionFileChangesSummary, SessionFileChangesPage,
)
from entity.typeref import make_config
from system.lifecycle import LifecycleFailure


class SessionFileChangesPersistenceFailure(LifecycleFailure):
    """文件副作用已完成后，必要统计提交失败。"""


class SessionFileChangesBusyError(RuntimeError):
    """删除尚未开始，会话统计提交锁在允许期限内仍被占用。"""


class SessionFileChangeStore:
    def __init__(self, sessions_root: Path) -> None:
        self._sessions_root = sessions_root.resolve()
        self._cache: dict[str, SessionFileChangesData] = {}
        self._locks: dict[str, threading.RLock] = {}
        self._registry_lock = threading.Lock()
        self._closed_sessions: set[str] = set()

    def _validate_session_id(self, session_id: str) -> None:
        if (not isinstance(session_id, str) or not session_id
                or session_id in (".", "..")
                or any(char in session_id for char in ":/\\\x00\r\n")):
            raise ValueError("Invalid session ID for file changes")
        (self._sessions_root / session_id).resolve().relative_to(self._sessions_root)

    def _session_lock(self, session_id: str) -> threading.RLock:
        self._validate_session_id(session_id)
        with self._registry_lock:
            return self._locks.setdefault(session_id, threading.RLock())

    @staticmethod
    def _normalize_path(logical_path: str) -> str:
        if not isinstance(logical_path, str) or ":" not in logical_path:
            raise ValueError("File change path requires a namespace")
        namespace, relative = logical_path.split(":", 1)
        namespace = namespace.strip()
        if not namespace or any(
            char in namespace for char in "/\\\x00\r\n"
        ):
            raise ValueError("Invalid file change namespace")
        relative = relative.replace("\\", "/").strip("/")
        if ".." in relative.split("/") or ":" in relative or "\x00" in relative:
            raise ValueError("Invalid file change relative path")
        relative = PurePosixPath(relative).as_posix()
        return f"{namespace}:{'' if relative == '.' else relative}"

    def _comparison_key(self, logical_path: str) -> str:
        normalized = self._normalize_path(logical_path)
        namespace, relative = normalized.split(":", 1)
        return f"{namespace}:{os.path.normcase(relative).replace(chr(92), '/')}"

    @staticmethod
    def _validate_utc_timestamp(value: str) -> None:
        if not isinstance(value, str):
            raise TypeError("File change timestamp must be a string")
        parsed = datetime.fromisoformat(value)
        if parsed.utcoffset() != timedelta(0) or parsed.isoformat(timespec="milliseconds") != value:
            raise ValueError("File change timestamp must be canonical UTC with milliseconds")

    @staticmethod
    def _validate_actor(actor: SessionFileChangeActor) -> None:
        if not isinstance(actor, SessionFileChangeActor):
            raise TypeError("File change actor has an invalid type")
        if (not isinstance(actor.session_id, str) or not actor.session_id
                or not isinstance(actor.character_name, str) or not actor.character_name):
            raise ValueError("File change actor requires a session and character")

    def _validate_data(
        self,
        data: SessionFileChangesData,
        expected_session_id: str
        ) -> None:
        if not isinstance(data, SessionFileChangesData) or data.session_id != expected_session_id:
            raise TypeError("File changes root belongs to a different session or type")
        if type(data.revision) is not int or data.revision < 0 or not isinstance(data.entries, dict):
            raise ValueError("Invalid file changes root fields")
        if (data.revision == 0) != (len(data.entries) == 0):
            raise ValueError("Empty file changes root has an invalid revision")
        total_operations = 0
        latest_revision = 0
        for key, entry in data.entries.items():
            if not isinstance(entry, SessionFileChangeEntry):
                raise TypeError("Invalid file change entry type")
            if (not isinstance(key, str) or key != self._comparison_key(entry.path)
                    or entry.path != self._normalize_path(entry.path)):
                raise ValueError("Invalid file change path key")
            if (entry.kind not in SESSION_FILE_CHANGE_KINDS
                    or entry.display_state not in ("created", "modified", "deleted")
                    or type(entry.created_by_session) is not bool
                    or entry.last_tool_name not in SESSION_FILE_CHANGE_TOOL_OPERATIONS
                    or entry.last_operation not in SESSION_FILE_CHANGE_TOOL_OPERATIONS[entry.last_tool_name]):
                raise ValueError("Invalid file change operation classification")
            if (type(entry.operation_count) is not int or not 1 <= entry.operation_count <= data.revision
                    or type(entry.last_revision) is not int or not 1 <= entry.last_revision <= data.revision):
                raise ValueError("Invalid file change entry counts")
            if not isinstance(entry.actors, list) or not 1 <= len(entry.actors) <= entry.operation_count:
                raise ValueError("Invalid file change authors")
            authors: set[tuple[str, str]] = set()
            for actor in entry.actors:
                self._validate_actor(actor)
                identity = (actor.session_id, actor.character_name)
                if identity in authors:
                    raise ValueError("Duplicate file change author")
                authors.add(identity)
            self._validate_utc_timestamp(entry.last_operated_at)
            if entry.last_operation in ("copy", "move"):
                if (not entry.source_path or not entry.destination_path
                        or entry.source_path != self._normalize_path(entry.source_path)
                        or entry.destination_path != self._normalize_path(entry.destination_path)):
                    raise ValueError("File transfer requires canonical endpoints")
                endpoints = {self._comparison_key(entry.destination_path)}
                if entry.last_operation == "move":
                    endpoints.add(self._comparison_key(entry.source_path))
                if key not in endpoints:
                    raise ValueError("File transfer entry does not match its endpoints")
            elif entry.source_path is not None or entry.destination_path is not None:
                raise ValueError("Non-transfer entry retains transfer endpoints")
            if entry.last_operation == "move":
                if entry.path == entry.source_path and entry.display_state != "deleted":
                    raise ValueError("Move source must be deleted state")
                if entry.path == entry.destination_path and entry.display_state == "deleted":
                    raise ValueError("Move destination cannot be deleted state")
            if entry.display_state == "deleted":
                if not (entry.last_operation == "delete"
                        or (entry.last_operation == "move" and entry.source_path == entry.path)):
                    raise ValueError("Deleted state must represent a deleted path")
            elif entry.last_operation == "delete":
                raise ValueError("Delete operation must be hidden in deleted state")
            if entry.display_state == "created" and not entry.created_by_session:
                raise ValueError("Created state requires a session-created path")
            if entry.display_state == "modified" and entry.created_by_session:
                raise ValueError("Modified state cannot retain created lifecycle")
            total_operations += entry.operation_count
            latest_revision = max(latest_revision, entry.last_revision)
        if latest_revision != data.revision or not data.revision <= total_operations <= 2 * data.revision:
            raise ValueError("Invalid file changes aggregate counts")

    def _load_unlocked(self, session_id: str) -> SessionFileChangesData:
        if session_id in self._closed_sessions:
            raise FileNotFoundError("Session file changes are closed for deletion")
        path = self._sessions_root / session_id / SESSION_FILE_CHANGES_ES_FILENAME
        if path.with_name(f"{path.name}.bak").exists():
            raise FileExistsError("File changes backup requires manual inspection")
        cached = self._cache.get(session_id)
        if cached is not None:
            return cached
        if not path.exists():
            data = SessionFileChangesData(session_id=session_id)
        else:
            data = load(SESSION_FILE_CHANGES_ES_KEY, make_config(path), SessionFileChangesData)
            self._validate_data(data, session_id)
        self._cache[session_id] = data
        return data

    def _apply_operation(
        self,
        candidate: SessionFileChangesData,
        actor: SessionFileChangeActor,
        operation: SessionFileChangeOperation,
        completed_at: str
        ) -> None:
        path = self._normalize_path(operation.path)
        source = self._normalize_path(operation.source_path) if operation.source_path is not None else None
        destination = self._normalize_path(operation.destination_path) if operation.destination_path is not None else None
        targets: list[tuple[str, str]] = [(path, "normal")]
        if operation.operation == "move":
            if source is None or destination is None:
                raise ValueError("Move requires both endpoints")
            targets = [(source, "source"), (destination, "destination")]
        candidate.revision += 1
        visited: set[str] = set()
        for target, role in targets:
            key = self._comparison_key(target)
            if key in visited:
                continue
            visited.add(key)
            previous = candidate.entries.get(key)
            actors = list(previous.actors) if previous is not None else []
            if not any(item.session_id == actor.session_id and item.character_name == actor.character_name for item in actors):
                actors.append(actor.model_copy(deep=True))
            if operation.operation == "delete" or role == "source":
                display_state = "deleted"
                created_by_session = previous.created_by_session if previous is not None else False
            elif operation.operation in ("create", "copy") or role == "destination":
                display_state = "modified" if previous is not None else "created"
                created_by_session = False if previous is not None else True
            elif previous is not None and previous.display_state == "created":
                display_state = "created"
                created_by_session = True
            else:
                display_state = "modified"
                created_by_session = False
            candidate.entries[key] = SessionFileChangeEntry(
                path=target, kind=operation.kind, display_state=display_state,
                created_by_session=created_by_session,
                operation_count=1 if previous is None else previous.operation_count + 1,
                last_operation=operation.operation, last_tool_name=operation.tool_name,
                actors=actors, last_operated_at=completed_at, last_revision=candidate.revision,
                source_path=source, destination_path=destination,
            )

    def record_success(
        self,
        session_id: str,
        actor: SessionFileChangeActor,
        operation: SessionFileChangeOperation,
        *,
        is_cancelled: Callable[[], bool]
        ) -> bool:
        try:
            with self._session_lock(session_id):
                if session_id in self._closed_sessions or is_cancelled():
                    return False
                if not (self._sessions_root / session_id).is_dir():
                    raise FileNotFoundError("File changes session directory no longer exists")
                self._validate_actor(actor)
                candidate = self._load_unlocked(session_id).model_copy(deep=True)
                self._apply_operation(candidate, actor, operation, datetime.now(timezone.utc).isoformat(timespec="milliseconds"))
                self._validate_data(candidate, session_id)
                if is_cancelled():
                    return False
                path = self._sessions_root / session_id / SESSION_FILE_CHANGES_ES_FILENAME
                save(SESSION_FILE_CHANGES_ES_KEY, make_config(path), candidate)
                self._cache[session_id] = candidate
                return True
        except Exception as exc:
            raise SessionFileChangesPersistenceFailure(
                f"Failed to persist successful file operation for session {session_id}"
            ) from exc

    def _visible_entries(self, data: SessionFileChangesData) -> list[tuple[str, SessionFileChangeEntry]]:
        return [
            (key, entry) for key, entry in data.entries.items()
            if not (entry.display_state == "deleted" and entry.created_by_session)
        ]

    def _summary(self, data: SessionFileChangesData) -> SessionFileChangesSummary:
        visible = self._visible_entries(data)
        latest = max((entry for _, entry in visible), key=lambda item: item.last_revision, default=None)
        return SessionFileChangesSummary(
            session_id=data.session_id, revision=data.revision,
            file_count=sum(entry.kind == "file" for _, entry in visible),
            directory_count=sum(entry.kind == "directory" for _, entry in visible),
            operation_count=data.revision,
            last_operated_at=latest.last_operated_at if latest is not None else None,
        )

    def get_summary(self, session_id: str) -> SessionFileChangesSummary:
        with self._session_lock(session_id):
            return self._summary(self._load_unlocked(session_id))

    def get_page(
        self,
        session_id: str,
        *,
        offset: int = 0,
        limit: int = SESSION_FILE_CHANGES_DEFAULT_LIMIT
        ) -> SessionFileChangesPage:
        if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= SESSION_FILE_CHANGES_MAX_LIMIT:
            raise ValueError("Invalid file changes pagination")
        with self._session_lock(session_id):
            data = self._load_unlocked(session_id)
            visible = self._visible_entries(data)
            ordered = sorted(visible, key=lambda item: (-item[1].last_revision, item[0]))
            return SessionFileChangesPage(
                summary=self._summary(data), offset=offset, limit=limit, total_count=len(ordered),
                items=[entry.model_copy(deep=True) for _, entry in ordered[offset:offset + limit]],
            )

    def block_session(
        self,
        session_id: str,
        *,
        timeout: float = SESSION_FILE_CHANGES_DELETE_LOCK_TIMEOUT_SECONDS
        ) -> None:
        lock = self._session_lock(session_id)
        if not lock.acquire(timeout=timeout):
            raise SessionFileChangesBusyError("Session file changes are still being committed")
        try:
            self._closed_sessions.add(session_id)
        finally:
            lock.release()

    def unblock_session(self, session_id: str) -> None:
        lock = self._session_lock(session_id)
        if not lock.acquire(timeout=SESSION_FILE_CHANGES_DELETE_LOCK_TIMEOUT_SECONDS):
            raise LifecycleFailure("Could not reopen session file changes after deletion stopped")
        try:
            self._closed_sessions.discard(session_id)
        finally:
            lock.release()

    def forget_session(self, session_id: str) -> None:
        lock = self._session_lock(session_id)
        if not lock.acquire(timeout=SESSION_FILE_CHANGES_DELETE_LOCK_TIMEOUT_SECONDS):
            raise LifecycleFailure("Could not release deleted session file changes")
        try:
            self._cache.pop(session_id, None)
            self._closed_sessions.add(session_id)
        finally:
            lock.release()
