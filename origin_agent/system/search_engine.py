"""SearchFiles/Grep 搜索引擎封装。

Windows x64 优先使用随 Agent 分发的固定版本 ripgrep；不可用、单次
正则不兼容或结构化输出解析失败时，回退到纯 Python 实现。精确搜索
始终基于实时文件系统，不维护持久化索引。
"""

from __future__ import annotations

import asyncio
import fnmatch
import hashlib
import json
import logging
import platform
import re
import subprocess  # nosec
import sys
from collections import deque
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Iterator, TYPE_CHECKING

from abstract.tools.registry import tool_error, tool_result
from entity.constant import (
    FILE_SNIFF_BYTES,
    SEARCH_IGNORE_FILENAMES,
    SEARCH_OVERFLOW_LOG_DIR,
    SEARCH_PROCESS_STDERR_MAX_BYTES,
    SEARCH_RESULT_LIMIT_DEFAULT,
    SEARCH_RIPGREP_EXE_SHA256,
    SEARCH_RIPGREP_WINDOWS_X64_RELATIVE_PATH,
    SEARCH_TEXT_EXTENSIONS,
)
from system.pathutils import get_agent_dir
from system.sandbox import SandboxError
from system.subprocess_utils import safe_decode

if TYPE_CHECKING:
    from entry.base_agent_loop import ToolContext

logger = logging.getLogger(__name__)

_RIPGREP_SHA256_CACHE: tuple[Path, str] | None = None


class RipgrepUnavailable(RuntimeError):
    """固定 ripgrep 二进制不可用，可回退到 Python 搜索。"""


class RipgrepRecoverableError(RuntimeError):
    """本次 ripgrep 调用失败，但整次回退可保持结果完整性。"""


class RipgrepFatalError(RuntimeError):
    """不应静默回退的 ripgrep 错误。"""


def _s():
    from system.application import Application

    return Application.current().sandbox


def parse_bool_arg(args: dict[str, Any], name: str, default: bool = False) -> bool:
    value = args.get(name, default)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on", "y"}
    return bool(value)


def normalize_search_limit(value: Any) -> int:
    try:
        limit = int(value)
    except (TypeError, ValueError):
        return SEARCH_RESULT_LIMIT_DEFAULT
    if limit <= 0:
        return SEARCH_RESULT_LIMIT_DEFAULT
    return limit


