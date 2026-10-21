"""会话离线导出的 Gateway 叶服务：捕获、精确资源读取与复核。

只持有并发容量与线程池，不缓存 History、不创建导出任务、不写盘、不调用模型。
重 CPU（摘要、投影、视觉签名）全部在线程池执行；主事件循环只做同步确认、
分段让出与轻量 guard 复核。
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import mimetypes
import os
import stat
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, TypeVar
from collections.abc import Callable

from pydantic import BaseModel, ConfigDict, ValidationError, model_validator

from entity.constant import (
    META_FILE_SUFFIX, SESSIONS_DIR_NAME, SESSION_EXPORT_HEAVY_CAPACITY,
    SESSION_EXPORT_MAX_RESOURCES, SESSION_EXPORT_REQUEST_TIMEOUT_SECONDS,
    SESSION_EXPORT_RESOURCE_CAPACITY, SESSION_EXPORT_RESOURCE_MAX_BYTES,
    SESSION_EXPORT_READ_CHUNK_BYTES,
)
from entity.puretype import (
    MessageMetrics, SessionExportLimits, SessionExportResourceProof,
    SessionExportResourceRequest, SessionExportResourceSource,
    SessionExportSnapshotResponse, SessionExportStamp, SessionExportVisualEntry,
    SessionExportVerifyRequest, SessionExportVerifyResponse, SessionInfo,
    SessionStatus, SessionVisualKind, SessionVisualResourceState,
)
from entity.puretype_after import SessionExportHistorySource
from entry.session_export import (
    SessionExportBusyError, SessionExportChangedError, SessionExportError,
    SessionExportLimitError, SessionExportTimeoutError, export_history_digest, project_export_history,
)
from system.file_metadata import MetaFormatError, parse_meta_content
from system.local_fonts import (
    LocalFontAccessError, local_font_mime_type, resolve_local_font,
)
from system.sandbox import ResolvedPath, Sandbox, SandboxError
from system.session_store import SessionStore
from system.session_visual_resources import (
    SessionVisualResourceError, SessionVisualResourceService,
)

if TYPE_CHECKING:
    from entry.base_agent_loop import IMainSessionLoop
    from gateway.session_manager import SessionManager
    from system.runtime import RuntimeSystem

ExportWorkT = TypeVar("ExportWorkT")


logger = logging.getLogger(__name__)


class SessionExportInputError(SessionExportError):
    """请求结构、路径或来源无效。"""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(code, message, 400)


class SessionExportNotFoundError(SessionExportError):
    """会话不存在、删除中或目标资源缺失。"""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(code, message, 404)


class SessionExportNotReadyError(SessionExportError):
    """会话存在但 Loop 未恢复、身份不匹配或已归档不可导出。"""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(code, message, 409)


class SessionExportCapacityError(SessionExportError):
    """进程级并发容量已满，不排队直接拒绝。"""

    def __init__(self) -> None:
        super().__init__("export_capacity", "Too many concurrent export operations", 429)


class SessionExportMetricsError(SessionExportError):
    """消息计时文件已存在但结构损坏；不能转成空 metrics。"""

    def __init__(self, message: str) -> None:
        super().__init__("invalid_metrics", message, 409)


class SessionExportResourceRead(BaseModel):
    """一次资源读取结果；非持久化，含业务校验方法。"""

    model_config = ConfigDict(extra="forbid")

    status: Literal["saved", "missing", "denied", "too_large"]
    content: bytes | None = None
    mime_type: str | None = None
    proof: SessionExportResourceProof

    @model_validator(mode="after")
    def _check_consistency(self) -> "SessionExportResourceRead":
        if self.proof.status != self.status:
            raise ValueError("Resource read status does not match proof")
        if self.status == "saved":
            if self.content is None or self.mime_type is None:
                raise ValueError("Saved resource requires content and MIME type")
            if self.proof.digest is None or self.proof.identity is None or self.proof.size is None:
                raise ValueError("Saved resource requires digest, identity and size")
            if len(self.content) != self.proof.size:
                raise ValueError("Saved resource size does not match proof")
        elif self.content is not None or self.mime_type is not None:
            raise ValueError("Unavailable resource must not carry content")
        return self

    @property
    def code(self) -> str:
        return {
            "missing": "resource_missing",
            "denied": "resource_denied",
            "too_large": "resource_too_large",
        }.get(self.status, "resource_unavailable")


class _CapacityTicket:
    """容量占用的唯一释放票据；重复释放只生效一次。"""

    def __init__(self, release: Callable[[], None]) -> None:
        self._release = release
        self._lock = threading.Lock()
        self._released = False

    def release(self) -> None:
        with self._lock:
            if self._released:
                return
            self._released = True
        self._release()


class _SourceUnavailable(Exception):
    """线程侧资源不可用信号；由 status 与 code 承载结果。"""

    def __init__(self, status: Literal["missing", "denied", "too_large"], code: str) -> None:
        super().__init__(code)
        self.status = status
        self.code = code


def _guess_media_type(path: Path) -> str:
    mime, _ = mimetypes.guess_type(str(path))
    if mime is None:
        return "application/octet-stream"
    if mime.startswith(("text/", "application/json", "application/xml", "image/svg")):
        if "charset" not in mime:
            mime = f"{mime}; charset=utf-8"
    return mime


def _digest_text(*parts: str) -> str:
    digest = hashlib.sha256()
    for part in parts:
        digest.update(part.encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


def _file_stat_signature(info: os.stat_result) -> tuple[int, int, int, int, int, int]:
    """同一种 stat 来源内部比较；不把 Windows 路径结果与 fd 结果混用。"""
    return (
        stat.S_IFMT(info.st_mode), info.st_dev, info.st_ino,
        info.st_size, info.st_mtime_ns, info.st_ctime_ns,
    )


def _assert_read_unchanged(
    kind: str, source_ref: str,
    path_before: os.stat_result, handle_before: os.stat_result,
    handle_after: os.stat_result, path_after: os.stat_result, total: int,
) -> None:
    """独立复核路径和打开句柄；保留字节数和后续 SHA-256 复核。"""
    reason = None
    if _file_stat_signature(path_before) != _file_stat_signature(path_after):
        reason = "path_state_changed"
    elif _file_stat_signature(handle_before) != _file_stat_signature(handle_after):
        reason = "handle_state_changed"
    elif total != path_before.st_size or total != handle_before.st_size:
        reason = "read_size_changed"
    elif os.name != "nt" and (
        path_before.st_dev, path_before.st_ino
    ) != (handle_before.st_dev, handle_before.st_ino):
        reason = "opened_identity_changed"
    # Windows 不同 Python/底层 stat 路径的 dev/ino 与时间精度未必一致。
    # 路径前后和同一 fd 前后仍分别全量比较，绝不是忽略文件变化。
    if reason is not None:
        logger.warning(
            "session export file check failed kind=%s source_ref=%s reason=%s "
            "path_before=%s path_after=%s handle_before=%s handle_after=%s bytes=%s",
            kind, source_ref, reason, _file_stat_signature(path_before),
            _file_stat_signature(path_after), _file_stat_signature(handle_before),
            _file_stat_signature(handle_after), total,
        )
        raise SessionExportChangedError()


def _canonical_metadata_digest(info: SessionInfo) -> str:
    """只覆盖导出实际下发的明确字段，不读取 Profile 或密钥。"""
    payload = {
        "title": info.title,
        "tags": list(info.tags),
        "status": info.status.value,
        "loop_type": info.loop_type.value,
        "agents": list(info.agents or ()),
        "pinned": info.pinned,
    }
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


class SessionExportService:
    """由 GatewaySystem 持有的无会话缓存叶服务。"""

    def __init__(
        self,
        runtime: "RuntimeSystem",
        sessions: "SessionManager",
        sandbox: Sandbox,
        visuals: SessionVisualResourceService,
    ) -> None:
        self._runtime = runtime
        self._sessions = sessions
        self._sandbox = sandbox
        self._visuals = visuals
        self._heavy_in_use = 0
        self._resource_in_use = 0
        self._capacity_lock = threading.Lock()
        # 容量与线程数一致，超过容量的请求在同步检查处直接拒绝，不进入队列。
        self._executor = ThreadPoolExecutor(
            max_workers=SESSION_EXPORT_HEAVY_CAPACITY + SESSION_EXPORT_RESOURCE_CAPACITY,
            thread_name_prefix="session-export",
        )

    # -- 容量与线程 -----------------------------------------------------

    def _acquire_heavy(self) -> "_CapacityTicket":
        with self._capacity_lock:
            if self._heavy_in_use >= SESSION_EXPORT_HEAVY_CAPACITY:
                raise SessionExportCapacityError()
            self._heavy_in_use += 1
        return _CapacityTicket(self._release_heavy)

    def _release_heavy(self) -> None:
        with self._capacity_lock:
            self._heavy_in_use -= 1

    def _acquire_resource(self) -> "_CapacityTicket":
        with self._capacity_lock:
            if self._resource_in_use >= SESSION_EXPORT_RESOURCE_CAPACITY:
                raise SessionExportCapacityError()
            self._resource_in_use += 1
        return _CapacityTicket(self._release_resource)

    def _release_resource(self) -> None:
        with self._capacity_lock:
            self._resource_in_use -= 1

    async def _run_sync(self, fn: Callable[[threading.Event, float], ExportWorkT], deadline: float, ticket: _CapacityTicket) -> ExportWorkT:
        """在线程池执行同步函数；容量由工作线程 finally 释放，取消时不提前释放。"""
        loop = asyncio.get_running_loop()
        cancel = threading.Event()

        def runner() -> ExportWorkT:
            try:
                return fn(cancel, deadline)
            finally:
                ticket.release()

        try:
            future = self._executor.submit(runner)
        except BaseException:
            cancel.set()
            ticket.release()
            raise
        wrapped = asyncio.wrap_future(future, loop=loop)
        wrapped.add_done_callback(lambda done: None if done.cancelled() else done.exception())
        try:
            return await asyncio.shield(wrapped)
        except SessionExportError as error:
            logger.warning("session export worker failed code=%s status=%s message=%s", error.code, error.status, str(error))
            raise
        except asyncio.CancelledError:
            cancel.set()
            # 等真实线程结束，不能让调用方 finally 提前释放容量。
            while not wrapped.done():
                try:
                    await asyncio.shield(wrapped)
                except asyncio.CancelledError:
                    continue
                except SessionExportError:
                    break
            if not wrapped.cancelled():
                try:
                    wrapped.result()
                except SessionExportError:
                    pass
            raise

    # -- 同步确认 -------------------------------------------------------

    def _require_running(self) -> None:
        self._runtime.require_running()

    def _confirm_session(self, session_id: str) -> tuple[SessionInfo, IMainSessionLoop]:
        """同步确认会话存在、非删除、Loop 已就绪且身份匹配且空闲。"""
        logger.debug("session export confirm session=%s phase=confirm", session_id)
        manager = self._sessions
        info = manager.get(session_id)
        if info is None or not manager.exists(session_id) or manager.is_session_deleting(session_id):
            logger.warning("session export confirm failed session=%s reason=session_not_found", session_id)
            raise SessionExportNotFoundError("session_not_found", "Session not found")
        loop = manager.get_loop(session_id)
        if loop is None:
            logger.warning("session export confirm failed session=%s reason=loop_not_ready", session_id)
            raise SessionExportNotReadyError("loop_not_ready", "Session loop is not ready")
        if loop.loop.session_id != session_id:
            logger.warning("session export confirm failed session=%s reason=session_rotating actual=%s", session_id, loop.loop.session_id)
            raise SessionExportNotReadyError("session_rotating", "Session is rotating")
        if loop.loop.is_active():
            logger.info("session export confirm deferred session=%s reason=loop_active", session_id)
            raise SessionExportBusyError()
        queue = loop.loop.message_queue
        if queue is not None and queue.pending_deliveries():
            logger.info("session export confirm deferred session=%s reason=pending_deliveries", session_id)
            raise SessionExportBusyError()
        return info, loop

    def _check_guard(self, loop: IMainSessionLoop, instance_id: str, epoch: int) -> None:
        self._require_running()
        _, current = self._confirm_session(loop.loop.session_id)
        if current is not loop or loop.loop.get_session_export_guard() != (instance_id, epoch):
            actual = loop.loop.get_session_export_guard()
            logger.warning(
                "session export guard changed session=%s expected_instance=%s expected_epoch=%s actual_instance=%s actual_epoch=%s",
                loop.loop.session_id, instance_id, epoch, actual[0], actual[1],
            )
            raise SessionExportChangedError()

    # -- metrics --------------------------------------------------------

    def _read_metrics(self, session_id: str, cancel: threading.Event, deadline: float) -> tuple[dict[int, MessageMetrics], str]:
        """严格、有界读取同一次 metrics 字节快照，缺失与空文件不同。"""
        from entity.constant import SESSION_EXPORT_HISTORY_MAX_BYTES
        store = SessionStore(self._runtime.context.workspace / SESSIONS_DIR_NAME)
        path = store.message_metrics_path(session_id)
        try:
            path_before = path.stat()
        except FileNotFoundError:
            return {}, "absent"
        try:
            with path.open("rb") as stream:
                handle_before = os.fstat(stream.fileno())
                blocks: list[bytes] = []
                total = 0
                while True:
                    if cancel.is_set():
                        raise SessionExportChangedError()
                    if time.monotonic() > deadline:
                        raise SessionExportTimeoutError()
                    chunk = stream.read(SESSION_EXPORT_READ_CHUNK_BYTES)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > SESSION_EXPORT_HISTORY_MAX_BYTES:
                        raise SessionExportLimitError("Message metrics exceed byte budget")
                    blocks.append(chunk)
                handle_after = os.fstat(stream.fileno())
            path_after = path.stat()
        except FileNotFoundError as error:
            logger.warning("session export file check failed kind=metrics session=%s reason=path_disappeared", session_id)
            raise SessionExportChangedError() from error
        _assert_read_unchanged("metrics", session_id, path_before, handle_before, handle_after, path_after, total)
        content = b"".join(blocks)
        try:
            raw = json.loads(content)
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            raise SessionExportMetricsError("Stored message metrics are invalid") from error
        if not isinstance(raw, dict):
            raise SessionExportMetricsError("Message metrics must be an object")
        result: dict[int, MessageMetrics] = {}
        for key, value in raw.items():
            if cancel.is_set():
                raise SessionExportChangedError()
            if time.monotonic() > deadline:
                raise SessionExportTimeoutError()
            if not key.isdecimal() or str(int(key)) != key:
                raise SessionExportMetricsError("Invalid message metrics index")
            try:
                result[int(key)] = MessageMetrics.model_validate(value)
            except ValidationError as error:
                raise SessionExportMetricsError("Invalid message metrics entry") from error
        return result, hashlib.sha256(content).hexdigest()

    # -- 视觉状态 -------------------------------------------------------

    def _visual_entries(self, session_id: str, cancel: threading.Event, deadline: float) -> tuple[list[SessionExportVisualEntry], str]:
        """源配置与入口原字节都参与复核，不依赖只覆盖stage入口的旧version。"""
        entries: list[SessionExportVisualEntry] = []
        evidence: list[object] = []
        for kind in (SessionVisualKind.stage, SessionVisualKind.chat_style):
            if cancel.is_set():
                raise SessionExportChangedError()
            if time.monotonic() > deadline:
                raise SessionExportTimeoutError()
            source = self._visuals.source_path(session_id, kind)
            configured = False
            directory_evidence: object = "missing"
            try:
                directory = self._sandbox.resolve_read(source)
                info = directory.real.stat()
                configured = True
                directory_evidence = [str(directory.real), info.st_dev, info.st_ino, info.st_mode]
            except FileNotFoundError:
                pass
            except (PermissionError, SandboxError):
                configured = True
                directory_evidence = "unreadable"
            meta = self._read_or_unavailable(
                SessionExportResourceSource(kind="sandbox", path=source + META_FILE_SUFFIX), cancel, deadline, keep_content=True,
            )
            metadata = None
            metadata_error = None
            error_code = None
            if meta.status == "saved":
                configured = True
                try:
                    metadata = parse_meta_content(meta.content.decode("utf-8"))
                except (MetaFormatError, UnicodeDecodeError):
                    metadata_error = "Invalid metadata"
                    error_code = "invalid_metadata"
            elif meta.status != "missing":
                configured = True
                metadata_error = "Unreadable metadata"
                error_code = "visual_unreadable"
            state = self._visuals.resolve_from_metadata(session_id, kind, metadata, metadata_error=metadata_error)
            logical = self._visuals.build_entry_logical_path(state)
            entry = self._read_or_unavailable(
                SessionExportResourceSource(kind="sandbox", path=logical), cancel, deadline, keep_content=True,
            )
            ready = entry.status == "saved"
            if ready:
                configured = True
            if not configured:
                availability = "unconfigured"
            elif metadata_error == "Invalid metadata" or state.redirect_error is not None:
                availability = "invalid_metadata"
                error_code = error_code or "invalid_metadata"
            elif directory_evidence == "unreadable" or meta.status == "denied" or entry.status == "denied":
                availability = "unreadable"
                error_code = error_code or "visual_unreadable"
            elif ready:
                availability = "ready"
            else:
                availability = "missing_entry"
                error_code = error_code or entry.code
            value = SessionExportVisualEntry(
                kind=kind.value, configured=configured, availability=availability,
                status="ready" if ready else "error" if availability == "unreadable" else "missing",
                source_path=source, effective_path=state.effective_path,
                entry_path=logical if ready else None, error_code=error_code,
            )
            entries.append(value)
            evidence.append([value.model_dump(), directory_evidence, meta.proof.model_dump(), entry.proof.model_dump()])
        return entries, hashlib.sha256(json.dumps(evidence, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()

    # -- 资源读取 -------------------------------------------------------

    @staticmethod
    def _assert_no_reparse(resolved: ResolvedPath, bases: dict[str, Path]) -> None:
        base = bases.get(resolved.namespace)
        if base is None:
            raise SandboxError("Namespace base unavailable")
        try:
            relative = resolved.real.relative_to(base)
        except ValueError as exc:
            raise SandboxError("Resolved path escapes namespace") from exc
        current = base
        for part in relative.parts:
            current = current / part
            info = os.lstat(current)
            if stat.S_ISLNK(info.st_mode):
                raise SandboxError("Reparse point rejected")
            if os.name == "nt" and info.st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT:
                raise SandboxError("Reparse point rejected")

    def _resolve_source(self, source: SessionExportResourceSource) -> tuple[Path, str, str]:
        """解析来源为物理路径、MIME 与物理映射摘要；拒绝符号链接/reparse。"""
        if source.kind == "local_font":
            path = resolve_local_font(source.path, strict_reparse=True)
            return path, local_font_mime_type(path), _digest_text("local_font", str(path))
        namespace, separator, relative = source.path.partition(":")
        if not separator or namespace != namespace.strip() or not namespace or not relative or relative.startswith(("/", "\\")) or ":" in relative or ".." in relative.replace("\\", "/").split("/") or any(char in source.path for char in "\x00\r\n"):
            raise SessionExportInputError("invalid_resource_path", "Invalid logical resource path")
        resolved = self._sandbox.resolve_read(source.path)
        bases = self._sandbox.namespace_bases()
        base = bases.get(namespace)
        if base is None:
            raise SandboxError("Namespace is unavailable")
        from system.local_fonts import reject_reparse_components
        reject_reparse_components((base / relative).absolute())
        self._assert_no_reparse(resolved, bases)
        return resolved.real, _guess_media_type(resolved.real), _digest_text("sandbox", str(resolved.real))

    def _read_source(
        self, source: SessionExportResourceSource, cancel: threading.Event, deadline: float,
        *, keep_content: bool,
    ) -> tuple[str, bytes | None, str | None, str | None, str | None, int | None]:
        """读取精确文件；返回 (status, content, mime, digest, identity, size)。"""
        def check() -> None:
            if cancel.is_set():
                raise SessionExportChangedError()
            if time.monotonic() > deadline:
                raise SessionExportTimeoutError()

        try:
            check()
            path, mime, mapping = self._resolve_source(source)
        except FileNotFoundError as exc:
            raise _SourceUnavailable("missing", "resource_missing") from exc
        except LocalFontAccessError as exc:
            status = "missing" if exc.code == "font_not_found" else (
                "too_large" if exc.code == "font_too_large" else "denied"
            )
            raise _SourceUnavailable(status, exc.code) from exc
        except SandboxError as exc:
            raise _SourceUnavailable("denied", "sandbox_denied") from exc
        except PermissionError as exc:
            raise _SourceUnavailable("denied", "permission_denied") from exc

        logical = source.path
        try:
            before = os.lstat(path)
        except FileNotFoundError as exc:
            raise _SourceUnavailable("missing", "resource_missing") from exc
        except PermissionError as exc:
            raise _SourceUnavailable("denied", "permission_denied") from exc
        if not stat.S_ISREG(before.st_mode):
            raise _SourceUnavailable("denied", "not_a_regular_file")
        if before.st_size > SESSION_EXPORT_RESOURCE_MAX_BYTES:
            raise _SourceUnavailable("too_large", "resource_too_large")

        digest = hashlib.sha256()
        collected = bytearray()
        total = 0
        try:
            with path.open("rb") as stream:
                handle_before = os.fstat(stream.fileno())
                while True:
                    check()
                    block = stream.read(SESSION_EXPORT_READ_CHUNK_BYTES)
                    if not block:
                        break
                    total += len(block)
                    if total > SESSION_EXPORT_RESOURCE_MAX_BYTES:
                        raise _SourceUnavailable("too_large", "resource_too_large")
                    digest.update(block)
                    if keep_content:
                        collected.extend(block)
                handle_after = os.fstat(stream.fileno())
        except FileNotFoundError as exc:
            raise _SourceUnavailable("missing", "resource_missing") from exc
        except PermissionError as exc:
            raise _SourceUnavailable("denied", "permission_denied") from exc

        try:
            final = os.lstat(path)
        except FileNotFoundError as exc:
            raise SessionExportChangedError() from exc
        _assert_read_unchanged(
            "resource", _digest_text(source.kind, source.path)[:16],
            before, handle_before, handle_after, final, total,
        )

        try:
            resolved_again, _, current_mapping = self._resolve_source(source)
        except (FileNotFoundError, PermissionError, SandboxError, LocalFontAccessError) as error:
            raise SessionExportChangedError() from error
        if resolved_again != path or current_mapping != mapping:
            raise SessionExportChangedError()
        identity = _digest_text(
            mapping, logical, str(before.st_dev), str(before.st_ino), str(total), str(before.st_mtime_ns), str(before.st_ctime_ns),
        )
        content = bytes(collected) if keep_content else None
        return "saved", content, mime, digest.hexdigest(), identity, total

    def _read_or_unavailable(
        self, source: SessionExportResourceSource, cancel: threading.Event, deadline: float,
        *, keep_content: bool,
    ) -> SessionExportResourceRead:
        try:
            status, content, mime, digest, identity, size = self._read_source(
                source, cancel, deadline, keep_content=keep_content,
            )
        except _SourceUnavailable as exc:
            if exc.code == "export_aborted":
                raise SessionExportChangedError() from exc
            return SessionExportResourceRead(
                status=exc.status,
                proof=SessionExportResourceProof(source=source, status=exc.status),
            )
        return SessionExportResourceRead(
            status="saved", content=content, mime_type=mime,
            proof=SessionExportResourceProof(
                source=source, status="saved", digest=digest, size=size, identity=identity,
            ),
        )

    # -- 公开操作 -------------------------------------------------------

    async def encode_snapshot(self, snapshot: SessionExportSnapshotResponse) -> bytes:
        """有界增量编码与最后 guard 复核，不在主事件循环编码大响应。"""
        from entity.constant import SESSION_EXPORT_SNAPSHOT_MAX_BYTES
        ticket = self._acquire_heavy()
        deadline = time.monotonic() + SESSION_EXPORT_REQUEST_TIMEOUT_SECONDS
        def encode(cancel: threading.Event, dl: float) -> bytes:
            chunks: list[bytes] = []
            total = 0
            encoder = json.JSONEncoder(ensure_ascii=False, allow_nan=False, separators=(",", ":"))
            for part in encoder.iterencode(snapshot.model_dump(mode="json")):
                for offset in range(0, len(part), SESSION_EXPORT_READ_CHUNK_BYTES):
                    if cancel.is_set():
                        raise SessionExportChangedError()
                    if time.monotonic() > dl:
                        raise SessionExportTimeoutError()
                    chunk = part[offset:offset + SESSION_EXPORT_READ_CHUNK_BYTES].encode("utf-8")
                    total += len(chunk)
                    if total > SESSION_EXPORT_SNAPSHOT_MAX_BYTES:
                        raise SessionExportLimitError("Export snapshot exceeds response byte budget")
                    chunks.append(chunk)
            return b"".join(chunks)
        try:
            data = await self._run_sync(encode, deadline, ticket)
            _, loop = self._confirm_session(snapshot.session_id)
            self._check_guard(loop, snapshot.stamp.loop_instance_id, snapshot.stamp.export_epoch)
            info = self._sessions.get(snapshot.session_id)
            if info is None or _canonical_metadata_digest(info) != snapshot.stamp.metadata_digest:
                raise SessionExportChangedError()
            return data
        finally:
            ticket.release()

    async def close(self) -> None:
        """Gateway 所属请求结束后释放真实线程池。"""
        task = asyncio.create_task(asyncio.to_thread(self._executor.shutdown, wait=True, cancel_futures=True))
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            while not task.done():
                try:
                    await asyncio.shield(task)
                except asyncio.CancelledError:
                    continue
            task.result()
            raise

    async def capture(self, session_id: str) -> SessionExportSnapshotResponse:
        """捕获完整主会话 History 与视觉状态，并做一致性复核。"""
        logger.info("session export capture start session=%s", session_id)
        self._require_running()
        info, loop = self._confirm_session(session_id)
        guard = loop.loop.get_session_export_guard()
        metadata_before = _canonical_metadata_digest(info)
        ticket = self._acquire_heavy()
        try:
            logger.debug("session export capture phase=source session=%s", session_id)
            source: SessionExportHistorySource = await loop.loop.capture_session_export_source()
            logger.debug(
                "session export capture source session=%s history_count=%s instance=%s epoch=%s",
                session_id, source.history_count, source.loop_instance_id, source.export_epoch,
            )
            deadline = time.monotonic() + SESSION_EXPORT_REQUEST_TIMEOUT_SECONDS

            def work(cancel: threading.Event, dl: float) -> Any:
                def check() -> None:
                    if cancel.is_set():
                        raise SessionExportChangedError()
                    if time.monotonic() > dl:
                        raise SessionExportTimeoutError()
                logger.info("session export capture phase=metrics session=%s", session_id)
                metrics, metrics_digest = self._read_metrics(session_id, cancel, dl)
                logger.info("session export capture phase=history session=%s", session_id)
                snapshot = project_export_history(source, metrics, check)
                snapshot.history_digest = _digest_text(snapshot.history_digest, metrics_digest)
                logger.info("session export capture phase=visuals session=%s", session_id)
                entries, visual_digest = self._visual_entries(session_id, cancel, dl)
                return snapshot, entries, visual_digest

            logger.debug("session export capture phase=worker session=%s", session_id)
            snapshot, entries, visual_digest = await self._run_sync(work, deadline, ticket)
            # 回主 loop 复核 guard 与轻量 metadata。
            logger.debug("session export capture phase=guard session=%s", session_id)
            self._check_guard(loop, guard[0], guard[1])
            current = self._sessions.get(session_id)
            if current is None:
                raise SessionExportChangedError()
            metadata_digest = _canonical_metadata_digest(current)
            if metadata_digest != metadata_before:
                raise SessionExportChangedError()
            stamp = SessionExportStamp(
                loop_instance_id=snapshot.loop_instance_id, export_epoch=snapshot.export_epoch,
                history_digest=snapshot.history_digest, metadata_digest=metadata_digest,
                visual_digest=visual_digest,
            )
            logger.info(
                "session export capture success session=%s history_count=%s row_count=%s visuals=%s",
                session_id, snapshot.history_count, len(snapshot.rows), len(entries),
            )
            return SessionExportSnapshotResponse(
                session_id=session_id,
                captured_at=datetime.now(timezone.utc).isoformat(),
                title=info.title, tags=list(info.tags), history_count=snapshot.history_count,
                rows=snapshot.rows, stamp=stamp, visuals=entries,
                limits=SessionExportLimits(),
            )
        except SessionExportError as error:
            logger.warning(
                "session export capture failed session=%s code=%s status=%s message=%s",
                session_id, error.code, error.status, str(error),
            )
            raise
        finally:
            ticket.release()

    async def read_resource(
        self, session_id: str, request: SessionExportResourceRequest,
    ) -> SessionExportResourceRead:
        """按 stamp 精确读取单个资源；已识别不可用返回带 proof 的结果。"""
        logger.debug("session export resource start session=%s kind=%s", session_id, request.source.kind)
        self._require_running()
        _, loop = self._confirm_session(session_id)
        stamp = request.stamp
        self._check_guard(loop, stamp.loop_instance_id, stamp.export_epoch)
        ticket = self._acquire_resource()
        try:
            deadline = time.monotonic() + SESSION_EXPORT_REQUEST_TIMEOUT_SECONDS
            result = await self._run_sync(
                lambda cancel, dl: self._read_or_unavailable(
                    request.source, cancel, dl, keep_content=True,
                ),
                deadline, ticket,
            )
            self._check_guard(loop, stamp.loop_instance_id, stamp.export_epoch)
            if loop.loop.is_active():
                raise SessionExportChangedError()
            logger.debug("session export resource success session=%s kind=%s status=%s", session_id, request.source.kind, result.status)
            return result
        except SessionExportError as error:
            logger.warning("session export resource failed session=%s kind=%s code=%s status=%s message=%s", session_id, request.source.kind, error.code, error.status, str(error))
            raise
        finally:
            ticket.release()

    async def verify(
        self, session_id: str, request: SessionExportVerifyRequest,
    ) -> SessionExportVerifyResponse:
        """复核 History/均量元数据/视觉与每项资源 proof，最后再做 guard 检查。"""
        logger.info("session export verify start session=%s resources=%s", session_id, len(request.resources))
        self._require_running()
        _info, loop = self._confirm_session(session_id)
        stamp = request.stamp
        resources = request.resources
        if len(resources) > SESSION_EXPORT_MAX_RESOURCES:
            raise SessionExportLimitError("Too many resource proofs")
        from entity.constant import SESSION_EXPORT_RESOURCE_TOTAL_MAX_BYTES
        seen: set[tuple[str, str]] = set()
        byte_keys: set[tuple[str, int]] = set()
        total_bytes = 0
        for proof in resources:
            key = (proof.source.kind, proof.source.path)
            if key in seen:
                raise SessionExportInputError("duplicate_resource", "Duplicate resource source in proof list")
            seen.add(key)
            if proof.status == "saved" and (
                proof.digest is None or proof.identity is None or proof.size is None
            ):
                raise SessionExportInputError("invalid_proof", "Saved proof is missing integrity fields")
            if proof.status == "saved":
                if proof.size > SESSION_EXPORT_RESOURCE_MAX_BYTES:
                    raise SessionExportLimitError("Resource proof exceeds single-file budget")
                byte_key = (proof.digest, proof.size)
                if byte_key not in byte_keys:
                    total_bytes += proof.size
                    byte_keys.add(byte_key)
            elif proof.digest is not None or proof.identity is not None or proof.size is not None:
                raise SessionExportInputError("invalid_proof", "Unavailable proof contains saved fields")
        if total_bytes > SESSION_EXPORT_RESOURCE_TOTAL_MAX_BYTES:
            raise SessionExportLimitError("Resource proof total byte budget exceeded")

        ticket = self._acquire_heavy()
        try:
            source = await loop.loop.capture_session_export_source()
            deadline = time.monotonic() + SESSION_EXPORT_REQUEST_TIMEOUT_SECONDS

            def work(cancel: threading.Event, dl: float) -> Any:
                def check() -> None:
                    if cancel.is_set():
                        raise SessionExportChangedError()
                    if time.monotonic() > dl:
                        raise SessionExportTimeoutError()
                logger.info("session export verify phase=metrics session=%s", session_id)
                metrics, metrics_digest = self._read_metrics(session_id, cancel, dl)
                logger.info("session export verify phase=history session=%s", session_id)
                history_digest = _digest_text(export_history_digest(source, metrics, check), metrics_digest)
                logger.info("session export verify phase=visuals session=%s", session_id)
                entries, visual_digest = self._visual_entries(session_id, cancel, dl)
                for proof in resources:
                    check()
                    read = self._read_or_unavailable(
                        proof.source, cancel, dl, keep_content=True,
                    )
                    if read.status != proof.status:
                        raise SessionExportChangedError()
                    if read.status == "saved" and (
                        read.proof.digest != proof.digest
                        or read.proof.identity != proof.identity
                        or read.proof.size != proof.size
                    ):
                        raise SessionExportChangedError()
                return history_digest, visual_digest

            history_digest, visual_digest = await self._run_sync(work, deadline, ticket)
            if history_digest != stamp.history_digest:
                raise SessionExportChangedError()
            if visual_digest != stamp.visual_digest:
                raise SessionExportChangedError()
            self._check_guard(loop, stamp.loop_instance_id, stamp.export_epoch)
            current = self._sessions.get(session_id)
            if current is None or _canonical_metadata_digest(current) != stamp.metadata_digest:
                raise SessionExportChangedError()
            if loop.loop.is_active():
                raise SessionExportChangedError()
            logger.info("session export verify success session=%s resources=%s", session_id, len(resources))
            return SessionExportVerifyResponse(
                session_id=session_id,
                verified_at=datetime.now(timezone.utc).isoformat(),
            )
        except SessionExportError as error:
            logger.warning("session export verify failed session=%s code=%s status=%s message=%s", session_id, error.code, error.status, str(error))
            raise
        finally:
            ticket.release()
