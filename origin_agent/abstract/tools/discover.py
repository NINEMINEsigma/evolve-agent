"""Strict AST discovery of object tool declarations and their lifecycle."""

from __future__ import annotations

import ast
import importlib
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
    TOOLSET_DECLARATION_NAME,
)
from system.lifecycle import ApplicationStoppingError, LifecycleFailure
from system.pathutils import find_repo_root, get_agent_dir
from interface.approval_system import IApprovalSystem
from interface.agentspace_service import IAgentspaceService
from interface.browser_system import IBrowserSystem
from interface.cron_router import ICronRouter
from interface.dynamic_endpoint_system import IDynamicEndpointSystem
from interface.lsp_manager import ILSPManager
from interface.mcp_system import IMCPSystem
from interface.modality_capability_system import IModalityCapabilitySystem
from interface.runtime_system import IRuntimeSystem
from interface.sandbox import ISandbox
from interface.session_manager import ISessionManager
from interface.session_metadata_service import ISessionMetadataService
from interface.shell_manager import IShellManager
from interface.subagent_orchestrator import ISubAgentOrchestrator
from interface.tool_discovery_system import IToolDiscoverySystem
from interface.tool_registry import IToolRegistry
from .tool import BaseToolSet
from .toolsets_meta import register_builtin_toolset_descriptions

logger = logging.getLogger(__name__)


class ToolModule(Protocol):
    """Fixed object declaration exposed by dynamically imported modules."""

    TOOLSET: BaseToolSet


def _module_declares_toolset(module_path: Path) -> bool:
    """Find TOOLSET and reject retired or import-time registration contracts."""
    tree = ast.parse(module_path.read_text(encoding="utf-8"), filename=str(module_path))
    declarations = 0
    for node in tree.body:
        if isinstance(node, ast.Assign):
            declarations += sum(
                isinstance(target, ast.Name) and target.id == TOOLSET_DECLARATION_NAME
                for target in node.targets
            )
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            declarations += node.target.id == TOOLSET_DECLARATION_NAME
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "register_tools":
            raise ValueError(f"Retired tool registration entrypoint in {module_path}; declare TOOLSET")
    if declarations > 1:
        raise ValueError(f"Multiple TOOLSET declarations in {module_path}")
    # 不遍历工具类和函数主体；导入期的注册、全局注册表及旧 UI 路由导入直接拒绝。
    pending = list(tree.body)
    while pending:
        node = pending.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        if isinstance(node, ast.ImportFrom):
            if node.module == "abstract.tools.ui_event_router":
                raise ValueError(f"Retired UI event router import in {module_path}; use tool after_handle")
            if node.module == "abstract.tools.registry" and any(alias.name == "registry" for alias in node.names):
                raise ValueError(f"Legacy global tool registry import in {module_path}; declare TOOLSET")
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            receiver = node.func.value
            if (
                node.func.attr in ("register", "register_tool", "register_toolset")
                and isinstance(receiver, ast.Name)
                and receiver.id in ("registry", "ui_event_router")
            ):
                raise ValueError(f"Import-time tool registration in {module_path}; declare TOOLSET")
        pending.extend(ast.iter_child_nodes(node))
    return declarations == 1


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
    module_name: str, *, registry: IToolRegistry, loaded_modules: set[str],
) -> None:
    if module_name in loaded_modules:
        raise LifecycleFailure(f"Tool module already registered in this discovery: {module_name}")
    # 动态插件边界只读取固定 TOOLSET 属性，不做签名内省或全局注册表注入。
    module = cast(ToolModule, importlib.import_module(module_name))
    toolset = module.TOOLSET
    if not isinstance(toolset, BaseToolSet):
        raise TypeError(f"{module_name}.{TOOLSET_DECLARATION_NAME} must be a BaseToolSet")
    registry.register_toolset(toolset, merge=True)
    loaded_modules.add(module_name)
    logger.info("Registered tool module %s", module_name)


def _discover_tools(
    tools_path: Path, package_prefix: str, *, registry: IToolRegistry, loaded_modules: set[str],
) -> list[str]:
    registered: list[str] = []
    for path in _iter_tool_paths(tools_path):
        if not _module_declares_toolset(path):
            continue
        parts = path.relative_to(tools_path).with_suffix("").parts
        module_name = f"{package_prefix}.{'.'.join(parts)}"
        _register_module(module_name, registry=registry, loaded_modules=loaded_modules)
        registered.append(module_name)
    return registered


def discover_builtin_tools(
    tools_dir: str, package_prefix: str, *, registry: IToolRegistry,
) -> list[str]:
    """Import and register object declarations in path order; failures propagate."""
    return _discover_tools(
        Path(tools_dir).resolve(), package_prefix, registry=registry, loaded_modules=set(),
    )


class ToolDiscoverySystem(IToolDiscoverySystem):
    """Own startup discovery without duplicating registries or MCP connections."""

    def __init__(self) -> None:
        # 延迟类型导入，避免 abstract.tools 包入口形成业务模块循环导入。
        from interface.approval_system import IApprovalSystem
        from interface.browser_system import IBrowserSystem
        from interface.cron_router import ICronRouter
        from interface.dynamic_endpoint_system import IDynamicEndpointSystem
        from interface.mcp_system import IMCPSystem
        from interface.session_manager import ISessionManager
        from interface.subagent_orchestrator import ISubAgentOrchestrator
        from interface.agentspace_service import IAgentspaceService
        from interface.lsp_manager import ILSPManager
        from interface.modality_capability_system import IModalityCapabilitySystem
        from interface.sandbox import ISandbox
        from interface.session_metadata_service import ISessionMetadataService
        from interface.shell_manager import IShellManager

        super().__init__(dependencies=(
            IRuntimeSystem, IToolRegistry, ISandbox, IShellManager,
            IAgentspaceService, ISessionMetadataService, IApprovalSystem,
            ILSPManager, IBrowserSystem, IModalityCapabilitySystem, ICronRouter,
            ISessionManager, ISubAgentOrchestrator, IDynamicEndpointSystem, IMCPSystem,
        ))
        self._loaded_modules: set[str] = set()
        self._started = False
        self._import_root: str | None = None

    @property
    def loaded_modules(self) -> frozenset[str]:
        return frozenset(self._loaded_modules)

    async def virtual_awake(self) -> None:
        if self._started:
            raise LifecycleFailure("Tool discovery cannot be restarted")
        self._started = True
        runtime = self.get_system(IRuntimeSystem)
        registry = self.get_system(IToolRegistry)
        sandbox = self.get_system(ISandbox)
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
                    registry=registry, loaded_modules=self._loaded_modules,
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
                    registry=registry, loaded_modules=self._loaded_modules,
                )
            _register_module(MCP_TOOL_MODULE, registry=registry, loaded_modules=self._loaded_modules)
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
