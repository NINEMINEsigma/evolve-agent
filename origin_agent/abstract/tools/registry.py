"""Central registry for tool schemas and handlers.

Each tool module calls ``registry.register()`` at module level to declare its
schema, handler, toolset membership, and availability check. Downstream code
uses ``get_definitions()`` to obtain OpenAI-format schemas (filtered by
availability) and ``dispatch()`` to execute handlers by name.

All mutation is serialised via ``threading.RLock`` and a monotonically
increasing generation counter enables external cache invalidation.
"""

import asyncio
import json
import logging
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# ToolEntry
# ---------------------------------------------------------------------------


class ToolEntry:
    """Metadata for a single registered tool.

    Uses ``__slots__`` for memory efficiency — instances are created for
    every registered tool and live for the lifetime of the process.
    """

    __slots__ = (
        "name",
        "toolset",
        "schema",
        "handler",
        "check_fn",
        "requires_env",
        "is_async",
        "description",
        "emoji",
        "max_result_size_chars",
        "dynamic_schema_overrides",
    )

    def __init__(
        self,
        name: str,
        toolset: str,
        schema: dict,
        handler: Callable,
        check_fn: Optional[Callable] = None,
        requires_env: Optional[List[str]] = None,
        is_async: bool = False,
        description: str = "",
        emoji: str = "",
        max_result_size_chars: Optional[int] = None,
        dynamic_schema_overrides: Optional[Callable] = None,
    ):
        self.name = name
        self.toolset = toolset
        self.schema = schema
        self.handler = handler
        self.check_fn = check_fn
        self.requires_env = requires_env or []
        self.is_async = is_async
        self.description = description
        self.emoji = emoji
        self.max_result_size_chars = max_result_size_chars
        # Optional zero-arg callable returning a dict of schema overrides
        # applied at get_definitions() time. Use for fields that depend on
        # runtime config.
        self.dynamic_schema_overrides = dynamic_schema_overrides


# ---------------------------------------------------------------------------
# check_fn TTL cache
#
# check_fn callables probe external state (Docker daemon, binary availability,
# config paths). For a long-lived process, calling them on every
# get_definitions() is pure waste — external state changes on human
# timescales. Cache results for ~30 s so env-var flips propagate within a
# turn or two without any explicit invalidation.
# ---------------------------------------------------------------------------

_CHECK_FN_TTL_SECONDS = 30.0
_check_fn_cache: Dict[Callable, Tuple[float, bool]] = {}
_check_fn_cache_lock = threading.Lock()

DEFAULT_RESULT_SIZE_CHARS = 100000


def _check_fn_cached(fn: Callable) -> bool:
    """Return bool(fn()), TTL-cached across calls. Swallows exceptions as False."""
    now = time.monotonic()
    with _check_fn_cache_lock:
        cached = _check_fn_cache.get(fn)
        if cached is not None:
            ts, value = cached
            if now - ts < _CHECK_FN_TTL_SECONDS:
                return value
    try:
        value = bool(fn())
    except Exception:
        value = False
    with _check_fn_cache_lock:
        _check_fn_cache[fn] = (now, value)
    return value


def invalidate_check_fn_cache() -> None:
    """Drop all cached ``check_fn`` results. Call after config changes that
    affect tool availability."""
    with _check_fn_cache_lock:
        _check_fn_cache.clear()


# ---------------------------------------------------------------------------
# ToolRegistry (singleton)
# ---------------------------------------------------------------------------


