"""Abstract base class for pluggable memory providers.

Memory providers give agents persistent recall across sessions.

Lifecycle (expected caller protocol):
  initialize()          -- connect, create resources, warm up
  system_prompt_block() -- static text for the system prompt
  prefetch(query)       -- background recall before each turn
  sync_turn(user, asst) -- persist a completed turn
  get_tool_schemas()    -- tool schemas to expose to the model
  handle_tool_call()    -- dispatch a tool call
  shutdown()            -- clean exit

Optional hooks (override to opt in):
  on_turn_start(turn, message, **kwargs)    -- per-turn tick
  on_session_end(messages)                  -- end-of-session extraction
  on_session_switch(new_session_id, **kwargs) -- mid-process session rotation
  on_pre_compress(messages) -> str          -- extract before context compression
  on_memory_write(action, target, content)  -- mirror built-in memory writes
  on_delegation(task, result, **kwargs)     -- parent-side observation of subagent work
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class MemoryProvider(ABC):
    """Abstract base class for memory providers.

    Subclass this to implement a custom memory backend. All abstract methods
    must be implemented; optional hooks can be overridden as needed.
    """

    # ------------------------------------------------------------------
    # Core lifecycle -- every provider must implement these
    # ------------------------------------------------------------------

    @property
    @abstractmethod
    def name(self) -> str:
        """Short identifier for this provider (e.g. 'builtin', 'honcho', 'hindsight').

        Returns
        -------
        str
            A human-readable identifier used for logging, config, and debugging.
        """

    @abstractmethod
    def is_available(self) -> bool:
        """Return True if this provider is configured and ready.

        Called during agent initialisation to decide whether to activate the
        provider. Should *not* make network calls -- just check configuration
        keys and installed dependencies.

        Returns
        -------
        bool
            True if the provider has everything it needs to run.
        """

    @abstractmethod
    def initialize(self, session_id: str, **kwargs: Any) -> None:
        """Initialise the provider for a session.

        Called once at agent startup.  May create resources (tables, indices,
        document stores), establish connections, start background threads, etc.

        Parameters
        ----------
        session_id : str
            The unique identifier for the conversation session the provider
            should scope itself to.

        **kwargs : Any
            Environment context passed by the agent.  Common keys include:

            hermes_home (str)
                The active HERMES_HOME directory path.  Use this for
                profile-scoped storage instead of hardcoding paths.
            platform (str)
                ``"cli"``, ``"telegram"``, ``"discord"``, ``"cron"``, etc.
            agent_context (str)
                ``"primary"``, ``"subagent"``, ``"cron"``, or ``"flush"``.
                Providers should skip writes for non-primary contexts.
            agent_identity (str)
                Profile name (e.g. ``"coder"``).  Use for per-profile
                provider identity scoping.
            agent_workspace (str)
                Shared workspace name (e.g. ``"hermes"``).
            parent_session_id (str)
                For subagents, the parent's session_id.
            user_id (str)
                Platform user identifier (gateway sessions).
        """

    @abstractmethod
    def system_prompt_block(self) -> str:
        """Return static text to include in the system prompt.

        This is for *static* provider information (instructions, status).
        Prefetched recall context is injected separately via :meth:`prefetch`.

        Returns
        -------
        str
            Text to inject, or empty string to skip.
        """

    @abstractmethod
    def prefetch(self, query: str, *, session_id: str = "") -> str:
        """Recall relevant context for the upcoming turn.

        Called before each API call.  Return formatted text to inject as
        context, or an empty string if nothing relevant was found.
        Implementations should be fast -- use background threads for the
        actual recall and return cached results here.

        Parameters
        ----------
        query : str
            The user's latest message (or equivalent query string) to use as a
            search / recall prompt.
        session_id : str
            Session identifier for providers serving concurrent sessions.
            Providers that don't need per-session scoping can ignore it.

        Returns
        -------
        str
            Formatted recall text, or empty string.
        """

    @abstractmethod
    def sync_turn(
        self,
        user_message: str,
        assistant_response: str,
        *,
        session_id: str = "",
    ) -> None:
        """Persist a completed turn to the backend.

        Called after each conversational turn.  Should be non-blocking --
        queue for background processing if the backend has latency.

        Parameters
        ----------
        user_message : str
            The user's message for this turn.
        assistant_response : str
            The assistant's response for this turn.
        session_id : str
            Session identifier for providers serving concurrent sessions.
        """

    @abstractmethod
    def get_tool_schemas(self) -> List[Dict[str, Any]]:
        """Return tool schemas this provider exposes.

        Each schema follows the OpenAI function-calling format::

            {"name": "...", "description": "...", "parameters": {...}}

        Return an empty list if this provider has no tools (context-only).

        Returns
        -------
        list[dict[str, Any]]
            A list of OpenAI-compatible tool definition dicts.
        """

    @abstractmethod
    def handle_tool_call(self, tool_name: str, args: Dict[str, Any]) -> str:
        """Handle a tool call for one of this provider's tools.

        Only called for tool names previously returned by :meth:`get_tool_schemas`.

        Parameters
        ----------
        tool_name : str
            The name of the tool being invoked.
        args : dict[str, Any]
            The arguments provided to the tool.

        Returns
        -------
        str
            The tool result as a JSON string.
        """

    @abstractmethod
    def shutdown(self) -> None:
        """Clean shutdown -- flush queues, close connections, release resources.

        Called when the agent or session ends.  Implementations should ensure
        all pending writes are flushed and connections are closed gracefully.
        """

    # ------------------------------------------------------------------
    # Optional hooks -- override these to opt in to lifecycle events
    # ------------------------------------------------------------------

    def on_turn_start(self, turn_number: int, message: str, **kwargs: Any) -> None:
        """Called at the start of each turn with the user message.

        Use for turn-counting, scope management, or periodic maintenance.

        Parameters
        ----------
        turn_number : int
            The 1-based turn count for the current session.
        message : str
            The user's message for this turn.
        **kwargs : Any
            Runtime context.  May include keys such as ``remaining_tokens``,
            ``model``, ``platform``, ``tool_count``.
        """

    def on_session_end(self, messages: List[Dict[str, Any]]) -> None:
        """Called when a session ends (explicit exit or timeout).

        Use for end-of-session fact extraction, summarisation, etc.

        Parameters
        ----------
        messages : list[dict[str, Any]]
            The full conversation history for the session being ended.

        Note
        ----
        NOT called after every turn -- only at actual session boundaries
        (CLI exit, ``/reset``, gateway session expiry).
        """

    def on_session_switch(
        self,
        new_session_id: str,
        *,
        parent_session_id: str = "",
        reset: bool = False,
        **kwargs: Any,
    ) -> None:
        """Called when the agent switches session_id mid-process.

        Fires on ``/resume``, ``/branch``, ``/reset``, ``/new``, and context
        compression -- any path that reassigns the session identifier without
        tearing the provider down.

        Providers that cache per-session state in :meth:`initialize`
        (``_session_id``, ``_document_id``, accumulated turn buffers, counters)
        should update or reset that state here so subsequent writes land in the
        correct session's record.

        Parameters
        ----------
        new_session_id : str
            The session_id the agent just switched to.
        parent_session_id : str
            The previous session_id when lineage is meaningful -- set for
            ``/branch`` (fork lineage), context compression (continuation
            lineage), and ``/resume`` (the session we are leaving).  Empty
            string when no lineage applies.
        reset : bool
            ``True`` when this is a genuinely new conversation, not a
            resumption.  Fired by ``/reset`` / ``/new``.  Providers should
            flush accumulated per-session buffers when this is set.  ``False``
            for ``/resume`` / ``/branch`` / compression where the logical
            conversation continues under the new id.
        **kwargs : Any
            Additional context.
        """

    def on_pre_compress(self, messages: List[Dict[str, Any]]) -> str:
        """Called before context compression discards old messages.

        Use to extract insights from messages about to be compressed.

        Parameters
        ----------
        messages : list[dict[str, Any]]
            The list of messages that will be summarised / discarded.

        Returns
        -------
        str
            Text to include in the compression summary prompt so the
            compressor preserves provider-extracted insights.  Return empty
            string for no contribution (backwards-compatible default).
        """
        return ""

    def on_memory_write(
        self,
        action: str,
        target: str,
        content: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Called when the built-in memory tool writes an entry.

        Use to mirror built-in memory writes to your backend.

        Parameters
        ----------
        action : str
            ``"add"``, ``"replace"``, or ``"remove"``.
        target : str
            ``"memory"`` or ``"user"``.
        content : str
            The entry content.
        metadata : dict[str, Any] or None
            Structured provenance for the write when available.  Common keys
            include ``write_origin``, ``execution_context``, ``session_id``,
            ``parent_session_id``, ``platform``, and ``tool_name``.
        """

    def on_delegation(
        self,
        task: str,
        result: str,
        *,
        child_session_id: str = "",
        **kwargs: Any,
    ) -> None:
        """Called on the *parent* agent when a subagent completes.

        The parent's memory provider receives the task+result pair as an
        observation of what was delegated and what came back.  The subagent
        itself typically has no provider session.

        Parameters
        ----------
        task : str
            The delegation prompt sent to the subagent.
        result : str
            The subagent's final response.
        child_session_id : str
            The subagent's session_id, if available.
        **kwargs : Any
            Additional context.
        """
