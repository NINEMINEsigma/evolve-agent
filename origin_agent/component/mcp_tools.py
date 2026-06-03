"""MCP 工具桥接模块 — 将 MCP server 工具接入 ToolRegistry。

本模块在导入时通过副作用设置 ``abstract.mcp.client._tool_registry``
的回调，使 MCP server 发现的工具自动注册到全局 ``ToolRegistry``。

用法：:

    import component.mcp_tools  # 设置回调（副作用）
    component.mcp_tools.init_mcp(ctx)   # 启动 MCP server 连接
    ...
    component.mcp_tools.shutdown_mcp()  # 关闭所有连接
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional

if TYPE_CHECKING:
    from system.context import RuntimeContext

logger = logging.getLogger(__name__)

# 是否已连接到 MCP server
_mcp_initialized: bool = False

# ---------------------------------------------------------------------------
# 回调桥接 — 将 MCP _tool_registry 接入项目 ToolRegistry
# ---------------------------------------------------------------------------


def _bridge_on_register(
    name: str,
    schema: dict,
    handler: Callable[[dict, Any], str],
    **kwargs: Any,
) -> None:
    """MCP 工具注册回调 → 项目 ToolRegistry.register()。

    接收来自 ``abstract.mcp.client._register_server_tools()`` 的参数，
    转发给全局 ``tool_registry.register()``。
    """
    # 延迟导入避免循环依赖
    from abstract.tools.registry import registry as tool_registry

    toolset = kwargs.pop("toolset", f"mcp-{name.split('_')[1] if '_' in name else name}")
    check_fn = kwargs.pop("check_fn", None)
    is_async = kwargs.pop("is_async", False)
    description = kwargs.pop("description", schema.get("description", ""))

    tool_registry.register(
        name=name,
        toolset=toolset,
        schema=schema,
        handler=handler,
        check_fn=check_fn,
        is_async=is_async,
        description=description,
        # MCP 工具 refresh 时允许同类别覆盖
        override=False,
    )


def _bridge_on_deregister(name: str) -> None:
    """MCP 工具注销回调 → 项目 ToolRegistry.deregister()。"""
    from abstract.tools.registry import registry as tool_registry
    tool_registry.deregister(name)


def _bridge_on_get_toolset(name: str) -> Optional[str]:
    """MCP toolset 查询回调 → 项目 ToolRegistry。"""
    from abstract.tools.registry import registry as tool_registry
    return tool_registry.get_toolset_for_tool(name)


def _bridge_on_register_alias(alias: str, toolset_name: str) -> None:
    """MCP toolset 别名回调 → 项目 ToolRegistry。"""
    from abstract.tools.registry import registry as tool_registry
    tool_registry.register_toolset_alias(alias, toolset_name)


# ---------------------------------------------------------------------------
# 设置桥接回调（导入时副作用）
# ---------------------------------------------------------------------------

try:
    from abstract.mcp.client import _tool_registry

    _tool_registry.on_register = _bridge_on_register
    _tool_registry.on_deregister = _bridge_on_deregister
    _tool_registry.on_get_toolset = _bridge_on_get_toolset
    _tool_registry.on_register_alias = _bridge_on_register_alias
    _MCP_AVAILABLE = True
    logger.debug("MCP tool registry callbacks installed")
except ImportError as exc:
    _MCP_AVAILABLE = False
    logger.warning("MCP module not available, MCP tools disabled: %s", exc)

# ---------------------------------------------------------------------------
# 配置加载
# ---------------------------------------------------------------------------


def _load_mcp_config(path: Optional[Path]) -> Dict[str, dict]:
    """从 JSON 配置文件加载 MCP server 配置。

    支持的格式：:

        {
            "time": {
                "command": "uvx",
                "args": ["mcp-server-time"]
            },
            "my-server": {
                "url": "http://localhost:8000/mcp",
                "headers": {"Authorization": "Bearer ..."},
                "enabled": true
            }
        }

    返回空 dict 表示无配置。
    """
    if not path or not path.exists():
        return {}

    try:
        raw = path.read_text(encoding="utf-8")
        config = json.loads(raw)
        if not isinstance(config, dict):
            logger.warning("MCP config at %s is not a dict, ignoring", path)
            return {}
        # 过滤出符合 {name: {command|url: ...}} 格式的条目
        servers: Dict[str, dict] = {}
        for key, val in config.items():
            if isinstance(val, dict) and ("command" in val or "url" in val):
                servers[key] = val
            else:
                logger.debug("Skipping invalid MCP server entry '%s'", key)
        return servers
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Failed to load MCP config from %s: %s", path, exc)
        return {}


# ---------------------------------------------------------------------------
# 生命周期管理
# ---------------------------------------------------------------------------


def init_mcp(ctx: RuntimeContext) -> List[str]:
    """初始化并连接 MCP server。

    从 ``ctx.mcp_config_path`` 读取配置（若未设置则跳过），
    启动后台 MCP 事件循环，连接所有 server 并注册其工具。

    返回已注册的 MCP 工具名列表。在 MCP 不可用或配置为空时返回 []。
    """
    global _mcp_initialized

    if not _MCP_AVAILABLE:
        logger.info("MCP SDK not available — skipping MCP initialization")
        return []

    if _mcp_initialized:
        logger.debug("MCP already initialized, skipping")
        return _get_registered_mcp_tools()

    config_path = getattr(ctx, "mcp_config_path", None)
    if not config_path:
        logger.info("No mcp_config_path set — MCP servers disabled")
        return []

    servers = _load_mcp_config(Path(config_path))
    if not servers:
        logger.info("No MCP servers configured (empty config at %s)", config_path)
        return []

    try:
        from abstract.mcp.client import register_mcp_servers
        tool_names = register_mcp_servers(servers)
        _mcp_initialized = True
        logger.info(
            "MCP initialized: %d servers, %d tools registered",
            len(servers),
            len(tool_names),
        )
        return tool_names
    except Exception as exc:
        logger.error("Failed to initialize MCP servers: %s", exc)
        return []


def shutdown_mcp() -> None:
    """关闭所有 MCP server 连接并清理资源。

    在 agent 关闭时调用，确保子进程被终止、后台线程退出。
    """
    global _mcp_initialized

    if not _MCP_AVAILABLE or not _mcp_initialized:
        return

    try:
        from abstract.mcp.client import shutdown_mcp_servers
        shutdown_mcp_servers()
        logger.info("MCP servers shut down")
    except Exception as exc:
        logger.warning("MCP shutdown error: %s", exc)

    _mcp_initialized = False


def _get_registered_mcp_tools() -> List[str]:
    """返回当前已注册的所有 MCP 工具名列表。"""
    try:
        from abstract.mcp.client import get_mcp_status
        status = get_mcp_status()
        tools = []
        for server_state in status:
            tools.extend(server_state.get("tools", []))
        return tools
    except Exception:
        return []


# 导入时副作用：只要 ``import component.mcp_tools``，回调即安装完成。
# 后续需显式调用 ``init_mcp(ctx)`` 以连接 server。