"""抽象插件 — 基于目录的插件发现。

无外部依赖。纯 Python stdlib。
"""

from .discover import scan_plugins, is_plugin_dir, detect_plugin_type, read_plugin_metadata