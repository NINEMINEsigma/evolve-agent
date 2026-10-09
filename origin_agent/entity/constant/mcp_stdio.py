"""MCP stdio transport lifecycle constants."""

# stdio 子进程优雅退出等待时间，单位秒。
# 与 SDK v1.26.0 PROCESS_TERMINATION_TIMEOUT 保持一致；
# 超时后使用平台 kill-tree 强制终止，并抛出 LifecycleFailure。
MCP_STDIO_PROCESS_TERMINATION_TIMEOUT: float = 2.0

# stdin 关闭后有界等待时间，单位秒。
# SDK 在 finally 中先关闭 stdin 再等待进程退出；
# 本模块复刻该序列，独立设此超时以控制等待边界。
MCP_STDIO_STDIN_CLOSE_TIMEOUT: float = 5.0
