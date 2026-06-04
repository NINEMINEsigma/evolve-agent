from typing import *
from logging import getLogger

logger = getLogger(__name__)

def as_bool(value: object, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    temp = str(value).strip().lower()
    if temp in ("true", "1", "yes", "on"):
        return True
    if temp in ("false", "0", "no", "off"):
        return False
    logger.warning("expected a boolean-ish value, got %r; using default=%s", value, default)
    return default