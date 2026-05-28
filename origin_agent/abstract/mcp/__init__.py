"""Hermes MCP — Model Context Protocol client library.

Standalone package extracted from Hermes Agent. Provides a full MCP client
that can connect to MCP servers via stdio, HTTP/StreamableHTTP, or SSE
transport, discover their tools, and call them programmatically.

Dependencies:
    - ``mcp>=1.0.0`` — MCP Python SDK (required)

Usage:
    >>> from hermes_mcp.client import MCPServerRegistry, _tool_registry
    >>> from hermes_mcp.oauth_manager import MCPOAuthManager, get_manager

    # Set up tool registration callbacks
    >>> _tool_registry.on_register = lambda name, schema, handler: print(f"Registered: {name}")

    # Connect to MCP servers
    >>> from hermes_mcp.client import register_mcp_servers, shutdown_mcp_servers
    >>> tools = register_mcp_servers({
    ...     "time": {"command": "uvx", "args": ["mcp-server-time"]},
    ... })
    >>> print(f"Registered {len(tools)} MCP tools")
"""

from .oauth import build_oauth_auth, remove_oauth_tokens, HermesTokenStorage
from .oauth_manager import MCPOAuthManager, get_manager
from .client import (
    MCPServerRegistry,
    MCPServerTask,
    SamplingHandler,
    _tool_registry,
    register_mcp_servers,
    discover_mcp_tools,
    shutdown_mcp_servers,
    get_mcp_status,
    is_mcp_tool_parallel_safe,
    probe_mcp_server_tools,
    _build_safe_env,
    _sanitize_error,
    _validate_remote_mcp_url,
    sanitize_mcp_name_component,
    _ENV_VAR_PATTERN,
    _CREDENTIAL_PATTERN,
)

__all__ = [
    # OAuth
    "build_oauth_auth",
    "remove_oauth_tokens",
    "HermesTokenStorage",
    "MCPOAuthManager",
    "get_manager",
    # Client
    "MCPServerRegistry",
    "MCPServerTask",
    "SamplingHandler",
    "_tool_registry",
    "register_mcp_servers",
    "discover_mcp_tools",
    "shutdown_mcp_servers",
    "get_mcp_status",
    "is_mcp_tool_parallel_safe",
    "probe_mcp_server_tools",
    # Helpers
    "_build_safe_env",
    "_sanitize_error",
    "_validate_remote_mcp_url",
    "sanitize_mcp_name_component",
    "_ENV_VAR_PATTERN",
    "_CREDENTIAL_PATTERN",
]
