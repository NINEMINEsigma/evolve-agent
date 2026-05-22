"""Agent main loop — receives user messages, calls LLM + tools, returns replies.

Wires together three subsystems from the abstract layer:
  - ``abstract.tools.registry`` — tool schema discovery and dispatch
  - ``abstract.memory.manager`` — memory prefetch / sync
  - ``component.llm`` — LLM client

Per-session message history is kept in-memory.  Tools are discovered
at startup via ``abstract.tools.discover.discover_builtin_tools``
(Stage 4 will register concrete tools).
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List

from abstract.memory.manager import MemoryManager
from abstract.tools.registry import registry as tool_registry
from component.llm import LLMClient, LLMResponse
from system.context import RuntimeContext
from system.prompt import build_system_prompt

logger = logging.getLogger(__name__)

# Maximum tool-calling loop iterations per message to prevent infinite loops.
_MAX_TOOL_TURNS = 8


class AgentLoop:
    """Per-process singleton that orchestrates one LLM conversation turn.

    Usage::

        loop = AgentLoop(ctx)
        reply = await loop.process_message(session_id, user_message)
    """

    def __init__(self, ctx: RuntimeContext) -> None:
        self._ctx = ctx
        self._llm = LLMClient(ctx)
        self._memory = MemoryManager()
        # Per-session conversation history: session_id → list of OpenAI-format messages
        self._histories: Dict[str, List[Dict[str, Any]]] = {}

    # -- public API ----------------------------------------------------------

    async def process_message(
        self,
        session_id: str,
        user_message: str,
    ) -> str:
        """Process one user message and return the assistant's reply.

        This is the core agent loop:
          1. Prefetch memory context
          2. Build the message history with system prompt
          3. Call LLM, execute tool calls, repeat until a text reply
          4. Sync the completed turn to memory
        """
        # ---- memory prefetch ----
        memory_ctx = self._memory.prefetch_all(
            user_message, session_id=session_id
        )

        # ---- build messages ----
        messages = self._build_messages(session_id, user_message, memory_ctx)

        # ---- tool-calling loop ----
        turn = 0
        while turn < _MAX_TOOL_TURNS:
            turn += 1
            resp = await self._llm.chat(
                messages,
                tools=self._get_tool_definitions(),
            )

            if not resp.tool_calls:
                # Plain text reply — store and return
                assistant_text = resp.content or ""
                self._append(session_id, "assistant", assistant_text,
                             reasoning_content=resp.reasoning_content)
                self._memory.sync_all(
                    user_message, assistant_text, session_id=session_id,
                )
                return assistant_text

            # Store assistant message with tool_calls in history
            self._store_assistant_with_tools(session_id, resp)

            # Execute tool calls and persist results to history
            history = self._get_history(session_id)
            for tc in resp.tool_calls:
                tool_msg = self._execute_tool(tc)
                messages.append(tool_msg)
                history.append(tool_msg)

            messages = self._get_full_history(session_id)

        logger.warning(
            "Tool-call loop exceeded max turns (%d) for session=%s",
            _MAX_TOOL_TURNS, session_id,
        )
        return "I ran into an issue processing your request. Please try again."

    # -- internal helpers ----------------------------------------------------

    def _get_history(self, session_id: str) -> List[Dict[str, Any]]:
        if session_id not in self._histories:
            self._histories[session_id] = []
        return self._histories[session_id]

    def _append(
        self, session_id: str, role: str, content: str,
        reasoning_content: str | None = None,
    ) -> None:
        entry: Dict[str, Any] = {"role": role, "content": content}
        if reasoning_content:
            entry["reasoning_content"] = reasoning_content
        self._get_history(session_id).append(entry)

    def _build_messages(
        self,
        session_id: str,
        user_message: str,
        memory_ctx: str,
    ) -> List[Dict[str, Any]]:
        """Build the full message list for this turn."""
        system_prompt = build_system_prompt(
            mode=self._ctx.mode,
            memory_context=memory_ctx,
            lang="zh",
        )

        history = self._get_history(session_id)
        messages: List[Dict[str, Any]] = [
            {"role": "system", "content": system_prompt},
        ]
        messages.extend(history)
        messages.append({"role": "user", "content": user_message})
        return messages

    def _get_full_history(self, session_id: str) -> List[Dict[str, Any]]:
        """Rebuild full message list from stored history (used mid-loop)."""
        system_prompt = build_system_prompt(mode=self._ctx.mode, lang="zh")
        history = self._get_history(session_id)
        messages: List[Dict[str, Any]] = [
            {"role": "system", "content": system_prompt},
        ]
        messages.extend(history)
        return messages

    def _store_assistant_with_tools(
        self, session_id: str, resp: LLMResponse,
    ) -> None:
        """Store an assistant message that contains tool calls."""
        tool_calls_data = [
            {
                "id": tc.id,
                "type": "function",
                "function": {"name": tc.name, "arguments": json.dumps(tc.arguments)},
            }
            for tc in resp.tool_calls
        ]
        history = self._get_history(session_id)
        entry: Dict[str, Any] = {
            "role": "assistant",
            "content": resp.content or None,
            "tool_calls": tool_calls_data,
        }
        if resp.reasoning_content:
            entry["reasoning_content"] = resp.reasoning_content
        history.append(entry)

    def _execute_tool(self, tc) -> Dict[str, Any]:
        """Execute a single tool call and return an OpenAI-format tool message."""
        logger.info("Tool call: %s args=%s", tc.name, tc.arguments)
        try:
            result = tool_registry.dispatch(tc.name, tc.arguments)
        except Exception as exc:
            result = json.dumps({"error": str(exc)})
        return {
            "role": "tool",
            "tool_call_id": tc.id,
            "content": result,
        }

    def _get_tool_definitions(self) -> List[Dict[str, Any]]:
        """Return available tool schemas for the LLM."""
        names = tool_registry.get_all_tool_names()
        if not names:
            return None  # type: ignore[return-value]
        return tool_registry.get_definitions(tool_names=set(names))