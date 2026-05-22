"""Hermes Plugins — directory-based plugin discovery.

No external dependencies. Pure Python stdlib.
"""

from .discover import scan_plugins, is_plugin_dir, detect_plugin_type, read_plugin_metadata
