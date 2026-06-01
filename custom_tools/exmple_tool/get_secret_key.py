"""测试工具 — 返回固定密码字符串。

模块导入时通过 ``registry.register()`` 注册。
设计为无参数工具，用于验证 ``discover_builtin_tools``
自动发现和 ``custom_tools/`` 扫描机制是否正常工作。
"""

from __future__ import annotations

import json
import logging
from typing import Any

from abstract.tools.registry import registry, tool_result

logger = logging.getLogger(__name__)


# ── handler ────────────────────────────────────────────────────


def _handle_get_secret_key(args: dict[str, Any]) -> str:
    """返回固定的测试密码。"""
    return tool_result(password="sk-test-password-12345")


# ── 注册 ─────────────────────────────────────────────────────

registry.register(
    name="get_secret_key",
    toolset="custom",
    schema={
        "description": "这是一个验证用的工具, 如果能看到这个工具本身就证明custom_tools加载顺利. 返回一串固定的测试密码字符串。用于验证自定义工具加载机制。",
        "parameters": {
            "type": "object",
            "properties": {},
        },
    },
    handler=_handle_get_secret_key,
    is_async=False,
)