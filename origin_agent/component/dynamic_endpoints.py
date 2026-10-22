"""动态端点注册表及其进程生命周期所有权。"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any

from framework import AsyncSystem

from entity.constant import DYNAMIC_ENDPOINTS_STORE_FILENAME
from entity.puretype import DynamicEndpointInfo
from util.atomic_io import write_text_atomic
from system.lifecycle import ApplicationStoppingError, LifecycleFailure
from interface.dynamic_endpoint_system import IDynamicEndpointSystem
from interface.runtime_system import IRuntimeSystem
from interface.session_manager import ISessionManager


class DynamicEndpointSystem(IDynamicEndpointSystem):
    """持有动态端点注册表、锁和原JSON持久化。"""

    def __init__(self) -> None:
        super().__init__(dependencies=(IRuntimeSystem, ISessionManager))
        self._runtime: IRuntimeSystem | None = None
        self._session_manager: ISessionManager | None = None
        self._store_path: Path | None = None
        self._endpoints: dict[str, DynamicEndpointInfo] = {}
        self._lock = threading.RLock()
        self._frozen = False

    async def virtual_awake(self) -> None:
        self._runtime = self.get_system(IRuntimeSystem)
        self._session_manager = self.get_system(ISessionManager)
        self._store_path = self._runtime.context.workspace / DYNAMIC_ENDPOINTS_STORE_FILENAME
        self._load_all_endpoints()

    async def virtual_shotdown(self) -> None:
        self.close_admission()

    @property
    def runtime(self) -> IRuntimeSystem:
        if self._runtime is None:
            raise LifecycleFailure("DynamicEndpointSystem has not been awakened")
        return self._runtime

    @property
    def session_manager(self) -> ISessionManager:
        if self._session_manager is None:
            raise LifecycleFailure("DynamicEndpointSystem has not been awakened")
        return self._session_manager

    @property
    def store_path(self) -> Path:
        if self._store_path is None:
            raise LifecycleFailure("DynamicEndpointSystem has not been awakened")
        return self._store_path

    def close_admission(self) -> None:
        with self._lock:
            self._frozen = True

    def _require_open(self) -> None:
        if self._frozen:
            raise ApplicationStoppingError("Dynamic endpoint admission has been closed")

    def lookup_endpoint(self, endpoint_name: str) -> DynamicEndpointInfo | None:
        with self._lock:
            return self._endpoints.get(endpoint_name)

    def list_session_endpoints(
        self,
        session_id: str,
        agent_name: str | None = None
        ) -> list[dict[str, Any]]:
        ctx = self.runtime.context
        with self._lock:
            return [
                {
                    "name": info.name,
                    "url": f"/dynamic/{info.session_id}/{info.agent_name}/{info.name}",
                    "absolute_url": (
                        f"http://{ctx.gateway_host}:{ctx.gateway_port}"
                        f"/dynamic/{info.session_id}/{info.agent_name}/{info.name}"
                    ),
                    "agent_name": info.agent_name,
                    "created_at": info.created_at,
                }
                for info in self._endpoints.values()
                if info.session_id == session_id
                and (agent_name is None or info.agent_name == agent_name)
            ]

    def register_endpoint(
        self,
        session_id: str,
        agent_name: str,
        name: str
        ) -> DynamicEndpointInfo:
        with self.runtime.admission(), self._lock:
            self._require_open()
            for info in self._endpoints.values():
                if (
                    info.session_id == session_id
                    and info.agent_name == agent_name
                    and info.name == name
                ):
                    raise ValueError(
                        f"Endpoint name '{name}' already registered for this session+agent"
                    )
            info = DynamicEndpointInfo(
                session_id=session_id,
                agent_name=agent_name,
                name=name,
                created_at=time.time(),
            )
            self._endpoints[name] = info
            self._save_all_endpoints_locked()
            return info

    def unregister_endpoint(self, name: str) -> DynamicEndpointInfo:
        with self.runtime.admission(), self._lock:
            self._require_open()
            info = self._endpoints.pop(name, None)
            if info is None:
                raise LookupError(f"Endpoint not found: {name}")
            self._delete_endpoint_on_disk_locked(name)
            return info

    def migrate_session_endpoints(
        self,
        old_sid: str,
        new_sid: str
        ) -> int:
        with self.runtime.admission(), self._lock:
            self._require_open()
            count = 0
            for info in self._endpoints.values():
                if info.session_id == old_sid:
                    info.session_id = new_sid
                    count += 1
            if count:
                self._save_all_endpoints_locked()
            return count

    def cleanup_session_endpoints(self, session_id: str) -> int:
        with self._lock:
            in_memory = sum(
                1 for info in self._endpoints.values()
                if info.session_id == session_id
            )
            for name in tuple(
                name for name, info in self._endpoints.items()
                if info.session_id == session_id
            ):
                del self._endpoints[name]

            if not self.store_path.exists():
                return in_memory
            raw = json.loads(self.store_path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                raise TypeError("Dynamic endpoint store must be an object")
            kept = {
                name: data for name, data in raw.items()
                if not (
                    isinstance(data, dict)
                    and data.get("session_id") == session_id
                )
            }
            on_disk = len(raw) - len(kept)
            if on_disk:
                self._write_locked(kept)
            return max(in_memory, on_disk)

    def _load_all_endpoints(self) -> None:
        if not self.store_path.exists():
            return
        raw = json.loads(self.store_path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise TypeError("Dynamic endpoint store must be an object")
        with self._lock:
            for name, data in raw.items():
                info = DynamicEndpointInfo.model_validate(data)
                if self.session_manager.exists(info.session_id):
                    self._endpoints[name] = info

    def _save_all_endpoints_locked(self) -> None:
        payload = {
            name: info.model_dump()
            for name, info in self._endpoints.items()
        }
        if self.store_path.exists():
            raw = json.loads(self.store_path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                raise TypeError("Dynamic endpoint store must be an object")
            for name, data in raw.items():
                if name not in payload:
                    payload[name] = data
        self._write_locked(payload)

    def _write_locked(self, payload: dict[str, Any]) -> None:
        self.store_path.parent.mkdir(parents=True, exist_ok=True)
        write_text_atomic(
            self.store_path,
            json.dumps(payload, ensure_ascii=False, indent=2),
            tmp_suffix=".tmp",
        )

    def _delete_endpoint_on_disk_locked(self, name: str) -> None:
        if not self.store_path.exists():
            return
        raw = json.loads(self.store_path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise TypeError("Dynamic endpoint store must be an object")
        if raw.pop(name, None) is not None:
            self._write_locked(raw)
