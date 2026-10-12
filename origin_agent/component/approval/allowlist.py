"""工具白名单业务存储；实例由 ApprovalSystem 唯一持有。"""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import Any

from entity.constant import TOOL_ALLOWLIST_FILENAME, TOOL_INTERNAL_ARG_KEYS
from entity.puretype import ToolAllowlistEntry

logger = logging.getLogger(__name__)

# 工具执行链路的内部注入键共用 TOOL_INTERNAL_ARG_KEYS；额外排除 reason
# ——它是模型可传的合法审批参数，仅不参与白名单匹配，MCP 下发侧不剥离。
_EXCLUDED_KEYS = TOOL_INTERNAL_ARG_KEYS | {"reason"}


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


class ToolAllowlistStore:
    """保存原 JSON 白名单规则，不建立独立的模块级锁或配置入口。"""

    def __init__(self, workspace: Path) -> None:
        self._path = workspace / TOOL_ALLOWLIST_FILENAME
        self._lock = threading.RLock()

    def _load_store(self) -> list[ToolAllowlistEntry]:
        if not self._path.exists():
            return []
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            if isinstance(data, list):
                return [ToolAllowlistEntry(**entry) for entry in data if isinstance(entry, dict)]
            if isinstance(data, dict):
                entries = data.get("entries", [])
                if isinstance(entries, list):
                    return [ToolAllowlistEntry(**entry) for entry in entries if isinstance(entry, dict)]
            return []
        except Exception as exc:
            logger.exception("Failed to load tool allowlist: %s", exc)
            return []

    def _save_store(self, entries: list[ToolAllowlistEntry]) -> None:
        # 保持既有白名单的尽力保存语义；本迁移不更改审批业务策略。
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(
                json.dumps([entry.model_dump() for entry in entries], ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as exc:
            logger.exception("Failed to save tool allowlist: %s", exc)

    def is_allowed(self, tool_name: str, args: dict[str, Any]) -> bool:
        normalized = normalize_args(args)
        with self._lock:
            return any(
                entry.tool == tool_name and entry.args == normalized
                for entry in self._load_store()
            )

    def add_allowed(self, tool_name: str, args: dict[str, Any]) -> None:
        normalized = normalize_args(args)
        with self._lock:
            entries = self._load_store()
            if any(entry.tool == tool_name and entry.args == normalized for entry in entries):
                return
            entries.append(ToolAllowlistEntry(tool=tool_name, args=normalized))
            self._save_store(entries)


def is_allowed(tool_name: str, args: dict[str, Any]) -> bool:
    """公共审批业务入口；不持有实例或状态。"""
    from component.approval.system import ApprovalSystem
    from system.application import Application
    return Application.current().get_system(ApprovalSystem).allowlist.is_allowed(tool_name, args)


def add_allowed(tool_name: str, args: dict[str, Any]) -> None:
    """公共审批业务入口；委托唯一系统拥有的白名单。"""
    from component.approval.system import ApprovalSystem
    from system.application import Application
    Application.current().get_system(ApprovalSystem).allowlist.add_allowed(tool_name, args)
