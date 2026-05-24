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

import asyncio
import json
import logging
from typing import Any, Awaitable, Callable, Dict, List

from abstract.memory.manager import MemoryManager
from abstract.tools.registry import registry as tool_registry
from component.llm import LLMClient, LLMResponse
from system.context import RuntimeContext
from system.prompt import build_system_prompt

logger = logging.getLogger(__name__)

# Maximum tool-calling loop iterations per message to prevent infinite loops.
_MAX_TOOL_TURNS = 90


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
        self._memory_initialized: bool = False
        self._interrupted: Dict[str, bool] = {}
        # Per-session conversation history: session_id → list of OpenAI-format messages
        self._histories: Dict[str, List[Dict[str, Any]]] = {}
        # Callback fired on tool_call / tool_result events.
        # Signature: async (session_id, event_type, tool_name, payload) -> None
        self._tool_event_callback: Callable[[str, str, str, str], Awaitable[None]] | None = None

    # -- public API ----------------------------------------------------------

    def set_tool_event_callback(
        self,
        cb: Callable[[str, str, str, str], Awaitable[None]],
    ) -> None:
        """Register an async callback for tool execution events.

        *cb* is called with ``(session_id, event_type, tool_name, payload)``
        where *event_type* is ``"tool_call"`` or ``"tool_result"`` and
        *payload* is a JSON string.
        """
        self._tool_event_callback = cb

    def interrupt(self, session_id: str) -> None:
        """Request the agent loop to stop processing for a session.

        Also denies any pending shell-command confirm requests for this
        session so that a blocking ``_request_user_confirm()`` is
        unblocked immediately.
        """
        self._interrupted[session_id] = True
        try:
            from gateway.server import _deny_session_confirms
            _deny_session_confirms(session_id)
        except Exception:
            pass
        logger.info("Interrupt requested for session=%s", session_id)

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
        # ---- lazy-init memory providers ----
        if not self._memory_initialized:
            for provider in self._memory.providers:
                try:
                    provider.initialize(session_id)
                except Exception:
                    pass
            self._memory_initialized = True

        # ---- memory prefetch ----
        memory_ctx = self._memory.prefetch_all(
            user_message, session_id=session_id
        )

        # ---- build messages ----
        messages = self._build_messages(session_id, user_message, memory_ctx)

        # ---- tool-calling loop ----
        turn = 0
        while turn < _MAX_TOOL_TURNS:
            # ---- honour interrupt ----
            if self._interrupted.pop(session_id, False):
                return "已中断。"
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
                tool_msg = await self._execute_tool(tc, session_id)
                messages.append(tool_msg)
                history.append(tool_msg)

                # If evolve_code succeeded, exit the loop cleanly.
                # No need to continue — the orchestrator will restart us.
                if tc.name == "evolve_code":
                    try:
                        parsed = json.loads(tool_msg["content"])
                        if parsed.get("evolved"):
                            return "进化已完成，正在重启以应用新代码..."
                    except (json.JSONDecodeError, KeyError, TypeError):
                        pass

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

    def _collect_skill_prompts(self) -> list[str]:
        """Load enabled skills and return their formatted prompts."""
        blocks: list[str] = []
        try:
            from abstract.skills.loader import list_skills, load_skill
            skills = list_skills()
            for s in skills:
                name = s.get("name", "")
                if not name:
                    continue
                try:
                    payload = load_skill(name)
                    if payload.get("success") and payload.get("content"):
                        blocks.append(
                            f"[Skill: {name}]\n{payload['content']}"
                        )
                except Exception:
                    pass
        except Exception:
            pass
        return blocks

    def _build_messages(
        self,
        session_id: str,
        user_message: str,
        memory_ctx: str,
    ) -> List[Dict[str, Any]]:
        """Build the full message list for this turn."""
        # Collect enabled skill prompts
        skill_blocks = self._collect_skill_prompts()

        system_prompt = build_system_prompt(
            mode=self._ctx.mode,
            memory_context=memory_ctx,
            extra_blocks=skill_blocks,
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

    async def _execute_tool(self, tc, session_id: str = "") -> Dict[str, Any]:
        """Execute a single tool call and return an OpenAI-format tool message."""
        # Inject session context so tools like run_command can identify the
        # frontend session for user confirmation prompts.
        args = dict(tc.arguments) if tc.arguments else {}
        args["_session_id"] = session_id

        logger.info("Tool call: %s args=%s", tc.name, tc.arguments)

        # ---- notify frontend: tool_call ----
        if self._tool_event_callback:
            asyncio.create_task(
                self._tool_event_callback(
                    session_id, "tool_call", tc.name,
                    json.dumps(tc.arguments, ensure_ascii=False),
                )
            )

        # Route to memory manager if it owns this tool
        if self._memory.has_tool(tc.name):
            try:
                result = self._memory.handle_tool_call(tc.name, args)
            except Exception as exc:
                result = json.dumps({"error": str(exc)})
        else:
            entry = tool_registry.get_entry(tc.name)
            try:
                if entry and entry.is_async:
                    result = await entry.handler(args)
                else:
                    result = tool_registry.dispatch(tc.name, args)
            except Exception as exc:
                result = json.dumps({"error": str(exc)})

        # ---- notify frontend: tool_result ----
        if self._tool_event_callback:
            asyncio.create_task(
                self._tool_event_callback(
                    session_id, "tool_result", tc.name, result,
                )
            )

        return {
            "role": "tool",
            "tool_call_id": tc.id,
            "content": result,
        }

    def _get_tool_definitions(self) -> List[Dict[str, Any]]:
        """Return available tool schemas for the LLM (registry + memory)."""
        names = set(tool_registry.get_all_tool_names())
        definitions = tool_registry.get_definitions(tool_names=names)

        # Merge memory tool schemas (wrap in OpenAI format)
        for schema in self._memory.get_tool_schemas():
            definitions.append({"type": "function", "function": schema})

        return definitions if definitions else None  # type: ignore[return-value]