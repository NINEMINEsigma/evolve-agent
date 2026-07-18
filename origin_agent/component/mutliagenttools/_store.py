"""多 Agent 工具层 — 子 Agent 注册表磁盘存储。

每个子 Agent 独立持久化到 ``agentspace/subagents/<name>.es``，
并通过 ``agentspace/subagents/_index.json`` 维护已注册名称列表。
序列化/反序列化通过 easysave 实现，使用版本 key 隔离格式版本。
所有访问通过 ``SubagentStore`` CRUD API，禁止直接操作内部数据结构。
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from easysave import save, load

from entity.constant import (
    SUBAGENT_DIR_NAME,
    SUBAGENT_INDEX_FILENAME,
    SUBAGENT_SETTING_SUFFIX,
)
from entity.puretype import AgentConfig
from system.atomic_io import write_text_atomic

logger = logging.getLogger(__name__)

# easysave 版本 key — 用于序列化格式版本隔离
__VERSION__ = "v1"


class SubagentStore:
    """子 Agent 注册表磁盘存储。

    每次操作均真实读写磁盘，不维护内存缓存。
    """

    def __init__(self, agentspace: Path | str) -> None:
        self._agentspace = Path(agentspace)

    # ── 路径辅助 ─────────────────────────────────────────────────────

    def _subagents_dir(self) -> Path:
        """返回子 Agent 配置存放目录。"""
        return self._agentspace / SUBAGENT_DIR_NAME

    def _setting_path(self, name: str) -> Path:
        """返回指定 name 的 setting 文件路径。"""
        return self._subagents_dir() / f"{name}{SUBAGENT_SETTING_SUFFIX}"

    def _index_path(self) -> Path:
        """返回索引文件路径。"""
        return self._subagents_dir() / SUBAGENT_INDEX_FILENAME

    # ── 公开 CRUD ────────────────────────────────────────────────────

    def get(self, name: str) -> AgentConfig | None:
        """读取指定 name 的配置。

        Returns:
            AgentConfig 实例；文件不存在或版本 key 不匹配时返回 None；反序列化损坏时抛出 ValueError。
        """
        path = self._setting_path(name)
        if not path.exists():
            return None
        try:
            return load(__VERSION__, str(path), AgentConfig)
        except (FileNotFoundError, KeyError):
            # 文件不存在或版本 key 不匹配（旧格式）
            return None
        except Exception as exc:
            raise ValueError(f"Corrupted setting file for subagent '{name}': {exc}") from exc

    def list(self) -> dict[str, AgentConfig]:
        """返回所有有效子 Agent 配置。

        读取索引后逐个校验对应 setting 文件；缺失或损坏的 name 会被
        从索引中移除并写回。
        """
        names = self._read_index()
        valid: dict[str, AgentConfig] = {}
        stale: list[str] = []

        for name in names:
            try:
                profile = self.get(name)
            except ValueError:
                logger.warning("Removing stale subagent '%s' due to corrupted setting", name)
                stale.append(name)
                continue
            if profile is None:
                logger.warning("Removing stale subagent '%s' with missing setting file", name)
                stale.append(name)
                continue
            valid[name] = profile

        if stale:
            cleaned = [n for n in names if n not in stale]
            self._write_index(cleaned)

        return valid

    def add(self, name: str, profile: AgentConfig) -> None:
        """新增一个子 Agent 配置。

        若对应 setting 文件已存在则抛出 ``FileExistsError``，不覆盖。
        写入 setting 文件后更新索引。

        TODO: 如果观测到并发注册冲突，请在此引入 threading.RLock。
        """
        path = self._setting_path(name)
        if path.exists():
            raise FileExistsError(f"Subagent '{name}' already exists.")

        self._subagents_dir().mkdir(parents=True, exist_ok=True)
        save(__VERSION__, str(path), profile)
        logger.info("Persisted setting for subagent: %s", name)

        names = self._read_index()
        if name not in names:
            names.append(name)
            self._write_index(names)

    def remove(self, name: str) -> bool:
        """删除指定 name 的子 Agent 配置及索引项。

        返回是否实际删除了 setting 文件。

        TODO: 如果观测到并发注销冲突，请在此引入 threading.RLock。
        """
        path = self._setting_path(name)
        existed = path.exists()
        if existed:
            path.unlink()
            logger.info("Removed setting for subagent: %s", name)

        names = self._read_index()
        if name in names:
            names.remove(name)
            self._write_index(names)

        return existed

    # ── 索引读写 ─────────────────────────────────────────────────────

    def _read_index(self) -> list[str]:
        """读取索引文件；不存在或损坏时返回空列表。"""
        path = self._index_path()
        if not path.exists():
            return []
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            logger.warning("Corrupted subagent index, treating as empty: %s", exc)
            return []
        if not isinstance(raw, list):
            logger.warning("Invalid subagent index format, treating as empty")
            return []
        return [str(item) for item in raw if isinstance(item, str)]

    def _write_index(self, names: list[str]) -> None:
        """原子写入索引文件。"""
        self._subagents_dir().mkdir(parents=True, exist_ok=True)
        write_text_atomic(
            self._index_path(),
            json.dumps(names, ensure_ascii=False, indent=2),
            tmp_suffix=".tmp",
        )