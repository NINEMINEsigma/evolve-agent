"""Agentspace 文件变化监听器。"""

from __future__ import annotations

import hashlib
import logging
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from entity.constant import (
    AGENTSPACE_ATOMIC_TMP_SUFFIX,
    AGENTSPACE_INTERNAL_DIR_NAME,
    AGENTSPACE_TRASH_DIR_NAME,
)
from entity.puretype import (
    AgentspaceEvent,
    AgentspaceEventKind,
    AgentspaceEventSource,
)
from .event_hub import AgentspaceEventHub

logger = logging.getLogger(__name__)


class AgentspaceWatcher:
    def __init__(
        self,
        root: Path,
        event_hub: AgentspaceEventHub,
        debounce_ms: int,
        ignored_relative_roots: set[str],
    ) -> None:
        self._root = root.resolve()
        self._event_hub = event_hub
        self._debounce_seconds = debounce_ms / 1000.0
        self._ignored_roots = ignored_relative_roots
        self._observer: Any | None = None
        self._timers: dict[str, threading.Timer] = {}
        self._timer_lock = threading.Lock()

    def start(self, loop: Any) -> None:
        del loop  # EventHub 已绑定；参数保留为明确生命周期合同。
        if self._observer is not None:
            return
        from watchdog.events import FileSystemEventHandler
        from watchdog.observers import Observer

        watcher = self

        class Handler(FileSystemEventHandler):
            def on_created(self, event: Any) -> None:
                watcher._handle(AgentspaceEventKind.CREATED, event.src_path, event.is_directory)

            def on_modified(self, event: Any) -> None:
                watcher._handle(AgentspaceEventKind.MODIFIED, event.src_path, event.is_directory)

            def on_deleted(self, event: Any) -> None:
                watcher._cancel_pending(event.src_path)
                watcher._handle(AgentspaceEventKind.DELETED, event.src_path, event.is_directory)

            def on_moved(self, event: Any) -> None:
                watcher._cancel_pending(event.src_path)
                watcher._handle_move(event.src_path, event.dest_path, event.is_directory)

        observer = Observer()
        observer.schedule(Handler(), str(self._root), recursive=True)
        observer.start()
        self._observer = observer

    def stop(self) -> None:
        with self._timer_lock:
            timers = list(self._timers.values())
            self._timers.clear()
        for timer in timers:
            timer.cancel()
        observer = self._observer
        self._observer = None
        if observer is not None:
            observer.stop()
            observer.join(timeout=5)

    def _relative(self, raw_path: str) -> str | None:
        try:
            return Path(raw_path).resolve(strict=False).relative_to(self._root).as_posix()
        except (ValueError, OSError):
            return None

    @staticmethod
    def _version(raw_path: str, is_directory: bool) -> str | None:
        if is_directory:
            return None
        try:
            raw = Path(raw_path).read_bytes()
            try:
                content = raw.decode("utf-8", errors="strict")
                content = content.replace("\r\n", "\n").replace("\r", "\n")
                raw = content.encode("utf-8")
            except UnicodeDecodeError:
                pass
            return hashlib.sha256(raw).hexdigest()
        except OSError:
            return None

    def _classification(self, relative: str) -> str:
        first = relative.split("/", 1)[0]
        if first == AGENTSPACE_TRASH_DIR_NAME:
            return "trash"
        if first == AGENTSPACE_INTERNAL_DIR_NAME:
            return "ignored"
        if first in self._ignored_roots:
            return "ignored"
        if AGENTSPACE_ATOMIC_TMP_SUFFIX in Path(relative).name:
            return "ignored"
        return "normal"

    def _publish_trash_changed(self) -> None:
        self._event_hub.publish_threadsafe(
            AgentspaceEvent(
                kind=AgentspaceEventKind.TRASH_CHANGED,
                source=AgentspaceEventSource.WATCHER,
                path=AGENTSPACE_TRASH_DIR_NAME,
                is_directory=True,
                timestamp=datetime.now(timezone.utc).isoformat(),
            )
        )

    def _cancel_pending(self, raw_path: str) -> None:
        relative = self._relative(raw_path)
        if relative is None:
            return
        with self._timer_lock:
            timer = self._timers.pop(relative, None)
        if timer is not None:
            timer.cancel()

    def _handle(
        self,
        kind: AgentspaceEventKind,
        raw_path: str,
        is_directory: bool,
    ) -> None:
        relative = self._relative(raw_path)
        if relative is None or not relative:
            return
        classification = self._classification(relative)
        if classification == "ignored":
            return
        if classification == "trash":
            self._publish_trash_changed()
            return
        if kind == AgentspaceEventKind.MODIFIED:
            self._debounce_modified(relative, raw_path, is_directory)
            return
        self._publish(kind, relative, raw_path, is_directory)

    def _debounce_modified(
        self,
        relative: str,
        raw_path: str,
        is_directory: bool,
    ) -> None:
        def emit() -> None:
            with self._timer_lock:
                self._timers.pop(relative, None)
            self._publish(
                AgentspaceEventKind.MODIFIED,
                relative,
                raw_path,
                is_directory,
            )

        with self._timer_lock:
            previous = self._timers.pop(relative, None)
            if previous is not None:
                previous.cancel()
            timer = threading.Timer(self._debounce_seconds, emit)
            timer.daemon = True
            self._timers[relative] = timer
            timer.start()

    def _publish(
        self,
        kind: AgentspaceEventKind,
        relative: str,
        raw_path: str,
        is_directory: bool,
    ) -> None:
        self._event_hub.publish_threadsafe(
            AgentspaceEvent(
                kind=kind,
                source=AgentspaceEventSource.WATCHER,
                path=relative,
                is_directory=is_directory,
                version=(
                    self._version(raw_path, is_directory)
                    if kind in (AgentspaceEventKind.CREATED, AgentspaceEventKind.MODIFIED)
                    else None
                ),
                timestamp=datetime.now(timezone.utc).isoformat(),
            )
        )

    def _handle_move(self, raw_source: str, raw_destination: str, is_directory: bool) -> None:
        source = self._relative(raw_source)
        destination = self._relative(raw_destination)
        if source is None and destination is None:
            return
        source_class = self._classification(source) if source else "ignored"
        destination_class = self._classification(destination) if destination else "ignored"
        if source_class == "trash" or destination_class == "trash":
            self._publish_trash_changed()
        if source_class == "normal" and destination_class == "normal":
            self._event_hub.publish_threadsafe(
                AgentspaceEvent(
                    kind=AgentspaceEventKind.MOVED,
                    source=AgentspaceEventSource.WATCHER,
                    path=source,
                    new_path=destination,
                    is_directory=is_directory,
                    version=self._version(raw_destination, is_directory),
                    timestamp=datetime.now(timezone.utc).isoformat(),
                )
            )
        elif source_class == "normal" and source:
            self._publish(AgentspaceEventKind.DELETED, source, raw_source, is_directory)
        elif destination_class == "normal" and destination:
            self._publish(AgentspaceEventKind.CREATED, destination, raw_destination, is_directory)
