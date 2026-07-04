"""会话文件存储工具。

新增 History 持久化格式：history.es（基于 easysave 多态序列化）。
保留旧接口：messages.jsonl、summary.txt、token_usage.json 等，
旧 JSONL 仅用于迁移脚本读取。
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from entity.puretype import Role
from entity.messages import History
from entity.constant import History_Version as __SessionStore_Version__
from easysave import save, load

from system.atomic_io import write_text_atomic

logger = logging.getLogger(__name__)


class SessionStore:
    """封装单个 sessions 根目录下的会话文件读写。"""

    def __init__(self, base_dir: Path | str) -> None:
        self.base_dir = Path(base_dir)

    def session_dir(self, session_id: str) -> Path:
        return self.base_dir / session_id

    def messages_path(self, session_id: str) -> Path:
        return self.session_dir(session_id) / "messages.jsonl"

    def summary_path(self, session_id: str) -> Path:
        return self.session_dir(session_id) / "summary.txt"

    def token_usage_path(self, session_id: str) -> Path:
        return self.session_dir(session_id) / "token_usage.json"

    def tool_resources_path(self, session_id: str) -> Path:
        return self.session_dir(session_id) / "tool_resources.json"

    def history_path(self, session_id: str) -> Path:
        return self.session_dir(session_id) / "history.es"

    def read_history(self, session_id: str) -> History | None:
        """从 easysave 多态序列化文件读取 History 实例。"""
        path = self.history_path(session_id)
        if not path.exists():
            return None
        try:
            data = load(__SessionStore_Version__, str(path), History)
            if isinstance(data, History):
                data.remove_unpaired_tool_calls()
                return data
            logger.error("Loaded history for session=%s is not History instance: %s", session_id, type(data))
            return None
        except KeyError as exc:
            logger.exception("Failed to load history for session=%s: %s", session_id, exc)
            return None
        except Exception as exc:
            logger.exception("Failed to load history for session=%s: %s", session_id, exc)
            raise

    def write_history(self, session_id: str, history: History) -> None:
        """将 History 实例以 easysave 多态序列化写入磁盘。"""
        path = self.history_path(session_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            save(__SessionStore_Version__, str(path), history)
        except Exception as exc:
            logger.exception("Failed to save history for session %s: %s", session_id, exc)
            raise

    def append_message(self, session_id: str, entry: dict[str, Any]) -> None:
        path = self.messages_path(session_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def read_messages(self, session_id: str) -> list[dict]:
        path = self.messages_path(session_id)
        if not path.exists():
            return []
        entries: list[dict] = []
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    entries.append(json.loads(line))
        return entries

    def overwrite_messages(self, session_id: str, entries: list[dict]) -> None:
        path = self.messages_path(session_id)
        lines = [json.dumps(m, ensure_ascii=False) + "\n" for m in entries]
        write_text_atomic(path, "".join(lines))

    def remove_last_user_message(self, session_id: str) -> None:
        path = self.messages_path(session_id)
        if not path.exists():
            return
        text = path.read_text(encoding="utf-8")
        lines = text.strip().split("\n") if text.strip() else []
        if not lines:
            return
        last = json.loads(lines[-1])
        if last.get("role") != Role.USER:
            return
        lines.pop()
        write_text_atomic(path, "\n".join(lines) + "\n" if lines else "")

    def write_token_usage(self, session_id: str, token_usage: int) -> None:
        payload = json.dumps({"token_usage": token_usage}, ensure_ascii=False)
        write_text_atomic(self.token_usage_path(session_id), payload)

    def read_token_usage(self, session_id: str) -> int:
        path = self.token_usage_path(session_id)
        if not path.exists():
            return 0
        data = json.loads(path.read_text(encoding="utf-8"))
        return int(data.get("token_usage", 0))

    def read_summary(self, session_id: str) -> str:
        path = self.summary_path(session_id)
        if not path.is_file():
            return ""
        return path.read_text(encoding="utf-8").strip()

    def write_summary(self, session_id: str, summary: str) -> None:
        write_text_atomic(self.summary_path(session_id), summary)

    def read_tool_resources(self, session_id: str) -> dict[str, Any]:
        path = self.tool_resources_path(session_id)
        if not path.exists():
            return {"task_progress": {}, "clipboard_display": {}}
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return {"task_progress": {}, "clipboard_display": {}}
        return {
            "task_progress": data.get("task_progress", {}) if isinstance(data.get("task_progress"), dict) else {},
            "clipboard_display": data.get("clipboard_display", {}) if isinstance(data.get("clipboard_display"), dict) else {},
        }

    def write_tool_resources(self, session_id: str, resources: dict[str, Any]) -> None:
        payload = json.dumps(resources, ensure_ascii=False, indent=2)
        write_text_atomic(self.tool_resources_path(session_id), payload)

