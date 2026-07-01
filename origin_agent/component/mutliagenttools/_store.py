"""多 Agent 工具层 — 全局子 Agent 注册表（持久化到磁盘）。

模块导入时自动从磁盘加载已有注册项。
同目录下各工具模块通过 ``_subagent_registry`` 读写，
写操作后需显式调用 ``_save_subagents()`` 落盘。
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from entity.constant import SUBAGENT_STORE_FILENAME
from system.atomic_io import write_text_atomic

logger = logging.getLogger(__name__)


# ── 持久化路径 ─────────────────────────────────────────────────────

def _get_store_path() -> Path:
    """返回子 Agent 注册表持久化文件路径。

    从 ``RuntimeContext.workspace`` 获取实际工作空间路径。
    RuntimeContext 未初始化时抛出 RuntimeError。
    """
    from system.context import get_runtime_context

    ctx = get_runtime_context()
    return ctx.workspace / SUBAGENT_STORE_FILENAME

# ── 内存注册表 ─────────────────────────────────────────────────────

# key: name, value: {"base_url": str, "model": str, "api_key": str | None}
_subagent_registry: dict[str, dict[str, Any]] = {}


# ── 持久化辅助 ─────────────────────────────────────────────────────


def _save_subagents() -> None:
    """将当前注册表原子写入磁盘。失败时抛出异常。"""
    store_path = _get_store_path()
    write_text_atomic(
        store_path,
        json.dumps(_subagent_registry, ensure_ascii=False, indent=2),
        tmp_suffix=".tmp",
    )


def _load_subagents() -> None:
    """从磁盘加载注册表到内存。失败时抛出异常。"""
    global _subagent_registry
    store_path = _get_store_path()
    if not store_path.exists():
        return
    raw = json.loads(store_path.read_text(encoding="utf-8"))
    if isinstance(raw, dict):
        _subagent_registry = raw
        logger.info("Loaded %d subagents from disk", len(_subagent_registry))


# ── 启动时自动加载 ─────────────────────────────────────────────────
_load_subagents()