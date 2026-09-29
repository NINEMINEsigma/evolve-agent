"""会话视觉资源的目录约定与 HTTP 探测协议。"""

from types import MappingProxyType

from .chat_style import CHAT_STYLE_DIR_NAME, CHAT_STYLE_ENTRY_FILE

# 功能名到（源目录名、入口文件名）的只读映射；chat_style 复用既有常量。
SESSION_VISUAL_LAYOUT = MappingProxyType({
    "stage": ("stage", "index.html"),
    "site": ("site", "index.html"),
    "chat_style": (CHAT_STYLE_DIR_NAME, CHAT_STYLE_ENTRY_FILE),
})
# 同级元数据内的目录重定向字段名。
VISUAL_REDIRECT_KEY: str = "redirect"
# 查询参数：原始读取、版本探测及探测来源；值 1 表示启用。
VISUAL_RAW_PARAM: str = "visual_raw"
VISUAL_PROBE_PARAM: str = "visual_probe"
VISUAL_SID_PARAM: str = "visual_sid"
VISUAL_KIND_PARAM: str = "visual_kind"
VISUAL_QUERY_ENABLED: str = "1"
# 最终 HEAD 响应的资源版本头，不从中间 307 响应取版本。
VISUAL_VERSION_HEADER: str = "X-Session-Visual-Version"
# 单次目录签名扫描的条目数上限与软时间预算（秒）。
VISUAL_SCAN_MAX_ENTRIES: int = 10000
VISUAL_SCAN_BUDGET_SECONDS: float = 0.2
