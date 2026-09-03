"""Agentspace 用户操作与 Agent 路径登记共享的短临界区。"""

from __future__ import annotations

import threading
from contextlib import contextmanager
from collections.abc import Iterator

from entity.puretype import AgentspaceLockOwner
from .errors import AgentspaceLockedError
from .lock_registry import AgentspaceLockRegistry


class AgentspaceOperationGate:
    def __init__(self, lock_registry: AgentspaceLockRegistry) -> None:
        self._registry = lock_registry
        self._lock = threading.RLock()

    @contextmanager
    def user_operation(
        self,
        paths: list[str],
        include_descendants: bool = False,
    ) -> Iterator[None]:
        with self._lock:
            for path in paths:
                matches = self._registry.matching(path, include_descendants)
                if matches:
                    raise AgentspaceLockedError(
                        "该路径正在被 Agent 使用，请等待当前回复结束后重试。",
                        path=path,
                        locks=[item.model_dump(mode="json") for item in matches],
                    )
            yield

    @contextmanager
    def agent_access(
        self,
        owner: AgentspaceLockOwner,
        paths: list[tuple[str, bool]],
    ) -> Iterator[None]:
        with self._lock:
            for logical_path, recursive in paths:
                self._registry.acquire(owner, logical_path, recursive)
            yield
