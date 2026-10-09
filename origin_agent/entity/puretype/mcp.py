"""Non-persistent MCP cross-thread result ownership and OAuth lifecycle data."""

import asyncio
import concurrent.futures
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class MCPBridgeCall(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    result: concurrent.futures.Future[Any] = Field(default_factory=concurrent.futures.Future)
    task: asyncio.Task[Any] | None = None
    cancel_requested: bool = False
    cancel_sent: bool = False
    request_released: bool = False


class MCPOAuthProviderEntry(BaseModel):
    """Per-server OAuth state tracked by MCPOAuthManager (in-process only).

    Fields:
        server_url: The MCP server URL used to build the provider.
        oauth_config: Optional dict from ``mcp_servers.<name>.oauth``.
        provider: The httpx.Auth-compatible provider; None until first use.
            Typed as Any because OAuthClientProvider is only available when
            the optional MCP SDK is installed.
        last_mtime_ns: Last-seen st_mtime_ns of the on-disk tokens file.
        lock: Serialises concurrent access to this entry's state.
        pending_401: In-flight 401-handler futures keyed by failed
            access_token, for deduplicating thundering-herd 401s.
        resolved_port: The callback port bound for this provider.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    server_url: str
    oauth_config: dict | None = None
    provider: Any = None
    last_mtime_ns: int = 0
    lock: asyncio.Lock = Field(default_factory=asyncio.Lock)
    pending_401: dict[str, "asyncio.Future[bool]"] = Field(default_factory=dict)
    resolved_port: int = 0


