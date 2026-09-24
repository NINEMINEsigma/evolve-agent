"""沙盒命名空间和动态沙盒空间配置。"""

from enum import Enum


# ============================================================================
# 沙盒命名空间
# ============================================================================


class Namespace(str, Enum):
    """沙盒命名空间枚举。值不带冒号，冒号在路径解析/生成时拼接。"""

    WS = "ws"
    FORK = "fork"
    FIX = "fix"
    SKILLS = "skills"
    THIRD = "third"
    CUSTOM_HOOKS = "custom_hooks"
    CUSTOM_LLM_CLIENT = "custom_llm_client"
    CUSTOM_TOOLS = "custom_tools"


def is_namespaced_path(path: str) -> bool:
    """检查字符串是否以已知命名空间前缀开头（如 ws:xxx, fork:xxx）。"""
    return any(path.startswith(ns.value + ":") for ns in Namespace)


# 支持的内置命名空间前缀元组 — 从 Namespace 枚举派生。
# 动态命名空间由 Sandbox 单例的运行时注册表识别，不属于此静态元组。
# 只读内置命名空间（third/custom_*）映射项目根目录，仅允许 Read 访问。
NAMESPACE_PREFIXES: tuple[str, ...] = tuple(ns.value for ns in Namespace)

# fast 模式全局动态沙盒空间持久化（存放于 RuntimeContext.workspace 根目录）
DYNAMIC_SANDBOX_SPACES_ES_FILENAME: str = "dynamic_sandbox_spaces.es"
DYNAMIC_SANDBOX_SPACES_ES_KEY: str = "v1"

# 动态沙盒空间名称：不带冒号，以 ASCII 字母/下划线开头，仅含字母、数字、下划线
DYNAMIC_SANDBOX_SPACE_NAME_PATTERN: str = r"^[A-Za-z_][A-Za-z0-9_]*$"

# 动态沙盒空间用途描述最大字符数
DYNAMIC_SANDBOX_SPACE_DESCRIPTION_MAX_CHARS: int = 1000

# 仅普通模式/多Agent模式主Agent可调用的动态空间管理工具名
DYNAMIC_SANDBOX_MANAGEMENT_TOOL_NAMES: frozenset[str] = frozenset({
    "AddSandboxSpace",
    "RemoveSandboxSpace",
})
