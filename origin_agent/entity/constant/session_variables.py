"""会话变量池的文件布局、元数据键和有界读取约定。"""

from types import MappingProxyType

# 工作空间会话目录中的独立变量目录及多父继承分组名。
SESSION_VARIABLES_DIR_NAME = "variables"
SESSION_VARIABLE_VALUE_SUFFIX = ".json"
SESSION_VARIABLE_SOURCE_GROUP_NAME = "sources"
SESSION_VARIABLE_TEMPLATE_NAME = "session_variables.txt"
# 扫描深度按变量根下目录段计；节点包括目录和非变量文件。
SESSION_VARIABLE_MAX_DEPTH = 16
SESSION_VARIABLE_MAX_NODES = 4096
SESSION_VARIABLE_MAX_COUNT = 512
# 字节预算：单文件、全部来源逻辑内容、额外复核、实际读取和响应。
SESSION_VARIABLE_FILE_MAX_BYTES = 65536
SESSION_VARIABLE_TOTAL_MAX_BYTES = 524288
SESSION_VARIABLE_VERIFICATION_MAX_BYTES = 524288
SESSION_VARIABLE_OPERATION_READ_MAX_BYTES = 1048576
SESSION_VARIABLE_RESPONSE_MAX_BYTES = 1048576
# 单操作软时间预算（秒），不能中断阻塞中的操作系统读取。
SESSION_VARIABLE_SCAN_BUDGET_SECONDS = 2.0
# 显示文本按 Unicode 码点计，数字限定浏览器安全范围。
SESSION_VARIABLE_LABEL_MAX_CHARS = 256
SESSION_VARIABLE_DESCRIPTION_MAX_CHARS = 2048
SESSION_VARIABLE_SAFE_NUMBER_MAX = 9007199254740991
# 只读工具的独立结果字符上限，留出既有 _meta 封装余量。
SESSION_VARIABLES_READ_TOOL_NAME = "ReadSessionVariables"
SESSION_VARIABLES_READ_TOOL_RESULT_MAX_CHARS = 1100000
# 同级 .meta 的明确业务键；其他键只保留原文，不执行。
SESSION_VARIABLE_META_LABEL = "label"
SESSION_VARIABLE_META_DESCRIPTION = "description"
SESSION_VARIABLE_META_MIN = "min"
SESSION_VARIABLE_META_MAX = "max"
SESSION_VARIABLE_META_INTEGER = "integer"
SESSION_VARIABLE_META_PERCENT = "percent"
SESSION_VARIABLE_META_DISPLAY = "display"
SESSION_VARIABLE_DISPLAY_AUTO = "auto"
SESSION_VARIABLE_DISPLAY_NUMBER = "number"
SESSION_VARIABLE_DISPLAY_BAR = "bar"
SESSION_VARIABLE_DISPLAY_GAUGE = "gauge"
SESSION_VARIABLE_DISPLAYS = frozenset({
    SESSION_VARIABLE_DISPLAY_AUTO, SESSION_VARIABLE_DISPLAY_NUMBER,
    SESSION_VARIABLE_DISPLAY_BAR, SESSION_VARIABLE_DISPLAY_GAUGE,
})
SESSION_VARIABLE_NUMERIC_META_KEYS = frozenset({
    SESSION_VARIABLE_META_MIN, SESSION_VARIABLE_META_MAX,
    SESSION_VARIABLE_META_INTEGER, SESSION_VARIABLE_META_PERCENT,
    SESSION_VARIABLE_META_DISPLAY,
})
# 公开问题码与脱敏英文说明；前端按码翻译，未知码保留原说明。
SESSION_VARIABLE_ISSUE_MESSAGES = MappingProxyType({
    "invalid_json": "Value is not valid JSON.",
    "unsupported_value": "Only JSON numbers and strings are supported.",
    "non_finite_number": "Number must be finite.",
    "unsafe_number": "Number exceeds the browser-safe numeric range.",
    "invalid_utf8": "File is not valid UTF-8 text.",
    "value_read_error": "File could not be read.",
    "file_changed": "File changed while it was being read.",
    "file_too_large": "File exceeds the per-file byte limit.",
    "invalid_meta": "Metadata is not valid or is not a regular file.",
    "invalid_boolean": "Metadata boolean must be lowercase true or false.",
    "invalid_number": "Metadata must contain a finite browser-safe JSON number.",
    "invalid_display": "Display must be auto, number, bar, or gauge.",
    "invalid_range": "Minimum exceeds maximum.",
    "metadata_too_long": "Metadata display text exceeds its character limit.",
    "metadata_not_applicable": "Numeric metadata does not apply to strings.",
    "below_min": "Value is below the configured minimum.",
    "above_max": "Value is above the configured maximum.",
    "not_integer": "Value does not meet the integer requirement.",
    "unsafe_path": "Links, reparse points, and special files are not supported.",
    "orphan_metadata": "Metadata has no matching variable file.",
})
