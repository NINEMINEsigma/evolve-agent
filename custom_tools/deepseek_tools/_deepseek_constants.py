"""Private protocol constants for the DeepSeek custom tools."""

# DeepSeek API 的版本路径，基地址已有该后缀时不重复追加。
DEEPSEEK_API_VERSION_PATH: str = "/v1"

# DeepSeek 网页搜索端点后缀，拼接在含版本号的基路径之后。
DEEPSEEK_SEARCH_ENDPOINT_PATH: str = "/tools/search"

# DeepSeek 网页抓取端点后缀，拼接在含版本号的基路径之后。
DEEPSEEK_FETCH_ENDPOINT_PATH: str = "/tools/fetch"

# DeepSeek 搜索词与原始问题的长度上限，单位为 Unicode 码点。
DEEPSEEK_SEARCH_QUERY_MAX_CHARS: int = 128

# DeepSeek 搜索默认返回的结果条数。
DEEPSEEK_SEARCH_COUNT_DEFAULT: int = 10

# DeepSeek 搜索最多返回的结果条数，最少为 1 条。
DEEPSEEK_SEARCH_COUNT_MAX: int = 50

# DeepSeek 抓取目标 URL 的长度上限，单位为 Unicode 码点。
DEEPSEEK_FETCH_URL_MAX_CHARS: int = 8192

# DeepSeek HTTP 各 I/O 阶段超时与异步等待总预算，单位为秒。
DEEPSEEK_HTTP_TIMEOUT_SECONDS: float = 60.0
