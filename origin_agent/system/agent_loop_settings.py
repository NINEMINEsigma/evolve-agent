"""全局工具循环配置的独立持久化叶服务。"""

from __future__ import annotations

import os
from pathlib import Path
import tempfile
import threading

from easysave import contains, load, save

from entity.constant import (
    AGENT_LOOP_SETTINGS_ES_KEY,
    MAX_CONFIGURABLE_TOOL_TURNS,
    MAX_TOOL_TURNS,
    MIN_TOOL_TURNS,
)
from entity.puretype.agent_settings import AgentLoopSettingsData, AgentLoopSettingsState
from entity.typeref import make_config
from util.atomic_io import replace_atomic


class AgentLoopSettingsStore:
    """由RuntimeSystem唯一持有；无后台任务、无Application查询。"""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = threading.RLock()
        self._data: AgentLoopSettingsData | None = None

    def initialize(self) -> None:
        with self._lock:
            if self._data is not None:
                raise RuntimeError("Agent loop settings have already been initialized")
            self._check_backup()
            if not self._path.exists():
                self._data = AgentLoopSettingsData()
                return
            config = make_config(self._path)
            if not contains(AGENT_LOOP_SETTINGS_ES_KEY, config):
                raise ValueError(
                    f"Agent loop settings {self._path} have no supported "
                    f"{AGENT_LOOP_SETTINGS_ES_KEY!r} key; manual migration is required"
                )
            data = load(AGENT_LOOP_SETTINGS_ES_KEY, config, AgentLoopSettingsData)
            if not isinstance(data, AgentLoopSettingsData):
                raise TypeError(f"Invalid agent loop settings root in {self._path}")
            # easysave通过model_construct还原，必须显式校验已知字段。
            self._validate_value(data.max_tool_turns)
            self._data = data

    def _check_backup(self) -> None:
        backup = self._path.with_name(f"{self._path.name}.bak")
        if backup.exists():
            raise FileExistsError(
                f"Agent loop settings backup requires manual inspection: {backup}"
            )

    def _validate_value(self, value: int | None) -> None:
        if value is None:
            return
        if type(value) is not int:
            raise ValueError(f"max_tool_turns must be an integer or null in {self._path}")
        if not MIN_TOOL_TURNS <= value <= MAX_CONFIGURABLE_TOOL_TURNS:
            raise ValueError(
                f"max_tool_turns must be between {MIN_TOOL_TURNS} and "
                f"{MAX_CONFIGURABLE_TOOL_TURNS} in {self._path}"
            )

    def _require_data(self) -> AgentLoopSettingsData:
        if self._data is None:
            raise RuntimeError("Agent loop settings have not been initialized")
        return self._data

    @property
    def max_tool_turns(self) -> int:
        with self._lock:
            value = self._require_data().max_tool_turns
            return MAX_TOOL_TURNS if value is None else value

    def get_state(self) -> AgentLoopSettingsState:
        with self._lock:
            value = self._require_data().max_tool_turns
            return AgentLoopSettingsState(
                max_tool_turns=value,
                effective_max_tool_turns=MAX_TOOL_TURNS if value is None else value,
                default_max_tool_turns=MAX_TOOL_TURNS,
            )

    def set_max_tool_turns(self, value: int | None) -> AgentLoopSettingsState:
        with self._lock:
            self._validate_value(value)
            self._check_backup()
            if self._require_data().max_tool_turns == value:
                return self.get_state()
            candidate = AgentLoopSettingsData(max_tool_turns=value)
            self._save_unlocked(candidate)
            # 正式替换成功后无await/磁盘清理，立即发布同一候选根。
            self._data = candidate
            return self.get_state()

    def _save_unlocked(self, candidate: AgentLoopSettingsData) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(
            prefix=f"{self._path.name}.", suffix=".tmp", dir=str(self._path.parent),
        )
        temp_path = Path(temp_name)
        backup = temp_path.with_name(f"{temp_path.name}.bak")
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(self._path.read_bytes() if self._path.exists() else b"{}")
            # easysave内部提交及清理只接触本次外层临时路径，保留BaseModel类型。
            save(AGENT_LOOP_SETTINGS_ES_KEY, make_config(temp_path), candidate)
            if backup.exists():
                raise FileExistsError(f"Temporary settings backup was retained: {backup}")
            replace_atomic(temp_path, self._path)
        except BaseException as original_error:
            # 只清理本次拥有的临时资源；绝不删除正式目标的冲突备份。
            failures: list[BaseException] = [original_error]
            for owned_path in (temp_path, backup):
                try:
                    owned_path.unlink(missing_ok=True)
                except BaseException as cleanup_error:
                    failures.append(cleanup_error)
            if len(failures) > 1:
                raise BaseExceptionGroup("Agent loop settings save and cleanup failed", failures)
            raise
