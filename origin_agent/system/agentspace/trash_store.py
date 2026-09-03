"""Agentspace 垃圾桶的可恢复事务存储。"""

from __future__ import annotations

import hashlib
import json
import logging
import shutil
import uuid
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

from entity.constant import (
    AGENTSPACE_ATOMIC_TMP_SUFFIX,
    AGENTSPACE_RECOVERED_PREFIX,
    AGENTSPACE_RESTORE_SUFFIX,
    AGENTSPACE_TRASH_COMMITTED_FILENAME,
    AGENTSPACE_TRASH_ITEMS_DIR_NAME,
    AGENTSPACE_TRASH_METADATA_FILENAME,
    AGENTSPACE_TRASH_PAYLOAD_NAME,
    AGENTSPACE_TRASH_STAGING_PREFIX,
)
from entity.puretype import (
    AgentspaceEntryKind,
    AgentspaceTrashEntry,
    AgentspaceTrashState,
)
from system.atomic_io import (
    move_file_no_replace,
    move_tree_no_replace,
    write_text_atomic,
)
from .errors import (
    AgentspaceNotFoundError,
    AgentspaceTrashCorruptError,
    AgentspaceTrashError,
)

logger = logging.getLogger(__name__)


class AgentspaceTrashStore:
    """只通过 UUID 条目目录操作 `.trash`，不信任落盘 metadata 路径。"""

    def __init__(
        self,
        trash_root: Path,
        resolve_user_path: Callable[[str], tuple[str, Path]],
    ) -> None:
        self._root = trash_root
        self._items = trash_root / AGENTSPACE_TRASH_ITEMS_DIR_NAME
        self._resolve_user_path = resolve_user_path

    def _canonical_id(self, entry_id: str) -> str:
        try:
            parsed = uuid.UUID(entry_id)
        except (ValueError, AttributeError) as exc:
            raise AgentspaceTrashError("无效的垃圾桶条目 ID。") from exc
        return parsed.hex

    def _staging_path(self, entry_id: str) -> Path:
        return self._root / f"{AGENTSPACE_TRASH_STAGING_PREFIX}{entry_id}"

    def _item_path(self, entry_id: str) -> Path:
        return self._items / entry_id

    @staticmethod
    def _size(path: Path) -> int:
        if path.is_file():
            return path.stat().st_size
        if path.is_dir():
            total = 0
            for child in path.rglob("*"):
                if child.is_file() and not child.is_symlink():
                    try:
                        total += child.stat().st_size
                    except OSError:
                        continue
            return total
        return 0

    @staticmethod
    def _metadata_text(entry: AgentspaceTrashEntry) -> str:
        return entry.model_dump_json(exclude_none=False)

    def _read_metadata(self, container: Path, entry_id: str) -> tuple[AgentspaceTrashEntry, bytes]:
        metadata_path = container / AGENTSPACE_TRASH_METADATA_FILENAME
        raw = metadata_path.read_bytes()
        entry = AgentspaceTrashEntry.model_validate_json(raw, strict=True)
        if self._canonical_id(entry.entry_id) != entry_id:
            raise AgentspaceTrashCorruptError("垃圾桶条目 ID 与元数据不一致。")
        if container.name not in (
            entry_id,
            f"{AGENTSPACE_TRASH_STAGING_PREFIX}{entry_id}",
        ):
            raise AgentspaceTrashCorruptError("垃圾桶条目目录与元数据不一致。")
        return entry, raw

    def _marker_valid(self, container: Path, entry_id: str, metadata_raw: bytes) -> bool:
        marker_path = container / AGENTSPACE_TRASH_COMMITTED_FILENAME
        payload = container / AGENTSPACE_TRASH_PAYLOAD_NAME
        if not marker_path.is_file() or not payload.exists():
            return False
        try:
            marker = json.loads(marker_path.read_text(encoding="utf-8"))
            payload_kind = "dir" if payload.is_dir() else "file" if payload.is_file() else ""
            return (
                marker.get("entry_id") == entry_id
                and marker.get("metadata_sha256") == hashlib.sha256(metadata_raw).hexdigest()
                and marker.get("payload_kind") == payload_kind
            )
        except (OSError, ValueError, TypeError):
            return False

    def _safe_container(self, entry_id: str) -> Path:
        canonical = self._canonical_id(entry_id)
        candidates = (self._item_path(canonical), self._staging_path(canonical))
        root = self._root.resolve()
        for candidate in candidates:
            if not candidate.exists():
                continue
            try:
                candidate.resolve().relative_to(root)
            except ValueError as exc:
                raise AgentspaceTrashError("垃圾桶条目越出内部目录。") from exc
            if candidate.is_symlink():
                raise AgentspaceTrashError("垃圾桶条目不能是符号链接。")
            return candidate
        raise AgentspaceNotFoundError("垃圾桶条目不存在。", path=canonical)

    def _inspect(self, container: Path, entry_id: str) -> AgentspaceTrashEntry:
        payload = container / AGENTSPACE_TRASH_PAYLOAD_NAME
        try:
            entry, metadata_raw = self._read_metadata(container, entry_id)
            if self._marker_valid(container, entry_id, metadata_raw):
                return entry.model_copy(
                    update={
                        "state": AgentspaceTrashState.READY,
                        "size": self._size(payload),
                        "error": None,
                    }
                )
            if payload.exists():
                return entry.model_copy(
                    update={
                        "state": AgentspaceTrashState.RECOVERABLE,
                        "size": self._size(payload),
                        "error": "事务未提交，可恢复 payload。",
                    }
                )
            return entry.model_copy(
                update={
                    "state": AgentspaceTrashState.CORRUPT,
                    "error": "垃圾桶 payload 缺失。",
                }
            )
        except Exception as exc:
            state = (
                AgentspaceTrashState.RECOVERABLE
                if payload.exists()
                else AgentspaceTrashState.CORRUPT
            )
            return AgentspaceTrashEntry(
                entry_id=entry_id,
                state=state,
                name=payload.name if payload.exists() else None,
                kind=(
                    AgentspaceEntryKind.DIR
                    if payload.is_dir()
                    else AgentspaceEntryKind.FILE
                    if payload.is_file()
                    else None
                ),
                size=self._size(payload),
                error=f"元数据损坏：{type(exc).__name__}",
            )

    def recover_staging(self) -> None:
        self._root.mkdir(parents=True, exist_ok=True)
        self._items.mkdir(parents=True, exist_ok=True)
        for staging in self._root.glob(f"{AGENTSPACE_TRASH_STAGING_PREFIX}*"):
            raw_id = staging.name[len(AGENTSPACE_TRASH_STAGING_PREFIX):]
            try:
                entry_id = self._canonical_id(raw_id)
                entry, metadata_raw = self._read_metadata(staging, entry_id)
                if not self._marker_valid(staging, entry_id, metadata_raw):
                    continue
                destination = self._item_path(entry_id)
                if destination.exists():
                    logger.warning("Trash staging target already exists: %s", destination)
                    continue
                move_tree_no_replace(staging, destination)
                logger.info("Recovered committed trash staging entry %s (%s)", entry_id, entry.original_path)
            except Exception:
                logger.warning("Trash staging requires manual recovery: %s", staging, exc_info=True)

    def move_to_trash(self, relative_path: str) -> AgentspaceTrashEntry:
        normalized, source = self._resolve_user_path(relative_path)
        if not source.exists():
            raise AgentspaceNotFoundError("要删除的路径不存在。", path=normalized)
        entry_id = uuid.uuid4().hex
        staging = self._staging_path(entry_id)
        payload = staging / AGENTSPACE_TRASH_PAYLOAD_NAME
        staging.mkdir(parents=True, exist_ok=False)
        kind = AgentspaceEntryKind.DIR if source.is_dir() else AgentspaceEntryKind.FILE
        entry = AgentspaceTrashEntry(
            entry_id=entry_id,
            state=AgentspaceTrashState.READY,
            original_path=normalized,
            name=source.name,
            kind=kind,
            deleted_at=datetime.now(timezone.utc).isoformat(),
            size=self._size(source),
        )
        metadata_text = self._metadata_text(entry)
        metadata_path = staging / AGENTSPACE_TRASH_METADATA_FILENAME
        write_text_atomic(
            metadata_path,
            metadata_text,
            tmp_suffix=f".{uuid.uuid4().hex}{AGENTSPACE_ATOMIC_TMP_SUFFIX}",
        )
        try:
            if kind == AgentspaceEntryKind.DIR:
                move_tree_no_replace(source, payload)
            else:
                move_file_no_replace(source, payload)
            marker = json.dumps(
                {
                    "entry_id": entry_id,
                    "metadata_sha256": hashlib.sha256(metadata_text.encode("utf-8")).hexdigest(),
                    "payload_kind": kind.value,
                },
                ensure_ascii=False,
                sort_keys=True,
            )
            write_text_atomic(
                staging / AGENTSPACE_TRASH_COMMITTED_FILENAME,
                marker,
                tmp_suffix=f".{uuid.uuid4().hex}{AGENTSPACE_ATOMIC_TMP_SUFFIX}",
            )
            self._items.mkdir(parents=True, exist_ok=True)
            destination = self._item_path(entry_id)
            move_tree_no_replace(staging, destination)
            return entry
        except BaseException:
            logger.exception("Move to trash did not reach committed state: %s", normalized)
            raise

    def list_entries(self) -> list[AgentspaceTrashEntry]:
        self._root.mkdir(parents=True, exist_ok=True)
        self._items.mkdir(parents=True, exist_ok=True)
        entries: list[AgentspaceTrashEntry] = []
        for container in self._items.iterdir():
            if not container.is_dir():
                continue
            try:
                entry_id = self._canonical_id(container.name)
            except AgentspaceTrashError:
                continue
            entries.append(self._inspect(container, entry_id))
        for container in self._root.glob(f"{AGENTSPACE_TRASH_STAGING_PREFIX}*"):
            if not container.is_dir():
                continue
            try:
                entry_id = self._canonical_id(
                    container.name[len(AGENTSPACE_TRASH_STAGING_PREFIX):]
                )
            except AgentspaceTrashError:
                continue
            entries.append(self._inspect(container, entry_id))
        return sorted(entries, key=lambda item: item.deleted_at or "", reverse=True)

    def _auto_restore_target(
        self,
        relative_path: str,
        kind: AgentspaceEntryKind,
    ) -> tuple[str, Path]:
        normalized, target = self._resolve_user_path(relative_path)
        if not target.exists():
            return normalized, target
        name = target.name
        parent_relative = normalized.rpartition("/")[0]
        if kind == AgentspaceEntryKind.FILE:
            suffix = target.suffix
            stem = target.stem
            make_name = lambda index: f"{stem}{AGENTSPACE_RESTORE_SUFFIX}-{index}{suffix}"
        else:
            make_name = lambda index: f"{name}{AGENTSPACE_RESTORE_SUFFIX}-{index}"
        index = 1
        while True:
            candidate_name = make_name(index)
            candidate_relative = (
                f"{parent_relative}/{candidate_name}"
                if parent_relative
                else candidate_name
            )
            candidate_normalized, candidate = self._resolve_user_path(candidate_relative)
            if not candidate.exists():
                return candidate_normalized, candidate
            index += 1

    def preview_restore(self, entry_id: str) -> tuple[AgentspaceTrashEntry, str]:
        canonical = self._canonical_id(entry_id)
        container = self._safe_container(canonical)
        entry = self._inspect(container, canonical)
        payload = container / AGENTSPACE_TRASH_PAYLOAD_NAME
        if not payload.exists():
            raise AgentspaceTrashCorruptError("垃圾桶条目没有可恢复内容。")
        kind = AgentspaceEntryKind.DIR if payload.is_dir() else AgentspaceEntryKind.FILE
        if entry.state == AgentspaceTrashState.READY and entry.original_path:
            relative = entry.original_path
        else:
            relative = f"{AGENTSPACE_RECOVERED_PREFIX}{canonical}"
        target_relative, _ = self._auto_restore_target(relative, kind)
        return entry, target_relative

    def restore(self, entry_id: str) -> tuple[AgentspaceTrashEntry, str]:
        canonical = self._canonical_id(entry_id)
        container = self._safe_container(canonical)
        entry = self._inspect(container, canonical)
        payload = container / AGENTSPACE_TRASH_PAYLOAD_NAME
        if not payload.exists():
            raise AgentspaceTrashCorruptError("垃圾桶条目没有可恢复内容。")
        kind = AgentspaceEntryKind.DIR if payload.is_dir() else AgentspaceEntryKind.FILE
        base_relative = (
            entry.original_path
            if entry.state == AgentspaceTrashState.READY and entry.original_path
            else f"{AGENTSPACE_RECOVERED_PREFIX}{canonical}"
        )
        target_relative, target = self._auto_restore_target(base_relative, kind)
        if kind == AgentspaceEntryKind.DIR:
            move_tree_no_replace(payload, target)
        else:
            move_file_no_replace(payload, target)
        shutil.rmtree(container, ignore_errors=False)
        return entry, target_relative

    def purge(self, entry_id: str) -> None:
        container = self._safe_container(self._canonical_id(entry_id))
        root = self._root.resolve()
        try:
            container.resolve().relative_to(root)
        except ValueError as exc:
            raise AgentspaceTrashError("垃圾桶条目越出内部目录。") from exc
        if container.is_symlink():
            raise AgentspaceTrashError("拒绝清理符号链接垃圾桶条目。")
        if container.is_dir():
            shutil.rmtree(container)
        else:
            container.unlink()

    def empty(self) -> tuple[int, list[str]]:
        deleted = 0
        failures: list[str] = []
        seen: set[str] = set()
        for entry in self.list_entries():
            if entry.entry_id in seen:
                continue
            seen.add(entry.entry_id)
            try:
                self.purge(entry.entry_id)
                deleted += 1
            except Exception:
                logger.warning("Failed to purge trash entry %s", entry.entry_id, exc_info=True)
                failures.append(entry.entry_id)
        return deleted, failures
