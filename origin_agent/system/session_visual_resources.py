"""会话视觉资源的单层解析；配置只在源目录读取，快照不持久化。"""

from __future__ import annotations

import hashlib
import json
import os
import stat
import time
from pathlib import Path
from urllib.parse import quote, urlencode

from entity.constant import (
    META_FILE_SUFFIX, SESSIONS_DIR_NAME, SESSION_VISUAL_LAYOUT,
    STATIC_FILE_HTTP_PREFIX, VISUAL_REDIRECT_KEY, VISUAL_RAW_PARAM,
    VISUAL_PROBE_PARAM, VISUAL_SID_PARAM, VISUAL_KIND_PARAM,
    VISUAL_QUERY_ENABLED, VISUAL_SCAN_BUDGET_SECONDS, VISUAL_SCAN_MAX_ENTRIES,
)
from entity.puretype import (
    SessionVisualKind, SessionVisualResourceState, SessionVisualResources,
    SessionVisualSource, SessionVisualStatus,
)
from system.file_metadata import MetaFormatError, parse_meta_content
from system.sandbox import ResolvedPath, Sandbox, SandboxError


class SessionVisualResourceError(ValueError):
    """安全的入口错误，不包含物理路径。"""


class SessionVisualVersionUnavailable(SessionVisualResourceError):
    """签名预算耗尽或资源在扫描中失效；不能返回部分签名。"""


