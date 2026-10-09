#!/usr/bin/env python3
"""
MCP OAuth 2.1 Client Support

Implements the browser-based OAuth 2.1 authorization code flow with PKCE
for MCP servers that require OAuth authentication instead of static bearer
tokens.

Uses the MCP Python SDK's ``OAuthClientProvider`` (an ``httpx.Auth`` subclass)
which handles discovery, dynamic client registration, PKCE, token exchange,
refresh, and step-up authorization automatically.

This module provides the glue:
    - ``McpTokenStorage``: persists tokens/client-info to disk so they
      survive across process restarts.
    - Callback server: ephemeral localhost HTTP server to capture the OAuth
      redirect with the authorization code.
    - Provider factory helpers used by :class:`MCPOAuthManager` to build
      the ``httpx.Auth`` object with per-provider callback ports and
      explicit token directories.

Configuration in config.yaml::

    mcp_servers:
      my_server:
        url: "https://mcp.example.com/mcp"
        auth: oauth
        oauth:                                  # all fields optional
          client_id: "pre-registered-id"        # skip dynamic registration
          client_secret: "secret"               # confidential clients only
          scope: "read write"                   # default: server-provided
          redirect_port: 0                      # 0 = auto-pick free port
          client_name: "My Custom Client"       # default: "Evolve-Agent"
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import secrets
import socket
import stat
import sys
import time
import webbrowser
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import parse_qs, urlparse

logger = logging.getLogger(__name__)

from system.atomic_io import replace_atomic

# OAuth lifecycle constants from entity.constant
from entity.constant.mcp_oauth import (
    OAUTH_CALLBACK_TIMEOUT as _OAUTH_CALLBACK_TIMEOUT,
)

if TYPE_CHECKING:
    from .oauth_manager import MCPOAuthManager

# ---------------------------------------------------------------------------
# Lazy imports -- MCP SDK with OAuth support is optional
# ---------------------------------------------------------------------------

_OAUTH_AVAILABLE=False
try:
    from mcp.client.auth import OAuthClientProvider
    from mcp.shared.auth import (
        OAuthClientInformationFull,
        OAuthClientMetadata,
        OAuthMetadata,
        OAuthToken,
    )

    _OAUTH_AVAILABLE=True
except ImportError:
    logger.debug("MCP OAuth types not available -- OAuth MCP auth disabled")

try:
    from pydantic import AnyUrl
except ImportError:
    AnyUrl = None  # type: ignore[assignment, misc]


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class OAuthNonInteractiveError(RuntimeError):
    """Raised when OAuth requires browser interaction in a non-interactive env."""


# ---------------------------------------------------------------------------
# Module-level state
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _safe_filename(name: str) -> str:
    """Sanitize a server name for use as a filename (no path separators)."""
    return re.sub(r"[^\w\-]", "_", name).strip("_")[:128] or "default"


def _find_free_port() -> int:
    """Find an available TCP port on localhost."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _is_interactive() -> bool:
    """Return True if we can reasonably expect to interact with a user."""
    try:
        return sys.stdin.isatty()
    except (AttributeError, ValueError):
        return False


def _can_open_browser() -> bool:
    """Return True if opening a browser is likely to work."""
    # Explicit SSH session → no local display
    if os.environ.get("SSH_CLIENT") or os.environ.get("SSH_TTY"):
        return False
    # macOS and Windows usually have a display
    if os.name == "nt":
        return True
    try:
        if os.uname().sysname == "Darwin":
            return True
    except AttributeError:
        pass
    # Linux/other posix: need DISPLAY or WAYLAND_DISPLAY
    if os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"):
        return True
    return False


def _read_json(path: Path) -> dict | None:
    """Read existing credentials strictly; only a missing file is optional."""
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    data = json.loads(text)
    if not isinstance(data, dict):
        raise TypeError(f"OAuth JSON root must be an object: {path}")
    return data


