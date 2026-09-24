"""上传、静态文件和下载路由常量。"""

from datetime import timezone

from .sandbox import Namespace


# ============================================================================
# 上传
# ============================================================================

# agentspace 下的上传子目录名 — 文件上传的目标物理目录
UPLOADS_DIR_NAME: str = "uploads"

# 上传文件在沙箱中的逻辑路径前缀 — 如 ws:uploads/screenshot.png
UPLOADS_WS_PREFIX: str = f"{Namespace.WS.value}:{UPLOADS_DIR_NAME}/"

# 静态文件 HTTP 路由前缀 — 前端通过此 URL 访问 ws: 命名空间下的文件
# 路由映射 ws: 根目录，故 ws:uploads/x.png → /files/uploads/x.png
STATIC_FILE_HTTP_PREFIX: str = "/files"

# 下载路由 HTTP 前缀 — 触发浏览器 attachment 下载
DOWNLOADS_HTTP_PREFIX: str = "/downloads"

# 目录打包 zip 下载路由前缀 — 将整个目录打包为 zip 后下载
DIR_ZIP_HTTP_PREFIX: str = "/zip"

# 目录打包 zip 源文件合计大小上限（200MB）— 防止大目录拖垮网关事件循环
DIR_ZIP_MAX_TOTAL_BYTES: int = 200 * 1024 * 1024

# 文件名示例：20250617_123045_utc_a1b2c3d4_filename.ext
UPLOAD_TIME_RE_PATTERN = r"^(\d{8}_\d{6}_utc)_[a-f0-9]{8}_(.+)$"

# 上传文件名中携带的 UTC 时间戳格式，用于 list_uploads 按真实上传时间排序。
# 例如：20250617_123045_utc
UPLOAD_FILENAME_TIME_FORMAT = "%Y%m%d_%H%M%S_utc"

# 上传文件名时区（与 UPLOAD_FILENAME_TIME_FORMAT 配套使用）
UPLOAD_FILENAME_TIMEZONE = timezone.utc
