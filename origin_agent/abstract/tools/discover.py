"""Strict AST discovery of explicit tool declarations and their lifecycle."""

from __future__ import annotations

import ast
import importlib
import inspect
import logging
import stat
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Protocol, cast

from framework import AsyncSystem

from entity.constant import (
    ApplicationState,
    BUILTIN_TOOL_PACKAGES,
    MCP_TOOL_MODULE,
    Namespace,
    TOOL_DISCOVERY_EXCLUDED_FILENAMES,
    TOOL_REGISTRATION_ENTRYPOINT,
)
from system.lifecycle import ApplicationStoppingError, LifecycleFailure
from system.pathutils import find_repo_root, get_agent_dir
from system.runtime import RuntimeSystem
from .registry import ToolRegistry
from .toolsets_meta import register_builtin_toolset_descriptions
from .ui_event_router import UIEventRouter

logger = logging.getLogger(__name__)


class ToolModule(Protocol):
    """Static registration contract for dynamically imported tool modules."""

    def register_tools(self, registry: ToolRegistry, ui_events: UIEventRouter) -> None:
        ...


def _module_registers_tools(module_path: Path) -> bool:
    """Find one synchronous entrypoint; reject legacy declarations and invalid source."""
    tree = ast.parse(module_path.read_text(encoding="utf-8"), filename=str(module_path))
    declarations = [
        node for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == TOOL_REGISTRATION_ENTRYPOINT
    ]
    # 声明导入及顶层执行均纳入检查；不扫描函数或类定义内部的合法注册。
    pending = list(tree.body)
    while pending:
        node = pending.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        if isinstance(node, ast.ImportFrom) and node.module in (
            "abstract.tools.registry", "abstract.tools.ui_event_router",
        ):
            if any(alias.name in ("registry", "ui_event_router") for alias in node.names):
                raise ValueError(f"Legacy global tool registry import in {module_path}; use register_tools")
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            receiver = node.func.value
            if (
                node.func.attr == "register"
                and isinstance(receiver, ast.Name)
                and receiver.id in ("registry", "ui_event_router")
            ):
                raise ValueError(f"Import-time tool registration in {module_path}; use register_tools")
        pending.extend(ast.iter_child_nodes(node))
    if not declarations:
        return False
    if len(declarations) != 1 or not isinstance(declarations[0], ast.FunctionDef):
        raise TypeError(f"{module_path} must define one synchronous register_tools function")
    return True


def _iter_tool_paths(directory: Path) -> Iterator[Path]:
    # iterdir 的读取失败直接传播，避免 rglob 在部分 Python 版本中跳过目录错误。
    for path in sorted(directory.iterdir()):
        if stat.S_ISDIR(path.stat().st_mode):
            yield from _iter_tool_paths(path)
        elif (
            path.suffix == ".py"
            and path.name not in TOOL_DISCOVERY_EXCLUDED_FILENAMES
            and not path.stem.startswith("_")
        ):
            yield path


def _register_module(
    module_name: str,
    *,
    registry: ToolRegistry,
    ui_events: UIEventRouter,
    loaded_modules: set[str],
) -> None:
    if module_name in loaded_modules:
        raise LifecycleFailure(f"Tool module already registered in this discovery: {module_name}")
    # 对固定声明进行AST检查，但实际模块可能被动态插件装饰器替换；
    # 此处的签名/返回值检查仅针对外部扩展边界，不反射业务System。
    module = cast(ToolModule, importlib.import_module(module_name))
    register = module.register_tools
    if not callable(register) or inspect.iscoroutinefunction(register):
        raise TypeError(f"{module_name}.register_tools must be a synchronous callable")
    result = register(registry, ui_events)
    if result is not None:
        if inspect.iscoroutine(result):
            result.close()
        raise TypeError(f"{module_name}.register_tools must return None")
    loaded_modules.add(module_name)
    logger.info("Registered tool module %s", module_name)


def _discover_tools(
    tools_path: Path,
    package_prefix: str,
    *,
    registry: ToolRegistry,
    ui_events: UIEventRouter,
    loaded_modules: set[str],
) -> list[str]:
    registered: list[str] = []
    for path in _iter_tool_paths(tools_path):
        if not _module_registers_tools(path):
            continue
        parts = path.relative_to(tools_path).with_suffix("").parts
        module_name = f"{package_prefix}.{'.'.join(parts)}"
        _register_module(
            module_name, registry=registry, ui_events=ui_events,
            loaded_modules=loaded_modules,
        )
        registered.append(module_name)
    return registered


