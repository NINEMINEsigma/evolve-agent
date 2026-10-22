"""Exception types shared by lifecycle infrastructure modules."""

from __future__ import annotations


class LifecycleFailure(RuntimeError):
    """生命周期约定被破坏或资源未在期限内结束。"""