def _write_json(path: Path, data: dict) -> None:
    """Write a dict as JSON with restricted permissions (0o600).

    Uses ``os.open`` with ``O_EXCL`` and an explicit mode so the file is
    created atomically at 0o600. The previous ``write_text`` + post-write
    ``chmod`` opened a TOCTOU window where the temp file briefly inherited
    the process umask (commonly 0o644 = world-readable), exposing OAuth
    tokens to other local users between create and chmod. Mirrors the fix
    in ``agent/google_oauth.py`` (#19673).
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    # POSIX权限收紧属于凭据写入要求，失败不能伪装成功。
    if os.name != "nt":
        os.chmod(path.parent, 0o700)
    # Per-process random suffix avoids collisions between concurrent
    # writers and stale leftovers from a prior crashed write.
    tmp = path.with_suffix(f".tmp.{os.getpid()}.{secrets.token_hex(4)}")
    try:
        fd = os.open(
            str(tmp),
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            stat.S_IRUSR | stat.S_IWUSR,
        )
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, default=str)
            fh.flush()
            os.fsync(fh.fileno())
        replace_atomic(tmp, path)
    except BaseException as original:
        try:
            tmp.unlink(missing_ok=True)
        except BaseException as cleanup:
            raise BaseExceptionGroup("OAuth write and temporary cleanup failed", [original, cleanup])
        raise


# ---------------------------------------------------------------------------
# McpTokenStorage -- persistent token/client-info on disk
# ---------------------------------------------------------------------------


class McpTokenStorage:
    """Persist OAuth tokens and client registration to JSON files.

    File layout::

        agentspace/mcp-tokens/<server_name>.json         -- tokens
        agentspace/mcp-tokens/<server_name>.client.json   -- client info
        agentspace/mcp-tokens/<server_name>.meta.json     -- oauth server metadata
    """

    def __init__(self, server_name: str, token_dir: Path):
        self._server_name = _safe_filename(server_name)
        self._token_dir = token_dir

    def _tokens_path(self) -> Path:
        return self._token_dir / f"{self._server_name}.json"

    def _client_info_path(self) -> Path:
        return self._token_dir / f"{self._server_name}.client.json"

    def _meta_path(self) -> Path:
        return self._token_dir / f"{self._server_name}.meta.json"

    # -- tokens ------------------------------------------------------------

    async def get_tokens(self) -> "OAuthToken | None":
        data = _read_json(self._tokens_path())
        if data is None:
            return None
        # The token storage records an absolute wall-clock ``expires_at`` alongside the
        # SDK's serialized token (see ``set_tokens``). On read we rewrite
        # ``expires_in`` to the remaining seconds so the SDK's downstream
        # ``update_token_expiry`` computes the correct absolute time and
        # ``is_token_valid()`` correctly reports False for tokens that
        # expired while the process was down.
        #
        # Legacy token files (pre-Fix-A) have ``expires_in`` but no
        # ``expires_at``. We fall back to the file's mtime as a best-effort
        # wall-clock proxy for when the token was written: if (mtime +
        # expires_in) is in the past, clamp ``expires_in`` to zero so the
        # SDK refreshes before the first request. This self-heals one-time
        # on the next successful ``set_tokens``, which writes the new
        # ``expires_at`` field. The stored ``expires_at`` is stripped before
        # model_validate because it's not part of the SDK's OAuthToken schema.
        absolute_expiry = data.pop("expires_at", None)
        if absolute_expiry is not None:
            data["expires_in"] = int(max(absolute_expiry - time.time(), 0))
        elif data.get("expires_in") is not None:
            file_mtime = self._tokens_path().stat().st_mtime
            implied_expiry = file_mtime + int(data["expires_in"])
            data["expires_in"] = int(max(implied_expiry - time.time(), 0))
        return OAuthToken.model_validate(data)

    async def set_tokens(self, tokens: "OAuthToken") -> None:
        payload = tokens.model_dump(mode="json", exclude_none=True)
        # Persist an absolute ``expires_at`` so a process restart can
        # reconstruct the correct remaining TTL. Without this the MCP SDK's
        # ``_initialize`` reloads a relative ``expires_in`` which has no
        # wall-clock reference, leaving ``context.token_expiry_time=None``
        # and ``is_token_valid()`` falsely reporting True. See Fix A in
        # ``mcp-oauth-token-diagnosis`` skill + Claude Code's
        # ``OAuthTokens.expiresAt`` persistence (auth.ts ~180).
        expires_in = payload.get("expires_in")
        if expires_in is not None:
            payload["expires_at"] = time.time() + int(expires_in)
        _write_json(self._tokens_path(), payload)
        logger.debug("OAuth tokens saved for %s", self._server_name)

    # -- client info -------------------------------------------------------

    async def get_client_info(self) -> "OAuthClientInformationFull | None":
        data = _read_json(self._client_info_path())
        if data is None:
            return None
        return OAuthClientInformationFull.model_validate(data)

    async def set_client_info(self, client_info: "OAuthClientInformationFull") -> None:
        _write_json(self._client_info_path(), client_info.model_dump(mode="json", exclude_none=True))
        logger.debug("OAuth client info saved for %s", self._server_name)

    # -- oauth server metadata --------------------------------------------
    # The MCP SDK keeps discovered ``OAuthMetadata`` (token endpoint URL,
    # etc.) in memory only. Persisting it here lets a restarted process
    # refresh tokens without re-running metadata discovery. Without this,
    # cold-start refresh requests fall back to the SDK's guessed
    # ``{server_url}/token`` which returns 404 on most real providers and
    # forces a full browser re-authorization.

    def save_oauth_metadata(self, metadata: "OAuthMetadata") -> None:
        _write_json(self._meta_path(), metadata.model_dump(exclude_none=True, mode="json"))
        logger.debug("OAuth metadata saved for %s", self._server_name)

    def load_oauth_metadata(self) -> "OAuthMetadata | None":
        data = _read_json(self._meta_path())
        if data is None:
            return None
        return OAuthMetadata.model_validate(data)

    # -- cleanup -----------------------------------------------------------

    def remove(self) -> None:
        """Delete all stored OAuth state for this server."""
        for p in (self._tokens_path(), self._client_info_path(), self._meta_path()):
            p.unlink(missing_ok=True)

    def has_cached_tokens(self) -> bool:
        """Return True if we have tokens on disk (may be expired)."""
        return self._tokens_path().exists()


# ---------------------------------------------------------------------------
# Callback handler factory -- each invocation gets its own result dict
# ---------------------------------------------------------------------------


def _make_callback_handler() -> tuple[type, dict]:
    """Create a per-flow callback HTTP handler class with its own result dict.

    Returns ``(HandlerClass, result_dict)`` where *result_dict* is a mutable
    dict that the handler writes ``auth_code`` and ``state`` into when the
    OAuth redirect arrives.  Each call returns a fresh pair so concurrent
    flows don't stomp on each other.
    """
    result: dict[str, str | None] = {"auth_code": None, "state": None, "error": None}

    class _Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            params = parse_qs(urlparse(self.path).query)
            code = params.get("code", [None])[0]
            state = params.get("state", [None])[0]
            error = params.get("error", [None])[0]

            result["auth_code"] = code
            result["state"] = state
            result["error"] = error

            body = (
                "<html><body><h2>Authorization Successful</h2>"
                "<p>You can close this tab and return to the agent.</p></body></html>"
            ) if code else (
                "<html><body><h2>Authorization Failed</h2>"
                f"<p>Error: {error or 'unknown'}</p></body></html>"
            )
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(body.encode())

        def log_message(self, fmt: str, *args: object) -> None:
            logger.debug("OAuth callback: %s", fmt % args)

    return _Handler, result


# ---------------------------------------------------------------------------
# Async redirect + callback handlers for OAuthClientProvider
# ---------------------------------------------------------------------------


async def _redirect_handler(authorization_url: str, *, port: int | None = None) -> None:
    """Show the authorization URL to the user.

    Opens the browser automatically when possible; always prints the URL
    as a fallback for headless/SSH/gateway environments.
    """
    msg = (
        f"\n  MCP OAuth: authorization required.\n"
        f"  Open this URL in your browser:\n\n"
        f"    {authorization_url}\n"
    )
    print(msg, file=sys.stderr)

    # On a remote SSH session the OAuth provider redirects to
    # http://127.0.0.1:<port>/callback, which reaches the callback server on
    # the *remote* machine — not the user's local machine where the browser
    # opened.  Print a port-forward hint so the user knows to tunnel first.
    callback_port = port
    if callback_port and (os.getenv("SSH_CLIENT") or os.getenv("SSH_TTY")):
        print(
            f"  Remote session detected. The OAuth provider will redirect your browser to\n"
            f"    http://127.0.0.1:{callback_port}/callback\n"
            f"  which the callback listener on THIS machine is waiting on. If your browser\n"
            f"  is on a different machine, forward the port first in a separate terminal:\n"
            f"\n"
            f"    ssh -N -L {callback_port}:127.0.0.1:{callback_port} <user>@<this-host>\n"
            f"\n"
            f"  Then open the URL above.\n",
            file=sys.stderr,
        )

    if _can_open_browser():
        try:
            opened = webbrowser.open(authorization_url)
            if opened:
                print("  (Browser opened automatically.)\n", file=sys.stderr)
            else:
                print("  (Could not open browser — please open the URL manually.)\n", file=sys.stderr)
        except Exception:
            print("  (Could not open browser — please open the URL manually.)\n", file=sys.stderr)
    else:
        print("  (Headless environment detected — open the URL manually.)\n", file=sys.stderr)


async def _wait_for_callback(
    *, port: int, timeout: float = _OAUTH_CALLBACK_TIMEOUT,
    manager: MCPOAuthManager,
) -> tuple[str, str | None]:
    """Await one owned listener and confirm native cleanup before release."""
    from .oauth_callback import OAuthCallbackServer
    from system.lifecycle import ApplicationStoppingError
    import anyio

    manager.require_open()
    handler, result = _make_callback_handler()
    callback = OAuthCallbackServer(port, handler, result)
    manager.register_callback(callback)
    original: BaseException | None = None
    try:
        callback.start()
        try:
            await callback.wait(timeout)
        except TimeoutError as error:
            raise OAuthNonInteractiveError("OAuth callback timed out without an authorization code") from error
        if result["error"]:
            raise RuntimeError(f"OAuth authorization failed: {result['error']}")
        if result["auth_code"] is None:
            raise ApplicationStoppingError("OAuth callback stopped before authorization completed")
        return result["auth_code"], result["state"]
    except BaseException as error:
        original = error
        raise
    finally:
        try:
            # SDK传输取消作用域已取消时，仍等待独立且受持有的原生join任务。
            with anyio.CancelScope(shield=True):
                await callback.aclose()
        except BaseException as cleanup:
            if original is not None:
                raise BaseExceptionGroup("OAuth callback and cleanup failed", [original, cleanup])
            raise
        finally:
            manager.release_callback(callback)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def remove_oauth_tokens(server_name: str, token_dir: Path) -> None:
    """Delete stored OAuth tokens and client info for a server.

    This is a user-initiated re-authorization operation; application shutdown
    must NOT call this — tokens are preserved across restarts.
    """
    storage = McpTokenStorage(server_name, token_dir)
    storage.remove()
    logger.info("OAuth tokens removed for '%s'", server_name)


# ---------------------------------------------------------------------------
# Provider factory helpers
#
# These compose into the MCPOAuthManager._build_provider path. They are
# module-level pure functions that take explicit parameters; no global
# state is read or written.
# ---------------------------------------------------------------------------


def _configure_callback_port(cfg: dict) -> int:
    """Pick a callback port for one OAuth provider configuration.

    Mutates the local ``cfg`` copy by setting ``_resolved_port`` so downstream
    helpers can read it. Each provider gets its own port; no module-level
    port state is involved.
    """
    requested = int(cfg.get("redirect_port", 0))
    port = _find_free_port() if requested == 0 else requested
    cfg["_resolved_port"] = port
    return port


def _build_client_metadata(cfg: dict) -> "OAuthClientMetadata":
    """Build OAuthClientMetadata from the oauth config dict.

    Requires ``cfg['_resolved_port']`` to have been populated by
    :func:`_configure_callback_port` first.
    """
    port = cfg.get("_resolved_port")
    if port is None:
        raise ValueError(
            "_configure_callback_port() must be called before _build_client_metadata()"
        )
    client_name = cfg.get("client_name", "Evolve-Agent")
    scope = cfg.get("scope")
    redirect_uri = f"http://127.0.0.1:{port}/callback"

    metadata_kwargs: dict[str, str | list[str] | list[AnyUrl]] = {
        "client_name": client_name,
        "redirect_uris": [AnyUrl(redirect_uri)],
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
        "token_endpoint_auth_method": "none",
    }
    if scope:
        metadata_kwargs["scope"] = scope
    if cfg.get("client_secret"):
        metadata_kwargs["token_endpoint_auth_method"] = "client_secret_post"

    return OAuthClientMetadata.model_validate(metadata_kwargs)


def _maybe_preregister_client(
    storage: "McpTokenStorage",
    cfg: dict,
    client_metadata: "OAuthClientMetadata",
) -> None:
    """If cfg has a pre-registered client_id, persist it to storage."""
    client_id = cfg.get("client_id")
    if not client_id:
        return
    port = cfg["_resolved_port"]
    redirect_uri = f"http://127.0.0.1:{port}/callback"

    info_dict: dict[str, str | list[str]] = {
        "client_id": client_id,
        "redirect_uris": [redirect_uri],
        "grant_types": client_metadata.grant_types,
        "response_types": client_metadata.response_types,
        "token_endpoint_auth_method": client_metadata.token_endpoint_auth_method,
    }
    if cfg.get("client_secret"):
        info_dict["client_secret"] = cfg["client_secret"]
    if cfg.get("client_name"):
        info_dict["client_name"] = cfg["client_name"]
    if cfg.get("scope"):
        info_dict["scope"] = cfg["scope"]

    client_info = OAuthClientInformationFull.model_validate(info_dict)
    _write_json(storage._client_info_path(), client_info.model_dump(mode="json", exclude_none=True))
    logger.debug("Pre-registered client_id=%s for '%s'", client_id, storage._server_name)
