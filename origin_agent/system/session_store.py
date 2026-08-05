"""会话文件存储工具。

会话历史使用 history.es（基于 easysave 多态序列化）持久化。
同时管理 summary.txt、token_usage.json、tool_resources.json 等辅助文件。
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from entity.messages import History
from entity.puretype import TokenUsageRecord
from entity.constant import History_Version as __SessionStore_Version__
from easysave import save, load

from system.atomic_io import write_text_atomic

logger = logging.getLogger(__name__)


class SessionStore:
    """封装单个 sessions 根目录下的会话文件读写。"""

    # 工具副作用资源分区 → 独立文件（磁盘唯一真相，分区写互不干扰）
    _PARTITION_FILES: dict[str, str] = {
        "task_progress": "task_progress.json",
        "clipboard_display": "clipboard_display.json",
    }

    def __init__(self, base_dir: Path | str) -> None:
        self.base_dir = Path(base_dir)

    def session_dir(self, session_id: str) -> Path:
        return self.base_dir / session_id

    def summary_path(self, session_id: str) -> Path:
        return self.session_dir(session_id) / "summary.txt"

    def token_usage_path(self, session_id: str) -> Path:
        return self.session_dir(session_id) / "token_usage.json"

    def tool_resources_path(self, session_id: str) -> Path:
        # 旧单文件（仅兼容读取，不再写入）
        return self.session_dir(session_id) / "tool_resources.json"

    def partition_path(self, session_id: str, partition: str) -> Path:
        """返回指定资源分区的独立文件路径。"""
        return self.session_dir(session_id) / self._PARTITION_FILES[partition]

    def read_partition(self, session_id: str, partition: str) -> dict[str, Any]:
        """读单个分区；分区文件不存在时回退读旧单文件 tool_resources.json 对应键。

        必须逐分区判断文件存在（不能"任一分区存在就整体走分区"），
        否则 clear 只写 task_progress.json 后 clipboard_display 仍读旧单文件残留。
        """
        path = self.partition_path(session_id, partition)
        if path.is_file():
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        legacy = self.tool_resources_path(session_id)
        if legacy.is_file():
            data = json.loads(legacy.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                value = data.get(partition)
                return value if isinstance(value, dict) else {}
        return {}

    def write_partition(self, session_id: str, partition: str, values: dict[str, Any]) -> None:
        """原子写单个资源分区文件（write_text_atomic 自动建目录）。"""
        path = self.partition_path(session_id, partition)
        path.parent.mkdir(parents=True, exist_ok=True)
        write_text_atomic(path, json.dumps(dict(values), ensure_ascii=False, indent=2))

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

    def write_token_usage(self, session_id: str, record: TokenUsageRecord) -> None:
        payload = record.model_dump_json()
        write_text_atomic(self.token_usage_path(session_id), payload)

    def read_token_usage(self, session_id: str) -> TokenUsageRecord:
        path = self.token_usage_path(session_id)
        if not path.exists():
            return TokenUsageRecord()
        data = json.loads(path.read_text(encoding="utf-8"))
        return TokenUsageRecord.model_validate(data)

    def read_summary(self, session_id: str) -> str:
        path = self.summary_path(session_id)
        if not path.is_file():
            return ""
        return path.read_text(encoding="utf-8").strip()

    def write_summary(self, session_id: str, summary: str) -> None:
        write_text_atomic(self.summary_path(session_id), summary)

    def read_tool_resources(self, session_id: str) -> dict[str, Any]:
        """合并读全部分区（兼容旧单文件逐分区回退）。"""
        return {
            "task_progress": self.read_partition(session_id, "task_progress"),
            "clipboard_display": self.read_partition(session_id, "clipboard_display"),
        }

    def write_tool_resources(self, session_id: str, resources: dict[str, Any]) -> None:
        """按分区逐个写（会话轮转迁移用，签名保持兼容）。"""
        for partition, values in resources.items():
            if partition in self._PARTITION_FILES:
                self.write_partition(session_id, partition, values)

    def update_tool_resources(self, session_id: str, partition: str, values: dict[str, Any]) -> None:
        """单分区整体覆盖写（工具模块调用点），不再读-改-写整文件。"""
        self.write_partition(session_id, partition, values)

