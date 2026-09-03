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
from entity.puretype import TokenUsageRecord, MessageMetrics
from entity.constant import (
    History_Version as __SessionStore_Version__,
    SESSION_LLM_PROFILE_FILENAME,
    GLOBAL_LLM_PROFILE_FILENAME,
)
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
            data = load(__SessionStore_Version__, str(path), History, ignore_missing_fields=True)
            if isinstance(data, History):
                data.remove_unpaired_tool_calls()
                data.normalize_legacy_tool_results()
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

    # -- message metrics -------------------------------------------------------

    def message_metrics_path(self, session_id: str) -> Path:
        """返回消息计时元信息文件的路径。"""
        return self.session_dir(session_id) / "message_metrics.json"

    def read_message_metrics(self, session_id: str) -> dict[str, dict[str, Any]]:
        """读取消息计时元信息，键为 message index（字符串形式）。"""
        path = self.message_metrics_path(session_id)
        if not path.exists():
            return {}
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}

    def write_message_metrics(self, session_id: str, metrics: dict[str, dict[str, Any]]) -> None:
        """原子写入消息计时元信息。"""
        path = self.message_metrics_path(session_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        write_text_atomic(path, json.dumps(metrics, ensure_ascii=False, indent=2))

    def merge_message_metrics(
        self,
        collected: list[tuple[str, int, MessageMetrics]],
    ) -> None:
        """按 session_id 分组合并写入消息计时元信息。

        应对会话旋转：同一批 collected 中可能包含不同 session_id 的条目。
        每个 session 合并已有 metrics 后原子写入，异常时吞掉不抛出。
        """
        try:
            by_session: dict[str, dict[str, dict]] = {}
            for sess_id, msg_idx, m in collected:
                by_session.setdefault(sess_id, {})
                by_session[sess_id][str(msg_idx)] = m.model_dump()
            for sess_id, new_metrics in by_session.items():
                existing = self.read_message_metrics(sess_id)
                existing.update(new_metrics)
                self.write_message_metrics(sess_id, existing)
        except Exception:
            logger.warning(
                "Failed to merge message metrics for collected=%d entries", len(collected), exc_info=True,
            )

    # -- LLM Profile 名称指针 -----------------------------------------------

    def active_profile_name_path(self, session_id: str) -> Path:
        """返回会话级活动 Profile 名称指针路径。"""
        return self.session_dir(session_id) / SESSION_LLM_PROFILE_FILENAME

    def global_profile_name_path(self) -> Path:
        """返回全局最近使用 Profile 名称指针路径。"""
        return self.base_dir / GLOBAL_LLM_PROFILE_FILENAME

    @staticmethod
    def _read_profile_name_pointer(path: Path) -> str | None:
        """读取新格式名称指针；旧完整快照视为没有新指针。"""
        if not path.is_file():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict) and set(data) == {"profile_name"}:
            name = data["profile_name"]
            if not isinstance(name, str):
                raise TypeError(f"Profile name pointer in {path} must be a string")
            return name
        if isinstance(data, dict) and {
            "name", "llm_client_name", "base_url", "model",
        }.issubset(data):
            return None
        raise ValueError(f"Invalid Profile name pointer format: {path}")

    @staticmethod
    def _write_profile_name_pointer(path: Path, profile_name: str) -> None:
        """原子写入精确的 Profile 名称指针对象。"""
        if not isinstance(profile_name, str):
            raise TypeError("profile_name must be a string")
        write_text_atomic(
            path,
            json.dumps({"profile_name": profile_name}, ensure_ascii=False, indent=2),
        )

    def write_active_profile_name(self, session_id: str, profile_name: str) -> None:
        """写入会话级名称，并同步更新全局最近使用名称。"""
        self._write_profile_name_pointer(
            self.active_profile_name_path(session_id), profile_name,
        )
        self.write_global_profile_name(profile_name)

    def read_active_profile_name(self, session_id: str) -> str | None:
        """先读会话名称指针，缺失时回退全局名称指针。"""
        name = self._read_profile_name_pointer(
            self.active_profile_name_path(session_id),
        )
        if name is not None:
            return name
        return self.read_global_profile_name()

    def write_global_profile_name(self, profile_name: str) -> None:
        """写入全局最近使用 Profile 名称。"""
        self._write_profile_name_pointer(
            self.global_profile_name_path(), profile_name,
        )

    def read_global_profile_name(self) -> str | None:
        """读取全局最近使用 Profile 名称。"""
        return self._read_profile_name_pointer(
            self.global_profile_name_path(),
        )

    def iter_profile_pointer_files(self) -> list[Path]:
        """列出当前存在的全局及会话级 Profile 指针文件。"""
        paths: list[Path] = []
        global_path = self.global_profile_name_path()
        if global_path.is_file():
            paths.append(global_path)
        if not self.base_dir.is_dir():
            return paths
        for child in self.base_dir.iterdir():
            if not child.is_dir():
                continue
            candidate = child / SESSION_LLM_PROFILE_FILENAME
            if candidate.is_file():
                paths.append(candidate)
        return paths

    def replace_profile_name_pointers(
        self,
        old_name: str,
        new_name: str | None,
    ) -> list[Path]:
        """把所有新格式指针中的旧名称替换为目标名称。"""
        replacement = new_name or ""
        changed: list[Path] = []
        for path in self.iter_profile_pointer_files():
            current = self._read_profile_name_pointer(path)
            if current == old_name:
                self._write_profile_name_pointer(path, replacement)
                changed.append(path)
        return changed

    def copy_active_profile_name(self, old_session_id: str, new_session_id: str) -> None:
        """将来源会话的名称指针复制给延续会话。"""
        profile_name = self.read_active_profile_name(old_session_id)
        if profile_name is None:
            return
        self._write_profile_name_pointer(
            self.active_profile_name_path(new_session_id), profile_name,
        )
