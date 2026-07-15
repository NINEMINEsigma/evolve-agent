"""记忆工具共享逻辑层 — 会话隔离 + 父链继承。

通过 easysave 的对象引用机制实现子会话对父会话记忆的继承：
  - data 字典的外层 key 为 session_id
  - 内层 dict 的 __parents__ 字段是一个 list，包含对父会话记忆 dict 的同一 Python 对象引用
  - easysave 检测到同一对象被多处引用时自动序列化为 __ref::hash 节点，加载后恢复为同一对象

这样 forget 可以直接沿 __parents__ 引用链搜索并在父会话的 dict 中删除条目，
修改会反映到所有引用该父会话的子会话。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from easysave import load, save

logger = logging.getLogger(__name__)

# easysave key — 所有会话的记忆存储在同一个 key 下
__VERSION__ = "v1"

# 内层 dict 中保留的父引用字段名
PARENTS_KEY = "__parents__"

# session_id 为空时的 fallback key
FALLBACK_SESSION = "default"


def load_all_memory(path: str | Path) -> dict[str, dict[str, str]]:
    """从文件加载整个 data 字典。

    文件不存在或 key 不存在时返回空 dict。
    """
    try:
        return load(__VERSION__, str(path), dict[str, dict[str, str]])
    except (FileNotFoundError, KeyError):
        return {}
    except Exception:
        logger.warning("Failed to load memory data", exc_info=True)
        return {}


def save_all_memory(path: str | Path, data: dict[str, dict[str, str]]) -> None:
    """保存整个 data 字典到文件。"""
    save(__VERSION__, str(path), data)


def get_parent_ids(session_id: str) -> list[str]:
    """通过 Application 单例获取父会话 ID 列表。

    任何异常或不可用时返回空列表。
    """
    try:
        from system.application import Application
        app = Application.current()
        if app.session_manager is None:
            return []
        info = app.session_manager.get(session_id)
        if info is None:
            return []
        return list(info.parents)
    except Exception:
        logger.debug("Failed to get parent ids for session %s", session_id, exc_info=True)
        return []


def _get_or_create_session_dict(
    data: dict[str, dict[str, str]],
    session_id: str,
) -> dict[str, str]:
    """获取或创建指定会话的记忆 dict（不设置 __parents__）。"""
    if session_id not in data:
        data[session_id] = {}
    return data[session_id]


def ensure_session_memory(
    data: dict[str, dict[str, str]],
    session_id: str,
) -> dict[str, str]:
    """获取或创建当前会话的记忆 dict，并刷新 __parents__ 引用列表。

    只引用已在 data 中存在的父会话 dict（不创建空父 dict）。
    返回当前会话的 dict。
    """
    session_mem = _get_or_create_session_dict(data, session_id)

    parent_ids = get_parent_ids(session_id)
    # 只引用已在 data 中存在的父会话 dict，不为不存在的父会话创建空 dict
    # 否则 hook 的只读操作会在内存中产生空父 dict，后续 save 会将其持久化
    parent_refs: list[dict[str, str]] = []
    for pid in parent_ids:
        if pid in data:
            parent_refs.append(data[pid])

    if parent_refs:
        session_mem[PARENTS_KEY] = parent_refs  # type: ignore[assignment]
    elif PARENTS_KEY in session_mem:
        del session_mem[PARENTS_KEY]

    return session_mem


def collect_merged_memory(
    data: dict[str, dict[str, str]],
    session_id: str,
) -> dict[str, str]:
    """BFS 遍历 __parents__ 引用链，合并所有记忆。

    遍历顺序：当前会话 → 直接父们 → 祖父们 ...
    合并顺序：反转 BFS 顺序后逐层合并（子覆盖父，多父按列表顺序后到优先）。
    排除 PARENTS_KEY。用 id() 做 visited 防止循环引用。
    """
    if session_id not in data:
        return {}

    # BFS 按对象引用遍历，记录访问顺序
    visited: set[int] = set()
    bfs_order: list[dict[str, str]] = []

    queue: list[dict[str, str]] = [data[session_id]]
    while queue:
        current = queue.pop(0)
        obj_id = id(current)
        if obj_id in visited:
            continue
        visited.add(obj_id)
        bfs_order.append(current)

        parents = current.get(PARENTS_KEY)
        if isinstance(parents, list):
            for parent in parents:
                if isinstance(parent, dict) and id(parent) not in visited:
                    queue.append(parent)

    # 反转后逐层合并：最远的祖先最先，当前会话最后（覆盖父）
    merged: dict[str, str] = {}
    for layer_dict in reversed(bfs_order):
        for key, value in layer_dict.items():
            if key == PARENTS_KEY:
                continue
            merged[key] = value

    return merged


def find_key_in_chain(
    data: dict[str, dict[str, str]],
    session_id: str,
    key: str,
) -> dict[str, str] | None:
    """BFS 从当前会话搜索第一个包含 key 的 dict（含父链）。

    返回找到的 dict 对象（可能是父会话的 dict），用于 forget。
    排除 PARENTS_KEY 作为搜索目标。
    """
    if session_id not in data:
        return None
    if key == PARENTS_KEY:
        return None

    visited: set[int] = set()
    queue: list[dict[str, str]] = [data[session_id]]

    while queue:
        current = queue.pop(0)
        obj_id = id(current)
        if obj_id in visited:
            continue
        visited.add(obj_id)

        if key in current and key != PARENTS_KEY:
            return current

        parents = current.get(PARENTS_KEY)
        if isinstance(parents, list):
            for parent in parents:
                if isinstance(parent, dict) and id(parent) not in visited:
                    queue.append(parent)

    return None


def format_memory_text(merged: dict[str, str]) -> str:
    """将合并后的记忆 dict 格式化为 'id: content' 行。"""
    if not merged:
        return ""
    return "\n".join([f"{k}: {v}" for k, v in merged.items()])