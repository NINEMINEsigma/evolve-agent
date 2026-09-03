"""Agentspace 按回复轮次持有的路径锁注册表。"""

from __future__ import annotations

import os
import threading
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from entity.puretype import (
    AgentspaceEvent,
    AgentspaceEventKind,
    AgentspaceEventSource,
    AgentspaceLockInfo,
    AgentspaceLockOwner,
    AgentspacePathIdentity,
)
from .event_hub import AgentspaceEventHub


def _is_within(child: str, parent: str) -> bool:
    try:
        return os.path.commonpath([child, parent]) == parent
    except (ValueError, OSError):
        return False


class AgentspaceLockRegistry:
    """维护 canonical path → 多 owner 锁；所有状态由线程锁保护。"""

    def __init__(
        self,
        event_hub: AgentspaceEventHub,
        canonicalize: Callable[[str], AgentspacePathIdentity],
    ) -> None:
        self._event_hub = event_hub
        self._canonicalize = canonicalize
        self._lock = threading.RLock()
        self._records: dict[tuple[str, bool], dict[str, Any]] = {}

    def acquire(
        self,
        owner: AgentspaceLockOwner,
        logical_path: str,
        recursive: bool,
    ) -> AgentspaceLockInfo:
        identity = self._canonicalize(logical_path)
        changed = False
        with self._lock:
            key = (identity.canonical_key, recursive)
            record = self._records.setdefault(
                key,
                {
                    "path": identity.display_path,
                    "recursive": recursive,
                    "owners": {},
                },
            )
            if owner.owner_id not in record["owners"]:
                record["owners"][owner.owner_id] = owner
                changed = True
            result = AgentspaceLockInfo(
                path=record["path"],
                recursive=record["recursive"],
                owners=list(record["owners"].values()),
            )
        if changed:
            self._publish_snapshot()
        return result

    def release_round(self, round_id: str) -> None:
        changed = False
        with self._lock:
            for key in list(self._records):
                owners: dict[str, AgentspaceLockOwner] = self._records[key]["owners"]
                for owner_id, owner in list(owners.items()):
                    if owner.round_id == round_id:
                        del owners[owner_id]
                        changed = True
                if not owners:
                    del self._records[key]
        if changed:
            self._publish_snapshot()

    def snapshot(self) -> list[AgentspaceLockInfo]:
        with self._lock:
            records = [
                AgentspaceLockInfo(
                    path=record["path"],
                    recursive=record["recursive"],
                    owners=list(record["owners"].values()),
                )
                for record in self._records.values()
            ]
        return sorted(records, key=lambda item: (item.path.casefold(), item.recursive))

    def matching(
        self,
        relative_path: str,
        include_descendants: bool,
    ) -> list[AgentspaceLockInfo]:
        target = self._canonicalize(relative_path)
        matches: list[AgentspaceLockInfo] = []
        with self._lock:
            for (record_key, _recursive), record in self._records.items():
                applies_to_target = record_key == target.canonical_key or (
                    record["recursive"] and _is_within(target.canonical_key, record_key)
                )
                locked_descendant = include_descendants and _is_within(
                    record_key, target.canonical_key
                )
                if applies_to_target or locked_descendant:
                    matches.append(
                        AgentspaceLockInfo(
                            path=record["path"],
                            recursive=record["recursive"],
                            owners=list(record["owners"].values()),
                        )
                    )
        return matches

    def _publish_snapshot(self) -> None:
        self._event_hub.publish_threadsafe(
            AgentspaceEvent(
                kind=AgentspaceEventKind.LOCKS,
                source=AgentspaceEventSource.LOCKS,
                locks=self.snapshot(),
                timestamp=datetime.now(timezone.utc).isoformat(),
            )
        )
