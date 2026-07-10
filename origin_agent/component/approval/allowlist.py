"""统一工具 allowlist。

为 write / dangerous 工具提供统一的"始终允许"持久化能力。
"""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import Any

from entity.constant import TOOL_ALLOWLIST_FILENAME
from entity.puretype import ToolAllowlistEntry
from system.context import get_runtime_context

logger = logging.getLogger(__name__)

_EXCLUDED_KEYS = {"_session_id", "_pre_approved", "_approval_action", "reason"}
_lock = threading.RLock()


def _allowlist_path() -> Path:
    return get_runtime_context().workspace / TOOL_ALLOWLIST_FILENAME


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in sorted(value.items(), key=lambda item: str(item[0]))}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def normalize_args(args: dict[str, Any]) -> dict[str, Any]:
    return {
        str(k): _json_safe(v)
        for k, v in sorted(args.items(), key=lambda item: str(item[0]))
        if str(k) not in _EXCLUDED_KEYS
    }


def _empty_store() -> list[ToolAllowlistEntry]:
    return []


def _load_store() -> list[ToolAllowlistEntry]:
    path = _allowlist_path()
    if not path.exists():
        return _empty_store()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return [ToolAllowlistEntry(**entry) for entry in data if isinstance(entry, dict)]
        if isinstance(data, dict):
            entries = data.get("entries", [])
            if isinstance(entries, list):
                return [ToolAllowlistEntry(**entry) for entry in entries if isinstance(entry, dict)]
        return _empty_store()
    except Exception as exc:
        logger.exception("Failed to load tool allowlist: %s", exc)
        return _empty_store()


def _save_store(entries: list[ToolAllowlistEntry]) -> None:
    path = _allowlist_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps([e.model_dump() for e in entries], ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as exc:
        logger.exception("Failed to save tool allowlist: %s", exc)


def is_allowed(tool_name: str, args: dict[str, Any]) -> bool:
    normalized = normalize_args(args)
    with _lock:
        entries = _load_store()
        for entry in entries:
            if entry.tool == tool_name and entry.args == normalized:
                return True
    return False


def add_allowed(tool_name: str, args: dict[str, Any]) -> None:
    normalized = normalize_args(args)
    with _lock:
        entries = _load_store()
        for entry in entries:
            if entry.tool == tool_name and entry.args == normalized:
                return
        entries.append(ToolAllowlistEntry(tool=tool_name, args=normalized))
        _save_store(entries)