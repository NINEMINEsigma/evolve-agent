"""会话成功文件操作的存储与协议常量。"""

# 独立于 History 的每主会话聚合文件及 easysave 根键。
SESSION_FILE_CHANGES_ES_FILENAME = "file_changes.es"
SESSION_FILE_CHANGES_ES_KEY = "v1"
# 分页行数：默认 100，单次最多 200。
SESSION_FILE_CHANGES_DEFAULT_LIMIT = 100
SESSION_FILE_CHANGES_MAX_LIMIT = 200
# 删除封闭锁等待秒数，小于现有请求取消收尾预算。
SESSION_FILE_CHANGES_DELETE_LOCK_TIMEOUT_SECONDS = 5.0
# 成功操作、目标类型及正式工具名的运行时协议校验集合。
SESSION_FILE_CHANGE_KINDS = frozenset({"file", "directory"})
SESSION_FILE_CHANGE_TOOL_OPERATIONS = {
    "Write": frozenset({"create", "modify"}),
    "PatchEdit": frozenset({"modify"}),
    "Delete": frozenset({"delete"}),
    "Copy": frozenset({"create", "copy"}),
    "Move": frozenset({"create", "move"}),
}
