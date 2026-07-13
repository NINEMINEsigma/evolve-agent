"""LLM 客户端动态加载器。

按名称从 ``custom_llm_client/<name>.py`` 加载对应实现模块，
并调用其 ``create_llm_client`` 工厂构造 ``BaseLLMClient`` 实例。
"""

from __future__ import annotations

import importlib
import logging
import sys
import types
from pathlib import Path
from typing import Any

from abstract.llm.client import BaseLLMClient
from system.context import RuntimeContext
from system.pathutils import find_repo_root

logger = logging.getLogger(__name__)


def _ensure_namespace_package() -> None:
    """创建/复用 ``custom_llm_client`` 命名空间包，使 importlib 能定位插件。

    与 ``custom_hooks`` 的加载方式保持一致：将目录注册为 ``sys.modules``
    中的包入口，但不依赖 ``__init__.py`` 文件。
    """
    if "custom_llm_client" in sys.modules:
        return
    client_dir = find_repo_root() / "custom_llm_client"
    pkg = types.ModuleType("custom_llm_client")
    pkg.__path__ = [str(client_dir)]
    sys.modules["custom_llm_client"] = pkg


def create_llm_client(
    name: str,
    runtime_context: RuntimeContext,
    profile: dict[str, Any] | None = None,
) -> BaseLLMClient:
    """加载并构造名为 *name* 的 LLM 客户端。

    Args:
        name: 插件模块名，对应 ``custom_llm_client/<name>.py``。
        runtime_context: 父 Agent 运行时上下文，用于兜底配置。
        profile: 可选覆盖配置（如子 Agent / 多 Agent 角色配置）。

    Returns:
        BaseLLMClient 实例。

    Raises:
        RuntimeError: 模块不存在或接口不合法。
    """
    _ensure_namespace_package()
    module_name = f"custom_llm_client.{name}"
    try:
        mod = importlib.import_module(module_name)
    except ImportError as exc:
        raise RuntimeError(
            f"LLM client module '{name}' not found in custom_llm_client: {exc}"
        ) from exc

    factory = getattr(mod, "create_llm_client", None)
    if not callable(factory):
        raise RuntimeError(
            f"LLM client module '{name}' must expose a callable "
            f"``create_llm_client(runtime_context, profile=None)``"
        )

    client = factory(runtime_context, profile)
    if not isinstance(client, BaseLLMClient):
        raise RuntimeError(
            f"LLM client module '{name}' factory returned {type(client).__name__}, "
            f"not a BaseLLMClient subclass"
        )
    return client


def list_llm_clients() -> list[str]:
    """返回 ``custom_llm_client`` 目录下所有可选的客户端模块名。

    仅列出以 ``.py`` 结尾且不是 ``_`` 开头的文件，并去掉 ``.py`` 后缀。
    """
    client_dir = find_repo_root() / "custom_llm_client"
    if not client_dir.is_dir():
        return []
    return [
        path.stem
        for path in sorted(client_dir.glob("*.py"))
        if not path.name.startswith("_")
    ]