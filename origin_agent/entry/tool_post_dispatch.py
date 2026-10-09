"""工具结果准备与通知分离；仅消息写入History，预订/通知保持进程内。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol
from pydantic import BaseModel, ConfigDict, PrivateAttr

from entity.messages import ToolResultMessage
from entity.puretype import Role, ToolCallMeta, ToolResultNotification
from entry.agent_support.multimodal import (
    tool_result_to_content, tool_result_to_follow_up, content_to_text, extract_tool_embedded_messages,
)
from abstract.tools.ui_event_router import UIEventRouter
from system.application import Application

if TYPE_CHECKING:
    from entry.agent_sink import AgentSink


class ResultFieldInjector(Protocol):
    def __call__(self, result: dict) -> dict | None: ...
    def bind_result(self, message: ToolResultMessage) -> None: ...
    def mark_appended(self, message: ToolResultMessage, history_index: int) -> None: ...
    def mark_persisted(self) -> None: ...
    def abort(self) -> None: ...


class PreparedToolResult(BaseModel):
    """带业务方法的临时提交对象；不交给easysave。"""

    model_config = ConfigDict(arbitrary_types_allowed=True)
    message: ToolResultMessage
    notification: ToolResultNotification | None = None
    evolution_requested: bool = False
    _injector: ResultFieldInjector | None = PrivateAttr(default=None)

    def bind_injector(self, injector: ResultFieldInjector | None) -> None:
        self._injector = injector
        if injector is not None:
            injector.bind_result(self.message)

    def mark_appended(self, history_index: int) -> None:
        if self._injector is not None:
            self._injector.mark_appended(self.message, history_index)

    def mark_persisted(self) -> None:
        if self._injector is not None:
            self._injector.mark_persisted()

    def abort(self) -> None:
        if self._injector is not None:
            self._injector.abort()

    async def emit(self, sink: AgentSink, ui_events: UIEventRouter) -> None:
        notice = self.notification
        if notice is None:
            return
        await sink.emit_tool_result(
            notice.session_id, notice.tool_name, notice.tool_call_id, notice.display_content,
            character_name=notice.character_name, tool_call_meta=notice.tool_call_meta.model_dump(),
            embedded_messages=notice.embedded_messages,
            consumed_client_message_ids=notice.consumed_client_message_ids,
        )
        await ui_events.emit_for(notice.tool_name, notice.ui_result, sink, notice.session_id)


def prepare_tool_result(
    result: dict, *, tool_name: str, application_time: str, application_time_ms: int,
    approval_duration_ms: int, invocation_start_offset_ms: int, invocation_duration_ms: int,
    end_time_offset_ms: int, session_id: str, tool_call_id: str, character_name: str,
    field_injector: ResultFieldInjector | None = None, evolution_requested: bool = False,
) -> PreparedToolResult:
    try:
        meta = ToolCallMeta(
            application_time=application_time, application_time_ms=application_time_ms,
            approval_duration_ms=approval_duration_ms, invocation_start_offset_ms=invocation_start_offset_ms,
            invocation_duration_ms=invocation_duration_ms, end_time_offset_ms=end_time_offset_ms,
        )
        result["_meta"] = meta.model_dump()
        if field_injector is not None:
            injected = field_injector(result)
            if injected:
                result.update(injected)
        embedded = extract_tool_embedded_messages(result)
        consumed = result.pop("consumed_client_message_ids", None)
        follow_up = None
        if "_user_blocks" in result:
            follow_up, content = tool_result_to_follow_up(result, character_name)
        else:
            content = tool_result_to_content(result)
        message = ToolResultMessage(role=Role.TOOL, character_name=character_name,
                                    tool_call_id=tool_call_id, content=content)
        message._follow_up_messages = follow_up
        prepared = PreparedToolResult(
            message=message,
            notification=ToolResultNotification(
                tool_name=tool_name, session_id=session_id, tool_call_id=tool_call_id,
                character_name=character_name, display_content=content_to_text(content),
                tool_call_meta=meta, embedded_messages=embedded,
                consumed_client_message_ids=consumed, ui_result=result,
            ),
            evolution_requested=evolution_requested,
        )
        prepared.bind_injector(field_injector)
        return prepared
    except BaseException:
        if field_injector is not None:
            field_injector.abort()
        raise


async def finalize_tool_result(
    result: dict, *, tool_name: str, application_time: str, application_time_ms: int,
    approval_duration_ms: int, invocation_start_offset_ms: int, invocation_duration_ms: int,
    end_time_offset_ms: int, sink: AgentSink, session_id: str, tool_call_id: str,
    character_name: str, field_injector: ResultFieldInjector | None = None,
) -> ToolResultMessage:
    """尚待S17迁移的子会话旧调用路径；主会话已使用prepare→store→emit。"""
    prepared = prepare_tool_result(
        result, tool_name=tool_name, application_time=application_time,
        application_time_ms=application_time_ms, approval_duration_ms=approval_duration_ms,
        invocation_start_offset_ms=invocation_start_offset_ms, invocation_duration_ms=invocation_duration_ms,
        end_time_offset_ms=end_time_offset_ms, session_id=session_id,
        tool_call_id=tool_call_id, character_name=character_name, field_injector=field_injector,
    )
    await prepared.emit(sink, Application.current().get_system(UIEventRouter))
    return prepared.message
