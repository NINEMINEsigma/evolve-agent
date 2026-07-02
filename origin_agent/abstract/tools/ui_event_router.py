"""UI 事件路由器 — 工具模块在此注册自己的前端推送 handler。

工具文件通过模块级调用 ``ui_event_router.register(name, handler)``
注册工具名到 emit handler 的映射。``BasePrivateChatAgentLoop._execute_tool`` 执行完
工具后统一调用 ``ui_event_router.emit_for(...)``，无需感知具体工具名称

或推送方式。

handler 签名::

    async def handler(result: Any, sink: AgentSink, session_id: str, tool_name: str) -> None
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:
    from entry.agent_sink import AgentSink

logger = logging.getLogger(__name__)


class UIEventRouter:
    """工具名到 emit handler 的映射路由器。

    工具模块在注册工具时同步调用 ``register(tool_name, handler)``
    声明该工具的推送逻辑；执行层调用 ``emit_for()`` 完成分发。
    """

    def __init__(self) -> None:
        # tool_name → async handler(result, sink, session_id, tool_name)
        self._handlers: dict[str, Callable] = {}

    def register(self, tool_name: str, handler: Callable) -> None:
        """注册工具的前端推送 handler。

        Args:
            tool_name: 工具注册名（与 ``registry.register(name=...)`` 一致）。
            handler: 异步可调用对象，签名 ``(result, sink, session_id, tool_name) -> None``。
        """
        self._handlers[tool_name] = handler

    def get_handler(self, tool_name: str) -> Callable | None:
        """返回工具注册的 emit handler，未注册返回 None。"""
        return self._handlers.get(tool_name)

    async def emit_for(
        self,
        tool_name: str,
        result: Any,
        sink: AgentSink,
        session_id: str,
    ) -> None:
        """若工具已注册推送 handler，调用之。

        UI 推送失败是前端副作用，不应中断主工具执行流程；
        但必须记录异常，便于排查前端状态不一致问题。

        Args:
            tool_name: 刚执行的工具名。
            result: 工具 handler 返回的结果 dict。
            sink: 当前 loop 的 AgentSink 实例。
            session_id: 目标会话 ID。
        """
        handler = self._handlers.get(tool_name)
        if handler is None:
            return

        try:
            await handler(result, sink, session_id, tool_name)
        except Exception:
            logger.exception(
                "UIEventRouter: emit handler failed for tool=%s", tool_name,
            )


# 模块级单例
ui_event_router: UIEventRouter = UIEventRouter()