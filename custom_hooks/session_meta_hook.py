"""
会话元数据 hook。

在每轮用户消息中，通过 hook_message 注入：
1. 当前会话标题 + tags
2. 父子会话簇（主链遍历 + 多父合并标注）
3. 跨会话导航追踪（吸收原 session_track_hook 逻辑）

所有数据通过 Application.current().session_manager.get(sid) 获取 SessionInfo。
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from gateway.session_manager import SessionManager
    from entity.puretype import SessionInfo

logger = logging.getLogger(__name__)


def hook_tag_name(**kwargs) -> str:
    return "session_meta"


def _get_session_title(sid: str, sm: SessionManager) -> str:
    """获取会话标题，colloquy 会话强制返回 '随意聊聊'。"""
    from entity.constant import COLLOQUY_SESSION_ID
    if sid == COLLOQUY_SESSION_ID:
        return "随意聊聊"
    info = sm.get(sid)
    if info is None:
        return "(unknown)"
    return info.title or "(untitled)"


def _collect_merge_sources(
    info: SessionInfo | None,
    sm: SessionManager,
    visited: set[str],
) -> str:
    """收集 parents[1:] 的额外父会话标题，返回内联标注文本。

    多父合并场景下，parents[0] 是主父系（已在主链中），
    parents[1:] 是合并来源，以 '(also from: title1, title2)' 标注。
    """
    if not info or len(info.parents) <= 1:
        return ""
    extras: list[str] = []
    for ep_sid in info.parents[1:]:
        if ep_sid in visited:
            continue
        visited.add(ep_sid)
        extras.append(_get_session_title(ep_sid, sm))
    if not extras:
        return ""
    return f" (also from: {', '.join(extras)})"


def _build_cluster_tree(
    session_id: str,
    sm: SessionManager,
    visited: set[str] | None = None,
) -> list[tuple[str, int, bool]]:
    """
    构建会话簇树，返回 [(title, indent_level, is_current), ...] 的扁平列表。

    主链：沿 parents[0] 向上 → 当前 → 沿 continuation 向下。
    多父合并：对主链中每个节点，额外父会话以 '(also from: ...)' 内联标注。
    visited 全程共享，防止循环引用。
    """
    if visited is None:
        visited = set()
    if session_id in visited:
        return []
    visited.add(session_id)

    info = sm.get(session_id)
    if info is None:
        return []

    # ── 向上：沿 parents[0] 收集主祖先链 ──
    ancestor_stack: list[str] = []
    current_info = info
    while current_info and current_info.parents:
        parent_sid = current_info.parents[0]
        if parent_sid in visited or parent_sid == session_id:
            break
        parent_info = sm.get(parent_sid)
        if parent_info is None:
            break
        visited.add(parent_sid)
        ancestor_stack.append(parent_sid)
        current_info = parent_info

    # ── 向下：沿 continuation 收集后代链 ──
    descendant_chain: list[str] = []
    cont_sid = info.continuation
    while cont_sid and cont_sid not in visited and cont_sid != session_id:
        cont_info = sm.get(cont_sid)
        if cont_info is None:
            break
        visited.add(cont_sid)
        descendant_chain.append(cont_sid)
        cont_sid = cont_info.continuation

    # ── 构建扁平列表：祖先（远→近）→ 当前 → 后代 ──
    result: list[tuple[str, int, bool]] = []

    # 祖先：从最远到最近，缩进递增
    for i, anc_sid in enumerate(reversed(ancestor_stack)):
        level = i
        anc_info = sm.get(anc_sid)
        merge_note = _collect_merge_sources(anc_info, sm, visited)
        title = _get_session_title(anc_sid, sm) + merge_note
        result.append((title, level, False))

    # 当前会话
    current_level = len(ancestor_stack)
    merge_note = _collect_merge_sources(info, sm, visited)
    current_title = _get_session_title(session_id, sm) + merge_note
    result.append((current_title, current_level, True))

    # 后代：缩进递增
    for i, desc_sid in enumerate(descendant_chain):
        level = current_level + 1 + i
        desc_info = sm.get(desc_sid)
        merge_note = _collect_merge_sources(desc_info, sm, visited)
        title = _get_session_title(desc_sid, sm) + merge_note
        result.append((title, level, False))

    return result


def _format_cluster(cluster: list[tuple[str, int, bool]]) -> str:
    """将会话簇扁平列表格式化为树状缩进文本。"""
    if not cluster:
        return ""
    lines: list[str] = []
    for title, level, is_current in cluster:
        prefix = "  " * level + "- "
        if is_current:
            lines.append(f"{prefix}← Current: {title}")
        else:
            lines.append(f"{prefix}{title}")
    return "\n".join(lines)


def _format_navigation(session_id: str, workspace: str) -> str:
    """
    跨会话导航追踪（吸收原 session_track_hook 逻辑）。
    使用全局 cache 文件 session_meta_hook.json。
    """
    cache_path: Path = Path(workspace) / "session_cache" / "session_meta_hook.json"
    cache_path.parent.mkdir(parents=True, exist_ok=True)

    if not cache_path.exists():
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump({"session_queue": [session_id]}, f, ensure_ascii=False)
        return ""

    with open(cache_path, "r", encoding="utf-8") as f:
        cache_data = json.load(f)

    session_queue: list[str] = cache_data["session_queue"]

    if session_id not in session_queue:
        session_queue.append(session_id)
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump({"session_queue": session_queue}, f, ensure_ascii=False)
        return ""

    between_sessions = session_queue[session_queue.index(session_id) + 1:]
    session_queue.remove(session_id)
    session_queue.append(session_id)
    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump({"session_queue": session_queue}, f, ensure_ascii=False)

    if not between_sessions:
        return ""

    return (
        "Between this message and the user's previous message, "
        f"the user was also chatting in the following conversations: "
        f"{', '.join(between_sessions)}"
    )


def hook_message(session_id: str = "", workspace: str = "", **kwargs) -> str:
    try:
        from system.application import Application
        from entity.constant import COLLOQUY_SESSION_ID

        sm = Application.current().session_manager
        info = sm.get(session_id)
        if info is None:
            return ""

        # 标题处理
        title = "随意聊聊" if session_id == COLLOQUY_SESSION_ID else (info.title or "(untitled)")

        # tags 处理
        tags_str = f" [{', '.join(info.tags)}]" if info.tags else ""

        # 会话簇
        cluster = _build_cluster_tree(session_id, sm)
        cluster_text = _format_cluster(cluster)

        # 导航追踪
        nav_text = _format_navigation(session_id, workspace)

        # 拼接
        parts: list[str] = [f"Session: {title}{tags_str}"]
        if cluster_text:
            parts.append(f"Cluster:\n{cluster_text}")
        if nav_text:
            parts.append(f"Navigation: {nav_text}")

        return "\n".join(parts)
    except Exception:
        logger.debug("session_meta_hook failed", exc_info=True)
        return ""