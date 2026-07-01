"""异常降级与日志辅助工具。

提供统一封装，用于“可恢复副作用失败时记录日志但不中断主流程”的场景。
本模块只依赖标准库，避免上层模块引入循环依赖。
"""

from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable, Coroutine, TypeVar

T = TypeVar("T")


def log_exception(
    logger: logging.Logger,
    msg: str,
    *args: Any,
    exc_info: bool = True,
    level: int = logging.WARNING,
) -> None:
    """以统一级别和格式记录捕获的异常，默认附带 traceback。"""
    if logger.isEnabledFor(level):
        logger.log(level, msg, *args, exc_info=exc_info)


def swallow_exception(
    logger: logging.Logger,
    msg: str,
    *args: Any,
    level: int = logging.WARNING,
) -> None:
    """标记此处异常被业务上允许吞没，但仍强制记录日志。

    用于资源清理、前端推送降级等“失败不应中断主流程”的场景。
    """
    log_exception(logger, msg, *args, level=level, exc_info=True)


def safe_sync_call(
    logger: logging.Logger,
    fn: Callable[..., T],
    *args: Any,
    default: T | None = None,
    msg: str = "",
    level: int = logging.WARNING,
    **kwargs: Any,
) -> T | None:
    """同步调用包装：失败时记录日志并返回 default，不抛异常。

    仅用于副作用/辅助操作；核心业务逻辑不应使用此函数掩盖错误。
    """
    try:
        return fn(*args, **kwargs)
    except Exception:
        log_exception(
            logger,
            msg or f"{getattr(fn, '__qualname__', repr(fn))} failed",
            level=level,
        )
        return default


async def safe_async_call(
    logger: logging.Logger,
    coro: Awaitable[T],
    default: T | None = None,
    msg: str = "",
    level: int = logging.WARNING,
) -> T | None:
    """异步调用包装：失败时记录日志并返回 default，不抛异常。

    仅用于副作用/辅助操作；核心业务逻辑不应使用此函数掩盖错误。
    """
    try:
        return await coro
    except Exception:
        log_exception(logger, msg or "async call failed", level=level)
        return default