"""Watching 服务间隔常量。"""

# ============================================================================
# Watching Service (background_service.py)
# ============================================================================

# Watching 服务长短间隔的最小值（秒）
WATCHING_MIN_INTERVAL: int = 10

# Watching 服务默认长间隔（秒）— 无标识符命中时使用
WATCHING_DEFAULT_LONG_INTERVAL: int = 180

# Watching 服务默认短间隔（秒）— 标识符命中后使用
WATCHING_DEFAULT_SHORT_INTERVAL: int = 12
