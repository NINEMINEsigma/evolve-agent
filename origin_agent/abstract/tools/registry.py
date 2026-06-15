"""工具 schema 和 handler 的中央注册表。

每个工具模块在模块级别调用 ``registry.register()`` 声明其
schema、handler、toolset 成员关系和可用性检查。下游代码使用
``get_definitions()`` 获取 OpenAI 格式的 schema（按可用性筛选）
并通过名称 ``dispatch()`` 执行 handler。

所有变更通过 ``threading.RLock`` 序列化，单调递增的
generation 计数器支持外部缓存失效。
"""

import asyncio
import json
import logging
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# ToolEntry
# ---------------------------------------------------------------------------


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
        "emoji",
        "max_result_size_chars",
        "dynamic_schema_overrides",
        "danger_level",
        "no_timeout",
    )

    def __init__(
        self,
        name: str,
        toolset: str,
        schema: dict,
        handler: Callable,
        check_fn: Optional[Callable] = None,
        requires_env: Optional[list[str]] = None,
        is_async: bool = False,
        description: str = "",
        emoji: str = "",
        max_result_size_chars: Optional[int] = None,
        dynamic_schema_overrides: Optional[Callable] = None,
        danger_level: str = "readonly",
        no_timeout: bool = False,
    ):
        self.name: str = name
        self.toolset: str = toolset
        self.schema: dict = schema
        self.handler: Callable = handler
        self.check_fn: Optional[Callable] = check_fn
        self.requires_env: list[str] = requires_env or []
        self.is_async: bool = is_async
        self.description: str = description
        self.emoji: str = emoji
        self.max_result_size_chars: Optional[int] = max_result_size_chars
        # 可选的零参数可调用对象，返回 schema 覆盖字典，
        # 在 get_definitions() 时应用。用于依赖运行时配置的字段。
        self.dynamic_schema_overrides: Optional[Callable] = dynamic_schema_overrides
        self.danger_level: str = danger_level
        self.no_timeout: bool = no_timeout


# ---------------------------------------------------------------------------
# check_fn TTL 缓存
#
# check_fn 可调用对象探测外部状态（Docker 守护进程、二进制可用性、
# 配置路径）。对长期运行的进程，每次 get_definitions() 都调用是
# 纯粹浪费 — 外部状态在人类时间尺度上变化。缓存结果约 30 秒，
# 使 env var 翻转能在一两个回合内传播而无需显式失效。
# ---------------------------------------------------------------------------

_CHECK_FN_TTL_SECONDS: float = 30.0
_check_fn_cache: dict[Callable, Tuple[float, bool]] = {}
_check_fn_cache_lock: threading.Lock = threading.Lock()

DEFAULT_RESULT_SIZE_CHARS: int = 100000


def _check_fn_cached(fn: Callable) -> bool:
    """返回 bool(fn())，跨调用 TTL 缓存。异常吞没为 False。"""
    now: float = time.monotonic()
    with _check_fn_cache_lock:
        cached: Tuple[float, bool] | None = _check_fn_cache.get(fn)
        if cached is not None:
            ts: float
            value: bool
            ts, value = cached
            if now - ts < _CHECK_FN_TTL_SECONDS:
                return value
    try:
        value = bool(fn())
    except Exception:
        value = False
    with _check_fn_cache_lock:
        _check_fn_cache[fn] = (now, value)
    return value


def invalidate_check_fn_cache() -> None:
    """丢弃所有缓存的 ``check_fn`` 结果。在影响工具可用性的配置变更后调用。"""
    with _check_fn_cache_lock:
        _check_fn_cache.clear()


# ---------------------------------------------------------------------------
# ToolRegistry（单例）
# ---------------------------------------------------------------------------


