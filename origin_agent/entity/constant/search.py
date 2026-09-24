"""搜索工具的结果、引擎和文本识别常量。"""

# ============================================================================
# 搜索工具
# ============================================================================

# SearchFiles/Grep 默认返回结果上限；非 exhaustive 模式达到上限后提前截断
SEARCH_RESULT_LIMIT_DEFAULT: int = 100

# 搜索子进程 stderr 最大保留字节数，防止高错误输出占用过多内存
SEARCH_PROCESS_STDERR_MAX_BYTES: int = 65536

# 内置 ripgrep 版本；Windows x64 首期固定使用官方预编译包
SEARCH_RIPGREP_VERSION: str = "15.2.0"

# 官方 Windows x64 压缩包 SHA-256（ripgrep-15.2.0-x86_64-pc-windows-msvc.zip）
SEARCH_RIPGREP_WINDOWS_X64_ARCHIVE_SHA256: str = "71b2fef860abe467217a538ff31de02f5258807c0129f771846f87bd029aafc5"

# Windows x64 内置 rg.exe 相对 Agent 代码目录的位置
SEARCH_RIPGREP_WINDOWS_X64_RELATIVE_PATH: str = "vendor/ripgrep/win32-x64/rg.exe"

# Windows x64 内置 rg.exe SHA-256，用于运行时完整性校验
SEARCH_RIPGREP_EXE_SHA256: str = "14231169855ec5205cf5a1b6f1db358ff4aed4247c86b69ce8aae647c77f6680"

# ripgrep/Python 回退共同识别的文本文件扩展名
SEARCH_TEXT_EXTENSIONS: frozenset[str] = frozenset({
    ".py", ".txt", ".md", ".json", ".yaml", ".yml", ".toml", ".csv",
    ".ini", ".cfg", ".conf", ".js", ".ts", ".jsx", ".tsx", ".css",
    ".html", ".htm", ".xml", ".sh", ".bat", ".ps1", ".rs", ".go",
    ".java", ".c", ".cpp", ".h", ".hpp", ".rb", ".php", ".swift",
    ".kt", ".scala", ".sql", ".rst", ".log",
})

# 默认识别的 ignore 文件名；full_scan=true 时禁用
SEARCH_IGNORE_FILENAMES: tuple[str, ...] = (".gitignore", ".ignore", ".rgignore")

# exhaustive 模式下完整结果日志目录（逻辑路径，位于 ws:）
SEARCH_OVERFLOW_LOG_DIR: str = "ws:logs"
