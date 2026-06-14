"""会话文件存储工具。

保持现有磁盘格式：messages.jsonl、summary.txt、token_usage.json。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


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
        self._write_text_atomic(path, "".join(lines))

    def remove_last_user_message(self, session_id: str) -> None:
        path = self.messages_path(session_id)
        if not path.exists():
            return
        text = path.read_text(encoding="utf-8")
        lines = text.strip().split("\n") if text.strip() else []
        if not lines:
            return
        last = json.loads(lines[-1])
        if last.get("role") != "user":
            return
        lines.pop()
        self._write_text_atomic(path, "\n".join(lines) + "\n" if lines else "")

    def write_token_usage(self, session_id: str, token_usage: int) -> None:
        payload = json.dumps({"token_usage": token_usage}, ensure_ascii=False)
        self._write_text_atomic(self.token_usage_path(session_id), payload)

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
        self._write_text_atomic(self.summary_path(session_id), summary)

    @staticmethod
    def _write_text_atomic(path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f".{path.name}.tmp")
        tmp.write_text(content, encoding="utf-8")
        tmp.replace(path)