class ToolRegistry:
    """单例注册表，收集来自工具文件的 tool schema + handler。

    所有变更方法（register、deregister）持有 ``RLock``，
    因此可以安全地从多线程调用（如 MCP 动态刷新 vs 读取查询）。
    每次变更时递增的 ``_generation`` 计数器使基于 generation
    key 的外部缓存能廉价地检测过期。
    """

    def __init__(self):
        self._tools: dict[str, ToolEntry] = {}
        self._toolset_checks: dict[str, Callable] = {}
        self._toolset_aliases: dict[str, str] = {}
        # 序列化变更并为读取者提供稳定快照。
        self._lock: threading.RLock = threading.RLock()
        # 单调递增的 generation 计数器。每次变更时递增
        # （register / deregister / register_toolset_alias）。
        # 外部调用方可基于它 memoize：key 基于 generation 的缓存条目
        # 在 generation 未变化期间有效。
        self._generation: int = 0

    # -- 内部快照辅助方法 -----------------------------------------

    def _snapshot_state(self) -> Tuple[list[ToolEntry], dict[str, Callable]]:
        """返回注册表条目和 toolset 检查的一致性快照。"""
        with self._lock:
            return list(self._tools.values()), dict(self._toolset_checks)

    def _snapshot_entries(self) -> list[ToolEntry]:
        """返回已注册工具条目的稳定快照。"""
        return self._snapshot_state()[0]

    def _snapshot_toolset_checks(self) -> dict[str, Callable]:
        """返回 toolset 可用性检查的稳定快照。"""
        return self._snapshot_state()[1]

    def _evaluate_toolset_check(self, toolset: str, check: Optional[Callable]) -> bool:
        """运行 toolset 检查，缺失或失败时视为可用。"""
        if not check:
            return True
        try:
            return bool(check())
        except Exception:
            logger.debug("Toolset %s check raised; marking unavailable", toolset)
            return False

    # -- 查询方法 -----------------------------------------------------

    def get_entry(self, name: str) -> ToolEntry|None:
        """按名称返回已注册工具条目，不存在返回 None。"""
        with self._lock:
            return self._tools.get(name)

    def get_schema(self, name: str) -> dict|None:
        """返回工具的原始 schema 字典，绕过 check_fn 过滤。

        用于 token 估算和内省，这些场景下可用性不重要 — 只需 schema 内容。
        """
        entry: ToolEntry | None = self.get_entry(name)
        return entry.schema if entry else None

    def get_all_tool_names(self) -> list[str]:
        """返回所有已注册工具名称的排序列表。"""
        return sorted(entry.name for entry in self._snapshot_entries())

    def get_toolset_for_tool(self, name: str) -> str | None:
        """返回工具所属的 toolset，不存在返回 None。"""
        entry: ToolEntry | None = self.get_entry(name)
        return entry.toolset if entry else None

    def get_emoji(self, name: str, default: str = "⚡") -> str:
        """返回工具的 emoji，未设置时返回 *default*。"""
        entry: ToolEntry | None = self.get_entry(name)
        return entry.emoji if entry and entry.emoji else default

    def get_danger_level(self, name: str) -> str:
        """返回工具的危险等级，未注册时返回 "readonly"。

        返回值: "readonly" | "write" | "dangerous"
        """
        entry: ToolEntry | None = self.get_entry(name)
        return entry.danger_level if entry else "readonly"

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

    # -- 注册 ------------------------------------------------------

    def register(
        self,
        name: str,
        toolset: str,
        schema: dict,
        handler: Callable,
        check_fn: Optional[Callable] = None,
        requires_env: Optional[list[str]] = None,
        is_async: bool = False,
        description: str = "",
        emoji: str = "",
        max_result_size_chars: Optional[int] = None,
        dynamic_schema_overrides: Optional[Callable] = None,
        override: bool = False,
        danger_level: str = "readonly",
        no_timeout: bool = False,
    ) -> None:
        """注册工具。由每个工具文件在模块导入时调用。

        ``override=True`` 是显式 opt-in，用于意图替换来自不同 toolset
        的现有工具的插件。未设置时，会遮蔽现有工具的注册将被拒绝，
        以防止意外覆盖。

        同一 toolset 内注册的工具静默相互覆盖（最新的获胜 —
        预期用于重载/重新导入）。
        """
        with self._lock:
            existing: ToolEntry | None = self._tools.get(name)
            if existing and existing.toolset != toolset:
                # 允许相同类别覆盖（如 MCP-to-MCP 刷新）。
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
                    return

            self._tools[name] = ToolEntry(
                name=name,
                toolset=toolset,
                schema=schema,
                handler=handler,
                check_fn=check_fn,
                requires_env=requires_env or [],
                is_async=is_async,
                description=description or schema.get("description", ""),
                emoji=emoji,
                max_result_size_chars=max_result_size_chars,
                dynamic_schema_overrides=dynamic_schema_overrides,
                danger_level=danger_level,
                no_timeout=no_timeout,
            )
            if check_fn and toolset not in self._toolset_checks:
                self._toolset_checks[toolset] = check_fn
            self._generation += 1

    def deregister(self, name: str) -> None:
        """从注册表中移除工具。

        如果同一 toolset 中无其他工具残留，同时清理 toolset 检查。
        适用于动态工具刷新（如 MCP server 发送
        ``notifications/tools/list_changed``）。
        """
        with self._lock:
            entry: ToolEntry | None = self._tools.pop(name, None)
            if entry is None:
                return
            # 如果这是该 toolset 中的最后一个工具，移除 toolset 检查和别名。
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
        """返回请求工具名称的 OpenAI 格式 tool schema。

        仅包含 ``check_fn()`` 返回 True（或无 check_fn）的工具。
        ``check_fn()`` 结果通过 :func:`_check_fn_cached` 缓存约 30 秒，
        以摊平重复探测开销。

        返回 ``{"type": "function", "function": schema}`` 字典列表，
        适合直接传递给 OpenAI 格式的 chat completions API。
        """
        result: list[dict] = []
        # 在 30 秒 TTL 之上的每次调用缓存 — 处理一次 definitions
        # 调用中对同一 check_fn 的重复探测，无需重新读取 TTL 时钟。
        check_results: dict[Callable, bool] = {}
        entries_by_name: dict[str, ToolEntry] = {entry.name: entry for entry in self._snapshot_entries()}
        for name in sorted(tool_names):
            entry: ToolEntry | None = entries_by_name.get(name)
            if not entry:
                continue
            if entry.check_fn:
                if entry.check_fn not in check_results:
                    check_results[entry.check_fn] = _check_fn_cached(entry.check_fn)
                if not check_results[entry.check_fn]:
                    if not quiet:
                        logger.debug("Tool %s unavailable (check failed)", name)
                    continue
            # 确保 schema 始终包含 "name" 字段 — 使用 entry.name 作为兜底
            schema_with_name: dict = {**entry.schema, "name": entry.name}
            # 应用运行时动态覆盖
            if entry.dynamic_schema_overrides is not None:
                try:
                    overrides: dict = entry.dynamic_schema_overrides()
                    if isinstance(overrides, dict):
                        schema_with_name.update(overrides)
                except Exception as exc:
                    logger.warning(
                        "dynamic_schema_overrides for tool %s raised %s; "
                        "using static schema",
                        name, exc,
                    )
            result.append({"type": "function", "function": schema_with_name})
        return result

    # -- 分发 ----------------------------------------------------------

    def dispatch(self, name: str, args: dict, **kwargs: Any) -> Any:
        """按名称执行工具 handler。

        * 异步 handler 通过 ``asyncio.run()`` 自动桥接。
        * 所有异常被捕获并返回 ``{"error": "..."}``，保证一致的错误格式。

        返回 dict 或 str。
        """
        entry: ToolEntry | None = self.get_entry(name)
        if not entry:
            return {"error": f"Unknown tool: {name}"}
        try:
            if entry.is_async:
                return asyncio.run(entry.handler(args, **kwargs))
            return entry.handler(args, **kwargs)
        except Exception as e:
            logger.exception("Tool %s dispatch error: %s", name, e)
            sanitized: str = f"Tool execution failed: {type(e).__name__}: {e}"
            return {"error": sanitized}

    # -- toolset 可用性查询 --------------------------------------

    def get_max_result_size(
        self,
        name: str,
        default: Optional[int] = None,
    ) -> int:
        """返回每个工具的最大结果大小，或 *default*（或全局默认值）。"""
        entry: ToolEntry | None = self.get_entry(name)
        if entry and entry.max_result_size_chars is not None:
            return entry.max_result_size_chars
        if default is not None:
            return default
        return DEFAULT_RESULT_SIZE_CHARS

    def is_toolset_available(self, toolset: str) -> bool:
        """检查 toolset 的要求是否满足。

        当检查函数抛出意外异常时返回 False（而非崩溃）。
        """
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
        """返回用于 UI 展示的 toolset 元数据。

        每个值::

            {
                "available": bool,
                "tools": [str, ...],
                "description": "",
                "requirements": [str, ...],
            }
        """
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
        """构建向后兼容的 toolset-requirements 字典。

        每个值::

            {
                "name": str,
                "env_vars": [str, ...],
                "check_fn": Callable | None,
                "setup_url": None,
                "tools": [str, ...],
            }
        """
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

    def check_tool_availability(self, quiet: bool = False) -> Tuple[list[str], list[dict]]:
        """返回 ``(available_toolsets, unavailable_info)``。

        每个不可用条目::

            {
                "name": str,
                "env_vars": [str, ...],
                "tools": [str, ...],
            }
        """
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


