from __future__ import annotations

from abc import ABC, abstractmethod

from entity.puretype import (
    ApprovalResult,
    MessageContent,
    MessageMetrics,
    ToolCallDelta,
    ToolCallRequest,
)


class IAgentSink(ABC):
    """Declare the upward communication contract shared by frontend and parent sinks."""

    @abstractmethod
    async def ask_question(
        self,
        questions: list[dict],
        session_id: str = ""
        ) -> dict:
        """Ask the user a multi-question form and await its answer."""
        ...

    @abstractmethod
    async def request_approval(
        self,
        tool_name: str,
        args: dict,
        reason: str = "",
        content: str = "",
        session_id: str = ""
        ) -> ApprovalResult:
        """Request approval for one tool invocation."""
        ...

    @abstractmethod
    async def emit_tool_call(
        self,
        session_id: str,
        tool_name: str,
        tool_call_id: str,
        args: dict,
        character_name: str | None = None
        ) -> None:
        """Send a tool-call event to the upper layer."""
        ...

    @abstractmethod
    async def emit_tool_result(
        self,
        session_id: str,
        tool_name: str,
        tool_call_id: str,
        content: str,
        character_name: str | None = None,
        tool_call_meta: dict | None = None,
        embedded_messages: list[dict] | None = None,
        consumed_client_message_ids: list[str] | None = None
        ) -> None:
        """Send a tool-result event and its embedded messages."""
        ...

    @abstractmethod
    async def emit_tool_calls_discarded(
        self,
        session_id: str,
        stream_id: str,
        tool_call_ids: list[str]
        ) -> None:
        """Remove tool calls rejected by a batch boundary."""
        ...

    @abstractmethod
    async def emit_history_updated(self, session_id: str) -> None:
        """Invalidate the view of committed History changes."""
        ...

    @abstractmethod
    async def emit_user_message(
        self,
        session_id: str,
        content: MessageContent,
        character_name: str,
        message_index: int,
        visible_characters: list[str] | None = None,
        response_characters: list[str] | None = None,
        client_message_id: str | None = None,
        message_suffix: str | None = None,
        dynamic_message_suffix: str | None = None
        ) -> None:
        """Send a persisted user message."""
        ...

    @abstractmethod
    async def emit_assistant_message(
        self,
        session_id: str,
        content: MessageContent,
        character_name: str,
        visible_characters: list[str] | None = None,
        response_characters: list[str] | None = None
        ) -> None:
        """Send a complete assistant message."""
        ...

    @abstractmethod
    async def emit_stream_delta(
        self,
        session_id: str,
        stream_id: str,
        delta: str = "",
        reasoning_delta: str = "",
        tool_call: ToolCallRequest | None = None,
        tool_call_delta: ToolCallDelta | None = None,
        character_name: str | None = None
        ) -> None:
        """Send one structured streaming delta."""
        ...

    @abstractmethod
    async def emit_stream_done(
        self,
        session_id: str,
        stream_id: str,
        finish_reason: str = "stop",
        content: str = "",
        metrics: MessageMetrics | None = None
        ) -> None:
        """Send the terminal streaming event and metrics."""
        ...

    @abstractmethod
    async def emit_usage_update(
        self,
        session_id: str,
        token_usage: int,
        context_tokens: int
        ) -> None:
        """Send token-usage counters."""
        ...

    @abstractmethod
    async def emit_progress(
        self,
        session_id: str,
        tool_name: str,
        payload: str
        ) -> None:
        """Send a task-progress update."""
        ...

    @abstractmethod
    async def emit_clipboard_display(
        self,
        session_id: str,
        tool_name: str,
        payload: str
        ) -> None:
        """Send a clipboard-display update."""
        ...

    @abstractmethod
    async def emit_subagent_update(
        self,
        session_id: str,
        payload: dict
        ) -> None:
        """Send a sub-agent status update."""
        ...

    @abstractmethod
    async def emit_system_message(
        self,
        session_id: str,
        content: str,
        history_index: int | None = None,
        is_system_status: bool = False
        ) -> None:
        """Send a system message with optional persisted History metadata."""
        ...
