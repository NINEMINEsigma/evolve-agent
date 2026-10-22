"""MCP lifecycle adapter; all blocking work has a real native owner."""

from __future__ import annotations

import asyncio
import json
import logging
import math
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from framework import AsyncSystem

from abstract.mcp.client import (
    MCPCore, _MCP_AVAILABLE, _failure_summary, _validate_remote_mcp_url,
)
from abstract.mcp.work import MCPThreadWork
from interface.mcp_system import IMCPSystem
from interface.runtime_system import IRuntimeSystem
from interface.tool_registry import IToolRegistry
from entity.constant import SYSTEM_QUIESCE_TIMEOUT_SECONDS
from system.lifecycle import ApplicationStoppingError, LifecycleFailure, TaskOwner, close_resources

logger = logging.getLogger(__name__)


def _positive(
    value: Any,
    name: str,
    *,
    integer: bool = False,
    zero: bool = False
    ) -> None:
    if isinstance(value, bool) or not isinstance(value, int if integer else (int, float)):
        raise TypeError(f"{name} must be a number of the required type")
    if not math.isfinite(value) or (value < 0 if zero else value <= 0):
        raise ValueError(f"{name} must be finite and {'nonnegative' if zero else 'positive'}")


def _validate_server(name: str, config: Any) -> None:
    """Validate one server entry; unsupported values raise instead of guessing."""
    if not isinstance(config, dict):
        raise TypeError(f"MCP server entry must be an object: {name}")
    if not isinstance(config.get("enabled", True), bool):
        raise TypeError(f"MCP enabled must be boolean: {name}")
    if not config.get("enabled", True):
        return
    if "url" in config:
        _validate_remote_mcp_url(name, config["url"])
        if config.get("transport", "http") not in ("http", "streamable_http", "streamable-http", "sse"):
            raise ValueError(f"Unsupported MCP transport: {name}")
    elif not isinstance(config.get("command"), str) or not config["command"].strip():
        raise ValueError(f"MCP server requires command or url: {name}")
    if not isinstance(config.get("args", []), list) or not all(isinstance(arg, str) for arg in config.get("args", [])):
        raise TypeError(f"MCP args must be a string list: {name}")
    for key in ("headers", "env"):
        value = config.get(key)
        if value is not None and (not isinstance(value, dict) or not all(
            isinstance(k, str) and isinstance(v, str) for k, v in value.items()
        )):
            raise TypeError(f"MCP {key} must map strings to strings: {name}")
    for key in ("timeout", "connect_timeout"):
        if key in config:
            _positive(config[key], f"{name}.{key}")
    for key in ("ssl_verify", "supports_parallel_tool_calls"):
        if key in config and not isinstance(config[key], bool):
            raise TypeError(f"MCP {key} must be boolean: {name}")
    auth = config.get("auth", "")
    if not isinstance(auth, str) or auth.lower().strip() not in ("", "oauth"):
        raise ValueError(f"Unsupported MCP auth configuration: {name}")
    oauth = config.get("oauth")
    if oauth is not None:
        if not isinstance(oauth, dict):
            raise TypeError(f"MCP oauth must be an object: {name}")
        if "redirect_port" in oauth:
            _positive(oauth["redirect_port"], f"{name}.oauth.redirect_port", integer=True, zero=True)
            if oauth["redirect_port"] > 65535:
                raise ValueError("OAuth redirect port exceeds 65535")
        if "timeout" in oauth:
            _positive(oauth["timeout"], f"{name}.oauth.timeout")
    tools = config.get("tools", {})
    if tools is None:
        tools = {}
    if not isinstance(tools, dict):
        raise TypeError(f"MCP tools must be an object: {name}")
    for key in ("include", "exclude"):
        value = tools.get(key)
        if value is not None and not (isinstance(value, str) or isinstance(value, list) and all(isinstance(item, str) for item in value)):
            raise TypeError(f"MCP tools.{key} must be a string or string list: {name}")
    for key in ("resources", "prompts"):
        if key in tools and not isinstance(tools[key], bool):
            raise TypeError(f"MCP tools.{key} must be boolean: {name}")
    sampling = config.get("sampling", {})
    if not isinstance(sampling, dict) or not isinstance(sampling.get("enabled", True), bool):
        raise TypeError(f"MCP sampling must be an object with a boolean enabled flag: {name}")
    for key in ("max_rpm", "max_tokens_cap", "max_tool_rounds"):
        if key in sampling:
            _positive(sampling[key], f"{name}.sampling.{key}", integer=True, zero=key == "max_tool_rounds")
    if "timeout" in sampling:
        _positive(sampling["timeout"], f"{name}.sampling.timeout")
    allowed = sampling.get("allowed_models", [])
    if not isinstance(allowed, list) or not all(isinstance(item, str) for item in allowed):
        raise TypeError(f"MCP allowed_models must be a string list: {name}")
    if "model" in sampling and not isinstance(sampling["model"], str):
        raise TypeError(f"MCP sampling.model must be a string: {name}")


