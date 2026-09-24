"""截断、预览和会话内容限制常量。"""

# ============================================================================
# 截断/预览上限
# ============================================================================

# 日志/预览截断长度（字符数）— 用于 logger 输出、错误消息中的短预览
LOG_PREVIEW_CHARS: int = 200

# 工具结果/原始参数预览截断长度（字符数）— 用于工具返回值预览、JSON 参数预览
TOOL_RESULT_PREVIEW_CHARS: int = 2000

# 工具结果日志单个参数的截断长度（字符数）— 用于工具结果日志输出
TOOL_RESULT_LOG_ARGUMENT_CHARS: int = 100

# 工具结果完整内容保存截断阈值（字符数）— 超过时结果写入文件，仅返回预览
# 目前设置为一百万, 尽可能不再阻塞大部分工具调用, 同时组织真正的无限大文件输出
# TODO: 以后还需要更优的策略
TOOL_RESULT_SAVE_THRESHOLD_CHARS: int = 1000000

# 自动内容截断长度（字符数）— 用于自动内容截断
AUTO_CONTENT_MAX: int = 500000

# 自动标题生成时单条消息内容截断长度（字符数）— user/assistant 消息过长时截断后拼入 prompt
AUTO_TITLE_CONTENT_MAX: int = AUTO_CONTENT_MAX

# 会话标签生成时历史消息 JSON 截断长度（字符数）— 控制 tags prompt 的上下文长度
AUTO_TAGS_CONTENT_MAX: int = AUTO_CONTENT_MAX

# 会话合并时直接拼接摘要的字符阈值，超过则截断
MERGE_CONCAT_THRESHOLD: int = AUTO_CONTENT_MAX

# 前端聊天历史内容页默认读取的 History 消息条目数（不是投影行数）
SESSION_HISTORY_PAGE_DEFAULT_LIMIT: int = 80

# 前端聊天历史内容页单次允许读取的 History 消息条目数上限（不是投影行数）
SESSION_HISTORY_PAGE_MAX_LIMIT: int = 200

# 会话摘要生成时历史输入截断上限（字符数）— 暂时设为极大值，后续再细化
SUMMARY_INPUT_MAX_CHARS: int = 1_000_000_000

# 会话旋转/合并继承时，旧会话保留的尾部轮次数
INHERIT_LAST_ROUNDS: int = 10

# 元数据提取器角色名 — 用于标题/标签/摘要生成时 LLM 客户端的 character 参数，
# 明确声明"这不是 agent 在说话，是元数据提取工具在工作"。
# 对 BaseMessage 无技术效果，但语义上隔离了 agent 角色和元数据生成角色。
META_EXTRACTOR_CHARACTER: str = "__meta_extractor__"

# 上下文超限但无法生成延续摘要时写入 History 的系统状态消息。
# 该消息对 LLM 不可见，用于提示用户修复全局元数据 Profile 或目标会话活动 Profile 后恢复。
CONTEXT_LIMIT_METADATA_FAILURE_STATUS: str = (
    "上下文已达到上限，但无法生成延续摘要，本轮已中断。"
    "请检查全局元数据 Profile 或当前会话的活动 Profile 后再恢复。"
)
