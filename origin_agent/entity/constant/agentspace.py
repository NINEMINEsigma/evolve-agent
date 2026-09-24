"""Agentspace 编辑器的目录、监听和原子写入常量。"""

# ============================================================================
# Agentspace 编辑器
# ============================================================================

# 用户可恢复删除的内部垃圾桶布局（均位于 ws: 根目录下）
AGENTSPACE_TRASH_DIR_NAME: str = ".trash"
AGENTSPACE_TRASH_ITEMS_DIR_NAME: str = "items"
AGENTSPACE_TRASH_METADATA_FILENAME: str = "metadata.json"
AGENTSPACE_TRASH_PAYLOAD_NAME: str = "payload"
AGENTSPACE_TRASH_STAGING_PREFIX: str = ".staging-"
AGENTSPACE_TRASH_COMMITTED_FILENAME: str = "COMMITTED"
AGENTSPACE_INTERNAL_DIR_NAME: str = ".agentspace"

# 文件变化监听与 SSE 实时同步
AGENTSPACE_WATCH_DEBOUNCE_MS: int = 120
AGENTSPACE_EVENT_QUEUE_SIZE: int = 256
AGENTSPACE_SSE_HEARTBEAT_SECONDS: float = 15.0

# 编辑器原子写临时文件与恢复冲突命名
AGENTSPACE_ATOMIC_TMP_SUFFIX: str = ".agentspace.tmp"
AGENTSPACE_RESTORE_SUFFIX: str = ".restored"
AGENTSPACE_RECOVERED_PREFIX: str = "recovered-"
