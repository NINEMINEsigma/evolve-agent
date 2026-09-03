"""Agentspace 编辑器的文件、锁、垃圾桶与实时事件业务服务。"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import re
import threading
import unicodedata
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from collections.abc import Iterator

from entity.constant import (
    AGENTSPACE_ATOMIC_TMP_SUFFIX,
    AGENTSPACE_EVENT_QUEUE_SIZE,
    AGENTSPACE_INTERNAL_DIR_NAME,
    AGENTSPACE_TRASH_DIR_NAME,
    AGENTSPACE_WATCH_DEBOUNCE_MS,
    FILE_SNIFF_BYTES,
)
from entity.puretype import (
    AgentspaceEntry,
    AgentspaceEntryKind,
    AgentspaceEvent,
    AgentspaceEventKind,
    AgentspaceEventSource,
    AgentspaceFileSnapshot,
    AgentspaceLockInfo,
    AgentspaceLockOwner,
    AgentspacePathIdentity,
    AgentspaceTrashEntry,
)
from system.atomic_io import (
    create_text_exclusive,
    move_file_no_replace,
    move_tree_no_replace,
    replace_atomic,
)
from system.sandbox import Sandbox, SandboxError
from .errors import (
    AgentspaceAlreadyExistsError,
    AgentspaceInvalidPathError,
    AgentspaceNotFoundError,
    AgentspaceNotTextError,
    AgentspaceVersionConflictError,
)
from .event_hub import AgentspaceEventHub
from .lock_registry import AgentspaceLockRegistry
from .operation_gate import AgentspaceOperationGate
from .trash_store import AgentspaceTrashStore
from .watcher import AgentspaceWatcher

logger = logging.getLogger(__name__)

_NATURAL_PART = re.compile(r"(\d+)")


class AgentspaceService:
    def __init__(self, sandbox: Sandbox, agentspace_root: Path) -> None:
        self._sandbox = sandbox
        self._root = agentspace_root.resolve()
        self._event_hub = AgentspaceEventHub(AGENTSPACE_EVENT_QUEUE_SIZE)
        self._lock_registry = AgentspaceLockRegistry(
            self._event_hub,
            self.path_identity,
        )
        self._operation_gate = AgentspaceOperationGate(self._lock_registry)
        self._trash_store = AgentspaceTrashStore(
            self._root / AGENTSPACE_TRASH_DIR_NAME,
            self._resolve_user_path,
        )
        self._watcher = AgentspaceWatcher(
            self._root,
            self._event_hub,
            AGENTSPACE_WATCH_DEBOUNCE_MS,
            {AGENTSPACE_TRASH_DIR_NAME, AGENTSPACE_INTERNAL_DIR_NAME},
        )
        self._pending_changes: dict[str, str] = {}
        self._pending_lock = threading.Lock()
        self._started = False
        self._watcher_available = False

    @staticmethod
    def _timestamp() -> str:
        return datetime.now(timezone.utc).isoformat()

    def _normalize(
        self,
        path: str,
        *,
        allow_root: bool,
        allow_internal_trash: bool,
    ) -> str:
        if not isinstance(path, str):
            raise AgentspaceInvalidPathError("路径必须是字符串。")
        raw = path
        if raw.startswith("ws:"):
            raw = raw[3:]
        if "\x00" in raw:
            raise AgentspaceInvalidPathError("路径包含 NUL 字符。", path=path)
        if "\\" in raw:
            raise AgentspaceInvalidPathError("路径必须使用正斜杠。", path=path)
        if raw.startswith("/") or raw.endswith("/"):
            raise AgentspaceInvalidPathError("路径不能以斜杠开始或结束。", path=path)
        if len(raw) > 1 and raw[1] == ":":
            raise AgentspaceInvalidPathError("不允许绝对路径。", path=path)
        if raw == "":
            if allow_root:
                return ""
            raise AgentspaceInvalidPathError("路径不能为空。", path=path)
        parts = raw.split("/")
        if any(part in ("", ".", "..") for part in parts):
            raise AgentspaceInvalidPathError("路径包含无效段。", path=path)
        normalized = "/".join(unicodedata.normalize("NFC", part) for part in parts)
        if not allow_internal_trash and normalized.split("/", 1)[0] == AGENTSPACE_TRASH_DIR_NAME:
            raise AgentspaceInvalidPathError("垃圾桶内部路径不能直接访问。", path=path)
        return normalized

    def _resolve(
        self,
        path: str,
        *,
        allow_root: bool = False,
        allow_internal_trash: bool = False,
    ) -> tuple[str, Path]:
        normalized = self._normalize(
            path,
            allow_root=allow_root,
            allow_internal_trash=allow_internal_trash,
        )
        logical = f"ws:{normalized}"
        try:
            resolved = self._sandbox.resolve_write(logical)
        except SandboxError as exc:
            raise AgentspaceInvalidPathError("路径未通过工作空间沙盒校验。", path=path) from exc
        try:
            resolved.real.resolve(strict=False).relative_to(self._root)
        except ValueError as exc:
            raise AgentspaceInvalidPathError("路径越出工作空间。", path=path) from exc
        return normalized, resolved.real

    def _resolve_user_path(self, path: str) -> tuple[str, Path]:
        return self._resolve(path, allow_root=False, allow_internal_trash=False)

    def path_identity(self, logical_or_relative_path: str) -> AgentspacePathIdentity:
        normalized, real = self._resolve(
            logical_or_relative_path,
            allow_root=True,
            allow_internal_trash=True,
        )
        canonical = unicodedata.normalize("NFC", str(real.resolve(strict=False)))
        if os.name == "nt":
            canonical = os.path.normcase(canonical)
        return AgentspacePathIdentity(
            display_path=normalized,
            canonical_key=canonical,
        )

    @staticmethod
    def _natural_key(entry: AgentspaceEntry) -> tuple[object, ...]:
        parts: list[object] = []
        for part in _NATURAL_PART.split(entry.name.casefold()):
            parts.append(int(part) if part.isdigit() else part)
        return (
            0 if entry.kind == AgentspaceEntryKind.DIR else 1,
            *parts,
            entry.name,
        )

    @staticmethod
    def _file_version(raw: bytes) -> str:
        """计算编辑器版本。

        文本编辑器内部统一使用 LF，因此 CRLF/LF 仅换行风格差异不能制造
        假冲突；真实文本内容、空行和尾部换行仍会参与哈希。
        二进制或非 UTF-8 数据回退到原始 bytes 哈希。
        """
        try:
            normalized = raw.decode("utf-8", errors="strict")
            normalized = normalized.replace("\r\n", "\n").replace("\r", "\n")
            return hashlib.sha256(normalized.encode("utf-8")).hexdigest()
        except UnicodeDecodeError:
            return hashlib.sha256(raw).hexdigest()

    def _snapshot_from_path(self, relative_path: str, real: Path) -> AgentspaceFileSnapshot:
        if not real.exists():
            raise AgentspaceNotFoundError("文件不存在。", path=relative_path)
        if not real.is_file():
            raise AgentspaceInvalidPathError("目标不是文件。", path=relative_path)
        try:
            raw = real.read_bytes()
        except OSError as exc:
            raise AgentspaceNotFoundError("无法读取文件。", path=relative_path) from exc
        if b"\x00" in raw[:FILE_SNIFF_BYTES]:
            raise AgentspaceNotTextError("该文件是二进制文件，不能在文本编辑器中打开。", path=relative_path)
        try:
            content = raw.decode("utf-8", errors="strict")
        except UnicodeDecodeError as exc:
            raise AgentspaceNotTextError("该文件不是 UTF-8 文本，不能直接编辑。", path=relative_path) from exc
        # Monaco 统一使用 LF；版本仍基于原始 bytes，保存时会尽量保留当前文件换行风格。
        content = content.replace("\r\n", "\n").replace("\r", "\n")
        stat = real.stat()
        return AgentspaceFileSnapshot(
            path=relative_path,
            content=content,
            version=self._file_version(raw),
            size=len(raw),
            modified_ns=stat.st_mtime_ns,
        )

    def _publish(
        self,
        kind: AgentspaceEventKind,
        *,
        path: str | None = None,
        new_path: str | None = None,
        is_directory: bool | None = None,
        operation_id: str | None = None,
        version: str | None = None,
        source: AgentspaceEventSource = AgentspaceEventSource.SERVICE,
        message: str | None = None,
    ) -> None:
        self._event_hub.publish_threadsafe(
            AgentspaceEvent(
                kind=kind,
                source=source,
                path=path,
                new_path=new_path,
                is_directory=is_directory,
                operation_id=operation_id or None,
                version=version,
                timestamp=self._timestamp(),
                message=message,
            )
        )

    def list_directory(self, relative_path: str) -> list[AgentspaceEntry]:
        normalized, real = self._resolve(
            relative_path,
            allow_root=True,
            allow_internal_trash=False,
        )
        if not real.exists():
            raise AgentspaceNotFoundError("目录不存在。", path=normalized)
        if not real.is_dir():
            raise AgentspaceInvalidPathError("目标不是目录。", path=normalized)
        entries: list[AgentspaceEntry] = []
        try:
            children = list(real.iterdir())
        except OSError as exc:
            raise AgentspaceNotFoundError("无法列出目录。", path=normalized) from exc
        for child in children:
            if not normalized and child.name == AGENTSPACE_TRASH_DIR_NAME:
                continue
            child_path = f"{normalized}/{child.name}" if normalized else child.name
            entries.append(
                AgentspaceEntry(
                    name=child.name,
                    path=child_path,
                    kind=(
                        AgentspaceEntryKind.DIR
                        if child.is_dir()
                        else AgentspaceEntryKind.FILE
                    ),
                )
            )
        return sorted(entries, key=self._natural_key)

    def read_file(self, relative_path: str) -> AgentspaceFileSnapshot:
        normalized, real = self._resolve_user_path(relative_path)
        return self._snapshot_from_path(normalized, real)

    def write_file(
        self,
        relative_path: str,
        content: str,
        expected_version: str | None,
        operation_id: str = "",
    ) -> AgentspaceFileSnapshot:
        normalized, target = self._resolve_user_path(relative_path)
        operation_id = operation_id or uuid.uuid4().hex
        with self._operation_gate.user_operation([normalized]):
            if target.exists():
                if not target.is_file():
                    raise AgentspaceAlreadyExistsError("目标已存在且不是文件。", path=normalized)
                initial_raw = target.read_bytes()
                initial_version = self._file_version(initial_raw)
                if expected_version is None or initial_version != expected_version:
                    raise AgentspaceVersionConflictError(
                        "文件已发生变化，请先处理冲突。",
                        path=normalized,
                        current_version=initial_version,
                    )
                initial_stat = target.stat()
                initial_identity = (
                    initial_stat.st_dev,
                    initial_stat.st_ino,
                    initial_stat.st_size,
                    initial_stat.st_mtime_ns,
                )
                temp = target.with_name(
                    f".{target.name}.{uuid.uuid4().hex}{AGENTSPACE_ATOMIC_TMP_SUFFIX}"
                )
                line_ending = "\r\n" if b"\r\n" in initial_raw else "\n"
                disk_content = content.replace("\n", line_ending)
                try:
                    with temp.open("x", encoding="utf-8", newline="") as stream:
                        stream.write(disk_content)
                        stream.flush()
                        os.fsync(stream.fileno())
                    current_raw = target.read_bytes()
                    current_stat = target.stat()
                    current_identity = (
                        current_stat.st_dev,
                        current_stat.st_ino,
                        current_stat.st_size,
                        current_stat.st_mtime_ns,
                    )
                    if (
                        self._file_version(current_raw) != initial_version
                        or current_identity != initial_identity
                    ):
                        raise AgentspaceVersionConflictError(
                            "文件在保存期间再次变化。",
                            path=normalized,
                            current_version=self._file_version(current_raw),
                        )
                    replace_atomic(temp, target)
                finally:
                    temp.unlink(missing_ok=True)
                change = "edit"
                event_kind = AgentspaceEventKind.MODIFIED
            else:
                if expected_version is not None:
                    raise AgentspaceVersionConflictError(
                        "文件已被删除，不能按旧版本保存。",
                        path=normalized,
                        current_version=None,
                    )
                if not target.parent.is_dir():
                    raise AgentspaceNotFoundError("父目录不存在。", path=normalized)
                try:
                    create_text_exclusive(target, content)
                except FileExistsError as exc:
                    raise AgentspaceAlreadyExistsError("目标文件已存在。", path=normalized) from exc
                change = "create"
                event_kind = AgentspaceEventKind.CREATED
            snapshot = self._snapshot_from_path(normalized, target)
            self.record_user_change(change, normalized)
        self._publish(
            event_kind,
            path=normalized,
            is_directory=False,
            operation_id=operation_id,
            version=snapshot.version,
        )
        return snapshot

    def create_directory(
        self,
        relative_path: str,
        operation_id: str = "",
    ) -> AgentspaceEntry:
        normalized, target = self._resolve_user_path(relative_path)
        operation_id = operation_id or uuid.uuid4().hex
        with self._operation_gate.user_operation([normalized]):
            if target.exists():
                raise AgentspaceAlreadyExistsError("目标路径已存在。", path=normalized)
            if not target.parent.is_dir():
                raise AgentspaceNotFoundError("父目录不存在。", path=normalized)
            try:
                target.mkdir(exist_ok=False)
            except FileExistsError as exc:
                raise AgentspaceAlreadyExistsError("目标路径已存在。", path=normalized) from exc
            self.record_user_change("create", normalized)
        self._publish(
            AgentspaceEventKind.CREATED,
            path=normalized,
            is_directory=True,
            operation_id=operation_id,
        )
        return AgentspaceEntry(
            name=target.name,
            path=normalized,
            kind=AgentspaceEntryKind.DIR,
        )

    def rename_path(
        self,
        relative_path: str,
        new_name: str,
        operation_id: str = "",
    ) -> tuple[str, str]:
        normalized, source = self._resolve_user_path(relative_path)
        if (
            not new_name
            or new_name in (".", "..")
            or "/" in new_name
            or "\\" in new_name
            or "\x00" in new_name
        ):
            raise AgentspaceInvalidPathError("新名称必须是不含路径分隔符的文件名。", path=normalized)
        new_name = unicodedata.normalize("NFC", new_name)
        parent_relative = normalized.rpartition("/")[0]
        new_relative = f"{parent_relative}/{new_name}" if parent_relative else new_name
        new_normalized, target = self._resolve_user_path(new_relative)
        if not source.exists():
            raise AgentspaceNotFoundError("要重命名的路径不存在。", path=normalized)
        is_directory = source.is_dir()
        operation_id = operation_id or uuid.uuid4().hex
        with self._operation_gate.user_operation(
            [normalized, new_normalized],
            include_descendants=is_directory,
        ):
            if target.exists():
                raise AgentspaceAlreadyExistsError("同名目标已经存在。", path=new_normalized)
            try:
                if is_directory:
                    move_tree_no_replace(source, target)
                else:
                    move_file_no_replace(source, target)
            except FileExistsError as exc:
                raise AgentspaceAlreadyExistsError("同名目标已经存在。", path=new_normalized) from exc
            self.record_user_change("rename", new_normalized, old_path=normalized)
        version = None
        if not is_directory and target.exists():
            version = self._file_version(target.read_bytes())
        self._publish(
            AgentspaceEventKind.MOVED,
            path=normalized,
            new_path=new_normalized,
            is_directory=is_directory,
            operation_id=operation_id,
            version=version,
        )
        return normalized, new_normalized

    def move_to_trash(
        self,
        relative_path: str,
        operation_id: str = "",
    ) -> AgentspaceTrashEntry:
        normalized, source = self._resolve_user_path(relative_path)
        if not source.exists():
            raise AgentspaceNotFoundError("要删除的路径不存在。", path=normalized)
        is_directory = source.is_dir()
        operation_id = operation_id or uuid.uuid4().hex
        with self._operation_gate.user_operation(
            [normalized, AGENTSPACE_TRASH_DIR_NAME],
            include_descendants=True,
        ):
            entry = self._trash_store.move_to_trash(normalized)
            self.record_user_change("delete", normalized)
        self._publish(
            AgentspaceEventKind.DELETED,
            path=normalized,
            is_directory=is_directory,
            operation_id=operation_id,
        )
        self._publish(
            AgentspaceEventKind.TRASH_CHANGED,
            path=AGENTSPACE_TRASH_DIR_NAME,
            is_directory=True,
            operation_id=operation_id,
        )
        return entry

    def list_trash(self) -> list[AgentspaceTrashEntry]:
        return self._trash_store.list_entries()

    def restore_trash(
        self,
        entry_id: str,
        operation_id: str = "",
    ) -> tuple[AgentspaceTrashEntry, str]:
        _entry, expected_target = self._trash_store.preview_restore(entry_id)
        operation_id = operation_id or uuid.uuid4().hex
        with self._operation_gate.user_operation(
            [expected_target, AGENTSPACE_TRASH_DIR_NAME],
            include_descendants=True,
        ):
            _current_entry, current_target = self._trash_store.preview_restore(entry_id)
            if current_target != expected_target:
                raise AgentspaceAlreadyExistsError(
                    "恢复目标在操作期间发生变化，请重试。",
                    path=expected_target,
                )
            entry, restored_path = self._trash_store.restore(entry_id)
            self.record_user_change("create", restored_path)
        self._publish(
            AgentspaceEventKind.CREATED,
            path=restored_path,
            is_directory=entry.kind == AgentspaceEntryKind.DIR,
            operation_id=operation_id,
        )
        self._publish(
            AgentspaceEventKind.TRASH_CHANGED,
            path=AGENTSPACE_TRASH_DIR_NAME,
            is_directory=True,
            operation_id=operation_id,
        )
        return entry, restored_path

    def purge_trash(self, entry_id: str, operation_id: str = "") -> None:
        operation_id = operation_id or uuid.uuid4().hex
        with self._operation_gate.user_operation(
            [AGENTSPACE_TRASH_DIR_NAME],
            include_descendants=True,
        ):
            self._trash_store.purge(entry_id)
        self._publish(
            AgentspaceEventKind.TRASH_CHANGED,
            path=AGENTSPACE_TRASH_DIR_NAME,
            is_directory=True,
            operation_id=operation_id,
        )

    def empty_trash(self, operation_id: str = "") -> tuple[int, list[str]]:
        operation_id = operation_id or uuid.uuid4().hex
        with self._operation_gate.user_operation(
            [AGENTSPACE_TRASH_DIR_NAME],
            include_descendants=True,
        ):
            result = self._trash_store.empty()
        self._publish(
            AgentspaceEventKind.TRASH_CHANGED,
            path=AGENTSPACE_TRASH_DIR_NAME,
            is_directory=True,
            operation_id=operation_id,
        )
        return result

    @contextmanager
    def agent_access(
        self,
        owner: AgentspaceLockOwner,
        paths: list[tuple[str, bool]],
    ) -> Iterator[None]:
        ws_paths = [item for item in paths if item[0].startswith("ws:")]
        if not ws_paths:
            yield
            return
        with self._operation_gate.agent_access(owner, ws_paths):
            yield

    def acquire_agent_access(
        self,
        owner_id: str,
        session_id: str,
        character_name: str,
        logical_path: str,
        recursive: bool = False,
    ) -> None:
        owner = AgentspaceLockOwner(
            owner_id=owner_id,
            session_id=session_id,
            character_name=character_name,
            round_id=owner_id,
        )
        with self._operation_gate.agent_access(owner, [(logical_path, recursive)]):
            pass

    def release_agent_access(self, round_id: str) -> None:
        self._lock_registry.release_round(round_id)

    def locks_snapshot(self) -> list[AgentspaceLockInfo]:
        return self._lock_registry.snapshot()

    @property
    def watcher_available(self) -> bool:
        return self._watcher_available

    def subscribe_events(self):
        return self._event_hub.subscribe()

    def unsubscribe_events(self, subscription_id: str) -> None:
        self._event_hub.unsubscribe(subscription_id)

    def record_user_change(
        self,
        operation: str,
        path: str,
        old_path: str | None = None,
    ) -> None:
        with self._pending_lock:
            if operation == "rename" and old_path:
                self._pending_changes.pop(old_path, None)
                self._pending_changes[path] = "edit"
            elif operation == "delete":
                if self._pending_changes.get(path) == "create":
                    self._pending_changes.pop(path, None)
                else:
                    self._pending_changes[path] = "delete"
            elif operation == "create":
                self._pending_changes[path] = "create"
            elif operation == "edit":
                if self._pending_changes.get(path) != "create":
                    self._pending_changes[path] = "edit"

    def flush_pending_changes(self) -> str | None:
        with self._pending_lock:
            if not self._pending_changes:
                return None
            pending = self._pending_changes
            self._pending_changes = {}
        labels = {
            "edit": "modified",
            "create": "created",
            "delete": "deleted",
        }
        lines = ["User changes in agentspace:"]
        for path, operation in pending.items():
            lines.append(f"- {labels.get(operation, operation)}: {path}")
        return "\n".join(lines)

    async def start(self) -> None:
        if self._started:
            return
        loop = asyncio.get_running_loop()
        self._event_hub.bind_loop(loop)
        await asyncio.to_thread(self._trash_store.recover_staging)
        try:
            self._watcher.start(loop)
            self._watcher_available = True
        except Exception as exc:
            self._watcher_available = False
            logger.warning("Agentspace watcher unavailable: %s", exc, exc_info=True)
            self._publish(
                AgentspaceEventKind.WATCHER_ERROR,
                source=AgentspaceEventSource.SYSTEM,
                message="外部文件实时同步不可用，请使用手动刷新。",
            )
        self._started = True

    async def shutdown(self) -> None:
        if not self._started:
            return
        if self._watcher_available:
            await asyncio.to_thread(self._watcher.stop)
        self._event_hub.close()
        self._started = False
        self._watcher_available = False
