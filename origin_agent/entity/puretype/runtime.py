from pydantic import BaseModel

# ---------------------------------------------------------------------------
# Runtime Types
# ---------------------------------------------------------------------------

class SystemInfo(BaseModel):
    """运行时宿主系统信息，用于注入 base.txt 占位符。"""

    user_name: str = ""
    """当前操作系统用户名。"""

    host_name: str = ""
    """当前主机名。"""

    os_info: str = ""
    """操作系统平台描述（如 Windows-11-10.0.22631-SP0）。"""


class ProcessLineStreamResult(BaseModel):
    """逐行消费子进程输出后的结果摘要。"""

    returncode: int | None = None
    """子进程退出码；调用方主动截断时可能为空。"""

    stderr: str = ""
    """限制长度后的标准错误文本。"""

    truncated: bool = False
    """是否因调用方要求停止而提前终止。"""

    stdout_line_count: int = 0
    """已消费的 stdout 行数。"""


# ---------------------------------------------------------------------------
# Client Info Types
# ---------------------------------------------------------------------------

class ClientInfo(BaseModel):
    """连接客户端的运行时信息，用于注入 agent 上下文。"""

    device_type: str = ""
    """设备类型：mobile / desktop / tablet"""

    browser: str = ""
    """浏览器 User-Agent 原始字符串"""

    client_ip: str = ""
    """客户端 IP 地址（由后端从 ws.client.host 提取）"""

    frontend_version: str = ""
    """前端版本标识（如 EvolveAgent-Web/v1.0）"""

    screen_orientation: str = ""
    """屏幕方向（如 landscape-primary / portrait-primary）"""