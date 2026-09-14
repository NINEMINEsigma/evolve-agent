"""会话级附带资源清理编排层。

由 ``gateway/server.py::delete_session`` 在会话永久删除时调用，依次清理
Shell会话、Cron 定时任务与动态端点。三类资源互不依赖，每步独立容错；
清理失败不回滚已完成的会话删除。
"""

from __future__ import annotations

import logging

from component.extools.cron_tools import cleanup_session_cron_jobs
from component.extools.dynamic_endpoint_tools import cleanup_session_endpoints

logger = logging.getLogger(__name__)


async def cleanup_session_resources(session_id: str) -> None:
    """异步清理指定主会话的 Shell、Cron 与动态端点。"""
    try:
        from system.application import Application

        stopped = await Application.current().shell_manager.stop_session(session_id)
        if stopped:
            logger.info(
                "Session cleanup: stopped %d Shell session(s) | session=%s",
                stopped,
                session_id,
            )
    except Exception:
        logger.warning(
            "Session cleanup: failed to stop Shell sessions | session=%s",
            session_id,
            exc_info=True,
        )

    try:
        cleanup_session_cron_jobs(session_id)
    except Exception:
        logger.warning(
            "Session cleanup: failed to cleanup cron jobs | session=%s",
            session_id,
            exc_info=True,
        )

    try:
        removed = cleanup_session_endpoints(session_id)
        if removed:
            logger.info(
                "Session cleanup: removed %d endpoint(s) | session=%s",
                removed,
                session_id,
            )
    except Exception:
        logger.warning(
            "Session cleanup: failed to cleanup endpoints | session=%s",
            session_id,
            exc_info=True,
        )
