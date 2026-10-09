"""工具 schema 和 handler 的中央注册表。

每个工具模块在显式 ``register_tools(registry, ui_events)`` 入口调用
``registry.register()`` 声明其
schema、handler、toolset 成员关系和可用性检查。下游代码使用
``get_definitions()`` 获取 OpenAI 格式的 schema（按可用性筛选）
并通过名称 ``dispatch()`` 执行 handler。

所有变更通过 ``threading.RLock`` 序列化，单调递增的
generation 计数器支持外部缓存失效。

``ToolRegistry`` 是依赖 ``RuntimeSystem`` 的 framework ``AsyncSystem``。
运行期通过 ``app.get_system(ToolRegistry)`` 取得唯一实例，不提供模块级
单例或兼容代理。ToolDiscoverySystem 负责调用显式声明入口；完整应用装配待 P22。
"""

import asyncio
import concurrent.futures
import inspect
import json
import logging
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import copy_context
from typing import Any, Callable

from framework import AsyncSystem

from entity.constant import SYSTEM_QUIESCE_TIMEOUT_SECONDS
from entity.puretype import ToolAvailability, ToolDangerLevel
from entity.puretype.lifecycle import SyncToolCallRecord
from system.lifecycle import (
    ApplicationStoppingError, LifecycleFailure, TaskOwner,
    close_resources, contains_lifecycle_failure, requires_lifecycle_propagation,
)
from system.runtime import RuntimeSystem

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# ToolEntry
# ---------------------------------------------------------------------------


# NOTE: 已确认不重构为BaseModel
class ToolEntry:
    """单个已注册工具的元数据。

    使用 ``__slots__`` 以节省内存 — 实例为每个已注册工具创建，
    并在进程生命周期内持续存在。
    """

    __slots__ = (
        "name",
        "toolset",
        "schema",
        "handler",
        "check_fn",
        "requires_env",
        "is_async",
        "description",
        "max_result_size_chars",
        "dynamic_schema_overrides",
        "danger_level",
        "no_timeout",
        "availability",
        "resets_turn_counter",
    )

    def __init__(
        self,
        name: str,
        toolset: str,
        schema: dict,
        handler: Callable,
        check_fn: Callable | None = None,
        requires_env: list[str] | None = None,
        is_async: bool = False,
        description: str = "",
        max_result_size_chars: int | None = None,
        dynamic_schema_overrides: Callable | None = None,
        danger_level: ToolDangerLevel = ToolDangerLevel.safe,
        no_timeout: bool = False,
        availability: ToolAvailability = ToolAvailability.EVERY,
        resets_turn_counter: bool = False,
    ):
        self.name: str = name
        self.toolset: str = toolset
        self.schema: dict = schema
        self.handler: Callable = handler
        self.check_fn: Callable | None = check_fn
        self.requires_env: list[str] = requires_env or []
        self.is_async: bool = is_async
        self.description: str = description
        self.max_result_size_chars: int | None = max_result_size_chars
        # 可选的零参数可调用对象，返回 schema 覆盖字典，
        # 在 get_definitions() 时应用。用于依赖运行时配置的字段。
        self.dynamic_schema_overrides: Callable | None = dynamic_schema_overrides
        self.danger_level: ToolDangerLevel = danger_level
        self.no_timeout: bool = no_timeout
        self.availability: ToolAvailability = availability
        self.resets_turn_counter: bool = resets_turn_counter


# ---------------------------------------------------------------------------
# ToolsetEntry
# ---------------------------------------------------------------------------


# NOTE: 不继承 BaseModel — 与 ToolEntry 保持一致，使用 __slots__
class ToolsetEntry:
    """单个工具集的元数据。

    由 ``register_toolset()`` 显式注册，或由工具首次注册时自动创建
    无描述回退项。使用 ``__slots__`` 以节省内存。

    ``description`` 是简短描述，未加载时在工具集目录中显示。
    ``usage_guide`` 是详细使用说明，加载后在工具集目录中显示，
    替代简短描述。
    """

    __slots__ = (
        "name",
        "description",
        "usage_guide",
        "loaded_by_default",
    )

    def __init__(
        self,
        name: str,
        description: str = "",
        usage_guide: str = "",
        loaded_by_default: bool = False,
    ) -> None:
        self.name = name
        self.description = description
        self.usage_guide = usage_guide
        self.loaded_by_default = loaded_by_default


DEFAULT_RESULT_SIZE_CHARS: int = 100000

# 默认加载的工具集名称
DEFAULT_LOADED_TOOLSET: str = "core"


# ---------------------------------------------------------------------------
# 工具 handler context 兼容性检查
# ---------------------------------------------------------------------------

