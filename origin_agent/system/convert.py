from typing import TypeVar
from logging import getLogger
from enum import Enum

logger = getLogger(__name__)

E = TypeVar("E", bound=Enum)


def as_enum(value: str | None, enum_cls: type[E], default: E | None = None) -> E | None:
    """将字符串值转换为枚举成员，转换失败时返回 default 或 None。"""
    try:
        return enum_cls(value)
    except (ValueError, TypeError):
        if default is not None:
            return default
        logger.warning("cannot convert %r to %s", value, enum_cls.__name__)
        return None


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