class SessionVisualResourceService:
    """由 Application 持有，无会话缓存、额外 watcher 或持久化副作用。"""

    def __init__(self, sandbox: Sandbox) -> None:
        self._sandbox = sandbox

    @staticmethod
    def _valid_session_id(session_id: str) -> bool:
        return bool(
            isinstance(session_id, str) and session_id
            and session_id not in (".", "..")
            and not any(char in session_id for char in ":/\\\x00\r\n")
        )

    @staticmethod
    def _normalize(logical: str) -> str:
        """只消除等价路径段，不消除非法遍历或绝对路径。"""
        if not isinstance(logical, str) or ":" not in logical:
            raise SessionVisualResourceError("目标必须是带命名空间的逻辑路径")
        namespace, relative = logical.split(":", 1)
        if not namespace or namespace != namespace.strip():
            raise SessionVisualResourceError("命名空间格式无效")
        if any(char in logical for char in "\x00\r\n") or ":" in relative:
            raise SessionVisualResourceError("逻辑路径包含非法字符")
        if relative.startswith(("/", "\\")):
            raise SessionVisualResourceError("目标不能是绝对路径")
        parts = relative.replace("\\", "/").split("/")
        if ".." in parts:
            raise SessionVisualResourceError("目标不能包含父目录遍历")
        return namespace + ":" + "/".join(part for part in parts if part not in ("", "."))

    @staticmethod
    def _join(directory: str, name: str) -> str:
        return directory + ("" if directory.endswith(":") else "/") + name

    def source_path(self, session_id: str, kind: SessionVisualKind) -> str:
        if not self._valid_session_id(session_id):
            raise SessionVisualResourceError("会话标识无效")
        return f"ws:{SESSIONS_DIR_NAME}/{session_id}/{SESSION_VISUAL_LAYOUT[kind.value][0]}"

    def metadata_path(self, session_id: str, kind: SessionVisualKind) -> str:
        return self.source_path(session_id, kind) + META_FILE_SUFFIX

    def entry_name(self, kind: SessionVisualKind) -> str:
        return SESSION_VISUAL_LAYOUT[kind.value][1]

    def match_source_directory(self, logical_path: str) -> SessionVisualSource | None:
        try:
            logical = self._normalize(logical_path)
        except SessionVisualResourceError:
            return None
        if not logical.startswith("ws:"):
            return None
        parts = logical[3:].split("/")
        if len(parts) != 3 or parts[0] != SESSIONS_DIR_NAME or not self._valid_session_id(parts[1]):
            return None
        for kind in SessionVisualKind:
            if parts[2] == SESSION_VISUAL_LAYOUT[kind.value][0]:
                return SessionVisualSource(session_id=parts[1], kind=kind)
        return None

    def _read_metadata(self, session_id: str, kind: SessionVisualKind) -> tuple[dict[str, str] | None, str | None]:
        logical = self.metadata_path(session_id, kind)
        try:
            resolved = self._sandbox.resolve_read(logical)
            try:
                info = resolved.real.stat()
            except FileNotFoundError:
                return None, None
            if not stat.S_ISREG(info.st_mode):
                return None, "元数据路径不是普通文件"
            return parse_meta_content(self._sandbox.read(logical, limit=0)), None
        except MetaFormatError as exc:
            return None, f"元数据格式错误（第 {exc.line_number} 行）"
        except (SandboxError, OSError, ValueError):
            return None, "元数据无法读取或未通过沙盒校验"

    def _check_entry(self, directory: str, entry: str) -> ResolvedPath:
        root = self._sandbox.resolve_read(directory)
        if not root.real.is_dir():
            raise SessionVisualResourceError("目标目录不存在或不是目录")
        resolved = self._sandbox.resolve_read(self._join(directory, entry))
        if not resolved.real.is_file():
            raise SessionVisualResourceError("目标入口不存在或不是文件")
        # 实际打开确认读权限，不把仅 stat 成功视为资源 ready。
        with resolved.real.open("rb"):
            pass
        return resolved

    def resolve_from_metadata(
        self, session_id: str, kind: SessionVisualKind,
        metadata: dict[str, str] | None, *, metadata_error: str | None = None,
    ) -> SessionVisualResourceState:
        source = self.source_path(session_id, kind)
        entry = self.entry_name(kind)
        effective = source
        error = metadata_error
        if error is None and metadata is not None and VISUAL_REDIRECT_KEY in metadata:
            try:
                value = metadata[VISUAL_REDIRECT_KEY].strip()
                if not value:
                    raise SessionVisualResourceError("redirect 不能为空")
                target = self._normalize(value)
                self._check_entry(target, entry)
                effective = target
            except SessionVisualResourceError as exc:
                error = str(exc)
            except (SandboxError, OSError, ValueError):
                error = "重定向目标无法读取或未通过沙盒校验"
        try:
            self._check_entry(effective, entry)
            ready = True
        except (SandboxError, OSError, ValueError):
            if effective != source:
                error = "重定向入口在解析期间失效"
                effective = source
                try:
                    self._check_entry(source, entry)
                    ready = True
                except (SandboxError, OSError, ValueError):
                    ready = False
            else:
                ready = False
        state = SessionVisualResourceState(
            kind=kind,
            status=SessionVisualStatus.ready if ready else SessionVisualStatus.missing,
            source_path=source, effective_path=effective,
            redirected=effective != source, redirect_error=error, entry_name=entry,
        )
        if ready:
            state.entry_url = self.build_entry_url(state)
        return state

    def get_state(self, session_id: str, kind: SessionVisualKind) -> SessionVisualResourceState:
        metadata, error = self._read_metadata(session_id, kind)
        return self.resolve_from_metadata(session_id, kind, metadata, metadata_error=error)

    def get_all_states(self, session_id: str) -> SessionVisualResources:
        return SessionVisualResources(
            stage=self.get_state(session_id, SessionVisualKind.stage),
            site=self.get_state(session_id, SessionVisualKind.site),
            chat_style=self.get_state(session_id, SessionVisualKind.chat_style),
        )

    def build_entry_logical_path(self, state: SessionVisualResourceState) -> str:
        return self._join(state.effective_path, state.entry_name)

    def build_entry_url(self, state: SessionVisualResourceState, *, source: SessionVisualSource | None = None) -> str:
        namespace, relative = self.build_entry_logical_path(state).split(":", 1)
        path = "/".join(quote(part, safe="") for part in relative.split("/"))
        query = {VISUAL_RAW_PARAM: VISUAL_QUERY_ENABLED}
        if source is not None:
            query.update({
                VISUAL_PROBE_PARAM: VISUAL_QUERY_ENABLED,
                VISUAL_SID_PARAM: source.session_id,
                VISUAL_KIND_PARAM: source.kind.value,
            })
        return f"{STATIC_FILE_HTTP_PREFIX}/{quote(namespace, safe='')}/{path}?{urlencode(query)}"

    def resolve_entry(self, session_id: str, kind: SessionVisualKind) -> tuple[SessionVisualResourceState, ResolvedPath]:
        state = self.get_state(session_id, kind)
        if state.status != SessionVisualStatus.ready:
            raise SessionVisualResourceError("视觉入口不存在")
        return state, self._check_entry(state.effective_path, state.entry_name)

    def get_version(self, state: SessionVisualResourceState) -> str:
        """stage 只看入口；site/style 看目录整体。由调用方放在线程池执行。"""
        try:
            entry = self._check_entry(state.effective_path, state.entry_name)
            digest = hashlib.sha256(self.build_entry_logical_path(state).encode("utf-8"))
            # 同命名空间重新映射到其他目录也必须刷新，不把物理身份暴露给客户端。
            digest.update(str(entry.real).encode("utf-8"))
            if state.kind == SessionVisualKind.stage:
                with entry.real.open("rb") as stream:
                    for block in iter(lambda: stream.read(65536), b""):
                        digest.update(block)
                return digest.hexdigest()
            root = self._sandbox.resolve_read(state.effective_path).real
            started = time.monotonic()
            count = 0
            items: list[tuple[str, int, int, int]] = []
            pending = [root]
            while pending:
                directory = pending.pop()
                with os.scandir(directory) as entries:
                    for item in entries:
                        count += 1
                        if count > VISUAL_SCAN_MAX_ENTRIES or time.monotonic() - started > VISUAL_SCAN_BUDGET_SECONDS:
                            raise SessionVisualVersionUnavailable("目录签名扫描超出预算")
                        info = item.stat(follow_symlinks=False)
                        # Windows junction 与其他 reparse point 均不能递归跟随。
                        if item.is_symlink() or getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
                            continue
                        path = Path(item.path)
                        relative = path.relative_to(root).as_posix()
                        self._sandbox.resolve_read(self._join(state.effective_path, relative))
                        if stat.S_ISDIR(info.st_mode):
                            pending.append(path)
                        elif stat.S_ISREG(info.st_mode):
                            items.append((relative, info.st_size, info.st_mtime_ns, info.st_ctime_ns))
            if time.monotonic() - started > VISUAL_SCAN_BUDGET_SECONDS:
                raise SessionVisualVersionUnavailable("目录签名扫描超出预算")
            digest.update(json.dumps(sorted(items), ensure_ascii=False).encode("utf-8"))
            return digest.hexdigest()
        except (SandboxError, OSError, ValueError) as exc:
            raise SessionVisualVersionUnavailable("视觉资源签名暂不可用") from exc