def _handler_accepts_context(handler: Callable, context: Any) -> bool:
    """检查 handler 是否声明了 ``context`` 参数。

    仅当 ``context`` 非 None 且 handler 签名包含 ``context`` 形参时返回 True。

    inspect.signature is only used at the dynamic user-plugin boundary to
    determine whether a handler accepts a ``context`` keyword. This is the
    only place where signature introspection is necessary because tool
    handlers are user-authored extensions with no shared base class or
    protocol; the core project does not use reflection for its own known
    interfaces.
    """
    if context is None:
        return False
    try:
        sig = inspect.signature(handler)
        return "context" in sig.parameters
    except (ValueError, TypeError):
        # C 扩展或无法内省的可调用对象 — 保守地返回 False
        return False


# ---------------------------------------------------------------------------
# ToolRegistry（AsyncSystem）
# ---------------------------------------------------------------------------


class ToolRegistry(AsyncSystem):
    """工具注册表与执行器，注册为 framework AsyncSystem。

    依赖 RuntimeSystem；无参构造，``virtual_awake`` 取得 RuntimeSystem 并
    创建唯一 ``ThreadPoolExecutor``。同步 handler 通过 ``copy_context().run``
    保留上下文传播，以 ``executor.submit`` 取得真实
    ``concurrent.futures.Future`` 并登记；异步请求统一经 ``TaskOwner``
    登记。取消 await 不删除仍在运行的线程 Future。

    所有变更方法（register、deregister）持有 ``RLock``。
    check_fn 缓存与缓存锁已从模块级迁移为实例字段。
    """

    _CHECK_FN_TTL_SECONDS: float = 30.0

    def __init__(self) -> None:
        super().__init__(dependencies=(RuntimeSystem,))
        self._tools: dict[str, ToolEntry] = {}
        self._toolset_checks: dict[str, Callable] = {}
        self._toolset_aliases: dict[str, str] = {}
        self._toolsets: dict[str, ToolsetEntry] = {}
        # 序列化变更并为读取者提供稳定快照。
        self._lock: threading.RLock = threading.RLock()
        # 单调递增的 generation 计数器；每次变更时递增，外部缓存据此失效。
        self._generation: int = 0
        # check_fn TTL 缓存，迁移自模块级。
        self._check_fn_cache: dict[Callable, tuple[float, bool]] = {}
        self._check_fn_cache_lock: threading.Lock = threading.Lock()
        # 执行器与在途任务登记，virtual_awake 创建。
        self._executor: concurrent.futures.ThreadPoolExecutor | None = None
        self._sync_calls: dict[concurrent.futures.Future[Any], SyncToolCallRecord] = {}
        self._sync_calls_lock = threading.RLock()
        self._sync_changed: asyncio.Event | None = None
        self._sync_failures: list[BaseException] = []
        self._task_owner: TaskOwner | None = None
        self._executor_shutdown_task: asyncio.Task[None] | None = None
        self._dispatch_closed: bool = False
        self._runtime: RuntimeSystem | None = None

    async def virtual_awake(self) -> None:
        self._runtime = self.get_system(RuntimeSystem)
        self._task_owner = TaskOwner("tool-registry", self.runtime.record_failure)
        self._sync_changed = asyncio.Event()
        self._executor = concurrent.futures.ThreadPoolExecutor(
            thread_name_prefix="tool-handler",
        )

    @property
    def runtime(self) -> RuntimeSystem:
        if self._runtime is None:
            raise LifecycleFailure("ToolRegistry has not been awakened")
        return self._runtime

    # -- check_fn 缓存（实例级） -------------------------------------------

    def _check_fn_cached(self, fn: Callable) -> bool:
        """返回 bool(fn())，跨调用 TTL 缓存。异常吞没为 False。"""
        now: float = time.monotonic()
        with self._check_fn_cache_lock:
            cached: tuple[float, bool] | None = self._check_fn_cache.get(fn)
            if cached is not None:
                ts: float
                value: bool
                ts, value = cached
                if now - ts < self._CHECK_FN_TTL_SECONDS:
                    return value
        try:
            value = bool(fn())
        except Exception as error:
            if requires_lifecycle_propagation(error):
                raise
            logger.warning("Tool availability check failed", exc_info=True)
            value = False
        with self._check_fn_cache_lock:
            self._check_fn_cache[fn] = (now, value)
        return value

    def invalidate_check_fn_cache(self) -> None:
        """丢弃所有缓存的 ``check_fn`` 结果。"""
        with self._check_fn_cache_lock:
            self._check_fn_cache.clear()

    # -- 内部快照辅助方法 -----------------------------------------

    def _snapshot_state(self) -> tuple[list[ToolEntry], dict[str, Callable]]:
        """返回注册表条目和 toolset 检查的一致性快照。"""
        with self._lock:
            return list(self._tools.values()), dict(self._toolset_checks)

    def _snapshot_entries(self) -> list[ToolEntry]:
        """返回已注册工具条目的稳定快照。"""
        return self._snapshot_state()[0]

    def _snapshot_toolset_checks(self) -> dict[str, Callable]:
        """返回 toolset 可用性检查的稳定快照。"""
        return self._snapshot_state()[1]

    def _evaluate_toolset_check(self, toolset: str, check: Callable | None) -> bool:
        """运行 toolset 检查，缺失或失败时视为可用。"""
        if not check:
            return True
        try:
            return bool(check())
        except Exception as error:
            if requires_lifecycle_propagation(error):
                raise
            logger.warning("Toolset %s check raised; marking unavailable", toolset, exc_info=True)
            return False

    # -- 查询方法 -----------------------------------------------------

    def get_entry(self, name: str) -> ToolEntry|None:
        """按名称返回已注册工具条目，不存在返回 None。"""
        with self._lock:
            return self._tools.get(name)

    def get_schema(self, name: str) -> dict|None:
        """返回工具的原始 schema 字典，绕过 check_fn 过滤。"""
        entry: ToolEntry | None = self.get_entry(name)
        return entry.schema if entry else None

    def get_all_tool_names(self) -> list[str]:
        """返回所有已注册工具名称的排序列表。"""
        return sorted(entry.name for entry in self._snapshot_entries())

    def get_toolset_for_tool(self, name: str) -> str | None:
        """返回工具所属的 toolset，不存在返回 None。"""
        entry: ToolEntry | None = self.get_entry(name)
        return entry.toolset if entry else None

    def get_availability(self, name: str) -> ToolAvailability:
        """返回工具的 availability 位掩码（``ToolAvailability``）。

        Raises:
            KeyError: 工具未注册。
        """
        entry: ToolEntry | None = self.get_entry(name)
        if entry is None:
            raise KeyError(f"Tool not registered: {name}")
        return entry.availability

    def get_definitions_for_availability(
        self,
        scope: ToolAvailability,
        tool_names: set | None = None,
        quiet: bool = False,
    ) -> list[dict]:
        """返回指定 availability 范围的工具的 OpenAI 格式 schema。"""
        result: list[dict] = []
        check_results: dict[Callable, bool] = {}
        entries_by_name: dict[str, ToolEntry] = {
            entry.name: entry for entry in self._snapshot_entries()
        }

        names_to_check = tool_names or set(entries_by_name.keys())
        for name in sorted(names_to_check):
            entry: ToolEntry | None = entries_by_name.get(name)
            if not entry:
                if tool_names is not None:
                    raise KeyError(f"Tool not registered: {name}")
                continue
            if (entry.availability & scope) == 0:
                if not quiet:
                    logger.debug("Tool %s filtered out (availability=%s, scope=%s)", name, entry.availability, scope)
                continue
            if entry.check_fn:
                if entry.check_fn not in check_results:
                    check_results[entry.check_fn] = self._check_fn_cached(entry.check_fn)
                if not check_results[entry.check_fn]:
                    if not quiet:
                        logger.debug("Tool %s unavailable (check failed)", name)
                    continue
            schema_with_name: dict = {**entry.schema, "name": entry.name}
            if entry.dynamic_schema_overrides is not None:
                try:
                    overrides: dict = entry.dynamic_schema_overrides()
                    if isinstance(overrides, dict):
                        schema_with_name.update(overrides)
                except Exception as exc:
                    if requires_lifecycle_propagation(exc):
                        raise
                    logger.warning(
                        "dynamic_schema_overrides for tool %s raised %s; using static schema",
                        name, exc,
                    )
            result.append({"type": "function", "function": schema_with_name})
        return result

    def get_danger_level(self, name: str) -> ToolDangerLevel:
        """返回工具的危险等级，未注册时返回 ``ToolDangerLevel.safe``。"""
        entry: ToolEntry | None = self.get_entry(name)
        return entry.danger_level if entry else ToolDangerLevel.safe

    def is_tool_available(self, name: str) -> bool:
        """返回单个工具的即时可用性。"""
        entry: ToolEntry | None = self.get_entry(name)
        if entry is None:
            return False
        if entry.check_fn is None:
            return True
        return self._check_fn_cached(entry.check_fn)

    def get_tool_to_toolset_map(self) -> dict[str, str]:
        """返回 ``{tool_name: toolset_name}`` 映射。"""
        return {entry.name: entry.toolset for entry in self._snapshot_entries()}

    def get_registered_toolset_names(self) -> list[str]:
        """返回注册表中存在的排序去重 toolset 名称列表。"""
        return sorted({entry.toolset for entry in self._snapshot_entries()})

    def get_tool_names_for_toolset(self, toolset: str) -> list[str]:
        """返回指定 toolset 下注册的工具名称排序列表。"""
        return sorted(
            entry.name for entry in self._snapshot_entries()
            if entry.toolset == toolset
        )

    # -- toolset 别名支持 ---------------------------------------------

    def register_toolset_alias(self, alias: str, toolset: str) -> None:
        """注册规范 toolset 名称的显式别名。"""
        with self._lock:
            existing: str | None = self._toolset_aliases.get(alias)
            if existing and existing != toolset:
                logger.warning(
                    "Toolset alias collision: '%s' (%s) overwritten by %s",
                    alias, existing, toolset,
                )
            self._toolset_aliases[alias] = toolset
            self._generation += 1

    def get_registered_toolset_aliases(self) -> dict[str, str]:
        """返回 ``{alias: canonical_toolset}`` 映射的快照。"""
        with self._lock:
            return dict(self._toolset_aliases)

    def get_toolset_alias_target(self, alias: str) -> str | None:
        """返回别名的规范 toolset 名称，不存在返回 None。"""
        with self._lock:
            return self._toolset_aliases.get(alias)

    # -- 工具集元数据 --------------------------------------------------

    def register_toolset(
        self,
        name: str,
        description: str = "",
        usage_guide: str = "",
        loaded_by_default: bool = False,
    ) -> None:
        """显式注册工具集元数据。"""
        with self._lock:
            existing: ToolsetEntry | None = self._toolsets.get(name)
            if existing is not None:
                if description:
                    existing.description = description
                if usage_guide:
                    existing.usage_guide = usage_guide
                existing.loaded_by_default = loaded_by_default
            else:
                self._toolsets[name] = ToolsetEntry(
                    name=name,
                    description=description,
                    usage_guide=usage_guide,
                    loaded_by_default=loaded_by_default,
                )
            self._generation += 1

    def deregister_toolset(self, name: str) -> None:
        """显式注销工具集元数据。"""
        with self._lock:
            self._toolsets.pop(name, None)
            self._generation += 1

    def get_toolset_entry(self, name: str) -> ToolsetEntry | None:
        """返回工具集元数据条目，不存在返回 None。"""
        with self._lock:
            return self._toolsets.get(name)

    # -- 注册 ------------------------------------------------------

    def register(
        self,
        name: str,
        toolset: str,
        schema: dict,
        handler: Callable,
        check_fn: Callable | None = None,
        requires_env: list[str] | None = None,
        is_async: bool = False,
        description: str = "",
        max_result_size_chars: int | None = None,
        dynamic_schema_overrides: Callable | None = None,
        override: bool = False,
        danger_level: ToolDangerLevel = ToolDangerLevel.safe,
        no_timeout: bool = False,
        availability: ToolAvailability = ToolAvailability.EVERY,
        resets_turn_counter: bool = False,
    ) -> None:
        """由显式工具声明或 MCP 动态发现注册；冲突拒绝必须向调用方传播。"""
        with self._lock:
            existing: ToolEntry | None = self._tools.get(name)
            if existing and existing.toolset != toolset:
                both_mcp: bool = (
                    existing.toolset.startswith("mcp-")
                    and toolset.startswith("mcp-")
                )
                if both_mcp:
                    logger.debug(
                        "Tool '%s': MCP toolset '%s' overwriting MCP toolset '%s'",
                        name, toolset, existing.toolset,
                    )
                elif override:
                    logger.info(
                        "Tool '%s': toolset '%s' overriding existing toolset '%s' "
                        "(override=True opt-in)",
                        name, toolset, existing.toolset,
                    )
                else:
                    logger.error(
                        "Tool registration REJECTED: '%s' (toolset '%s') would "
                        "shadow existing tool from toolset '%s'. Pass "
                        "override=True to register() if the replacement is "
                        "intentional, or deregister the existing tool first.",
                        name, toolset, existing.toolset,
                    )
                    raise ValueError(
                        f"Tool {name!r} in {toolset!r} conflicts with {existing.toolset!r}; "
                        "set override=True only for an intentional replacement"
                    )

            self._tools[name] = ToolEntry(
                name=name,
                toolset=toolset,
                schema=schema,
                handler=handler,
                check_fn=check_fn,
                requires_env=requires_env or [],
                is_async=is_async,
                description=description or schema.get("description", ""),
                max_result_size_chars=max_result_size_chars,
                dynamic_schema_overrides=dynamic_schema_overrides,
                danger_level=danger_level,
                no_timeout=no_timeout,
                availability=availability,
                resets_turn_counter=resets_turn_counter,
            )
            if check_fn and toolset not in self._toolset_checks:
                self._toolset_checks[toolset] = check_fn
            if toolset not in self._toolsets:
                self._toolsets[toolset] = ToolsetEntry(name=toolset)
            self._generation += 1

    def deregister(self, name: str) -> None:
        """从注册表中移除工具。"""
        with self._lock:
            entry: ToolEntry | None = self._tools.pop(name, None)
            if entry is None:
                return
            toolset_still_exists: bool = any(
                e.toolset == entry.toolset for e in self._tools.values()
            )
            if not toolset_still_exists:
                self._toolset_checks.pop(entry.toolset, None)
                self._toolset_aliases = {
                    alias: target
                    for alias, target in self._toolset_aliases.items()
                    if target != entry.toolset
                }
            self._generation += 1
        logger.debug("Deregistered tool: %s", name)

    # -- schema 检索 --------------------------------------------------

    def get_definitions(
        self,
        tool_names: set,
        quiet: bool = False,
    ) -> list[dict]:
        """返回请求工具名称的 OpenAI 格式 tool schema。"""
        result: list[dict] = []
        check_results: dict[Callable, bool] = {}
        entries_by_name: dict[str, ToolEntry] = {entry.name: entry for entry in self._snapshot_entries()}
        for name in sorted(tool_names):
            entry: ToolEntry | None = entries_by_name.get(name)
            if not entry:
                continue
            if entry.check_fn:
                if entry.check_fn not in check_results:
                    check_results[entry.check_fn] = self._check_fn_cached(entry.check_fn)
                if not check_results[entry.check_fn]:
                    if not quiet:
                        logger.debug("Tool %s unavailable (check failed)", name)
                    continue
            schema_with_name: dict = {**entry.schema, "name": entry.name}
            if entry.dynamic_schema_overrides is not None:
                try:
                    overrides: dict = entry.dynamic_schema_overrides()
                    if isinstance(overrides, dict):
                        schema_with_name.update(overrides)
                except Exception as exc:
                    if requires_lifecycle_propagation(exc):
                        raise
                    logger.warning(
                        "dynamic_schema_overrides for tool %s raised %s; "
                        "using static schema",
                        name, exc,
                    )
            result.append({"type": "function", "function": schema_with_name})
        return result

    # -- 已加载工具集 schema 检索 ---------------------------------------------

    def get_definitions_for_loaded_toolsets(
        self,
        scope: ToolAvailability,
        loaded_toolsets: set[str],
        quiet: bool = False,
    ) -> list[dict]:
        """返回已加载工具集中符合 scope 和 check_fn 的工具 schema。"""
        result: list[dict] = []
        check_results: dict[Callable, bool] = {}
        entries_by_name: dict[str, ToolEntry] = {
            entry.name: entry for entry in self._snapshot_entries()
        }
        for name, entry in sorted(entries_by_name.items()):
            if entry.toolset not in loaded_toolsets:
                continue
            if (entry.availability & scope) == 0:
                if not quiet:
                    logger.debug(
                        "Tool %s filtered out (availability=%s, scope=%s)",
                        name, entry.availability, scope,
                    )
                continue
            if entry.check_fn:
                if entry.check_fn not in check_results:
                    check_results[entry.check_fn] = self._check_fn_cached(entry.check_fn)
                if not check_results[entry.check_fn]:
                    if not quiet:
                        logger.debug("Tool %s unavailable (check failed)", name)
                    continue
            schema_with_name: dict = {**entry.schema, "name": entry.name}
            if entry.dynamic_schema_overrides is not None:
                try:
                    overrides: dict = entry.dynamic_schema_overrides()
                    if isinstance(overrides, dict):
                        schema_with_name.update(overrides)
                except Exception as exc:
                    if requires_lifecycle_propagation(exc):
                        raise
                    logger.warning(
                        "dynamic_schema_overrides for tool %s raised %s; "
                        "using static schema",
                        name, exc,
                    )
            result.append({"type": "function", "function": schema_with_name})
        return result

    # -- 工具集目录 --------------------------------------------------------

    def get_toolset_catalog(
        self,
        scope: ToolAvailability,
        loaded_toolsets: set[str],
    ) -> list[dict]:
        """返回按当前 Loop scope 和 check_fn 过滤后的工具集目录。"""
        entries: list[ToolEntry] = self._snapshot_entries()
        check_results: dict[Callable, bool] = {}
        toolsets: dict[str, dict] = {}

        for entry in entries:
            if (entry.availability & scope) == 0:
                continue
            if entry.check_fn:
                if entry.check_fn not in check_results:
                    check_results[entry.check_fn] = self._check_fn_cached(entry.check_fn)
                if not check_results[entry.check_fn]:
                    continue

            ts: str = entry.toolset
            if ts not in toolsets:
                ts_entry: ToolsetEntry | None = self._toolsets.get(ts)
                is_loaded = ts in loaded_toolsets
                if is_loaded and ts_entry and ts_entry.usage_guide:
                    display_desc = ts_entry.usage_guide
                else:
                    display_desc = ts_entry.description if ts_entry else ""
                toolsets[ts] = {
                    "name": ts,
                    "description": display_desc,
                    "loaded": is_loaded,
                    "tools": [],
                }
            toolsets[ts]["tools"].append(entry.name)

        return sorted(toolsets.values(), key=lambda t: t["name"])

    # -- 关闭接收与在途任务管理 ---------------------------------------------

    @property
    def task_owner(self) -> TaskOwner:
        if self._task_owner is None:
            raise LifecycleFailure("ToolRegistry has not been awakened")
        return self._task_owner

    @contextmanager
    def _admit_dispatch(self) -> Iterator[None]:
        with self.runtime.admission():
            with self._sync_calls_lock:
                if self._dispatch_closed:
                    raise ApplicationStoppingError("Tool dispatch has been closed")
                yield

    def close_dispatch(self) -> None:
        """STOPPING 期间也可封闭接收，不调用要求 RUNNING 的入口。"""
        with self._sync_calls_lock:
            self._dispatch_closed = True

    def _settle_sync(self, record: SyncToolCallRecord) -> None:
        """由真实 Future 结局与请求交接共同决定回收，可由工作线程调用。"""
        failure: BaseException | None = None
        with self._sync_calls_lock:
            future = record.future
            if future.done():
                if future.cancelled():
                    error: BaseException | None = LifecycleFailure(
                        "Native tool Future was cancelled outside its owner"
                    )
                else:
                    error = future.exception()
                if error is not None and not record.failure_reported:
                    if contains_lifecycle_failure(error):
                        failure = error
                    elif record.cancelled_while_running and not isinstance(
                        error, ApplicationStoppingError
                    ):
                        failure = LifecycleFailure("Native tool failed after request cancellation")
                        failure.__cause__ = error
                    if failure is not None:
                        record.failure_reported = True
                        self._sync_failures.append(failure)
                if record.request_released:
                    self._sync_calls.pop(future, None)
        # 不在登记锁内取得 Runtime 锁；接收的锁顺序是 Runtime -> 登记表。
        if failure is not None:
            self.runtime.record_failure(failure)
        changed = self._sync_changed
        if changed is not None:
            self.runtime.loop.call_soon_threadsafe(changed.set)

    def _release_sync(self, record: SyncToolCallRecord, *, cancelled: bool) -> None:
        with self._sync_calls_lock:
            record.request_released = True
            record.cancelled_while_running = cancelled and not record.future.done()
        self._settle_sync(record)

    def _submit_sync(
        self, entry: ToolEntry, args: dict, kwargs: dict[str, Any],
    ) -> SyncToolCallRecord:
        context = copy_context()
        # 门闩保证线程即使立即调度，也先完成真实 Future 登记。
        ready = threading.Event()

        def invoke() -> Any:
            ready.wait()
            with self._admit_dispatch():
                pass
            return context.run(entry.handler, args, **kwargs)

        with self._admit_dispatch():
            executor = self._executor
            if executor is None:
                raise LifecycleFailure("ToolRegistry executor has not been initialized")
            future = executor.submit(invoke)
            record = SyncToolCallRecord(future=future)
            self._sync_calls[future] = record
            future.add_done_callback(lambda done: self._settle_sync(record))
            ready.set()
        return record

    @staticmethod
    def _observe_sync_adapter(future: asyncio.Future[Any]) -> None:
        # 真实错误由原生记录或等待方处理；适配 Future 不另设失败政策。
        if not future.cancelled():
            future.exception()

    async def cancel_pending_calls(self) -> None:
        """取消请求任务并等待真实异步收尾；原生线程仍由登记表持有。"""
        self.close_dispatch()
        await self.task_owner.cancel_and_wait(timeout=SYSTEM_QUIESCE_TIMEOUT_SECONDS)

    async def wait_idle(self) -> None:
        """有界等待请求交接和真实同步工作；超时保留登记并报告失败。"""
        self.close_dispatch()

        async def wait_sync() -> None:
            changed = self._sync_changed
            if changed is None:
                raise LifecycleFailure("ToolRegistry has not been awakened")
            loop = asyncio.get_running_loop()
            deadline = loop.time() + SYSTEM_QUIESCE_TIMEOUT_SECONDS
            while True:
                changed.clear()
                with self._sync_calls_lock:
                    if not self._sync_calls:
                        failures = tuple(self._sync_failures)
                        break
                remaining = deadline - loop.time()
                if remaining <= 0:
                    failure = LifecycleFailure("Native tool calls did not finish within shutdown deadline")
                    self.runtime.record_failure(failure)
                    raise failure
                try:
                    await asyncio.wait_for(changed.wait(), timeout=remaining)
                except asyncio.TimeoutError:
                    # 回到唯一截止判断，不能把超时当作真实线程退出。
                    continue
            if failures:
                raise BaseExceptionGroup("Native tool cleanup failed", failures)

        await close_resources((self.cancel_pending_calls, wait_sync))

    # -- 分发 ----------------------------------------------------------

    def _resolve_call(self, name: str, context: Any) -> ToolEntry | dict:
        entry = self.get_entry(name)
        if entry is None:
            return {"error": f"Unknown tool: {name}"}
        if context is not None:
            from entry.base_agent_loop import ToolContext
            if isinstance(context, ToolContext) and not context.loop.is_toolset_loaded(entry.toolset):
                return {
                    "error": f"Tool '{name}' belongs to toolset '{entry.toolset}' which is not loaded. Call LoadToolset with the toolset name first.",
                    "_toolset_not_loaded": True,
                    "_toolset": entry.toolset,
                }
        return entry

    @staticmethod
    def _tool_result(name: str, result: Any) -> dict:
        if isinstance(result, dict):
            return result
        logger.error("Tool '%s' returned non-dict result (type: %s)", name, type(result).__name__)
        return {"error": f"Tool '{name}' returned non-dict result (type: {type(result).__name__}). Tool handlers must return dict."}

    def dispatch(self, name: str, args: dict, context: Any = None) -> dict:
        """仅供非事件循环线程调用；同步 handler 同样由唯一执行器登记。"""
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            pass
        else:
            raise LifecycleFailure("Synchronous tool dispatch cannot block an event loop")
        with self._admit_dispatch():
            pass
        entry = self._resolve_call(name, context)
        if isinstance(entry, dict):
            return entry
        if entry.is_async:
            return {"error": f"Tool '{name}' is async; use async_dispatch in an async context"}
        kwargs = {"context": context} if _handler_accepts_context(entry.handler, context) else {}
        record = self._submit_sync(entry, args, kwargs)
        try:
            return self._tool_result(name, record.future.result())
        except ApplicationStoppingError:
            raise
        except Exception as error:
            if requires_lifecycle_propagation(error):
                raise
            logger.exception("Tool %s dispatch error", name)
            return {"error": f"Tool execution failed: {type(error).__name__}: {error}"}
        finally:
            self._release_sync(record, cancelled=False)

    async def _invoke_handler(
        self, entry: ToolEntry, args: dict, context: Any,
    ) -> dict:
        kwargs = {"context": context} if _handler_accepts_context(entry.handler, context) else {}
        if entry.is_async:
            with self._admit_dispatch():
                pass
            result = await entry.handler(args, **kwargs)
        else:
            record = self._submit_sync(entry, args, kwargs)
            cancelled = False
            try:
                adapter = asyncio.wrap_future(record.future)
                adapter.add_done_callback(self._observe_sync_adapter)
                result = await asyncio.shield(adapter)
            except asyncio.CancelledError:
                cancelled = True
                raise
            finally:
                self._release_sync(record, cancelled=cancelled)
        return self._tool_result(entry.name, result)

    async def async_dispatch(self, name: str, args: dict, context: Any = None) -> dict:
        """完整 handler 请求由 TaskOwner 持有；原生线程另行登记真实结局。"""
        with self._admit_dispatch():
            pass
        entry = self._resolve_call(name, context)
        if isinstance(entry, dict):
            return entry
        try:
            return await self.task_owner.run_request(
                lambda: self._invoke_handler(entry, args, context),
                name=f"tool-handler-{name}",
                admission=self._admit_dispatch,
            )
        except ApplicationStoppingError:
            raise
        except Exception as error:
            if requires_lifecycle_propagation(error):
                raise
            logger.exception("Tool %s async_dispatch error", name)
            return {"error": f"Tool execution failed: {type(error).__name__}: {error}"}

    # -- toolset 可用性查询 --------------------------------------

    def get_max_result_size(
        self,
        name: str,
        default: int | None = None,
    ) -> int:
        """返回每个工具的最大结果大小，或 *default*（或全局默认值）。"""
        entry: ToolEntry | None = self.get_entry(name)
        if entry and entry.max_result_size_chars is not None:
            return entry.max_result_size_chars
        if default is not None:
            return default
        return DEFAULT_RESULT_SIZE_CHARS

    def is_toolset_available(self, toolset: str) -> bool:
        """检查 toolset 的要求是否满足。"""
        with self._lock:
            check: Callable | None = self._toolset_checks.get(toolset)
        return self._evaluate_toolset_check(toolset, check)

    def check_toolset_requirements(self) -> dict[str, bool]:
        """返回 ``{toolset: available_bool}`` 映射。"""
        entries: list[ToolEntry]
        toolset_checks: dict[str, Callable]
        entries, toolset_checks = self._snapshot_state()
        toolsets: list[str] = sorted({entry.toolset for entry in entries})
        return {
            toolset: self._evaluate_toolset_check(toolset, toolset_checks.get(toolset))
            for toolset in toolsets
        }

    def get_available_toolsets(self) -> dict[str, dict]:
        """返回用于 UI 展示的 toolset 元数据。"""
        toolsets: dict[str, dict] = {}
        entries: list[ToolEntry]
        toolset_checks: dict[str, Callable]
        entries, toolset_checks = self._snapshot_state()
        for entry in entries:
            ts: str = entry.toolset
            if ts not in toolsets:
                toolsets[ts] = {
                    "available": self._evaluate_toolset_check(
                        ts, toolset_checks.get(ts)
                    ),
                    "tools": [],
                    "description": "",
                    "requirements": [],
                }
            toolsets[ts]["tools"].append(entry.name)
            if entry.requires_env:
                for env in entry.requires_env:
                    if env not in toolsets[ts]["requirements"]:
                        toolsets[ts]["requirements"].append(env)
        return toolsets

    def get_toolset_requirements(self) -> dict[str, dict]:
        """构建向后兼容的 toolset-requirements 字典。"""
        result: dict[str, dict] = {}
        entries: list[ToolEntry]
        toolset_checks: dict[str, Callable]
        entries, toolset_checks = self._snapshot_state()
        for entry in entries:
            ts: str = entry.toolset
            if ts not in result:
                result[ts] = {
                    "name": ts,
                    "env_vars": [],
                    "check_fn": toolset_checks.get(ts),
                    "setup_url": None,
                    "tools": [],
                }
            if entry.name not in result[ts]["tools"]:
                result[ts]["tools"].append(entry.name)
            for env in entry.requires_env:
                if env not in result[ts]["env_vars"]:
                    result[ts]["env_vars"].append(env)
        return result

    def check_tool_availability(self, quiet: bool = False) -> tuple[list[str], list[dict]]:
        """返回 ``(available_toolsets, unavailable_info)``。"""
        available: list[str] = []
        unavailable: list[dict] = []
        seen: set = set()
        entries: list[ToolEntry]
        toolset_checks: dict[str, Callable]
        entries, toolset_checks = self._snapshot_state()
        for entry in entries:
            ts: str = entry.toolset
            if ts in seen:
                continue
            seen.add(ts)
            if self._evaluate_toolset_check(ts, toolset_checks.get(ts)):
                available.append(ts)
            else:
                unavailable.append({
                    "name": ts,
                    "env_vars": entry.requires_env or [],
                    "tools": [e.name for e in entries if e.toolset == ts],
                })
        return available, unavailable

    async def _shutdown_executor(self) -> None:
        with self._sync_calls_lock:
            native_idle = not self._sync_calls
        if not native_idle or not self.task_owner.is_idle:
            failure = LifecycleFailure("Cannot release tool executor while calls are still owned")
            self.runtime.record_failure(failure)
            raise failure
        executor = self._executor
        if executor is None:
            return
        if self._executor_shutdown_task is None:
            self._executor_shutdown_task = asyncio.create_task(
                asyncio.to_thread(executor.shutdown, wait=True),
                name="tool-executor-shutdown",
            )
            self._executor_shutdown_task.add_done_callback(self._observe_executor_shutdown)
        task = self._executor_shutdown_task
        done, _ = await asyncio.wait({task}, timeout=SYSTEM_QUIESCE_TIMEOUT_SECONDS)
        if not done:
            failure = LifecycleFailure("Tool executor threads did not finish shutdown")
            self.runtime.record_failure(failure)
            raise failure
        task.result()
        self._executor = None

    def _observe_executor_shutdown(self, task: asyncio.Task[None]) -> None:
        if task.cancelled():
            self.runtime.record_failure(LifecycleFailure("Tool executor shutdown was cancelled"))
        else:
            error = task.exception()
            if error is not None:
                self.runtime.record_failure(error)

    async def virtual_shotdown(self) -> None:
        """工作实际结束后在线程中 join；失败保留依赖和活资源记录。"""
        self.close_dispatch()
        await close_resources((self.wait_idle, self._shutdown_executor))


# ---------------------------------------------------------------------------
# 工具响应序列化辅助函数
# ---------------------------------------------------------------------------

def tool_error(message: str, **extra: Any) -> dict:
    """返回工具 handler 的错误 dict。"""
    result: dict = {"error": str(message)}
    if extra:
        result.update(extra)
    return result


def tool_result(data: dict | None = None, **kwargs: Any) -> dict:
    """返回工具 handler 的结果 dict。"""
    if data is not None:
        return data
    return kwargs
