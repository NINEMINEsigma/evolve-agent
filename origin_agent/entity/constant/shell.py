"""Shell 会话（Windows ConPTY）限制常量。"""

# ============================================================================
# Shell会话（Windows ConPTY）
# ============================================================================

# 第一阶段支持的 Shell 类型与默认值
SHELL_SUPPORTED_TYPES: frozenset[str] = frozenset({"powershell", "pwsh", "cmd"})
SHELL_DEFAULT_TYPE: str = "powershell"

# StartShell/WriteShell/ReadShell/InterruptShell 单次等待硬上限（秒）
SHELL_WAIT_TIMEOUT_SECONDS: float = 30.0

# 首次收到输出后连续无新输出即返回的静默窗口（秒）
SHELL_OUTPUT_QUIET_SECONDS: float = 0.4

# ConPTY 非阻塞输出读取线程的轮询间隔（秒）
SHELL_OUTPUT_POLL_INTERVAL_SECONDS: float = 0.02

# Shell 启动后等待初始提示符/回显稳定的最长时间（秒）
SHELL_STARTUP_SETTLE_SECONDS: float = 1.0

# ReadShell 默认/最大返回字符数
SHELL_READ_DEFAULT_CHARS: int = 20000
SHELL_READ_MAX_CHARS: int = 100000

# 单个 Shell 原始控制序列文本与规范化文本的内存上限（字符数）
SHELL_RAW_BUFFER_MAX_CHARS: int = 1000000
SHELL_TEXT_BUFFER_MAX_CHARS: int = 1000000

# ConPTY 第一阶段固定窗口尺寸（列、行）
SHELL_DEFAULT_COLS: int = 80
SHELL_DEFAULT_ROWS: int = 24

# Shell ID 随机十六进制字符长度
SHELL_ID_LENGTH: int = 12

# 强制停止后等待输出线程收尾的上限（秒）
SHELL_STOP_WAIT_SECONDS: float = 5.0
