"""多Agent协作路由和重试限制常量。"""

# ============================================================================
# 多 Agent 协作
# ============================================================================

# 多 Agent 级联对话最大递归深度 — 防止循环引用
MULTI_AGENT_MAX_CASCADE_DEPTH: int = 10

# 多 Agent 模式下 JSON 格式回复解析失败最大重试次数
MULTI_AGENT_JSON_RETRIES: int = 5

# 多 Agent DSL 路由标签名
MULTI_AGENT_ROUTING_TAG_VISIBLE: str = "visible"
MULTI_AGENT_ROUTING_TAG_RESPONSE: str = "response"

# @response(...) 中表示"无响应"的简写
MULTI_AGENT_ROUTING_RESPONSE_NONE: str = "none"
MULTI_AGENT_ROUTING_RESPONSE_NULL: str = "null"
