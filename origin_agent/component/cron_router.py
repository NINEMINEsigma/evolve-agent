"""CronRouter — 将 cron 任务结果路由到对应 loop 的收件箱。

替代 ``component/extools/cron_tools.py`` 中的全局 ``_cron_event_callbacks`` 列表。
通过 ``Application.cron_router`` 访问，按 session_id 或 runtime 路由结果。
"""

from __future__ import annotations

import logging
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from entry.base_agent_loop import BaseAgentLoop, CronResultMessage

logger = logging.getLogger(__name__)


class CronRouter:
    """按 session_id 或 runtime 将 cron 结果投递到对应 loop 的 inbox。

    生命周期由 ``Application.cron_router`` 管理。
    """

    def __init__(self) -> None:
        # session_id → loop 的弱引用映射（loop 存活时投递，loop 消亡则丢弃）
        self._routes: dict[str, BaseAgentLoop] = {}

    def register(self, session_id: str, loop: BaseAgentLoop) -> None:
        """注册 session 对应的 loop，cron 结果将投递到 loop.inbox。"""
        self._routes[session_id] = loop

    def unregister(self, session_id: str) -> None:
        """移除 session 的路由。"""
        self._routes.pop(session_id, None)

    def dispatch(
        self,
        session_id: str,
        task_id: str,
        name: str,
        exit_code: int,
        stdout_preview: str,
    ) -> bool:
        """投递 cron 结果到对应 loop 的 inbox。

        Returns:
            True 表示成功投递，False 表示无对应 loop。
        """
        loop = self._routes.get(session_id)
        if loop is None:
            logger.debug("CronRouter: no loop for session=%s, discarding result", session_id)
            return False

        from entry.base_agent_loop import CronResultMessage
        msg = CronResultMessage(
            task_id=task_id,
            name=name,
            exit_code=exit_code,
            stdout_preview=stdout_preview,
        )
        loop.inbox.put(msg)
        loop.inbox.wake()
        logger.debug("CronRouter: dispatched %s to session=%s", task_id, session_id)
        return True

    async def shutdown(self) -> None:
        """清理所有路由。"""
        self._routes.clear()
        logger.info("CronRouter shutdown")