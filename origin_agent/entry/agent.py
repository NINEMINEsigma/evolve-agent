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
        self._memory_initialized: Dict[str, bool] = {}
        self._interrupted: Dict[str, bool] = {}
        # Per-session conversation history: session_id → list of OpenAI-format messages
        self._histories: Dict[str, List[Dict[str, Any]]] = {}
        # Skill prompt caching — invalidated when skills are modified
        self._skill_cache: list[str] = []
        self._skill_cache_valid: bool = False
        # Cumulative token consumption for dashboard display only.
        # Compression decisions use _estimate_context_tokens() instead.
        self._token_usage: Dict[str, int] = {}
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
        if session_id not in self._memory_initialized:
            for provider in self._memory.providers:
                try:
                    provider.initialize(session_id)
                except Exception:
                    pass
            self._memory_initialized[session_id] = True

        # ---- memory prefetch ----
        memory_ctx = self._memory.prefetch_all(
            user_message, session_id=session_id
        )

        # ---- compress history if too long ----
        await self._compress_history(session_id)

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
            # Track actual token usage from LLM response
            self._token_usage[session_id] = self._token_usage.get(session_id, 0) + resp.usage.total_tokens

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

            messages = self._get_full_history(session_id, memory_ctx)

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
        if self._skill_cache_valid:
            return self._skill_cache
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
        self._skill_cache = blocks
        self._skill_cache_valid = True
        return blocks

    def invalidate_skill_cache(self) -> None:
        """Force skill cache reload on next call."""
        self._skill_cache_valid = False

    def _estimate_context_tokens(self, session_id: str) -> int:
        """Count actual context tokens from history + system prompt via tiktoken.

        Drives compression decisions — distinct from the cumulative
        ``_token_usage`` counter which is only for dashboard display.
        """
        import tiktoken

        history = self._get_history(session_id)
        if not history:
            return 0

        try:
            enc = tiktoken.encoding_for_model(self._ctx.llm_model)
        except KeyError:
            # cl100k_base covers gpt-4, gpt-3.5-turbo, and most compatible models
            enc = tiktoken.get_encoding("cl100k_base")

        total = 0
        for msg in history:
            # OpenAI chat-message overhead: <|im_start|>role<|im_end|> ... <|im_end|>
            total += 4
            total += len(enc.encode(msg.get("role", "")))
            total += len(enc.encode(str(msg.get("content", ""))))
            rc = msg.get("reasoning_content")
            if rc:
                total += 4
                total += len(enc.encode(str(rc)))

        # Append system prompt estimate (built by _build_messages)
        total += 2000

        return total

    async def _compress_history(self, session_id: str, keep_last: int = 5) -> None:
        """Compress older history into a summary, keeping recent turns intact.

        Triggered when estimated context tokens exceed 70 % of the LLM window.
        Uses a lightweight LLM call (no tools) to summarize old messages.
        """
        history = self._get_history(session_id)
        if not history:
            return

        # Context limits from RuntimeContext (configurable)
        max_tokens = self._ctx.llm_max_context_tokens
        threshold_tokens = int(max_tokens * self._ctx.llm_context_upbound)

        # Use actual context size estimate — NOT cumulative _token_usage
        current_tokens = self._estimate_context_tokens(session_id)
        if current_tokens < threshold_tokens:
            return

        keep_msgs = keep_last * 2  # user+assistant pairs
        if len(history) <= keep_msgs:
            return

        old = history[:-keep_msgs]
        recent = history[-keep_msgs:]

        parts = []
        for m in old:
            role = m.get("role", "unknown")
            content = str(m.get("content", ""))[:500]
            if content:
                parts.append(f"[{role}]: {content}")

        if not parts:
            self._histories[session_id] = recent
            return

        old_text = "\n".join(parts[-50:])
        prompt, fallback, prefix = self._compression_prompts()
        summary_prompt = prompt.format(old_text=old_text)

        try:
            summary_resp = await self._llm.chat(
                [{"role": "user", "content": summary_prompt}],
                tools=[],
            )
            summary = summary_resp.content.strip()[:300] if summary_resp.content else ""
        except Exception:
            summary = fallback

        self._histories[session_id] = (
            [{"role": "system", "content": f"{prefix}\n{summary}"}]
            + recent
        )

    def _compression_prompts(self) -> tuple[str, str, str]:
        """Return (prompt_template, fallback_text, summary_prefix) from template files.

        Reads templates/zh/compress.txt (Chinese) or templates/compress.txt (English).
        """
        from pathlib import Path
        templates = Path(__file__).resolve().parent.parent / "templates"
        zh_dir = templates / "zh"
        use_zh = zh_dir.is_dir()

        prompt_tpl = ""
        compress_file = (zh_dir if use_zh else templates) / "compress.txt"
        if compress_file.is_file():
            try:
                prompt_tpl = compress_file.read_text(encoding="utf-8").strip()
            except OSError:
                pass

        if not prompt_tpl:
            prompt_tpl = (
                "请用200字以内总结以下对话的关键内容和决策点。只输出总结。\n\n"
                "对话内容：\n{old_text}\n\n总结："
            )

        if use_zh:
            return prompt_tpl, "（历史对话过长，已自动截断）", "[上下文摘要]"
        return prompt_tpl, "(History too long, truncated)", "[Context Summary]"

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
            workspace=self._ctx.workspace,
            self_path=str(self._ctx.self_path),
            fork_path=str(self._ctx.fork_path),
            fix_fork_path=str(self._ctx.fix_path) if self._ctx.fix_path else "",
            fix_log_path=str(self._ctx.fix_log_path or ""),
        )

        history = self._get_history(session_id)
        messages: List[Dict[str, Any]] = [
            {"role": "system", "content": system_prompt},
        ]
        messages.extend(history)
        messages.append({"role": "user", "content": user_message})
        return messages

    def _get_full_history(self, session_id: str, memory_ctx: str = "") -> List[Dict[str, Any]]:
        """Rebuild full message list from stored history (used mid-loop)."""
        skill_blocks = self._collect_skill_prompts()
        system_prompt = build_system_prompt(
            mode=self._ctx.mode,
            memory_context=memory_ctx,
            extra_blocks=skill_blocks,
            lang="zh",
            workspace=self._ctx.workspace,
            self_path=str(self._ctx.self_path),
            fork_path=str(self._ctx.fork_path),
            fix_fork_path=str(self._ctx.fix_path) if self._ctx.fix_path else "",
            fix_log_path=str(self._ctx.fix_log_path or ""),
        )
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
        # Honour interrupt — check before each tool execution
        if self._interrupted.pop(session_id, False):
            return {
                "role": "tool",
                "tool_call_id": tc.id,
                "content": "已中断。",
            }
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
                    result = await asyncio.to_thread(tool_registry.dispatch, tc.name, args)
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

    def get_session_messages(self, session_id: str) -> list[dict]:
        """Return conversation history formatted for frontend replay."""
        history = self._histories.get(session_id, [])
        messages = []
        for entry in history:
            role = entry.get("role", "")
            content = entry.get("content", "")
            if role == "user":
                messages.append({"role": "user", "content": str(content or "")})
            elif role == "assistant":
                messages.append({"role": "agent", "content": str(content or "")})
            elif role == "tool":
                messages.append({"role": "tool", "content": str(content or "")})
        return messages

    def get_token_usage(self, session_id: str) -> int:
        """Return the current prompt-token usage for a session."""
        return self._token_usage.get(session_id, 0)