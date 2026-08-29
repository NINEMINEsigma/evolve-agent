"""CronRouter — 将 cron 任务结果路由到对应 loop 的收件箱，并管理任务注册表。

替代 ``component/extools/cron_tools.py`` 中的全局 ``_cron_tasks`` 注册表和 ``_cron_event_callbacks`` 列表。
通过 ``Application.cron_router`` 访问，按 session_id 或 runtime 路由结果。
"""

from __future__ import annotations

import logging
import threading
from typing import Any, TYPE_CHECKING

from entity.constant import SYSTEM_CHARACTER_NAME

if TYPE_CHECKING:
    from entry.base_agent_loop import BaseAgentLoop

logger = logging.getLogger(__name__)


class CronRouter:
    """按 session_id 或 runtime 将 cron 结果投递到对应 loop 的 inbox。

    生命周期由 ``Application.cron_router`` 管理。
    持有 ``_tasks`` 注册表，替代 ``cron_tools.py`` 的模块级 ``_cron_tasks`` 全局变量。
    """

    def __init__(self) -> None:
        # session_id → loop 映射（loop 存活时投递，loop 消亡则丢弃）
        self._routes: dict[str, BaseAgentLoop] = {}
        # 任务注册表：session_id → task_id → _CronTask
        self._tasks: dict[str, dict[str, Any]] = {}
        self._lock: threading.RLock = threading.RLock()

    def locked(self):
        """返回底层锁，供 ``with cron_router.locked():`` 使用。"""
        return self._lock

    # -- 路由管理 ----------------------------------------------------------------

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
        """投递 cron 结果到对应 loop。

        SP-5 D7：主会话 loop（有 _message_queue）走队列 push；
        子 agent loop（无 _message_queue）保留 inbox 投递 + TODO 注释。

        Returns:
            True 表示成功投递，False 表示无对应 loop。
        """
        loop = self._routes.get(session_id)
        if loop is None:
            logger.debug("CronRouter: no loop for session=%s, discarding result", session_id)
            return False

        status = "completed" if exit_code == 0 else f"failed (exit={exit_code})"
        text = f"[cron-result] {name} ({task_id}) — {status}\n{stdout_preview}"

        queue = loop._message_queue
        if queue is not None:
            # 主会话：走会话消息队列
            queue.push(text, character_name=SYSTEM_CHARACTER_NAME, source="cron")
            logger.debug("CronRouter: dispatched %s to session=%s via queue", task_id, session_id)
        else:
            # TODO(SP-5): SubAgentLoop 暂无会话消息队列，cron 结果暂保留 inbox 投递；
            #             后续统一队列时收编。
            from entry.base_agent_loop import UserMessage
            loop.inbox.put(UserMessage(content=text, character_name=SYSTEM_CHARACTER_NAME))
            loop.inbox.wake()
            logger.debug("CronRouter: dispatched %s to session=%s via inbox", task_id, session_id)
            try:
                loop.schedule_inbox_processing()
            except Exception:
                logger.exception(
                    "Failed to schedule inbox processing for session=%s", session_id,
                )
        return True

    # -- 任务注册表管理 ----------------------------------------------------------

    def add_task(self, session_id: str, task_id: str, task: Any) -> None:
        """向注册表添加一个任务。"""
        if session_id not in self._tasks:
            self._tasks[session_id] = {}
        self._tasks[session_id][task_id] = task

    def get_task(self, session_id: str, task_id: str) -> Any | None:
        """获取指定任务，不存在时返回 None。"""
        return self._tasks.get(session_id, {}).get(task_id)

    def remove_task(self, session_id: str, task_id: str) -> Any | None:
        """从注册表移除并返回指定任务。"""
        session_tasks = self._tasks.get(session_id)
        if session_tasks:
            return session_tasks.pop(task_id, None)
        return None

    def get_session_tasks(self, session_id: str) -> dict[str, Any]:
        """返回指定 session 的所有任务。"""
        return self._tasks.get(session_id, {})

    def get_all_tasks(self) -> dict[str, dict[str, Any]]:
        """返回所有任务注册表的快照。"""
        return {sid: dict(tasks) for sid, tasks in self._tasks.items()}

    def pop_session_tasks(self, session_id: str) -> dict[str, Any]:
        """弹出并返回指定 session 的所有任务。"""
        return self._tasks.pop(session_id, {})

    # -- 生命周期 ----------------------------------------------------------------

    async def shutdown(self) -> None:
        """清理所有路由和任务。"""
        self._routes.clear()
        self._tasks.clear()
        logger.info("CronRouter shutdown")