def discover_builtin_tools(
    tools_dir: str,
    package_prefix: str,
    *,
    registry: ToolRegistry,
    ui_events: UIEventRouter,
) -> list[str]:
    """Import and register tools in path order, propagating all discovery failures."""
    return _discover_tools(
        Path(tools_dir).resolve(), package_prefix,
        registry=registry, ui_events=ui_events, loaded_modules=set(),
    )


class ToolDiscoverySystem(AsyncSystem):
    """Own startup discovery without duplicating registries or MCP connections."""

    def __init__(self) -> None:
        # 延迟类型导入，避免 abstract.tools 包入口形成业务模块循环导入。
        from abstract.mcp.system import MCPSystem
        from component.approval.system import ApprovalSystem
        from component.browser.system import BrowserSystem
        from component.cron_router import CronRouter
        from component.dynamic_endpoints import DynamicEndpointSystem
        from gateway.session_manager import SessionManager
        from subagent.orchestrator import SubAgentOrchestrator
        from system.agentspace.service import AgentspaceService
        from system.lsp import LSPManager
        from system.modality_capability import ModalityCapabilitySystem
        from system.sandbox import Sandbox
        from system.session_metadata import SessionMetadataService
        from system.shell_manager import ShellManager

        super().__init__(dependencies=(
            RuntimeSystem, ToolRegistry, UIEventRouter, Sandbox, ShellManager,
            AgentspaceService, SessionMetadataService, ApprovalSystem,
            LSPManager, BrowserSystem, ModalityCapabilitySystem, CronRouter,
            SessionManager, SubAgentOrchestrator, DynamicEndpointSystem, MCPSystem,
        ))
        self._loaded_modules: set[str] = set()
        self._started = False
        self._import_root: str | None = None

    @property
    def loaded_modules(self) -> frozenset[str]:
        return frozenset(self._loaded_modules)

    async def virtual_awake(self) -> None:
        from component import mcp_tools
        from system.sandbox import Sandbox

        if self._started:
            raise LifecycleFailure("Tool discovery cannot be restarted")
        self._started = True
        runtime = self.get_system(RuntimeSystem)
        registry = self.get_system(ToolRegistry)
        ui_events = self.get_system(UIEventRouter)
        sandbox = self.get_system(Sandbox)
        if runtime.state != ApplicationState.STARTING:
            raise ApplicationStoppingError("Tool discovery requires application startup")
        root = str(find_repo_root())
        if root not in sys.path:
            sys.path.insert(0, root)
            self._import_root = root
        try:
            agent_dir = get_agent_dir()
            for package in BUILTIN_TOOL_PACKAGES:
                _discover_tools(
                    agent_dir.joinpath(*package.split(".")), package,
                    registry=registry, ui_events=ui_events,
                    loaded_modules=self._loaded_modules,
                )
            custom_dir = sandbox.get_base(Namespace.CUSTOM_TOOLS)
            # 只有明确不存在的可选扩展目录允许跳过；非目录和权限失败继续传播。
            try:
                custom_dir.stat()
            except FileNotFoundError:
                pass
            else:
                _discover_tools(
                    custom_dir, Namespace.CUSTOM_TOOLS.value,
                    registry=registry, ui_events=ui_events,
                    loaded_modules=self._loaded_modules,
                )
            if MCP_TOOL_MODULE in self._loaded_modules:
                raise LifecycleFailure("MCP management tools were already registered")
            mcp_tools.register_tools(registry, ui_events)
            self._loaded_modules.add(MCP_TOOL_MODULE)
            register_builtin_toolset_descriptions(registry)
            if runtime.state != ApplicationState.STARTING:
                raise ApplicationStoppingError("Application stopped during tool discovery")
            logger.info(
                "Tool discovery complete: %d modules, %d tools",
                len(self._loaded_modules), len(registry.get_all_tool_names()),
            )
        except BaseException:
            self._release_import_root()
            # 已注册条目仍归原 Registry；失败架构交由 Application 清理，不重试发现。
            raise

    def _release_import_root(self) -> None:
        if self._import_root is not None:
            sys.path.remove(self._import_root)
            self._import_root = None

    async def virtual_shotdown(self) -> None:
        self._loaded_modules.clear()
        self._release_import_root()
