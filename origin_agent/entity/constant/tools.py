"""Tool registration protocol and built-in discovery scope."""

# 按原发现顺序扫描的 component 子包；顺序用于保持工具覆盖语义。
BUILTIN_TOOL_PACKAGES: tuple[str, ...] = (
    "component.tools",
    "component.extools",
    "component.multiagenttools",
    "component.automation",
    "component.browser",
)

# MCP 管理工具单独显式注册，远程工具由 MCPSystem 初始化。
MCP_TOOL_MODULE: str = "component.mcp_tools"

# 工具插件的唯一同步声明入口名称。
TOOL_REGISTRATION_ENTRYPOINT: str = "register_tools"

# 包入口与注册表实现不作为工具模块扫描。
TOOL_DISCOVERY_EXCLUDED_FILENAMES: frozenset[str] = frozenset({"__init__.py", "registry.py"})