# 模块级单例
registry: ToolRegistry = ToolRegistry()


# ---------------------------------------------------------------------------
# 工具响应序列化辅助函数
# ---------------------------------------------------------------------------
# 每个工具 handler 必须返回 JSON 字符串。这些辅助函数消除
# 工具文件中反复出现的样板代码。
#
# 用法：
#   from abstract.tools.registry import registry, tool_error, tool_result
#
#   return tool_error("something went wrong")
#   return tool_error("not found", code=404)
#   return tool_result(success=True, data=payload)
#   return tool_result(items)            # 直接传 dict


def tool_error(message: str, **extra: Any) -> dict:
    """返回工具 handler 的错误 dict。

    >>> tool_error("file not found")
    {"error": "file not found"}
    >>> tool_error("bad input", success=False)
    {"error": "bad input", "success": false}
    """
    result: dict = {"error": str(message)}
    if extra:
        result.update(extra)
    return result


def tool_result(data: Optional[dict] = None, **kwargs: Any) -> dict:
    """返回工具 handler 的结果 dict。

    接受 dict 位置参数 *或* 关键字参数（不能混用）：

    >>> tool_result(success=True, count=42)
    {"success": true, "count": 42}
    >>> tool_result({"key": "value"})
    {"key": "value"}
    """
    if data is not None:
        return data
    return kwargs