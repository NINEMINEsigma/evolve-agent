"""UI 事件路由器 — 工具模块在此声明其产生的前端事件类型。

工具文件通过模块级调用 ``ui_event_router.register(name, event_type)``
注册工具名到前端事件类型的映射。``BaseAgentLoop._execute_tool`` 执行完
工具后统一调用 ``ui_event_router.emit_for(...)``，无需感知具体工具名称。

内置事件类型：
- ``task_progress``        → 调用 ``sink.emit_progress()``
- ``clipboard_display``    → 调用 ``sink.emit_clipboard_display()``
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from entry.agent_sink import AgentSink

logger = logging.getLogger(__name__)


class UIEventRouter:
    """工具名到前端事件类型的映射路由器。

    工具模块在注册工具时同步调用 ``register()`` 声明该工具产生何种前端事件；
    执行层调用 ``emit_for()`` 完成实际推送。
    """

    def __init__(self) -> None:
        # tool_name → event_type
        self._mapping: dict[str, str] = {}
        # event_type → sink 方法名
        self._sink_methods: dict[str, str] = {
            "task_progress": "emit_progress",
            "clipboard_display": "emit_clipboard_display",
        }

    def register(self, tool_name: str, event_type: str) -> None:
        """注册工具名到前端事件类型的映射。

        Args:
            tool_name: 工具注册名（与 ``registry.register(name=...)`` 一致）。
            event_type: 前端事件类型，内置支持 ``task_progress`` / ``clipboard_display``。
        """
        if event_type not in self._sink_methods:
            logger.warning(
                "UIEventRouter: unknown event_type=%r for tool=%r, register anyway",
                event_type, tool_name,
            )
        self._mapping[tool_name] = event_type

    def get_event_type(self, tool_name: str) -> str | None:
        """返回工具注册的前端事件类型，未注册返回 None。"""
        return self._mapping.get(tool_name)

    async def emit_for(
        self,
        tool_name: str,
        result: Any,
        sink: AgentSink,
        session_id: str,
    ) -> None:
        """若工具已注册事件类型，向 sink 推送前端事件。

        异常静默吞没，避免影响主工具执行流程。

        Args:
            tool_name: 刚执行的工具名。
            result: 工具 handler 返回的结果 dict。
            sink: 当前 loop 的 AgentSink 实例。
            session_id: 目标会话 ID。
        """
        event_type = self._mapping.get(tool_name)
        if event_type is None:
            return

        method_name = self._sink_methods.get(event_type)
        if method_name is None:
            logger.warning("UIEventRouter: no sink method for event_type=%r", event_type)
            return

        payload = json.dumps(result, ensure_ascii=False)

        try:
            method = getattr(sink, method_name, None)
            if method is not None:
                await method(session_id, tool_name, payload)
        except Exception:
            logger.exception(
                "UIEventRouter: emit failed for tool=%s event=%s", tool_name, event_type,
            )


# 模块级单例
ui_event_router: UIEventRouter = UIEventRouter()