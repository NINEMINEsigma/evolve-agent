"""浏览器连接、探测、查询与自有进程释放常量。"""

# CDP 默认连接地址与连接超时（毫秒）。
CDP_ENDPOINT_DEFAULT: str = "http://localhost:9222"
CONNECT_TIMEOUT_MS: int = 5000
CDP_VERSION_PATH: str = "/json/version"
# 应用自有无头进程的退出等待上限（秒）。
BROWSER_PROCESS_EXIT_TIMEOUT_SECONDS: float = 5.0
# Windows Edge 固定候选路径；只探测，不启动用户日常浏览器。
EDGE_CANDIDATE_PATHS: tuple[str, ...] = (
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
)
# CDP 不可达时提供给调用方的操作说明。
EDGE_DEBUG_GUIDE: str = (
    "The browser CDP endpoint is unavailable. Use BrowserLaunch to start a debug Edge instance, "
    "or start Edge manually with --remote-debugging-port=9222 "
    "--user-data-dir=C:\\edge-cdp-profile. Chromium 136+ requires a non-default user data directory."
)
# DOM 文本摘要字符数、默认查询条数及查询硬上限。
DOM_TEXT_SUMMARY_CHARS: int = 80
QUERY_MAX_RESULTS: int = 50
QUERY_MAX_RESULTS_HARD: int = 200
