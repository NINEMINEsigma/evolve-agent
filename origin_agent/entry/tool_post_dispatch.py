"""工具结果准备与通知分离；仅消息写入History，预订/通知保持进程内。"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Protocol
from collections.abc import Awaitable
from pydantic import BaseModel, ConfigDict, PrivateAttr

from entity.messages import ToolResultMessage
from entity.puretype import Role, ToolCallMeta, ToolResultNotification
from abstract.tools.tool import ToolExecution, ToolPostprocessEffect
from entry.agent_support.multimodal import (
    tool_result_to_content, tool_result_to_follow_up, content_to_text, extract_tool_embedded_messages,
)

if TYPE_CHECKING:
    from entry.agent_sink import AgentSink
    from entry.base_agent_loop import BaseAgentLoop


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
    execution: ToolExecution | None = None
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

    def update_result_payload(self, result: dict) -> None:
        """Update the stored result and notification without losing input reservations."""
        payload = dict(result)
        notice = self.notification
        if notice is not None:
            payload["_meta"] = notice.tool_call_meta.model_dump()
            if "_queued_messages" in notice.ui_result:
                payload["_queued_messages"] = notice.ui_result["_queued_messages"]
        content = tool_result_to_content(payload, tool_call_id=self.message.tool_call_id)
        self.message.content = content
        if notice is not None:
            notice.display_content = content_to_text(content)
            notice.ui_result = payload
        if self.execution is not None:
            self.execution.result = payload

    async def emit(self, sink: AgentSink) -> None:
        notice = self.notification
        if notice is None:
            return
        await sink.emit_tool_result(
            notice.session_id, notice.tool_name, notice.tool_call_id, notice.display_content,
            character_name=notice.character_name, tool_call_meta=notice.tool_call_meta.model_dump(),
            embedded_messages=notice.embedded_messages,
            consumed_client_message_ids=notice.consumed_client_message_ids,
        )


class ToolPostprocessor:
    """Invocation postprocessing shared by main, multi, sub and task Loops."""

    def __init__(self, loop: BaseAgentLoop) -> None:
        from system.runtime import RuntimeSystem

        self._loop = loop
        self._runtime = loop.app.get_system(RuntimeSystem)
        self._cancel_cleanup_tasks: set[asyncio.Future] = set()

    async def _await_phase(self, operation: Awaitable[ToolPostprocessEffect]) -> ToolPostprocessEffect:
        # 复用有界取消交接，不把包装 await 的结束冒充真实工作完成。
        from entry.tool_executor import cancel_tool_wait

        task = asyncio.ensure_future(operation)
        cancel_wait = asyncio.create_task(self._loop.cancel_event.wait())
        try:
            done, _ = await asyncio.wait({task, cancel_wait}, return_when=asyncio.FIRST_COMPLETED)
            if task in done and not task.cancelled():
                return task.result()
            raise asyncio.CancelledError
        except asyncio.CancelledError:
            await cancel_tool_wait(task, self._cancel_cleanup_tasks, self._runtime.record_failure)
            raise
        finally:
            cancel_wait.cancel()
            await asyncio.gather(cancel_wait, return_exceptions=True)

    async def after_committed(
        self, prepared: PreparedToolResult, sink: AgentSink,
    ) -> ToolPostprocessEffect:
        from abstract.tools.registry import ToolRegistry

        execution = prepared.execution
        effect = ToolPostprocessEffect()
        if execution is not None and execution.body_completed_normally:
            if execution.result_message is not prepared.message or execution.history_index is None:
                raise RuntimeError("Tool postprocessing requires a committed result")
            registry = self._loop.app.get_system(ToolRegistry)
            try:
                effect = await self._await_phase(registry.async_postprocess(execution))
                if execution.context.is_interrupted:
                    raise asyncio.CancelledError
                if effect.suppress_tool_result_event and (
                    not execution.history_updated
                    or execution.tool_call_id not in effect.discarded_tool_call_ids
                ):
                    raise RuntimeError("Suppressed tool results require a committed History replacement")
                if effect.replacement_result is not None:
                    if not any(message is prepared.message for message in self._loop.history.iter_messages()):
                        raise RuntimeError("Cannot replace a tool result removed from History")
                    prepared.update_result_payload(effect.replacement_result)
                    if self._loop.session_store is not None:
                        self._loop.save_history(execution.context.session_id)
            except BaseException as original:
                # 已保存的结构变更不能因取消丢失after返回效果而漏发失效通知。
                if execution.history_updated:
                    try:
                        await sink.emit_history_updated(execution.context.session_id)
                    except BaseException as notification_error:
                        raise BaseExceptionGroup(
                            "Tool postprocessing and History notification failed",
                            [original, notification_error],
                        )
                raise
            if execution.history_updated:
                await sink.emit_history_updated(execution.context.session_id)
            if effect.system_message is not None:
                if execution.context.is_interrupted:
                    raise asyncio.CancelledError
                await sink.emit_system_message(execution.context.session_id, effect.system_message)
        if not effect.suppress_tool_result_event:
            await prepared.emit(sink)
        return effect


def prepare_tool_result(
    result: dict, *, tool_name: str, application_time: str, application_time_ms: int,
    approval_duration_ms: int, invocation_start_offset_ms: int, invocation_duration_ms: int,
    end_time_offset_ms: int, session_id: str, tool_call_id: str, character_name: str,
    field_injector: ResultFieldInjector | None = None,
    execution: ToolExecution | None = None,
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
            follow_up, content = tool_result_to_follow_up(result, character_name, tool_call_id=tool_call_id)
        else:
            content = tool_result_to_content(result, tool_call_id=tool_call_id)
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
            execution=execution,
        )
        prepared.bind_injector(field_injector)
        return prepared
    except BaseException:
        if field_injector is not None:
            field_injector.abort()
        raise