class ToolRegistry:
    """Singleton registry that collects tool schemas + handlers from tool files.

    All mutation methods (register, deregister) acquire an ``RLock`` so they
    are safe to call from multiple threads (e.g. MCP dynamic refresh vs.
    read queries).  A monotonically increasing ``_generation`` counter is
    bumped on every mutation so external caches keyed on generation can
    cheaply detect staleness.
    """

    def __init__(self):
        self._tools: Dict[str, ToolEntry] = {}
        self._toolset_checks: Dict[str, Callable] = {}
        self._toolset_aliases: Dict[str, str] = {}
        # Serialise mutations and provide a stable snapshot for readers.
        self._lock = threading.RLock()
        # Monotonically-increasing generation counter. Bumped on every
        # mutation (register / deregister / register_toolset_alias).
        # External callers can memoize against it: a cache entry keyed on
        # the generation is valid for as long as the generation hasn't changed.
        self._generation: int = 0

    # -- internal snapshot helpers -----------------------------------------

    def _snapshot_state(self) -> Tuple[List[ToolEntry], Dict[str, Callable]]:
        """Return a coherent snapshot of registry entries and toolset checks."""
        with self._lock:
            return list(self._tools.values()), dict(self._toolset_checks)

    def _snapshot_entries(self) -> List[ToolEntry]:
        """Return a stable snapshot of registered tool entries."""
        return self._snapshot_state()[0]

    def _snapshot_toolset_checks(self) -> Dict[str, Callable]:
        """Return a stable snapshot of toolset availability checks."""
        return self._snapshot_state()[1]

    def _evaluate_toolset_check(self, toolset: str, check: Optional[Callable]) -> bool:
        """Run a toolset check, treating missing or failing checks as available."""
        if not check:
            return True
        try:
            return bool(check())
        except Exception:
            logger.debug("Toolset %s check raised; marking unavailable", toolset)
            return False

    # -- query methods -----------------------------------------------------

    def get_entry(self, name: str) -> Optional[ToolEntry]:
        """Return a registered tool entry by name, or None."""
        with self._lock:
            return self._tools.get(name)

    def get_schema(self, name: str) -> Optional[dict]:
        """Return a tool's raw schema dict, bypassing check_fn filtering.

        Useful for token estimation and introspection where availability
        doesn't matter — only the schema content does.
        """
        entry = self.get_entry(name)
        return entry.schema if entry else None

    def get_all_tool_names(self) -> List[str]:
        """Return sorted list of all registered tool names."""
        return sorted(entry.name for entry in self._snapshot_entries())

    def get_toolset_for_tool(self, name: str) -> Optional[str]:
        """Return the toolset a tool belongs to, or None."""
        entry = self.get_entry(name)
        return entry.toolset if entry else None

    def get_emoji(self, name: str, default: str = "⚡") -> str:
        """Return the emoji for a tool, or *default* if unset."""
        entry = self.get_entry(name)
        return entry.emoji if entry and entry.emoji else default

    def get_tool_to_toolset_map(self) -> Dict[str, str]:
        """Return ``{tool_name: toolset_name}`` for every registered tool."""
        return {entry.name: entry.toolset for entry in self._snapshot_entries()}

    def get_registered_toolset_names(self) -> List[str]:
        """Return sorted unique toolset names present in the registry."""
        return sorted({entry.toolset for entry in self._snapshot_entries()})

    def get_tool_names_for_toolset(self, toolset: str) -> List[str]:
        """Return sorted tool names registered under a given toolset."""
        return sorted(
            entry.name for entry in self._snapshot_entries()
            if entry.toolset == toolset
        )

    # -- toolset alias support ---------------------------------------------

    def register_toolset_alias(self, alias: str, toolset: str) -> None:
        """Register an explicit alias for a canonical toolset name."""
        with self._lock:
            existing = self._toolset_aliases.get(alias)
            if existing and existing != toolset:
                logger.warning(
                    "Toolset alias collision: '%s' (%s) overwritten by %s",
                    alias, existing, toolset,
                )
            self._toolset_aliases[alias] = toolset
            self._generation += 1

    def get_registered_toolset_aliases(self) -> Dict[str, str]:
        """Return a snapshot of ``{alias: canonical_toolset}`` mappings."""
        with self._lock:
            return dict(self._toolset_aliases)

    def get_toolset_alias_target(self, alias: str) -> Optional[str]:
        """Return the canonical toolset name for an alias, or None."""
        with self._lock:
            return self._toolset_aliases.get(alias)

    # -- registration ------------------------------------------------------

    def register(
        self,
        name: str,
        toolset: str,
        schema: dict,
        handler: Callable,
        check_fn: Optional[Callable] = None,
        requires_env: Optional[List[str]] = None,
        is_async: bool = False,
        description: str = "",
        emoji: str = "",
        max_result_size_chars: Optional[int] = None,
        dynamic_schema_overrides: Optional[Callable] = None,
        override: bool = False,
    ) -> None:
        """Register a tool. Called at module-import time by each tool file.

        ``override=True`` is an explicit opt-in for plugins that intend to
        replace an existing tool from a different toolset. Without it,
        registrations that would shadow an existing tool are rejected to
        prevent accidental overwrites.

        Tools registered within the same toolset silently overwrite each
        other (latest wins — expected for reloads / re-imports).
        """
        with self._lock:
            existing = self._tools.get(name)
            if existing and existing.toolset != toolset:
                # Allow same-category overwrites (e.g. MCP-to-MCP refresh).
                both_mcp = (
                    existing.toolset.startswith("mcp-")
                    and toolset.startswith("mcp-")
                )
                if both_mcp:
                    logger.debug(
                        "Tool '%s': MCP toolset '%s' overwriting MCP toolset '%s'",
                        name, toolset, existing.toolset,
                    )
                elif override:
                    logger.info(
                        "Tool '%s': toolset '%s' overriding existing toolset '%s' "
                        "(override=True opt-in)",
                        name, toolset, existing.toolset,
                    )
                else:
                    logger.error(
                        "Tool registration REJECTED: '%s' (toolset '%s') would "
                        "shadow existing tool from toolset '%s'. Pass "
                        "override=True to register() if the replacement is "
                        "intentional, or deregister the existing tool first.",
                        name, toolset, existing.toolset,
                    )
                    return

            self._tools[name] = ToolEntry(
                name=name,
                toolset=toolset,
                schema=schema,
                handler=handler,
                check_fn=check_fn,
                requires_env=requires_env or [],
                is_async=is_async,
                description=description or schema.get("description", ""),
                emoji=emoji,
                max_result_size_chars=max_result_size_chars,
                dynamic_schema_overrides=dynamic_schema_overrides,
            )
            if check_fn and toolset not in self._toolset_checks:
                self._toolset_checks[toolset] = check_fn
            self._generation += 1

    def deregister(self, name: str) -> None:
        """Remove a tool from the registry.

        Also cleans up the toolset check if no other tools remain in the
        same toolset. Useful for dynamic tool refresh (e.g. MCP servers
        sending ``notifications/tools/list_changed``).
        """
        with self._lock:
            entry = self._tools.pop(name, None)
            if entry is None:
                return
            # Drop the toolset check and aliases if this was the last tool
            # in that toolset.
            toolset_still_exists = any(
                e.toolset == entry.toolset for e in self._tools.values()
            )
            if not toolset_still_exists:
                self._toolset_checks.pop(entry.toolset, None)
                self._toolset_aliases = {
                    alias: target
                    for alias, target in self._toolset_aliases.items()
                    if target != entry.toolset
                }
            self._generation += 1
        logger.debug("Deregistered tool: %s", name)

    # -- schema retrieval --------------------------------------------------

    def get_definitions(
        self,
        tool_names: set,
        quiet: bool = False,
    ) -> List[dict]:
        """Return OpenAI-format tool schemas for the requested tool names.

        Only tools whose ``check_fn()`` returns True (or have no check_fn)
        are included. ``check_fn()`` results are cached for ~30 s via
        :func:`_check_fn_cached` to amortize repeat probes.

        Returns a list of ``{"type": "function", "function": schema}`` dicts
        suitable for passing directly to OpenAI-format chat completions APIs.
        """
        result: List[dict] = []
        # Per-call cache on top of the 30 s TTL — handles repeat probes of
        # the same check_fn within one definitions pass without re-reading
        # the TTL clock.
        check_results: Dict[Callable, bool] = {}
        entries_by_name = {entry.name: entry for entry in self._snapshot_entries()}
        for name in sorted(tool_names):
            entry = entries_by_name.get(name)
            if not entry:
                continue
            if entry.check_fn:
                if entry.check_fn not in check_results:
                    check_results[entry.check_fn] = _check_fn_cached(entry.check_fn)
                if not check_results[entry.check_fn]:
                    if not quiet:
                        logger.debug("Tool %s unavailable (check failed)", name)
                    continue
            # Ensure schema always has a "name" field — use entry.name as fallback
            schema_with_name = {**entry.schema, "name": entry.name}
            # Apply runtime-dynamic overrides
            if entry.dynamic_schema_overrides is not None:
                try:
                    overrides = entry.dynamic_schema_overrides()
                    if isinstance(overrides, dict):
                        schema_with_name.update(overrides)
                except Exception as exc:
                    logger.warning(
                        "dynamic_schema_overrides for tool %s raised %s; "
                        "using static schema",
                        name, exc,
                    )
            result.append({"type": "function", "function": schema_with_name})
        return result

    # -- dispatch ----------------------------------------------------------

    def dispatch(self, name: str, args: dict, **kwargs: Any) -> str:
        """Execute a tool handler by name.

        * Async handlers are bridged automatically via ``asyncio.run()``.
        * All exceptions are caught and returned as ``{"error": "..."}``
          for a consistent error format.

        Returns a JSON string.
        """
        entry = self.get_entry(name)
        if not entry:
            return json.dumps({"error": f"Unknown tool: {name}"})
        try:
            if entry.is_async:
                return asyncio.run(entry.handler(args, **kwargs))
            return entry.handler(args, **kwargs)
        except Exception as e:
            logger.exception("Tool %s dispatch error: %s", name, e)
            sanitized = f"Tool execution failed: {type(e).__name__}: {e}"
            return json.dumps({"error": sanitized})

    # -- toolset availability queries --------------------------------------

    def get_max_result_size(
        self,
        name: str,
        default: Optional[int] = None,
    ) -> int:
        """Return per-tool max result size, or *default* (or a global default)."""
        entry = self.get_entry(name)
        if entry and entry.max_result_size_chars is not None:
            return entry.max_result_size_chars
        if default is not None:
            return default
        return DEFAULT_RESULT_SIZE_CHARS

    def is_toolset_available(self, toolset: str) -> bool:
        """Check if a toolset's requirements are met.

        Returns False (rather than crashing) when the check function raises
        an unexpected exception.
        """
        with self._lock:
            check = self._toolset_checks.get(toolset)
        return self._evaluate_toolset_check(toolset, check)

    def check_toolset_requirements(self) -> Dict[str, bool]:
        """Return ``{toolset: available_bool}`` for every toolset."""
        entries, toolset_checks = self._snapshot_state()
        toolsets = sorted({entry.toolset for entry in entries})
        return {
            toolset: self._evaluate_toolset_check(toolset, toolset_checks.get(toolset))
            for toolset in toolsets
        }

    def get_available_toolsets(self) -> Dict[str, dict]:
        """Return toolset metadata for UI display.

        Each value::

            {
                "available": bool,
                "tools": [str, ...],
                "description": "",
                "requirements": [str, ...],
            }
        """
        toolsets: Dict[str, dict] = {}
        entries, toolset_checks = self._snapshot_state()
        for entry in entries:
            ts = entry.toolset
            if ts not in toolsets:
                toolsets[ts] = {
                    "available": self._evaluate_toolset_check(
                        ts, toolset_checks.get(ts)
                    ),
                    "tools": [],
                    "description": "",
                    "requirements": [],
                }
            toolsets[ts]["tools"].append(entry.name)
            if entry.requires_env:
                for env in entry.requires_env:
                    if env not in toolsets[ts]["requirements"]:
                        toolsets[ts]["requirements"].append(env)
        return toolsets

    def get_toolset_requirements(self) -> Dict[str, dict]:
        """Build a toolset-requirements dict for backward compat.

        Each value::

            {
                "name": str,
                "env_vars": [str, ...],
                "check_fn": Callable | None,
                "setup_url": None,
                "tools": [str, ...],
            }
        """
        result: Dict[str, dict] = {}
        entries, toolset_checks = self._snapshot_state()
        for entry in entries:
            ts = entry.toolset
            if ts not in result:
                result[ts] = {
                    "name": ts,
                    "env_vars": [],
                    "check_fn": toolset_checks.get(ts),
                    "setup_url": None,
                    "tools": [],
                }
            if entry.name not in result[ts]["tools"]:
                result[ts]["tools"].append(entry.name)
            for env in entry.requires_env:
                if env not in result[ts]["env_vars"]:
                    result[ts]["env_vars"].append(env)
        return result

    def check_tool_availability(self, quiet: bool = False) -> Tuple[List[str], List[dict]]:
        """Return ``(available_toolsets, unavailable_info)``.

        Each unavailable entry::

            {
                "name": str,
                "env_vars": [str, ...],
                "tools": [str, ...],
            }
        """
        available: List[str] = []
        unavailable: List[dict] = []
        seen: set = set()
        entries, toolset_checks = self._snapshot_state()
        for entry in entries:
            ts = entry.toolset
            if ts in seen:
                continue
            seen.add(ts)
            if self._evaluate_toolset_check(ts, toolset_checks.get(ts)):
                available.append(ts)
            else:
                unavailable.append({
                    "name": ts,
                    "env_vars": entry.requires_env or [],
                    "tools": [e.name for e in entries if e.toolset == ts],
                })
        return available, unavailable


