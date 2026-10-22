"""会话变量池：共享只读解析和受预算约束的独立继承。"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager, nullcontext
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
import time
from typing import ContextManager, Literal

from pydantic import BaseModel, ConfigDict

from entity.constant import META_FILE_SUFFIX, Namespace, SESSIONS_DIR_NAME
from entity.constant import session_variables as constants
from entity.puretype import (
    SessionVariableDirectoryIdentity, SessionVariableEntry,
    SessionVariableFileIdentity, SessionVariableInheritanceData,
    SessionVariableIssue, SessionVariableMetadata, SessionVariablePoolResponse,
    SessionVariableSnapshotNode, SessionVariableSourceSnapshot,
)
from util.file_metadata import MetaFormatError, parse_meta_content
from system.lifecycle import LifecycleFailure
from interface.sandbox import ISandbox
from system.sandbox import SandboxError


class SessionVariableError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        code: str,
        logical_path: str = ""
        ) -> None:
        super().__init__(message)
        self.code = code
        self.logical_path = logical_path


class SessionVariableInputError(SessionVariableError):
    pass


class SessionVariableAccessError(SessionVariableError):
    pass


class SessionVariableLimitError(SessionVariableError):
    def __init__(
        self,
        message: str,
        *,
        logical_path: str = ""
        ) -> None:
        super().__init__(message, code="pool_limit_exceeded", logical_path=logical_path)


class SessionVariableConflictError(SessionVariableError):
    def __init__(
        self,
        message: str,
        *,
        logical_path: str = ""
        ) -> None:
        super().__init__(message, code="pool_conflict", logical_path=logical_path)


class SessionVariableCleanupFailure(LifecycleFailure):
    pass


class SessionVariableScanBudget(BaseModel):
    """单次操作的软截止与不同职责的字节额度，不持久化。"""

    model_config = ConfigDict(extra="forbid")
    deadline: float
    read_bytes: int = 0
    logical_bytes: int = 0
    verification_bytes: int = 0

    def check_time(self) -> None:
        if time.monotonic() > self.deadline:
            raise SessionVariableLimitError(
                f"Scan exceeded {constants.SESSION_VARIABLE_SCAN_BUDGET_SECONDS} seconds; reduce the pool size."
            )

    def consume_read(
        self,
        size: int,
        *,
        verification: bool
        ) -> None:
        if size < 0:
            raise ValueError("Read size cannot be negative")
        self.read_bytes += size
        if verification:
            self.verification_bytes += size
        if self.read_bytes > constants.SESSION_VARIABLE_OPERATION_READ_MAX_BYTES:
            raise SessionVariableLimitError(f"Operation read budget exceeded: {constants.SESSION_VARIABLE_OPERATION_READ_MAX_BYTES} bytes")
        if self.verification_bytes > constants.SESSION_VARIABLE_VERIFICATION_MAX_BYTES:
            raise SessionVariableLimitError(f"Verification budget exceeded: {constants.SESSION_VARIABLE_VERIFICATION_MAX_BYTES} bytes")
        self.check_time()

    def consume_logical(self, size: int) -> None:
        if size < 0:
            raise ValueError("Logical size cannot be negative")
        self.logical_bytes += size
        if self.logical_bytes > constants.SESSION_VARIABLE_TOTAL_MAX_BYTES:
            raise SessionVariableLimitError(f"Pool content budget exceeded: {constants.SESSION_VARIABLE_TOTAL_MAX_BYTES} bytes")
        self.check_time()


def _issue(
    path: str,
    code: str,
    *,
    kind: Literal["value", "metadata", "constraint", "path"] = "value",
    key: str | None = None
    ) -> SessionVariableIssue:
    return SessionVariableIssue(
        path=path, kind=kind, code=code,
        message=constants.SESSION_VARIABLE_ISSUE_MESSAGES[code], key=key,
    )


def _natural_key(path: str) -> tuple[tuple[int, str | int], ...]:
    return tuple((1, int(part)) if part.isdecimal() else (0, part.casefold())
                 for part in re.split(r"(\d+)", path))


def _is_link(info: os.stat_result) -> bool:
    if stat.S_ISLNK(info.st_mode):
        return True
    if os.name == "nt":
        return bool(info.st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT)
    return False


def _file_identity(info: os.stat_result) -> SessionVariableFileIdentity:
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns


def _new_budget() -> SessionVariableScanBudget:
    return SessionVariableScanBudget(
        deadline=time.monotonic() + constants.SESSION_VARIABLE_SCAN_BUDGET_SECONDS
    )


class SessionVariableService:
    """由 AgentspaceService 持有的无缓存叶服务；不创建后台工作。"""

    def __init__(self, sandbox: ISandbox) -> None:
        self._sandbox = sandbox

    def source_path(self, session_id: str) -> str:
        if (not session_id
                or session_id in (".", "..")
                or any(char in session_id for char in ":/\\\x00\r\n")):
            raise SessionVariableInputError("Invalid session ID", code="invalid_session_id")
        return f"{Namespace.WS.value}:{SESSIONS_DIR_NAME}/{session_id}/{constants.SESSION_VARIABLES_DIR_NAME}"

    def _checked_path(
        self,
        logical: str,
        *,
        write: bool = False
        ) -> Path:
        try:
            if write:
                self._sandbox.resolve_write(logical)
            else:
                self._sandbox.resolve_read(logical)
        except SandboxError as exc:
            raise SessionVariableInputError(
                "Path did not pass sandbox checks", code="unsafe_path", logical_path=logical
            ) from exc
        base = self._sandbox.get_base(Namespace.WS)
        prefix = Namespace.WS.value + ":"
        if not logical.startswith(prefix):
            raise SessionVariableInputError("Expected a workspace path", code="unsafe_path", logical_path=logical)
        parts = logical[len(prefix):].split("/")
        if any(part in ("", ".", "..") for part in parts):
            raise SessionVariableInputError("Invalid path segment", code="unsafe_path", logical_path=logical)
        current = base
        for index, part in enumerate(parts):
            current = current / part
            try:
                info = current.lstat()
            except FileNotFoundError:
                continue
            if index < len(parts) - 1 and not stat.S_ISDIR(info.st_mode):
                raise SessionVariableInputError("Ancestor is not a directory", code="invalid_root", logical_path=logical)
            if _is_link(info):
                raise SessionVariableInputError("Links and reparse points are not supported", code="unsafe_path", logical_path=logical)
            try:
                current.resolve(strict=False).relative_to(base.resolve())
            except ValueError as exc:
                raise SessionVariableInputError("Path escapes workspace", code="unsafe_path", logical_path=logical) from exc
        return current

    @staticmethod
    def _check_tree_limits(nodes: Sequence[SessionVariableSnapshotNode]) -> None:
        if len(nodes) > constants.SESSION_VARIABLE_MAX_NODES:
            raise SessionVariableLimitError(f"Node count exceeds {constants.SESSION_VARIABLE_MAX_NODES}")
        count = 0
        for node in nodes:
            depth = len(node.relative_path.split("/")) - (0 if node.is_directory else 1)
            if depth > constants.SESSION_VARIABLE_MAX_DEPTH:
                raise SessionVariableLimitError(f"Directory depth exceeds {constants.SESSION_VARIABLE_MAX_DEPTH}")
            if not node.is_directory and node.relative_path.lower().endswith(constants.SESSION_VARIABLE_VALUE_SUFFIX):
                count += 1
        if count > constants.SESSION_VARIABLE_MAX_COUNT:
            raise SessionVariableLimitError(f"Variable count exceeds {constants.SESSION_VARIABLE_MAX_COUNT}")

    @staticmethod
    def _version(
        root_exists: bool,
        nodes: Sequence[SessionVariableSnapshotNode],
        issues: Sequence[SessionVariableIssue] = (),
        *,
        scan_complete: bool = True
        ) -> str:
        digest = hashlib.sha256(b"present" if root_exists else b"missing")
        digest.update(json.dumps([scan_complete, [(issue.path, issue.code) for issue in issues]],
                                 ensure_ascii=False).encode("utf-8"))
        for node in sorted(nodes, key=lambda item: item.relative_path):
            header = json.dumps([node.relative_path, node.is_directory,
                                 [issue.code for issue in node.issues]], ensure_ascii=False).encode("utf-8")
            digest.update(len(header).to_bytes(8, "big"))
            digest.update(header)
            digest.update(hashlib.sha256(node.content).digest() if node.content is not None else b"unavailable")
        return digest.hexdigest()

    def _read_node(
        self,
        source: str,
        relative: str,
        budget: SessionVariableScanBudget,
        *,
        verification: bool,
        register_access: Callable[[str], ContextManager[None]] | None
        ) -> SessionVariableSnapshotNode:
        logical = source + "/" + relative
        node = SessionVariableSnapshotNode(relative_path=relative, is_directory=False)
        try:
            with register_access(logical) if register_access is not None else nullcontext():
                real = self._checked_path(logical)
                before = real.lstat()
                if _is_link(before) or not stat.S_ISREG(before.st_mode):
                    node.issues.append(_issue(logical, "unsafe_path", kind="path"))
                    return node
                if before.st_size > constants.SESSION_VARIABLE_FILE_MAX_BYTES:
                    node.issues.append(_issue(logical, "file_too_large"))
                    return node
                with real.open("rb") as stream:
                    opened = os.fstat(stream.fileno())
                    if _file_identity(before) != _file_identity(opened):
                        node.issues.append(_issue(logical, "file_changed"))
                        return node
                    raw = stream.read(constants.SESSION_VARIABLE_FILE_MAX_BYTES + 1)
                    budget.consume_read(len(raw), verification=verification)
                    after_fd = os.fstat(stream.fileno())
                after = self._checked_path(logical).lstat()
                if (_file_identity(before) != _file_identity(after_fd)
                        or _file_identity(before) != _file_identity(after)
                        or len(raw) != before.st_size):
                    node.issues.append(_issue(logical, "file_changed"))
                elif len(raw) > constants.SESSION_VARIABLE_FILE_MAX_BYTES:
                    node.issues.append(_issue(logical, "file_too_large"))
                else:
                    if not verification:
                        budget.consume_logical(len(raw))
                    node.content = raw
                    node.identity = _file_identity(after)
        except FileNotFoundError:
            node.issues.append(_issue(logical, "file_changed"))
        except PermissionError:
            node.issues.append(_issue(logical, "value_read_error"))
        except SessionVariableInputError:
            node.issues.append(_issue(logical, "unsafe_path", kind="path"))
        return node

    def _scan_tree(
        self,
        session_id: str,
        *,
        strict_paths: bool,
        budget: SessionVariableScanBudget,
        verification: bool = False,
        register_access: Callable[[str], ContextManager[None]] | None = None
        ) -> SessionVariableSourceSnapshot:
        budget.check_time()
        source = self.source_path(session_id)
        try:
            root = self._checked_path(source)
            info = root.lstat()
        except FileNotFoundError:
            return SessionVariableSourceSnapshot(session_id=session_id, root_exists=False,
                                                 version=self._version(False, []))
        except PermissionError as exc:
            raise SessionVariableAccessError("Cannot access variable root", code="access_denied", logical_path=source) from exc
        if not stat.S_ISDIR(info.st_mode):
            raise SessionVariableInputError("Variable root is not a directory", code="invalid_root", logical_path=source)
        nodes: list[SessionVariableSnapshotNode] = []
        issues: list[SessionVariableIssue] = []
        complete = True
        variable_count = 0
        pending = [""]
        while pending:
            budget.check_time()
            relative_dir = pending.pop()
            logical_dir = source + ("/" + relative_dir if relative_dir else "")
            try:
                directory = self._checked_path(logical_dir)
                children: list[str] = []
                with os.scandir(directory) as entries:
                    for child in entries:
                        budget.check_time()
                        children.append(child.name)
                        if len(nodes) + len(children) > constants.SESSION_VARIABLE_MAX_NODES:
                            raise SessionVariableLimitError(f"Node count exceeds {constants.SESSION_VARIABLE_MAX_NODES}", logical_path=source)
            except PermissionError as exc:
                raise SessionVariableAccessError("Cannot list variable directory", code="access_denied", logical_path=logical_dir) from exc
            except FileNotFoundError as exc:
                raise SessionVariableConflictError("Directory changed during scan", logical_path=logical_dir) from exc
            except SessionVariableInputError:
                if strict_paths or not relative_dir:
                    raise
                complete = False
                issues.append(_issue(logical_dir, "unsafe_path", kind="path"))
                continue
            for name in sorted(children, key=_natural_key):
                relative = relative_dir + "/" + name if relative_dir else name
                logical = source + "/" + relative
                try:
                    child_info = (directory / name).lstat()
                except FileNotFoundError:
                    node = SessionVariableSnapshotNode(relative_path=relative, is_directory=False,
                                                       issues=[_issue(logical, "file_changed")])
                else:
                    if _is_link(child_info) or not (stat.S_ISDIR(child_info.st_mode) or stat.S_ISREG(child_info.st_mode)):
                        node = SessionVariableSnapshotNode(relative_path=relative, is_directory=stat.S_ISDIR(child_info.st_mode),
                                                           issues=[_issue(logical, "unsafe_path", kind="path")])
                        complete = False
                    elif stat.S_ISDIR(child_info.st_mode):
                        node = SessionVariableSnapshotNode(relative_path=relative, is_directory=True)
                        pending.append(relative)
                    else:
                        node = self._read_node(source, relative, budget, verification=verification, register_access=register_access)
                if strict_paths and node.issues:
                    first = node.issues[0]
                    if first.code == "file_too_large":
                        raise SessionVariableLimitError(f"Cannot copy complete file: limit {constants.SESSION_VARIABLE_FILE_MAX_BYTES} bytes", logical_path=logical)
                    raise SessionVariableConflictError(f"Cannot copy complete pool ({first.code}); repair or move the affected file", logical_path=logical)
                nodes.append(node)
                self._check_tree_limits([node])
                if not node.is_directory and relative.lower().endswith(constants.SESSION_VARIABLE_VALUE_SUFFIX):
                    variable_count += 1
                    if variable_count > constants.SESSION_VARIABLE_MAX_COUNT:
                        raise SessionVariableLimitError(f"Variable count exceeds {constants.SESSION_VARIABLE_MAX_COUNT}", logical_path=source)
        budget.check_time()
        return SessionVariableSourceSnapshot(session_id=session_id, root_exists=True,
                                             version=self._version(True, nodes, issues, scan_complete=complete), nodes=nodes,
                                             issues=issues, scan_complete=complete)

    @staticmethod
    def _strip_trailing_newline(value: str) -> str:
        """仅去除键值与下一键标记之间的分隔换行（LF/CRLF），保留值内部换行。"""
        if value.endswith("\r\n"):
            return value[:-2]
        if value.endswith("\n") or value.endswith("\r"):
            return value[:-1]
        return value

    @staticmethod
    def _json_integer(text: str) -> int:
        # 拒绝过长整数字面量，避免 Python 大整数转换限制和浏览器精度丢失。
        if len(text.lstrip("-")) > len(str(constants.SESSION_VARIABLE_SAFE_NUMBER_MAX)):
            raise SessionVariableInputError("Unsafe number", code="unsafe_number")
        return int(text)

    @staticmethod
    def _json_constant(text: str) -> None:
        raise SessionVariableInputError("Non-finite number", code="non_finite_number")

    @classmethod
    def _decode_json(cls, text: str) -> object:
        return json.loads(text, parse_int=cls._json_integer, parse_constant=cls._json_constant)

    @staticmethod
    def _valid_number(value: object) -> bool:
        return (isinstance(value, (int, float)) and not isinstance(value, bool)
                and math.isfinite(value) and abs(value) <= constants.SESSION_VARIABLE_SAFE_NUMBER_MAX)

    def _parse_metadata(
        self,
        raw_metadata: dict[str, str] | None,
        *,
        kind: Literal["number", "string", "invalid"],
        metadata_path: str
        ) -> tuple[SessionVariableMetadata, list[SessionVariableIssue]]:
        raw = raw_metadata or {}
        issues: list[SessionVariableIssue] = []
        label = raw.get(constants.SESSION_VARIABLE_META_LABEL, "").strip()
        description = raw.get(constants.SESSION_VARIABLE_META_DESCRIPTION, "").strip()
        for key, text, limit in (
            (constants.SESSION_VARIABLE_META_LABEL, label, constants.SESSION_VARIABLE_LABEL_MAX_CHARS),
            (constants.SESSION_VARIABLE_META_DESCRIPTION, description, constants.SESSION_VARIABLE_DESCRIPTION_MAX_CHARS),
        ):
            if len(text) > limit:
                issues.append(_issue(metadata_path, "metadata_too_long", kind="metadata", key=key))
        if len(label) > constants.SESSION_VARIABLE_LABEL_MAX_CHARS:
            label = ""
        if len(description) > constants.SESSION_VARIABLE_DESCRIPTION_MAX_CHARS:
            description = ""
        minimum: int | float | None = None
        maximum: int | float | None = None
        integer = False
        percent = False
        display: Literal["auto", "number", "bar", "gauge"] = constants.SESSION_VARIABLE_DISPLAY_AUTO
        if kind == "string":
            for key in sorted(constants.SESSION_VARIABLE_NUMERIC_META_KEYS & raw.keys()):
                issues.append(_issue(metadata_path, "metadata_not_applicable", kind="metadata", key=key))
        else:
            def bound(key: str) -> int | float | None:
                if key not in raw:
                    return None
                try:
                    number = self._decode_json(raw[key].strip())
                except (json.JSONDecodeError, RecursionError, SessionVariableInputError):
                    issues.append(_issue(metadata_path, "invalid_number", kind="metadata", key=key))
                    return None
                if not self._valid_number(number):
                    issues.append(_issue(metadata_path, "invalid_number", kind="metadata", key=key))
                    return None
                if isinstance(number, (int, float)):
                    return number
                raise TypeError("Validated numeric metadata is not numeric")

            def flag(key: str) -> bool:
                if key not in raw:
                    return False
                text = raw[key].strip()
                if text not in ("true", "false"):
                    issues.append(_issue(metadata_path, "invalid_boolean", kind="metadata", key=key))
                    return False
                return text == "true"

            minimum = bound(constants.SESSION_VARIABLE_META_MIN)
            maximum = bound(constants.SESSION_VARIABLE_META_MAX)
            integer = flag(constants.SESSION_VARIABLE_META_INTEGER)
            percent = flag(constants.SESSION_VARIABLE_META_PERCENT)
            requested = raw.get(constants.SESSION_VARIABLE_META_DISPLAY, constants.SESSION_VARIABLE_DISPLAY_AUTO).strip()
            if requested == constants.SESSION_VARIABLE_DISPLAY_NUMBER:
                display = constants.SESSION_VARIABLE_DISPLAY_NUMBER
            elif requested == constants.SESSION_VARIABLE_DISPLAY_BAR:
                display = constants.SESSION_VARIABLE_DISPLAY_BAR
            elif requested == constants.SESSION_VARIABLE_DISPLAY_GAUGE:
                display = constants.SESSION_VARIABLE_DISPLAY_GAUGE
            elif requested != constants.SESSION_VARIABLE_DISPLAY_AUTO:
                issues.append(_issue(metadata_path, "invalid_display", kind="metadata", key=constants.SESSION_VARIABLE_META_DISPLAY))
            if minimum is not None and maximum is not None and minimum > maximum:
                issues.append(_issue(metadata_path, "invalid_range", kind="metadata"))
        return SessionVariableMetadata(label=label, description=description, min=minimum,
                                       max=maximum, integer=integer, percent=percent, display=display), issues

    def _parse_entry(
        self,
        relative_path: str,
        value_content: bytes | None,
        metadata_content: bytes | None,
        source_path: str,
        file_issues: list[SessionVariableIssue]
        ) -> SessionVariableEntry:
        path = source_path + "/" + relative_path
        metadata_path = path + META_FILE_SUFFIX
        issues = list(file_issues)
        raw_value: str | None = None
        raw_metadata: dict[str, str] | None = None
        kind: Literal["number", "string", "invalid"] = "invalid"
        value: int | float | str | None = None
        if value_content is not None:
            try:
                raw_value = value_content.decode("utf-8")
            except UnicodeDecodeError:
                issues.append(_issue(path, "invalid_utf8"))
            else:
                try:
                    decoded = self._decode_json(raw_value.removeprefix("\ufeff"))
                except (json.JSONDecodeError, RecursionError):
                    # JSON 输入超过解析器嵌套能力属于已知条目输入错误。
                    issues.append(_issue(path, "invalid_json"))
                except SessionVariableInputError as exc:
                    issues.append(_issue(path, exc.code))
                else:
                    if isinstance(decoded, str):
                        try:
                            decoded.encode("utf-8")
                        except UnicodeEncodeError:
                            issues.append(_issue(path, "invalid_utf8"))
                        else:
                            kind, value = "string", decoded
                    elif isinstance(decoded, (int, float)) and not isinstance(decoded, bool):
                        if not math.isfinite(decoded):
                            issues.append(_issue(path, "non_finite_number"))
                        elif not self._valid_number(decoded):
                            issues.append(_issue(path, "unsafe_number"))
                        else:
                            kind, value = "number", decoded
                    else:
                        issues.append(_issue(path, "unsupported_value"))
        if metadata_content is not None:
            try:
                raw_metadata = {
                    key: self._strip_trailing_newline(value)
                    for key, value in parse_meta_content(metadata_content.decode("utf-8")).items()
                }
            except UnicodeDecodeError:
                issues.append(_issue(metadata_path, "invalid_utf8", kind="metadata"))
            except MetaFormatError:
                issues.append(_issue(metadata_path, "invalid_meta", kind="metadata"))
        metadata, meta_issues = self._parse_metadata(raw_metadata, kind=kind, metadata_path=metadata_path)
        if not metadata.label:
            metadata.label = Path(relative_path).name[:-len(constants.SESSION_VARIABLE_VALUE_SUFFIX)]
        issues.extend(meta_issues)
        if kind == "number" and isinstance(value, (int, float)):
            if metadata.integer and isinstance(value, float) and not value.is_integer():
                issues.append(_issue(path, "not_integer", kind="constraint"))
            valid_range = metadata.min is None or metadata.max is None or metadata.min <= metadata.max
            if valid_range:
                if metadata.min is not None and value < metadata.min:
                    issues.append(_issue(path, "below_min", kind="constraint"))
                if metadata.max is not None and value > metadata.max:
                    issues.append(_issue(path, "above_max", kind="constraint"))
        return SessionVariableEntry(id=relative_path, path=path, metadata_path=metadata_path,
                                    group=relative_path.rpartition("/")[0], kind=kind, value=value,
                                    raw_value=raw_value, raw_metadata=raw_metadata,
                                    metadata=metadata, issues=issues)

    def has_visible_content(self, session_id: str) -> bool:
        """Check whether the variable Tab has any content or visible issue."""
        source = self.source_path(session_id)
        budget = _new_budget()
        try:
            snapshot = self._scan_tree(session_id, strict_paths=False, budget=budget)
        except SessionVariableError as exc:
            if not exc.logical_path:
                exc.logical_path = source
            raise
        if not snapshot.root_exists:
            return False
        if snapshot.issues or not snapshot.scan_complete:
            return True
        for node in snapshot.nodes:
            relative = node.relative_path
            if node.issues:
                return True
            if node.is_directory:
                continue
            lowered = relative.lower()
            if lowered.endswith(constants.SESSION_VARIABLE_VALUE_SUFFIX):
                return True
            if lowered.endswith(constants.SESSION_VARIABLE_VALUE_SUFFIX + META_FILE_SUFFIX):
                return True
        return False

    def read_pool(
        self,
        session_id: str,
        *,
        register_access: Callable[[str], ContextManager[None]] | None = None
        ) -> SessionVariablePoolResponse:
        source = self.source_path(session_id)
        budget = _new_budget()
        try:
            snapshot = self._scan_tree(session_id, strict_paths=False, budget=budget,
                                       register_access=register_access)
        except SessionVariableError as exc:
            if not exc.logical_path:
                exc.logical_path = source
            raise
        index = {node.relative_path: node for node in snapshot.nodes}
        variables: list[SessionVariableEntry] = []
        issues = list(snapshot.issues)
        claimed: set[str] = set()
        for relative, node in sorted(index.items(), key=lambda pair: (_natural_key(pair[0]), pair[0])):
            if node.is_directory or not relative.lower().endswith(constants.SESSION_VARIABLE_VALUE_SUFFIX):
                continue
            metadata_name = relative + META_FILE_SUFFIX
            meta_node = index.get(metadata_name)
            file_issues = list(node.issues)
            metadata_content = None
            if meta_node is not None:
                claimed.add(metadata_name)
                if meta_node.is_directory:
                    file_issues.append(_issue(source + "/" + metadata_name, "invalid_meta", kind="metadata"))
                else:
                    metadata_content = meta_node.content
                    file_issues.extend(issue.model_copy(update={"kind": "metadata"}) for issue in meta_node.issues)
            variables.append(self._parse_entry(relative, node.content, metadata_content, source, file_issues))
            claimed.add(relative)
        for relative, node in index.items():
            if relative not in claimed:
                issues.extend(node.issues)
                if not node.is_directory and relative.lower().endswith(constants.SESSION_VARIABLE_VALUE_SUFFIX + META_FILE_SUFFIX):
                    issues.append(_issue(source + "/" + relative, "orphan_metadata", kind="metadata"))
        result = SessionVariablePoolResponse(session_id=session_id, directory_path=source,
                                             root_exists=snapshot.root_exists, scan_complete=snapshot.scan_complete,
                                             version=snapshot.version, variables=variables,
                                             issues=sorted(issues, key=lambda issue: (issue.path, issue.code)))
        if len(result.model_dump_json().encode("utf-8")) > constants.SESSION_VARIABLE_RESPONSE_MAX_BYTES:
            raise SessionVariableLimitError(f"Encoded pool response exceeds {constants.SESSION_VARIABLE_RESPONSE_MAX_BYTES} bytes", logical_path=source)
        try:
            budget.check_time()
        except SessionVariableLimitError as exc:
            exc.logical_path = source
            raise
        return result

    def capture_inheritance(self, source_ids: Sequence[str]) -> SessionVariableInheritanceData:
        if not source_ids or len(set(source_ids)) != len(source_ids):
            raise SessionVariableInputError("Sources must be nonempty and unique", code="invalid_sources")
        budget = _new_budget()
        sources = [self._scan_tree(sid, strict_paths=True, budget=budget) for sid in source_ids]
        for source in sources:
            verified = self._scan_tree(source.session_id, strict_paths=True, budget=budget, verification=True)
            if verified.root_exists != source.root_exists or verified.version != source.version:
                raise SessionVariableConflictError("Source changed during capture; retry after completing writes",
                                                   logical_path=self.source_path(source.session_id))
            del verified
        target_nodes: list[SessionVariableSnapshotNode] = []
        if len(sources) == 1:
            target_nodes.extend(sources[0].nodes)
        else:
            if any(source.root_exists for source in sources):
                target_nodes.append(SessionVariableSnapshotNode(relative_path=constants.SESSION_VARIABLE_SOURCE_GROUP_NAME,
                                                                is_directory=True))
            for source in sources:
                if not source.root_exists:
                    continue
                prefix = constants.SESSION_VARIABLE_SOURCE_GROUP_NAME + "/" + source.session_id
                target_nodes.append(SessionVariableSnapshotNode(relative_path=prefix, is_directory=True))
                target_nodes.extend(node.model_copy(update={"relative_path": prefix + "/" + node.relative_path})
                                    for node in source.nodes)
        self._check_tree_limits(target_nodes)
        budget.check_time()
        return SessionVariableInheritanceData(sources=sources, target_nodes=target_nodes)

    def _ensure_directories(self, logical: str) -> None:
        prefix, relative = logical.split(":", 1)
        current = prefix + ":"
        for part in relative.split("/"):
            current += ("" if current.endswith(":") else "/") + part
            real = self._checked_path(current, write=True)
            try:
                real.mkdir()
            except FileExistsError:
                if not stat.S_ISDIR(real.lstat().st_mode):
                    raise SessionVariableConflictError("Parent path is not a directory", logical_path=current)
            self._checked_path(current, write=True)

    def _remove_owned_target(
        self,
        logical_path: str,
        expected_identity: SessionVariableDirectoryIdentity
        ) -> None:
        def check_owner() -> Path:
            root = self._checked_path(logical_path, write=True)
            info = root.lstat()
            if (info.st_dev, info.st_ino) != expected_identity or not stat.S_ISDIR(info.st_mode):
                raise SessionVariableCleanupFailure("Variable target identity changed; refusing cleanup")
            return root

        def remove_directory(logical: str) -> None:
            check_owner()
            directory = self._checked_path(logical, write=True)
            for child in list(directory.iterdir()):
                check_owner()
                child_logical = logical + "/" + child.name
                safe = self._checked_path(child_logical, write=True)
                info = safe.lstat()
                if stat.S_ISDIR(info.st_mode):
                    remove_directory(child_logical)
                elif stat.S_ISREG(info.st_mode):
                    self._checked_path(child_logical, write=True).unlink()
                else:
                    raise SessionVariableCleanupFailure("Unexpected node in variable target; refusing cleanup")
            check_owner()
            self._checked_path(logical, write=True).rmdir()

        try:
            remove_directory(logical_path)
        except BaseException as exc:
            if isinstance(exc, SessionVariableCleanupFailure):
                raise
            raise SessionVariableCleanupFailure("Failed to remove incomplete variable target") from exc

    @contextmanager
    def install_inheritance(
        self,
        data: SessionVariableInheritanceData,
        target_session_id: str
        ) -> Iterator[None]:
        logical = self.source_path(target_session_id)
        self._check_tree_limits(data.target_nodes)
        if not any(source.root_exists for source in data.sources):
            # 缺失源保持缺失，但仍拒绝覆盖事先存在的目标。
            root = self._checked_path(logical, write=True)
            if root.exists():
                raise SessionVariableConflictError("Variable target already exists", logical_path=logical)
            yield
            return
        self._ensure_directories(logical.rpartition("/")[0])
        root = self._checked_path(logical, write=True)
        try:
            root.mkdir()
        except FileExistsError as exc:
            raise SessionVariableConflictError("Variable target already exists", logical_path=logical) from exc
        info = root.lstat()
        owner: SessionVariableDirectoryIdentity = (info.st_dev, info.st_ino)

        def check_owner() -> None:
            current = self._checked_path(logical, write=True).lstat()
            if (current.st_dev, current.st_ino) != owner or not stat.S_ISDIR(current.st_mode):
                raise SessionVariableConflictError("Variable target identity changed", logical_path=logical)

        try:
            for node in sorted(data.target_nodes, key=lambda item: (len(item.relative_path.split("/")), item.relative_path)):
                check_owner()
                target = logical + "/" + node.relative_path
                real = self._checked_path(target, write=True)
                if node.is_directory:
                    real.mkdir()
                else:
                    if node.content is None or node.issues:
                        raise SessionVariableConflictError("Inheritance material is incomplete", logical_path=target)
                    with real.open("xb") as stream:
                        stream.write(node.content)
                        stream.flush()
                        os.fsync(stream.fileno())
                self._checked_path(target, write=True)
                check_owner()
            yield
            check_owner()
        except BaseException as failure:
            try:
                self._remove_owned_target(logical, owner)
            except BaseException as cleanup:
                raise BaseExceptionGroup("Variable initialization and cleanup failed", [failure, cleanup]) from None
            raise
