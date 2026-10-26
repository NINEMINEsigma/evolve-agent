"""主Agent运行限制常量。"""

# ============================================================================
# Agent
# ============================================================================

# 全局工具循环未配置时的默认轮次上限。
MAX_TOOL_TURNS: int = 90
# 可配置轮次的最小值，单位：轮；不提供无限制模式。
MIN_TOOL_TURNS: int = 1
# 可配置轮次的最大值：JavaScript安全整数上界，保证前后端无精度损失。
MAX_CONFIGURABLE_TOOL_TURNS: int = 9_007_199_254_740_991
# 全局工具循环配置文件，位于RuntimeContext.workspace根目录。
AGENT_LOOP_SETTINGS_ES_FILENAME: str = "agent_loop_settings.es"
# 全局工具循环配置初始持久化格式版本；结构变化必须升级。
AGENT_LOOP_SETTINGS_ES_KEY: str = "v1"