# Module-level singleton
registry = ToolRegistry()


# ---------------------------------------------------------------------------
# Helpers for tool response serialization
# ---------------------------------------------------------------------------
# Every tool handler must return a JSON string.  These helpers eliminate the
# boilerplate ``json.dumps({"error": msg}, ensure_ascii=False)`` that appears
# hundreds of times across tool files.
#
# Usage:
#   from hermes_tools.registry import registry, tool_error, tool_result
#
#   return tool_error("something went wrong")
#   return tool_error("not found", code=404)
#   return tool_result(success=True, data=payload)
#   return tool_result(items)            # pass a dict directly


def tool_error(message: str, **extra: Any) -> str:
    """Return a JSON error string for tool handlers.

    >>> tool_error("file not found")
    '{"error": "file not found"}'
    >>> tool_error("bad input", success=False)
    '{"error": "bad input", "success": false}'
    """
    result = {"error": str(message)}
    if extra:
        result.update(extra)
    return json.dumps(result, ensure_ascii=False)


def tool_result(data: Optional[dict] = None, **kwargs: Any) -> str:
    """Return a JSON result string for tool handlers.

    Accepts a dict positional arg *or* keyword arguments (not both):

    >>> tool_result(success=True, count=42)
    '{"success": true, "count": 42}'
    >>> tool_result({"key": "value"})
    '{"key": "value"}'
    """
    if data is not None:
        return json.dumps(data, ensure_ascii=False)
    return json.dumps(kwargs, ensure_ascii=False)
