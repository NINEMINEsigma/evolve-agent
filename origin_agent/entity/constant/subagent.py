"""子Agent存储、命名和并发限制常量。"""

# ============================================================================
# 子 Agent
# ============================================================================

# 子 Agent 注册表持久化文件名 — 存放于 workspace/ 下
# DEPRECATED: 已改为每个 subagent 独立存储在 agentspace/subagents/ 下，
# 保留此常量仅作为历史兼容参考。
SUBAGENT_STORE_FILENAME: str = "subagents.json"

# 子 Agent 配置存放目录名（位于 agentspace 下）
SUBAGENT_DIR_NAME: str = "subagents"

# 单个子 Agent 配置文件后缀（easysave 序列化格式）
SUBAGENT_SETTING_SUFFIX: str = ".es"

# 子 Agent 注册表索引文件名
SUBAGENT_INDEX_FILENAME: str = "_index.json"

# 子 Agent 注册名允许的字符：英文字母、数字、中文、下划线、连字符
SUBAGENT_NAME_PATTERN: str = r"^[a-zA-Z0-9\u4e00-\u9fa5_-]+$"

# 子 Agent 最大同时活跃数量 — 超出上限的子 Agent 进入等待队列
SUBAGENT_MAX_ACTIVE: int = 50
