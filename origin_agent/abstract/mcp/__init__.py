"""MCP client support for Evolve Agent.

Connects to MCP servers via stdio, HTTP/StreamableHTTP, or SSE transport,
discovers their tools, and registers them into the evolve-agent tool registry.

Dependencies:
    - ``mcp>=1.0.0`` — MCP Python SDK (required)

Usage:
    >>> from abstract.mcp.client import MCPServerRegistry, _tool_registry
    >>> from abstract.mcp.oauth_manager import MCPOAuthManager, get_manager

    # Set up tool registration callbacks
    >>> _tool_registry.on_register = lambda name, schema, handler: print(f"Registered: {name}")

    # Connect to MCP servers
    >>> from abstract.mcp.client import register_mcp_servers, shutdown_mcp_servers
    >>> tools = register_mcp_servers({
    ...     "time": {"command": "uvx", "args": ["mcp-server-time"]},
    ... })
    >>> print(f"Registered {len(tools)} MCP tools")
"""

from .oauth import build_oauth_auth, remove_oauth_tokens, McpTokenStorage
from .oauth_manager import MCPOAuthManager, get_manager
from .client import (
    MCPServerRegistry,
    MCPServerTask,
    SamplingHandler,
    _tool_registry,
    register_mcp_servers,
    shutdown_mcp_servers,
    get_mcp_status,
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
    "McpTokenStorage",
    "MCPOAuthManager",
    "get_manager",
    # Client
    "MCPServerRegistry",
    "MCPServerTask",
    "SamplingHandler",
    "_tool_registry",
    "register_mcp_servers",
    "shutdown_mcp_servers",
    "get_mcp_status",
    # Helpers
    "_build_safe_env",
    "_sanitize_error",
    "_validate_remote_mcp_url",
    "sanitize_mcp_name_component",
    "_ENV_VAR_PATTERN",
    "_CREDENTIAL_PATTERN",
]