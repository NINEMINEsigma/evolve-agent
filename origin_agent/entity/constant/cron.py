"""Cron 和动态端点任务限制常量。"""

# ============================================================================
# Cron
# ============================================================================

# Cron 任务持久化文件名 — 存放于 workspace/ 下
CRON_STORE_FILENAME: str = "cron_jobs.json"

# 动态端点持久化文件名 — 存放于 workspace/ 下
DYNAMIC_ENDPOINTS_STORE_FILENAME: str = "dynamic_endpoints.json"

# Cron 定时任务 stdout 预览最大长度（传给 Agent 的预览字符数）
# 超过此长度时，Agent 会收到提示去日志文件查看完整输出
CRON_STDOUT_PREVIEW_MAX_LENGTH: int = 5000

# Cron 最小可设间隔/等待秒数（schedule_cron 和 wait_cron 共用）
CRON_MIN_INTERVAL_SECONDS: int = 3

# 每个会话最多允许的 Cron 任务数量
CRON_MAX_JOBS_PER_SESSION: int = 20
