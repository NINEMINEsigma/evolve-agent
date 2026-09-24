"""通用超时、取消清理和退避常量。"""

# ============================================================================
# 超时
# ============================================================================

# Gateway 优雅关闭等待上限（秒）；超时后才强制取消 uvicorn 任务
GATEWAY_SHUTDOWN_TIMEOUT_SECONDS: float = 10.0

# 子进程默认超时（秒）— 用于 pip install、scp 传输、前端构建等子进程调用
SUBPROCESS_TIMEOUT_DEFAULT: int = 120

# 子进程短超时 (秒) - 用于检查版本的指令等
SUBPROCESS_SHORT_TIMEOUT_DEFAULT: int = 5

# 子进程软清理等待时间, 到时后强杀进程
SUBPROCESS_SOFT_CLEANUP_WAIT_TIME: int = 5

# 审批请求等待超时（秒）— 等待用户在前端确认工具调用
APPROVAL_WAIT_TIMEOUT: int = 120

# cron 任务执行超时（秒）— 单次定时任务的最大运行时间
CRON_TASK_TIMEOUT: int = 300

# LLM 流连续空闲超时（秒）— 连续该时长未收到任何流式数据（content/reasoning/
# tool_call/usage）时自动停止本轮并恢复会话为空闲；任一有效数据到达即重置计时
LLM_STREAM_IDLE_TIMEOUT: int = 300

# 主会话中断清理等待上限（秒）— HTTP 中断接口等待当前轮次协作式收尾的最长时间
MAIN_SESSION_INTERRUPT_TIMEOUT: float = 2.0

# 主会话强制取消后的收尾等待上限（秒）— 超时后返回 timeout，不继续阻塞中断接口
MAIN_SESSION_INTERRUPT_FORCE_CANCEL_TIMEOUT: float = 1.0

# LLM 流读取 task 响应取消的等待上限（秒）— 超时后延迟到读取结束再关闭异步迭代器
STREAM_READ_CANCEL_CLEANUP_TIMEOUT: float = 2.0

# 工具 handler task 响应取消的等待上限（秒）— 超时后转入后台强引用观察
TOOL_TASK_CANCEL_CLEANUP_TIMEOUT: float = 1.0

# ffmpeg 命令执行默认超时（秒）
FFMPEG_DEFAULT_TIMEOUT: int = 300

# 指数退避基数（秒）
BACKOFF_BASE: float = 1.0