def _normalize_non_negative_int(value: Any, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(0, parsed)


def logical_parent_and_target(logical_path: str) -> tuple[str, str]:
    if ":" not in logical_path:
        raise SandboxError(f"Path must carry a namespace prefix. Got: {logical_path!r}")
    ns, rest = logical_path.split(":", 1)
    rest = rest.strip().replace("\\", "/").strip("/")
    if not rest or "/" not in rest:
        return f"{ns}:", rest
    parent, target = rest.rsplit("/", 1)
    if not target or ".." in target.split("/"):
        raise SandboxError(f"Invalid target path: {logical_path!r}")
    return f"{ns}:{parent}", target


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def resolve_bundled_ripgrep() -> Path:
    global _RIPGREP_SHA256_CACHE

    if sys.platform != "win32" or platform.machine().lower() not in {"amd64", "x86_64"}:
        raise RipgrepUnavailable("bundled ripgrep is only provided for Windows x64")

    rg_path = (get_agent_dir() / SEARCH_RIPGREP_WINDOWS_X64_RELATIVE_PATH).resolve()
    if not rg_path.is_file():
        raise RipgrepUnavailable(f"bundled ripgrep not found: {rg_path}")
    if not SEARCH_RIPGREP_EXE_SHA256:
        raise RipgrepUnavailable("bundled ripgrep SHA-256 is not configured")

    if _RIPGREP_SHA256_CACHE is None or _RIPGREP_SHA256_CACHE[0] != rg_path:
        _RIPGREP_SHA256_CACHE = (rg_path, _sha256_file(rg_path))
    actual = _RIPGREP_SHA256_CACHE[1]
    if actual.casefold() != SEARCH_RIPGREP_EXE_SHA256.casefold():
        raise RipgrepUnavailable(
            f"bundled ripgrep SHA-256 mismatch: expected {SEARCH_RIPGREP_EXE_SHA256}, got {actual}"
        )
    return rg_path


def _logical_result_path(namespace: str, root: Path, file_path: Path) -> str:
    namespace_root = _s().namespace_bases().get(namespace, root)
    rel = file_path.resolve().relative_to(namespace_root.resolve()).as_posix()
    return f"{namespace}:{rel}" if rel else f"{namespace}:"


def _is_hidden_relative_path(path: Path, root: Path) -> bool:
    try:
        parts = path.relative_to(root).parts
    except ValueError:
        parts = path.parts
    return any(part.startswith(".") for part in parts if part not in {".", ""})


def _is_text_file(path: Path) -> bool:
    if path.suffix.lower() in SEARCH_TEXT_EXTENSIONS:
        return True
    try:
        with path.open("rb") as f:
            sample = f.read(FILE_SNIFF_BYTES)
    except OSError:
        logger.debug("Failed to sniff file type: %s", path, exc_info=True)
        return False
    return b"\x00" not in sample


def _load_pathspec_module():
    try:
        import pathspec  # type: ignore
    except ImportError as exc:
        raise RuntimeError("Python search fallback requires dependency 'pathspec'.") from exc
    return pathspec


def _prefixed_ignore_patterns(ignore_file: Path, root: Path) -> list[str]:
    try:
        base_rel = ignore_file.parent.relative_to(root).as_posix()
    except ValueError:
        base_rel = ""
    base_rel = "" if base_rel == "." else base_rel

    patterns: list[str] = []
    try:
        lines = ignore_file.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        logger.debug("Failed to read ignore file: %s", ignore_file, exc_info=True)
        return patterns

    for raw in lines:
        line = raw.rstrip("\n")
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        sign = "!" if stripped.startswith("!") else ""
        body = stripped[1:] if sign else stripped
        if not body:
            continue
        if body.startswith("/"):
            body = body.lstrip("/")
            prefixed = f"{base_rel}/{body}" if base_rel else body
        elif "/" not in body.rstrip("/"):
            prefixed = f"{base_rel}/**/{body}" if base_rel else f"**/{body}"
        else:
            prefixed = f"{base_rel}/{body}" if base_rel else body
        patterns.append(sign + prefixed)
    return patterns


def _build_ignore_matcher(patterns: list[str]):
    if not patterns:
        return None
    pathspec = _load_pathspec_module()
    return pathspec.PathSpec.from_lines("gitwildmatch", patterns)


def _iter_python_files(root: Path, *, full_scan: bool) -> Iterator[Path]:
    stack: list[tuple[Path, list[str]]] = [(root, [])]
    while stack:
        directory, inherited_patterns = stack.pop()
        patterns = list(inherited_patterns)
        if not full_scan:
            for ignore_name in SEARCH_IGNORE_FILENAMES:
                ignore_file = directory / ignore_name
                if ignore_file.is_file():
                    patterns.extend(_prefixed_ignore_patterns(ignore_file, root))
        spec = _build_ignore_matcher(patterns) if not full_scan else None
        try:
            entries = sorted(directory.iterdir(), key=lambda p: p.name.casefold())
        except OSError:
            logger.debug("Failed to list directory during search: %s", directory, exc_info=True)
            continue
        for entry in reversed(entries):
            try:
                is_dir = entry.is_dir()
                is_file = entry.is_file()
            except OSError:
                logger.debug("Failed to stat path during search: %s", entry, exc_info=True)
                continue
            if not full_scan and _is_hidden_relative_path(entry, root):
                continue
            if spec is not None:
                rel = entry.relative_to(root).as_posix()
                if is_dir:
                    rel += "/"
                if spec.match_file(rel):
                    continue
            if is_dir:
                if not entry.is_symlink():
                    stack.append((entry, patterns))
            elif is_file:
                yield entry


def _matches_glob(relative_path: str, name: str, pattern: str) -> bool:
    normalized = relative_path.replace("\\", "/")
    if "/" in pattern or "**" in pattern:
        return PurePosixPath(normalized).match(pattern)
    return fnmatch.fnmatchcase(name, pattern) or fnmatch.fnmatchcase(normalized, pattern)


def _write_overflow_log(kind: str, path: str, pattern: str, rows: list[str], *, total_count: int | None = None) -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    log_name = f"{SEARCH_OVERFLOW_LOG_DIR}/{kind}_{timestamp}.log"
    content = (
        f"# {kind} results for {path} pattern={pattern}\n"
        f"Total: {total_count if total_count is not None else len(rows)} matches\n\n"
        + "\n".join(rows)
    )
    _s().write(log_name, content)
    return log_name


def _finish_files_result(
    *,
    matches: list[str],
    total_count: int,
    truncated: bool,
    engine: str,
    limit: int,
    full_scan: bool,
    exhaustive: bool,
    path: str,
    pattern: str,
    warning: str | None = None,
) -> dict[str, Any]:
    result = tool_result(
        matches=matches[:limit],
        count=total_count if exhaustive else len(matches[:limit]),
        truncated=truncated or (exhaustive and total_count > limit),
        engine=engine,
        limit=limit,
        full_scan=full_scan,
        exhaustive=exhaustive,
    )
    if warning:
        result["warning"] = warning
    if exhaustive and total_count > limit:
        log_path = _write_overflow_log("search_files", path, pattern, matches, total_count=total_count)
        result["log_path"] = log_path
        result["_note"] = f"Results exceeded {limit} matches. Full list written to log file."
    return result


def _finish_grep_result(
    *,
    matches: list[dict[str, Any]],
    total_count: int,
    truncated: bool,
    engine: str,
    limit: int,
    full_scan: bool,
    exhaustive: bool,
    literal: bool,
    path: str,
    pattern: str,
    warning: str | None = None,
) -> dict[str, Any]:
    result = tool_result(
        matches=matches[:limit],
        count=total_count if exhaustive else len(matches[:limit]),
        truncated=truncated or (exhaustive and total_count > limit),
        engine=engine,
        limit=limit,
        full_scan=full_scan,
        exhaustive=exhaustive,
        literal=literal,
    )
    if warning:
        result["warning"] = warning
    if exhaustive and total_count > limit:
        rows: list[str] = []
        for match in matches:
            rows.append(f"{match['file']}:{match['line']}:{match['match']}")
            for before in match.get("context_before", []):
                rows.append(f"  - {before}")
            for after in match.get("context_after", []):
                rows.append(f"  + {after}")
            rows.append("")
        log_path = _write_overflow_log("grep", path, pattern, rows, total_count=total_count)
        result["log_path"] = log_path
        result["_note"] = f"Results exceeded {limit} matches. Full list written to log file."
    return result


async def _run_ripgrep_files(
    *,
    rg: Path,
    logical_path: str,
    namespace: str,
    root: Path,
    pattern: str,
    limit: int,
    full_scan: bool,
    exhaustive: bool,
    session_id: str,
) -> tuple[list[str], int, bool]:
    args = [
        str(rg),
        "--files",
        "--color",
        "never",
        "--line-buffered",
        "--no-require-git",
        f"--glob={pattern}",
    ]
    if full_scan:
        args.extend(["--hidden", "--no-ignore"])

    matches: list[str] = []

    def on_line(raw_line: bytes) -> bool:
        rel = safe_decode(raw_line).strip("\r\n")
        if not rel:
            return True
        file_path = (root / rel).resolve()
        matches.append(_logical_result_path(namespace, root, file_path))
        return exhaustive or len(matches) <= limit

    try:
        result = await _s().run_async_line_processor(
            args,
            cwd_ns=logical_path,
            on_stdout_line=on_line,
            session_id=session_id,
            stderr_byte_limit=SEARCH_PROCESS_STDERR_MAX_BYTES,
        )
    except OSError as exc:
        raise RipgrepRecoverableError(f"failed to start ripgrep: {exc}") from exc

    if not result.truncated and result.returncode not in (0, 1):
        raise RipgrepRecoverableError(result.stderr or f"ripgrep exited with code {result.returncode}")

    total_count = len(matches)
    truncated = result.truncated or (not exhaustive and total_count > limit)
    if not exhaustive and total_count > limit:
        matches = matches[:limit]
        total_count = len(matches)
    return matches, total_count, truncated


def _attach_contexts(matches: list[dict[str, Any]], context_lines: int) -> None:
    if not matches:
        return

    by_file: dict[Path, list[dict[str, Any]]] = {}
    for match in matches:
        real_path = match.pop("_real_path", None)
        if context_lines > 0 and isinstance(real_path, Path):
            by_file.setdefault(real_path, []).append(match)
    if context_lines <= 0:
        return

    for file_path, file_matches in by_file.items():
        wanted = {int(match["line"]): match for match in file_matches}
        max_line = max(wanted) + context_lines
        before_buffer: deque[str] = deque(maxlen=context_lines)
        pending_after: list[tuple[dict[str, Any], int]] = []
        try:
            with file_path.open("r", encoding="utf-8", errors="replace") as f:
                for line_number, raw_line in enumerate(f, start=1):
                    line = raw_line.rstrip("\r\n")
                    if pending_after:
                        next_pending: list[tuple[dict[str, Any], int]] = []
                        for match, remaining in pending_after:
                            match["context_after"].append(line)
                            remaining -= 1
                            if remaining > 0:
                                next_pending.append((match, remaining))
                        pending_after = next_pending
                    current_match = wanted.get(line_number)
                    if current_match is not None:
                        current_match["context_before"] = list(before_buffer)
                        pending_after.append((current_match, context_lines))
                    before_buffer.append(line)
                    if line_number >= max_line and not pending_after:
                        break
        except OSError:
            logger.debug("Failed to read context for search matches: %s", file_path, exc_info=True)


async def _run_ripgrep_grep(
    *,
    rg: Path,
    logical_path: str,
    namespace: str,
    root: Path,
    pattern: str,
    limit: int,
    max_file_size: int,
    context_lines: int,
    full_scan: bool,
    exhaustive: bool,
    literal: bool,
    session_id: str,
    single_target: str | None,
) -> tuple[list[dict[str, Any]], int, bool]:
    args = [
        str(rg),
        "--json",
        "--color",
        "never",
        "--line-number",
        "--line-buffered",
        "--no-require-git",
        "--engine",
        "auto",
        "--max-filesize",
        str(max_file_size),
    ]
    if full_scan:
        args.extend(["--hidden", "--no-ignore"])
    if literal:
        args.append("--fixed-strings")
    args.append(f"--regexp={pattern}")
    if single_target:
        args.extend(["--", single_target])

    matches: list[dict[str, Any]] = []

    def on_line(raw_line: bytes) -> bool:
        text = safe_decode(raw_line).strip()
        if not text:
            return True
        event = json.loads(text)
        if event.get("type") != "match":
            return True
        data = event.get("data")
        if not isinstance(data, dict):
            raise RipgrepRecoverableError("ripgrep JSON match event missing data")
        path_data = data.get("path")
        lines_data = data.get("lines")
        if not isinstance(path_data, dict) or not isinstance(lines_data, dict):
            raise RipgrepRecoverableError("ripgrep JSON match event missing path or lines")
        rel = path_data.get("text")
        line_text = lines_data.get("text")
        line_number = data.get("line_number")
        if not isinstance(rel, str) or not isinstance(line_text, str) or not isinstance(line_number, int):
            raise RipgrepRecoverableError("ripgrep JSON match event contains unsupported encoded fields")
        file_path = (root / rel).resolve()
        matches.append({
            "file": _logical_result_path(namespace, root, file_path),
            "line": line_number,
            "match": line_text.rstrip("\r\n"),
            "context_before": [],
            "context_after": [],
            "_real_path": file_path,
        })
        return exhaustive or len(matches) <= limit

    try:
        result = await _s().run_async_line_processor(
            args,
            cwd_ns=logical_path,
            on_stdout_line=on_line,
            session_id=session_id,
            stderr_byte_limit=SEARCH_PROCESS_STDERR_MAX_BYTES,
        )
    except json.JSONDecodeError as exc:
        raise RipgrepRecoverableError(f"failed to parse ripgrep JSON output: {exc}") from exc
    except asyncio.LimitOverrunError as exc:
        raise RipgrepRecoverableError(f"ripgrep JSON output line exceeded the stream limit: {exc}") from exc
    except OSError as exc:
        raise RipgrepRecoverableError(f"failed to start ripgrep: {exc}") from exc

    if not result.truncated and result.returncode not in (0, 1):
        raise RipgrepRecoverableError(result.stderr or f"ripgrep exited with code {result.returncode}")

    total_count = len(matches)
    truncated = result.truncated or (not exhaustive and total_count > limit)
    if not exhaustive and total_count > limit:
        matches = matches[:limit]
        total_count = len(matches)
    _attach_contexts(matches, context_lines)
    return matches, total_count, truncated


def _python_search_files(
    *,
    root: Path,
    namespace: str,
    pattern: str,
    limit: int,
    full_scan: bool,
    exhaustive: bool,
) -> tuple[list[str], int, bool]:
    matches: list[str] = []
    truncated = False
    for file_path in _iter_python_files(root, full_scan=full_scan):
        rel = file_path.relative_to(root).as_posix()
        if not _matches_glob(rel, file_path.name, pattern):
            continue
        matches.append(_logical_result_path(namespace, root, file_path))
        if not exhaustive and len(matches) > limit:
            truncated = True
            matches = matches[:limit]
            break
    return matches, len(matches), truncated


def _python_grep(
    *,
    root: Path,
    namespace: str,
    logical_path: str,
    pattern: str,
    limit: int,
    max_file_size: int,
    context_lines: int,
    full_scan: bool,
    exhaustive: bool,
    literal: bool,
    single_file: bool,
) -> tuple[list[dict[str, Any]], int, bool]:
    regex = None if literal else re.compile(pattern)
    files = [root] if single_file else _iter_python_files(root, full_scan=full_scan)
    matches: list[dict[str, Any]] = []
    truncated = False

    for file_path in files:
        try:
            if file_path.stat().st_size > max_file_size:
                continue
        except OSError:
            logger.debug("Failed to stat file during grep: %s", file_path, exc_info=True)
            continue
        if not _is_text_file(file_path):
            continue

        before_buffer: deque[str] = deque(maxlen=context_lines)
        pending_after: list[tuple[dict[str, Any], int]] = []
        try:
            with file_path.open("r", encoding="utf-8", errors="replace") as f:
                for line_number, raw_line in enumerate(f, start=1):
                    line = raw_line.rstrip("\r\n")
                    if pending_after:
                        next_pending: list[tuple[dict[str, Any], int]] = []
                        for match, remaining in pending_after:
                            if remaining > 0:
                                match["context_after"].append(line)
                                remaining -= 1
                            if remaining > 0:
                                next_pending.append((match, remaining))
                        pending_after = next_pending

                    hit = pattern in line if literal else bool(regex.search(line))  # type: ignore[union-attr]
                    if hit:
                        if single_file:
                            result_path = logical_path
                        else:
                            result_path = _logical_result_path(namespace, root, file_path)
                        match = {
                            "file": result_path,
                            "line": line_number,
                            "match": line,
                            "context_before": list(before_buffer),
                            "context_after": [],
                        }
                        matches.append(match)
                        if context_lines > 0:
                            pending_after.append((match, context_lines))
                        if not exhaustive and len(matches) > limit:
                            truncated = True
                            matches = matches[:limit]
                            retained_ids = {id(item) for item in matches}
                            pending_after = [
                                (item, remaining)
                                for item, remaining in pending_after
                                if id(item) in retained_ids
                            ]
                            for _ in range(context_lines):
                                try:
                                    following = next(f).rstrip("\r\n")
                                except StopIteration:
                                    break
                                next_pending = []
                                for item, remaining in pending_after:
                                    item["context_after"].append(following)
                                    remaining -= 1
                                    if remaining > 0:
                                        next_pending.append((item, remaining))
                                pending_after = next_pending
                                if not pending_after:
                                    break
                            return matches, len(matches), truncated
                    before_buffer.append(line)
        except OSError:
            logger.debug("Failed to read file during grep: %s", file_path, exc_info=True)
            continue

    return matches, len(matches), truncated


async def search_files(args: dict[str, Any], context: ToolContext | None = None) -> dict[str, Any]:
    path = str(args.get("path", "")).strip()
    pattern = str(args.get("pattern", "")).strip()
    limit = normalize_search_limit(args.get("limit", SEARCH_RESULT_LIMIT_DEFAULT))
    full_scan = parse_bool_arg(args, "full_scan", False)
    exhaustive = parse_bool_arg(args, "exhaustive", False)
    session_id = getattr(context, "session_id", "") if context is not None else ""

    if not path:
        return tool_error("path is required")
    if not pattern:
        return tool_error("pattern is required")

    try:
        resolved = _s().resolve_read(path)
    except SandboxError as exc:
        return tool_error(str(exc), path=path)
    if not resolved.real.is_dir():
        return tool_error(f"Not a directory: {path}")

    try:
        rg = resolve_bundled_ripgrep()
        matches, total_count, truncated = await _run_ripgrep_files(
            rg=rg,
            logical_path=path,
            namespace=resolved.namespace,
            root=resolved.real,
            pattern=pattern,
            limit=limit,
            full_scan=full_scan,
            exhaustive=exhaustive,
            session_id=session_id,
        )
        return _finish_files_result(
            matches=matches,
            total_count=total_count,
            truncated=truncated or (exhaustive and total_count > limit),
            engine="ripgrep",
            limit=limit,
            full_scan=full_scan,
            exhaustive=exhaustive,
            path=path,
            pattern=pattern,
        )
    except subprocess.TimeoutExpired:
        return tool_error("Search timed out", path=path, pattern=pattern, engine="ripgrep")
    except (RipgrepUnavailable, RipgrepRecoverableError) as exc:
        warning = str(exc)

    try:
        matches, total_count, truncated = _python_search_files(
            root=resolved.real,
            namespace=resolved.namespace,
            pattern=pattern,
            limit=limit,
            full_scan=full_scan,
            exhaustive=exhaustive,
        )
    except RuntimeError as exc:
        return tool_error(str(exc), path=path, pattern=pattern, engine="python")

    return _finish_files_result(
        matches=matches,
        total_count=total_count,
        truncated=truncated or (exhaustive and total_count > limit),
        engine="python",
        limit=limit,
        full_scan=full_scan,
        exhaustive=exhaustive,
        path=path,
        pattern=pattern,
        warning=warning,
    )


async def grep(args: dict[str, Any], context: ToolContext | None = None) -> dict[str, Any]:
    path = str(args.get("path", "")).strip()
    pattern = str(args.get("pattern", "")).strip()
    limit = normalize_search_limit(args.get("limit", SEARCH_RESULT_LIMIT_DEFAULT))
    max_file_size = _normalize_non_negative_int(args.get("max_file_size", 524_288_000), 524_288_000)
    context_lines = _normalize_non_negative_int(args.get("context_lines", 2), 2)
    full_scan = parse_bool_arg(args, "full_scan", False)
    exhaustive = parse_bool_arg(args, "exhaustive", False)
    literal = parse_bool_arg(args, "literal", False)
    session_id = getattr(context, "session_id", "") if context is not None else ""

    if not path:
        return tool_error("path is required")
    if not pattern:
        return tool_error("pattern is required")

    try:
        resolved = _s().resolve_read(path)
    except SandboxError as exc:
        return tool_error(str(exc), path=path)

    single_file = resolved.real.is_file()
    if single_file:
        rg_logical_path, single_target = logical_parent_and_target(path)
        rg_root = resolved.real.parent
    elif resolved.real.is_dir():
        rg_logical_path = path
        single_target = None
        rg_root = resolved.real
    else:
        return tool_error(f"Not a file or directory: {path}")

    try:
        rg = resolve_bundled_ripgrep()
        matches, total_count, truncated = await _run_ripgrep_grep(
            rg=rg,
            logical_path=rg_logical_path,
            namespace=resolved.namespace,
            root=rg_root,
            pattern=pattern,
            limit=limit,
            max_file_size=max_file_size,
            context_lines=context_lines,
            full_scan=full_scan,
            exhaustive=exhaustive,
            literal=literal,
            session_id=session_id,
            single_target=single_target,
        )
        if single_file:
            for match in matches:
                match["file"] = path
        return _finish_grep_result(
            matches=matches,
            total_count=total_count,
            truncated=truncated or (exhaustive and total_count > limit),
            engine="ripgrep",
            limit=limit,
            full_scan=full_scan,
            exhaustive=exhaustive,
            literal=literal,
            path=path,
            pattern=pattern,
        )
    except subprocess.TimeoutExpired:
        return tool_error("Search timed out", path=path, pattern=pattern, engine="ripgrep")
    except (RipgrepUnavailable, RipgrepRecoverableError) as exc:
        warning = str(exc)

    try:
        matches, total_count, truncated = _python_grep(
            root=resolved.real,
            namespace=resolved.namespace,
            logical_path=path,
            pattern=pattern,
            limit=limit,
            max_file_size=max_file_size,
            context_lines=context_lines,
            full_scan=full_scan,
            exhaustive=exhaustive,
            literal=literal,
            single_file=single_file,
        )
    except re.error as exc:
        return tool_error(f"Invalid regex pattern: {exc}", path=path, pattern=pattern, engine="python")
    except RuntimeError as exc:
        return tool_error(str(exc), path=path, pattern=pattern, engine="python")

    return _finish_grep_result(
        matches=matches,
        total_count=total_count,
        truncated=truncated or (exhaustive and total_count > limit),
        engine="python",
        limit=limit,
        full_scan=full_scan,
        exhaustive=exhaustive,
        literal=literal,
        path=path,
        pattern=pattern,
        warning=warning,
    )
