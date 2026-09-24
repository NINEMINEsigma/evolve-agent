"""会话级审批模式的内存状态与持久化服务。"""

from __future__ import annotations

import logging
from pathlib import Path
import threading

from easysave import load, save
from entity.constant import (
    SESSION_APPROVAL_MODE_ES_FILENAME,
    SESSION_APPROVAL_MODE_ES_KEY,
)
from entity.puretype import ApprovalMode, SessionApprovalModeState
from entity.typeref import make_config

logger = logging.getLogger(__name__)


class ApprovalModeStore:
    """管理所有主会话的审批模式，并按会话尽力持久化。"""

    def __init__(self, sessions_dir: Path | str) -> None:
        self._sessions_dir = Path(sessions_dir)
        self._modes: dict[str, ApprovalMode] = {}
        self._lock = threading.RLock()

    @staticmethod
    def _validate_session_id(session_id: str) -> None:
        if (
            not session_id
            or session_id in {".", ".."}
            or "/" in session_id
            or "\\" in session_id
            or Path(session_id).name != session_id
        ):
            raise ValueError(f"Invalid session ID for approval mode: {session_id!r}")

    def _mode_path(self, session_id: str) -> Path:
        self._validate_session_id(session_id)
        return self._sessions_dir / session_id / SESSION_APPROVAL_MODE_ES_FILENAME

    def _load_mode_unlocked(self, session_id: str) -> ApprovalMode:
        path = self._mode_path(session_id)
        if not path.exists():
            return ApprovalMode.MANUAL
        try:
            state = load(
                SESSION_APPROVAL_MODE_ES_KEY,
                make_config(path),
                SessionApprovalModeState,
                ignore_missing_fields=True,
            )
            if not isinstance(state, SessionApprovalModeState):
                raise TypeError(
                    "Approval mode root must be SessionApprovalModeState"
                )
            if not hasattr(state, "mode") or not isinstance(state.mode, ApprovalMode):
                raise TypeError("Approval mode state must contain an ApprovalMode")
            return state.mode
        except Exception:
            logger.warning(
                "Failed to load approval mode; using manual | session=%s path=%s",
                session_id,
                path,
                exc_info=True,
            )
            return ApprovalMode.MANUAL

    def _persist_mode_unlocked(
        self,
        session_id: str,
        mode: ApprovalMode,
    ) -> None:
        path = self._mode_path(session_id)
        state = SessionApprovalModeState(mode=mode)
        save(SESSION_APPROVAL_MODE_ES_KEY, make_config(path), state)

    def _persist_best_effort_unlocked(
        self,
        session_id: str,
        mode: ApprovalMode,
    ) -> None:
        try:
            self._persist_mode_unlocked(session_id, mode)
        except Exception:
            logger.warning(
                "Failed to persist approval mode | session=%s mode=%s path=%s",
                session_id,
                mode.value,
                self._mode_path(session_id),
                exc_info=True,
            )

    def get_mode(self, session_id: str) -> ApprovalMode:
        """返回会话模式；首次访问时从磁盘惰性恢复。"""
        self._validate_session_id(session_id)
        with self._lock:
            cached = self._modes.get(session_id)
            if cached is not None:
                return cached
            mode = self._load_mode_unlocked(session_id)
            self._modes[session_id] = mode
            return mode

    def initialize_session(self, session_id: str) -> ApprovalMode:
        """把新主会话显式初始化为手动模式。"""
        return self.set_mode(session_id, ApprovalMode.MANUAL)

    def set_mode(
        self,
        session_id: str,
        mode: ApprovalMode,
    ) -> ApprovalMode:
        """先更新内存模式，再尽力原子写入磁盘。"""
        self._validate_session_id(session_id)
        actual = mode if isinstance(mode, ApprovalMode) else ApprovalMode(mode)
        with self._lock:
            self._modes[session_id] = actual
            self._persist_best_effort_unlocked(session_id, actual)
        return actual

    def forget_session(self, session_id: str) -> None:
        """永久删除会话后，幂等移除对应的内存缓存。"""
        self._validate_session_id(session_id)
        with self._lock:
            self._modes.pop(session_id, None)

    def reset_all_non_manual_modes(self) -> list[str]:
        """显式把所有现存会话的非手动模式重置为手动模式。"""
        with self._lock:
            session_ids = set(self._modes)
            sessions_root_exists = self._sessions_dir.exists()
            if sessions_root_exists:
                try:
                    children = list(self._sessions_dir.iterdir())
                except Exception:
                    logger.warning(
                        "Failed to enumerate approval mode session directories | root=%s",
                        self._sessions_dir,
                        exc_info=True,
                    )
                    children = []
                for child in children:
                    try:
                        if not child.is_dir():
                            continue
                        self._validate_session_id(child.name)
                        session_ids.add(child.name)
                    except Exception:
                        logger.warning(
                            "Skipping invalid approval mode session directory | path=%s",
                            child,
                            exc_info=True,
                        )

            reset: list[str] = []
            for session_id in sorted(session_ids):
                try:
                    mode = self._modes.get(session_id)
                    if mode is None:
                        mode = self._load_mode_unlocked(session_id)
                        self._modes[session_id] = mode
                    if mode == ApprovalMode.MANUAL:
                        continue
                    self._modes[session_id] = ApprovalMode.MANUAL
                    if sessions_root_exists:
                        self._persist_best_effort_unlocked(
                            session_id,
                            ApprovalMode.MANUAL,
                        )
                    reset.append(session_id)
                except Exception:
                    logger.warning(
                        "Failed to reset approval mode | session=%s",
                        session_id,
                        exc_info=True,
                    )
            return reset
