"""文件系统工具的 I/O 限制常量。"""

# ============================================================================
# 文件系统 I/O 限制
# ============================================================================

# Write 工具内容上限（overwrite 和 append 共用）
WRITE_FILE_MAX_CHARS: int = 100000

# PatchEdit 工具内容上限
EDIT_FILE_MAX_CHARS: int = 100000

# Read 工具单次读取最大行数（硬上限）
READ_FILE_MAX_LINES: int = 2000

# Read 工具默认返回行数
READ_FILE_DEFAULT_LIMIT: int = 100

# Write 截断时返回的尾部字符数 — 用于作为 PatchEdit 的 old_string 或继续追加
WRITE_FILE_TRUNCATION_TAIL: int = 25

# 文件类型嗅探采样字节数 — 通过检查前 N 字节中是否含空字节判断是否为文本文件
FILE_SNIFF_BYTES: int = 4096