def _validate_servers(raw: Any) -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
    """Validate every entry independently; only unusable entries are skipped.

    Returns ``(valid, invalid)`` where ``invalid`` maps a server name to the
    logged failure summary. A malformed document root still raises because no
    per-server context exists at that level.
    """
    if not isinstance(raw, dict):
        raise TypeError("MCP configuration must be an object")
    valid: dict[str, dict[str, Any]] = {}
    invalid: dict[str, str] = {}
    for name, config in raw.items():
        if not isinstance(name, str) or not name.strip():
            raise TypeError("MCP server entries require a nonempty name")
        try:
            _validate_server(name, config)
        except (TypeError, ValueError) as error:
            invalid[name] = _failure_summary(error)
            logger.error(
                "MCP server '%s' configuration is unusable and will be skipped: %s",
                name, invalid[name],
            )
            continue
        valid[name] = config
    return valid, invalid


class MCPSystem(IMCPSystem):
    def __init__(self) -> None:
        super().__init__(dependencies=(IRuntimeSystem, IToolRegistry))
        self._runtime: IRuntimeSystem | None = None
        self._core: MCPCore | None = None
        self._work: MCPThreadWork | None = None
        self._requests: TaskOwner | None = None
        self._frozen = False
        # 校验或连接失败的 server 名称→摘要；跳过而非中止启动。
        self._rejected: dict[str, str] = {}
        self._stop_task: asyncio.Task[None] | None = None
        self._close_task: asyncio.Task[None] | None = None

    @property
    def runtime(self) -> IRuntimeSystem:
        if self._runtime is None:
            raise LifecycleFailure("MCPSystem has not been awakened")
        return self._runtime

    @property
    def core(self) -> MCPCore:
        if self._core is None:
            raise LifecycleFailure("MCPCore has not been initialized")
        return self._core

    @property
    def work(self) -> MCPThreadWork:
        if self._work is None:
            raise LifecycleFailure("MCP native work has not been initialized")
        return self._work

    @property
    def requests(self) -> TaskOwner:
        if self._requests is None:
            raise LifecycleFailure("MCP request owner has not been initialized")
        return self._requests

    async def virtual_awake(self) -> None:
        self._runtime = self.get_system(IRuntimeSystem)
        self._core = MCPCore(self.runtime.context, self.get_system(IToolRegistry), self.runtime)
        self._requests = TaskOwner("mcp-system", self.runtime.record_failure)
        self._work = MCPThreadWork("mcp-core-work", self.runtime.record_failure)
        self._work.start()
        try:
            config, self._rejected = await self.work.run(self._load_config)
            enabled = {name: value for name, value in config.items() if value.get("enabled", True)}
            if enabled:
                await self.work.run(lambda: self.core.register(enabled))
        except BaseException as original:
            # framework 不调用失败awake节点的正常shotdown，此处必须自行清理。
            self.close_admission()
            try:
                await self._close()
            except BaseException as cleanup:
                raise BaseExceptionGroup("MCP startup and cleanup failed", [original, cleanup])
            raise

    def _load_config(self) -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
        """Read the config file; unusable entries never abort application startup.

        Document-level problems (unreadable file, broken JSON) and single-entry
        problems are logged and skipped. Only a missing MCP SDK still raises,
        because that is an environment prerequisite for every server rather
        than one server's configuration.
        """
        path_string = self.runtime.context.mcp_config_path
        if not path_string:
            return {}, {}
        path = Path(path_string)
        try:
            text = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("x", encoding="utf-8") as stream:
                stream.write("{}")
            text = "{}"
        except OSError as error:
            logger.error(
                "MCP configuration '%s' is unreadable and MCP stays disabled: %s",
                path, _failure_summary(error),
            )
            return {}, {}
        try:
            document = json.loads(text)
        except ValueError as error:
            logger.error(
                "MCP configuration '%s' is not valid JSON and MCP stays disabled: %s",
                path, _failure_summary(error),
            )
            return {}, {}
        if not isinstance(document, dict):
            logger.error(
                "MCP configuration '%s' must contain a JSON object; MCP stays disabled", path,
            )
            return {}, {}
        config, rejected = _validate_servers(document)
        if any(value.get("enabled", True) for value in config.values()) and not _MCP_AVAILABLE:
            raise ImportError("MCP SDK is required by enabled MCP servers")
        return config, rejected

    @contextmanager
    def _admission(self) -> Iterator[None]:
        with self.runtime.admission():
            if self._frozen:
                raise ApplicationStoppingError("MCPSystem admission is closed")
            yield

    async def refresh(self) -> dict[str, Any]:
        return await self.requests.run_request(
            self._refresh, name="mcp-refresh", admission=self._admission,
        )

    async def _refresh(self) -> dict[str, Any]:
        config, self._rejected = await self.work.run(self._load_config)
        with self._admission():
            pass
        if not any(value.get("enabled", True) for value in config.values()) and self.core.mcp_loop is None:
            return {
                "refreshed": True, "added": [], "removed": [],
                "failed": list(self._rejected), "status": self.status(),
                "errors": dict(self._rejected),
            }
        result = await self.work.run(lambda: self.core.refresh(config))
        result["cleanup_pending"] = result.get("cleanup_pending", [])
        status = self.status()
        reported = result.get("failed")
        failed: list[str] = list(reported) if isinstance(reported, list) else []
        failed.extend(name for name in self._rejected if name not in failed)
        result["failed"] = failed
        result["status"] = status
        result["errors"] = {
            entry["name"]: entry["error"] for entry in status if entry.get("error")
        }
        return result

    def status(self) -> list[dict[str, Any]]:
        """Report connected servers plus the ones skipped at config/connect time."""
        status = self.core.status()
        with self.core.lock:
            skipped = {**self._rejected, **self.core.server_failures}
        reported = {entry["name"] for entry in status}
        for name, error in skipped.items():
            if name in reported:
                continue
            status.append({
                "name": name,
                "transport": "",
                "tools": 0,
                "connected": False,
                "error": error,
            })
        return status

    def close_admission(self) -> None:
        self._frozen = True
        if self._core is not None:
            self._core.close_admission()

    def _observe_cleanup(self, task: asyncio.Task[None]) -> None:
        if task.cancelled():
            self.runtime.record_failure(LifecycleFailure("MCPSystem cleanup was cancelled"))
        elif (error := task.exception()) is not None:
            self.runtime.record_failure(error)

    async def stop_calls(self) -> None:
        self.close_admission()
        if self._stop_task is None:
            self._stop_task = asyncio.create_task(self._stop(), name="mcp-system-stop")
            self._stop_task.add_done_callback(self._observe_cleanup)
        await asyncio.shield(self._stop_task)

    async def _stop(self) -> None:
        await close_resources((
            lambda: self.requests.cancel_and_wait(timeout=SYSTEM_QUIESCE_TIMEOUT_SECONDS),
            lambda: self.work.run(self.core.stop_calls),
            self.work.wait_idle,
        ))

    async def _close(self) -> None:
        if self._close_task is None:
            self._close_task = asyncio.create_task(self._shutdown(), name="mcp-system-close")
            self._close_task.add_done_callback(self._observe_cleanup)
        await asyncio.shield(self._close_task)

    async def _shutdown(self) -> None:
        await close_resources((
            self.stop_calls,
            lambda: self.work.run(self.core.shutdown),
            self.work.close,
        ))

    async def virtual_shotdown(self) -> None:
        self.close_admission()
        await self._close()
