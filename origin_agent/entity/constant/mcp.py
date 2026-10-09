"""MCP connection failure thresholds."""

# 连续失败达到此次数时打开服务器断路器；保留既有阈值。
MCP_CIRCUIT_BREAKER_THRESHOLD: int = 3

# 断路器打开后允许再次探测的冷却时间，单位秒。
MCP_CIRCUIT_BREAKER_COOLDOWN_SECONDS: float = 60.0

# MCP工具调用、初始连接、整批桥接与关闭等待期限，单位秒。
MCP_TOOL_TIMEOUT_SECONDS: float = 120.0
MCP_CONNECT_TIMEOUT_SECONDS: float = 60.0
MCP_BRIDGE_TIMEOUT_SECONDS: float = 120.0
MCP_CLEANUP_TIMEOUT_SECONDS: float = 30.0

# 长连接读超时与传输故障指数退避上限，单位秒。
MCP_SSE_READ_TIMEOUT_SECONDS: float = 300.0
MCP_MAX_BACKOFF_SECONDS: float = 60.0

# 仅用于明确传输故障，配置/逻辑/清理错误不得重试。
MCP_MAX_RECONNECT_RETRIES: int = 5
MCP_MAX_INITIAL_CONNECT_RETRIES: int = 3
