#!/usr/bin/env python3
"""Central manager for per-server MCP OAuth state.

One instance per :class:`MCPCore`, created in ``MCPCore._run_loop`` on the
MCP event loop thread with an explicit ``token_dir``. Holds per-server
OAuth provider instances and coordinates:

- **Cross-process token reload** via mtime-based disk watch.
- **401 deduplication** via in-flight futures keyed by failed access_token.
- **Reconnect signalling** for long-lived MCP sessions.
- **Lifecycle** via :meth:`close_admission` (sync, idempotent) and
  :meth:`aclose` (async, repeatable, waits for real cleanup). The
  :attr:`is_idle` property lets :class:`MCPCore` verify that all real
  resources (pending tasks, callback servers/threads, cleanup task)
  have exited.

Thread-safety: ``_entries`` is guarded by ``_entries_lock`` for
get-or-create semantics. Per-entry state is guarded by the entry's own
``asyncio.Lock`` (used from the MCP event loop thread). Callback server
registry is guarded by ``_callback_lock``.

OAuth errors (logic, storage, cleanup) propagate; the manager never
silently swallows exceptions to fabricate success.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from mcp.client.auth.oauth2 import OAuthClientProvider

from .oauth import _OAUTH_CALLBACK_TIMEOUT
from entity.constant import SYSTEM_QUIESCE_TIMEOUT_SECONDS
from entity.puretype import MCPOAuthProviderEntry
from system.lifecycle import ApplicationStoppingError, LifecycleFailure
from .oauth_callback import OAuthCallbackServer

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# McpOAuthProvider — OAuthClientProvider subclass with disk-watch
# ---------------------------------------------------------------------------


def _make_oauth_provider_class(manager: "MCPOAuthManager") -> type | None:
    """Lazy-import the SDK base class and return our subclass.

    Wrapped in a function so this module imports cleanly even when the
    MCP SDK's OAuth module is unavailable (e.g. older mcp versions).
    """
    try:
        from mcp.client.auth.oauth2 import OAuthClientProvider
    except ImportError:  # pragma: no cover — SDK required in CI
        return None

    class McpOAuthProvider(OAuthClientProvider):
        """OAuthClientProvider with pre-flow disk-mtime reload.

        Before every ``async_auth_flow`` invocation, asks the manager to
        check whether the tokens file on disk has been modified externally.
        If so, the manager resets ``_initialized`` so the next flow
        re-reads from storage.

        This makes external-process refreshes (cron, another CLI instance)
        visible to the running MCP session without requiring a restart.

        Reference: Claude Code's ``invalidateOAuthCacheIfDiskChanged``
        (``src/utils/auth.ts:1320``, CC-1096 / GH#24317).
        """

        def __init__(self, *args: object, server_name: str = "", **kwargs: object):
            super().__init__(*args, **kwargs)
            self._server_name = server_name

        async def _initialize(self) -> None:
            """Load stored tokens + client info AND seed token_expiry_time.

            Also eagerly fetches OAuth authorization-server metadata (PRM +
            ASM) when we have stored tokens but no cached metadata, so the
            SDK's ``_refresh_token`` can build the correct token_endpoint
            URL on the preemptive-refresh path.

            The SDK's base ``_initialize`` populates ``current_tokens`` but
            does NOT call ``update_token_expiry``, so ``token_expiry_time``
            stays ``None`` and ``is_token_valid()`` returns True for any
            loaded token regardless of actual age. After a process restart
            this ships stale Bearer tokens to the server.

            Seeding ``token_expiry_time`` from the reloaded token fixes that.
            Paired with :class:`McpTokenStorage` persisting an absolute
            ``expires_at`` timestamp so the remaining TTL reflects real
            wall-clock age.
            """
            await super()._initialize()
            tokens = self.context.current_tokens
            if tokens is not None and tokens.expires_in is not None:
                self.context.update_token_expiry(tokens)

            # Cold-load: restore OAuth server metadata from disk before any
            # refresh attempt.
            storage = self.context.storage
            from .oauth import McpTokenStorage
            if (
                isinstance(storage, McpTokenStorage)
                and self.context.oauth_metadata is None
            ):
                meta = storage.load_oauth_metadata()
                if meta is not None:
                    self.context.oauth_metadata = meta
                    logger.debug(
                        "MCP OAuth '%s': restored metadata from disk "
                        "(token_endpoint=%s)",
                        self._server_name,
                        meta.token_endpoint,
                    )

            # Pre-flight OAuth AS discovery so ``_refresh_token`` has a
            # correct ``token_endpoint`` before the first refresh attempt.
            if (
                tokens is not None
                and self.context.oauth_metadata is None
            ):
                await self._prefetch_oauth_metadata()

        async def _prefetch_oauth_metadata(self) -> None:
            """Fetch PRM + ASM from the well-known endpoints, cache on context.

            Mirrors the SDK's 401-branch discovery (oauth2.py ~line 511-551)
            but runs synchronously before the first request instead of
            inside the httpx auth_flow generator. Uses the SDK's own URL
            builders and response handlers so we track whatever the SDK
            version we're pinned to expects.
            """
            import httpx  # local import: httpx is an MCP SDK dependency
            from mcp.client.auth.utils import (
                build_oauth_authorization_server_metadata_discovery_urls,
                build_protected_resource_metadata_discovery_urls,
                create_oauth_metadata_request,
                handle_auth_metadata_response,
                handle_protected_resource_response,
            )

            server_url = self.context.server_url
            async with httpx.AsyncClient(timeout=10.0) as client:
                # Step 1: PRM discovery to learn the authorization_server URL.
                for url in build_protected_resource_metadata_discovery_urls(
                    None, server_url
                ):
                    req = create_oauth_metadata_request(url)
                    resp = await client.send(req)
                    prm = await handle_protected_resource_response(resp)
                    if prm:
                        self.context.protected_resource_metadata = prm
                        if prm.authorization_servers:
                            self.context.auth_server_url = str(
                                prm.authorization_servers[0]
                            )
                        break

                # Step 2: ASM discovery against the auth_server_url (or
                # server_url fallback for legacy providers).
                for url in build_oauth_authorization_server_metadata_discovery_urls(
                    self.context.auth_server_url, server_url
                ):
                    req = create_oauth_metadata_request(url)
                    resp = await client.send(req)
                    ok, asm = await handle_auth_metadata_response(resp)
                    if not ok:
                        break
                    if asm:
                        self.context.oauth_metadata = asm
                        # Persist immediately so a subsequent cold-load can
                        # skip discovery entirely.
                        storage = self.context.storage
                        from .oauth import McpTokenStorage
                        if isinstance(storage, McpTokenStorage):
                            storage.save_oauth_metadata(asm)
                        logger.debug(
                            "MCP OAuth '%s': pre-flight ASM discovered "
                            "token_endpoint=%s",
                            self._server_name, asm.token_endpoint,
                        )
                        break

        def _persist_oauth_metadata_if_changed(self) -> None:
            """Persist discovered OAuth metadata for future process restarts.

            Called after the SDK's normal 401-branch auth flow completes so
            metadata discovered via the lazy path (not pre-flight) is also
            saved. No-op when nothing to persist or metadata hasn't changed.
            """
            meta = self.context.oauth_metadata
            if meta is None:
                return
            storage = self.context.storage
            from .oauth import McpTokenStorage
            if not isinstance(storage, McpTokenStorage):
                return
            existing = storage.load_oauth_metadata()
            if (
                existing is None
                or str(existing.token_endpoint) != str(meta.token_endpoint)
            ):
                storage.save_oauth_metadata(meta)

        async def async_auth_flow(self, request):  # type: ignore[override]
            manager.require_open()
            await manager.invalidate_if_disk_changed(self._server_name)

            # Bridge the bidirectional generator protocol. httpx's
            # auth_flow driver calls ``auth_flow.asend(response)`` to feed
            # HTTP responses back into the generator. A naive wrapper using
            # ``async for item in inner: yield item`` DISCARDS those
            # .asend(response) values and resumes the inner generator with
            # None, so the SDK's ``response = yield request`` branch sees
            # response=None and crashes.
            #
            # The bridge below forwards each .asend() value into the inner
            # generator via inner.asend(incoming), preserving the
            # bidirectional contract. The finally clause ensures the inner
            # generator is always closed, even on cancellation.
            inner = super().async_auth_flow(request)
            try:
                outgoing = await inner.__anext__()
                while True:
                    incoming = yield outgoing
                    outgoing = await inner.asend(incoming)
            except StopAsyncIteration:
                # Persist any metadata the SDK discovered lazily during the
                # 401 branch so a subsequent cold-load skips discovery.
                self._persist_oauth_metadata_if_changed()
                return
            finally:
                # Ensure the inner generator is always closed. If we exit
                # normally (StopAsyncIteration) the generator is already
                # exhausted and aclose is a no-op. If we exit via
                # cancellation or exception, aclose propagates the
                # cancellation into the inner generator so its finally
                # blocks run and transport resources are released.
                await inner.aclose()

    return McpOAuthProvider


# ---------------------------------------------------------------------------
# Manager
# ---------------------------------------------------------------------------


class MCPOAuthManager:
    """Single source of truth for per-server MCP OAuth state.

    Created by :class:`MCPCore` with an explicit ``token_dir``. The Core
    calls ``close_admission()`` (sync) to stop new OAuth work, then
    ``await aclose()`` to wait for real cleanup. The ``is_idle`` property
    verifies that all pending tasks, callback servers/threads, and the
    cleanup task itself have exited.

    Thread-safe: the ``_entries`` dict is guarded by ``_entries_lock`` for
    get-or-create semantics. Per-entry state is guarded by the entry's own
    ``asyncio.Lock`` (used from the MCP event loop thread).
    """

    def __init__(self, token_dir: Path) -> None:
        self._token_dir = token_dir
        self._entries: dict[str, MCPOAuthProviderEntry] = {}
        self._entries_lock = threading.Lock()
        self._active_calls: set[asyncio.Task[Any]] = set()
        self._callback_waits: dict[int, OAuthCallbackServer] = {}
        self._loop = asyncio.get_running_loop()
        self._closed = False
        self._aclose_done = False
        self._aclose_task: asyncio.Task[None] | None = None

    # -- Provider construction / caching -------------------------------------

    def get_or_build_provider(
        self,
        server_name: str,
        server_url: str,
        oauth_config: dict | None,
    ) -> OAuthClientProvider | None:
        """Return a cached OAuth provider for ``server_name`` or build one.

        Idempotent: repeat calls with the same name return the same instance.
        If ``server_url`` changes for a given name, the cached entry is
        discarded and a fresh provider is built.

        Returns None if the MCP SDK's OAuth support is unavailable.
        """
        self.require_open()
        with self._entries_lock:
            entry = self._entries.get(server_name)
            if entry is not None and entry.server_url != server_url:
                logger.info(
                    "MCP OAuth '%s': URL changed from %s to %s, discarding cache",
                    server_name, entry.server_url, server_url,
                )
                entry = None

            if entry is None:
                entry = MCPOAuthProviderEntry(
                    server_url=server_url,
                    oauth_config=oauth_config,
                )
                self._entries[server_name] = entry

            if entry.provider is None:
                entry.provider = self._build_provider(server_name, entry)

            return entry.provider

    def _build_provider(
        self,
        server_name: str,
        entry: MCPOAuthProviderEntry,
    ) -> OAuthClientProvider | None:
        """Build the underlying OAuth provider.

        Constructs :class:`McpOAuthProvider` directly using the helpers
        from ``oauth.py``. The subclass injects a pre-flow disk-watch hook
        so external token refreshes are visible to running MCP sessions.
        The provider closure captures ``self`` (the manager) so callback
        servers can be registered for shutdown cleanup.

        Returns None if the MCP SDK's OAuth support is unavailable.
        """
        provider_cls = _make_oauth_provider_class(self)
        if provider_cls is None:
            raise ImportError(f"MCP OAuth SDK support is required for '{server_name}'")

        from .oauth import (
            McpTokenStorage,
            _OAUTH_AVAILABLE,
            _build_client_metadata,
            _configure_callback_port,
            _is_interactive,
            _maybe_preregister_client,
            _redirect_handler,
            _wait_for_callback,
        )

        if not _OAUTH_AVAILABLE:
            raise ImportError(f"MCP OAuth SDK support is required for '{server_name}'")

        cfg = dict(entry.oauth_config or {})
        storage = McpTokenStorage(server_name, self._token_dir)

        if not _is_interactive() and not storage.has_cached_tokens():
            logger.warning(
                "MCP OAuth for '%s': non-interactive environment and no "
                "cached tokens found. Run interactively first to complete "
                "initial authorization.",
                server_name,
            )

        port = _configure_callback_port(cfg)
        entry.resolved_port = port
        client_metadata = _build_client_metadata(cfg)
        _maybe_preregister_client(storage, cfg, client_metadata)

        return provider_cls(
            server_name=server_name,
            server_url=entry.server_url,
            client_metadata=client_metadata,
            storage=storage,
            redirect_handler=partial(_redirect_handler, port=port),
            callback_handler=partial(
                _wait_for_callback,
                manager=self,
                port=port,
                timeout=float(cfg.get("timeout", _OAUTH_CALLBACK_TIMEOUT)),
            ),
            timeout=float(cfg.get("timeout", _OAUTH_CALLBACK_TIMEOUT)),
        )

    def remove(self, server_name: str) -> None:
        """Evict the provider from cache AND delete tokens from disk.

        Called during forced re-auth to clear stale OAuth state. This is a
        user-initiated operation, not application shutdown.
        """
        with self._entries_lock:
            self._entries.pop(server_name, None)

        from .oauth import McpTokenStorage
        McpTokenStorage(server_name, self._token_dir).remove()
        logger.info(
            "MCP OAuth '%s': evicted from cache and removed from disk",
            server_name,
        )

    # -- Disk watch ----------------------------------------------------------

    async def invalidate_if_disk_changed(self, server_name: str) -> bool:
        """If the tokens file on disk has a newer mtime than last-seen, force
        the MCP SDK provider to reload its in-memory state.

        Returns True if the cache was invalidated (mtime differed). This is
        the core fix for the external-refresh workflow: a cron job writes
        fresh tokens to disk, and on the next tool call the running MCP
        session picks them up without a restart.
        """
        self.require_open()
        from .oauth import _safe_filename

        entry = self._entries.get(server_name)
        if entry is None or entry.provider is None:
            return False

        async with entry.lock:
            tokens_path = self._token_dir / f"{_safe_filename(server_name)}.json"
            try:
                mtime_ns = tokens_path.stat().st_mtime_ns
            except FileNotFoundError:
                return False

            if mtime_ns != entry.last_mtime_ns:
                old = entry.last_mtime_ns
                entry.last_mtime_ns = mtime_ns
                # Force the SDK's OAuthClientProvider to reload from storage
                # on its next auth flow. ``_initialized`` is a known field on
                # OAuthClientProvider (oauth2.py line 268), not a dynamic
                # attribute; accessed directly per project no-reflection rule.
                entry.provider._initialized = False  # noqa: SLF001
                logger.info(
                    "MCP OAuth '%s': tokens file changed (mtime %d -> %d), "
                    "forcing reload",
                    server_name, old, mtime_ns,
                )
                return True
            return False

    # -- 401 handler (dedup'd) -----------------------------------------------

    async def handle_401(
        self,
        server_name: str,
        failed_access_token: str | None = None,
    ) -> bool:
        """Handle a 401 from a tool call, deduplicated across concurrent callers.

        Returns:
            True  if a (possibly new) access token is now available — caller
                  should trigger a reconnect and retry the operation.
            False if no recovery path exists — caller should surface a
                  ``needs_reauth`` error to the model.

        Thundering-herd protection: if N concurrent tool calls hit 401 with
        the same ``failed_access_token``, only one recovery attempt fires.
        Others await the same future.

        The 401 handler task is owned by this manager and tracked in
        ``_pending_tasks`` so :meth:`aclose` can cancel and await it. The
        per-entry ``asyncio.Lock`` serialises concurrent 401 handling for
        the same server so we don't race on provider state.

        If the caller (a dedup waiter) is cancelled while awaiting the
        shared future, the future itself is NOT cancelled — other waiters
        still get their result. On shutdown, ``_release_pending_401``
        cancels all shared futures so no waiter hangs.
        """
        self._check_loop()
        if self._closed:
            return False
        entry = self._entries.get(server_name)
        if entry is None or entry.provider is None:
            return False
        caller = asyncio.current_task()
        if caller is None:
            raise LifecycleFailure("OAuth recovery requires an owned calling task")
        self._active_calls.add(caller)
        key = failed_access_token or "<unknown>"
        leader = False
        pending: asyncio.Future[bool] | None = None
        try:
            async with entry.lock:
                if self._closed:
                    return False
                pending = entry.pending_401.get(key)
                if pending is None:
                    pending = self._loop.create_future()
                    pending.add_done_callback(self._observe_pending)
                    entry.pending_401[key] = pending
                    leader = True
            if not leader:
                return await asyncio.shield(pending)
            # 第一位请求方直接负责真实操作，不另起无人等待的认证task。
            # 其取消责任已经由Core的请求TaskOwner持有，其他等待方只共享结果。
            changed = await self.invalidate_if_disk_changed(server_name)
            value = changed or entry.provider.context.can_refresh_token()
            if not pending.done():
                pending.set_result(value)
            return pending.result()
        except asyncio.CancelledError:
            if leader and pending is not None and not pending.done():
                pending.set_exception(ApplicationStoppingError("OAuth recovery caller was cancelled"))
            raise
        except BaseException as error:
            if leader and pending is not None and not pending.done():
                pending.set_exception(error)
            raise
        finally:
            if leader:
                entry.pending_401.pop(key, None)
            self._active_calls.discard(caller)

    @staticmethod
    def _observe_pending(future: asyncio.Future[bool]) -> None:
        if not future.cancelled():
            future.exception()

    # -- Callback server registry (internal) --------------------------------

    def _check_loop(self) -> None:
        if asyncio.get_running_loop() is not self._loop:
            raise LifecycleFailure("MCP OAuth manager used from a foreign loop")

    def require_open(self) -> None:
        self._check_loop()
        if self._closed:
            raise ApplicationStoppingError("MCP OAuth manager admission is closed")

    def register_callback(self, callback: OAuthCallbackServer) -> None:
        self._check_loop()
        if self._closed:
            raise ApplicationStoppingError("OAuth callback admission is closed")
        self._callback_waits[id(callback)] = callback

    def release_callback(self, callback: OAuthCallbackServer) -> None:
        self._check_loop()
        if callback.is_idle:
            self._callback_waits.pop(id(callback), None)

    def close_admission(self) -> None:
        self._check_loop()
        self._closed = True
        for entry in self._entries.values():
            for pending in entry.pending_401.values():
                if not pending.done():
                    pending.set_result(False)
        for callback in tuple(self._callback_waits.values()):
            callback.request_stop()

    @property
    def is_idle(self) -> bool:
        self._check_loop()
        return (
            not self._active_calls
            and all(callback.is_idle for callback in self._callback_waits.values())
            and (self._aclose_task is None or self._aclose_task.done())
        )

    async def aclose(self) -> None:
        self._check_loop()
        if asyncio.current_task() in self._active_calls:
            raise LifecycleFailure("OAuth recovery cannot wait for its own shutdown")
        self.close_admission()
        if self._aclose_task is None:
            self._aclose_task = asyncio.create_task(self._do_aclose(), name="mcp-oauth-close")
            self._aclose_task.add_done_callback(self._observe_close)
        await asyncio.shield(self._aclose_task)

    @staticmethod
    def _observe_close(task: asyncio.Task[None]) -> None:
        if not task.cancelled():
            task.exception()

    async def _do_aclose(self) -> None:
        errors: list[BaseException] = []
        for callback in tuple(self._callback_waits.values()):
            try:
                await callback.aclose()
            except BaseException as error:
                errors.append(error)
            self.release_callback(callback)
        # 调用task归Core请求Owner，Manager不再对借用task发第二次取消。
        # Core已停止请求/连接；此处只确认结果交接退出，不抢占其取消责任。
        if self._active_calls:
            _, pending = await asyncio.wait(
                tuple(self._active_calls), timeout=SYSTEM_QUIESCE_TIMEOUT_SECONDS,
            )
            if pending:
                errors.append(LifecycleFailure("OAuth request handoffs remain active"))
                for task in pending:
                    if not task.done():
                        task.cancel()
        if errors:
            raise BaseExceptionGroup("MCP OAuth shutdown failed", errors)
        self._entries.clear()
