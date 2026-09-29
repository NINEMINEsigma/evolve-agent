"""子Agent命名和并发限制常量。"""

# 子Agent名称允许的字符：英文字母、数字、中文、下划线、连字符
SUBAGENT_NAME_PATTERN: str = r"^[a-zA-Z0-9\u4e00-\u9fa5_-]+$"

# 子Agent最大同时活跃数量 — 超出上限的子Agent进入等待队列
SUBAGENT_MAX_ACTIVE: int = 50
