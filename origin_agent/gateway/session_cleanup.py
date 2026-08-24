"""会话级附带资源清理编排层。

由 ``gateway/server.py::delete_session`` 在会话永久删除时调用，
集中清理三类会话级附带资源——后台任务、cron 定时任务、动态端点——
使会话删除彻底回收这些附带资源，避免孤儿残留。

清理顺序（依赖约束）：
    1. 后台任务（含 watching service）— watching 的 flusher 线程通过
       动态端点回调投递，端点是被 watching 引用的资源，须先停引用方。
    2. cron 定时任务 — 停 timer + 磁盘同步（复用现成函数）。
    3. 动态端点 — 清内存 + 磁盘（含幽灵条目）。

每步独立 try/except，失败仅记录 warning 不阻断——会话索引/目录已删，
清理失败不应回滚删除（与 delete_session 现有容错风格一致）。
"""

from __future__ import annotations

import logging

from component.extools.bg_registry import stop_session_background_tasks
from component.extools.cron_tools import cleanup_session_cron_jobs
from component.extools.dynamic_endpoint_tools import cleanup_session_endpoints

logger = logging.getLogger(__name__)


def cleanup_session_resources(session_id: str) -> None:
    """清理指定会话的三类附带资源（后台任务、cron、动态端点）。

    按依赖顺序调用，每步独立 try/except，失败记录 warning 不阻断。
    供 ``delete_session`` 在会话索引/目录删除、子 Agent 关闭之后调用，
    作为会话级收尾。
    """
    # 1. 先停引用方（含 watching 的 flusher 线程，其通过动态端点回调投递）
    try:
        stopped = stop_session_background_tasks(session_id)
        if stopped:
            logger.info(
                "Session cleanup: stopped %d background task(s) | session=%s",
                stopped, session_id,
            )
    except Exception:
        logger.warning(
            "Session cleanup: failed to stop background tasks | session=%s",
            session_id, exc_info=True,
        )

    # 2. 停 cron timer + 磁盘同步（复用现成函数）
    try:
        cleanup_session_cron_jobs(session_id)
    except Exception:
        logger.warning(
            "Session cleanup: failed to cleanup cron jobs | session=%s",
            session_id, exc_info=True,
        )

    # 3. 最后清被引用的端点（内存 + 磁盘，含幽灵条目）
    try:
        removed = cleanup_session_endpoints(session_id)
        if removed:
            logger.info(
                "Session cleanup: removed %d endpoint(s) | session=%s",
                removed, session_id,
            )
    except Exception:
        logger.warning(
            "Session cleanup: failed to cleanup endpoints | session=%s",
            session_id, exc_info=True,
        )