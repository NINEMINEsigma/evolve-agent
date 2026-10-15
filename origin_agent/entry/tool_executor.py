"""ToolExecutor — 统一工具调用执行器。

封装单个工具调用的完整流程：取消检查、parse error 处理、审批、
registry 分发、异常转换、前端事件推送和 UI 事件路由。

审批流程直接复用 ``component.approval.executor.execute_with_approval``。
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime
from typing import Any, Awaitable

from entity.puretype import (
    Role,
    ToolCallMeta,
    ToolCallRequest,
    LLMProfile,
    MainSessionActivityPhase,
)
from entity.gentype import RefWrapper
from entity.constant import TOOL_TASK_CANCEL_CLEANUP_TIMEOUT, ApplicationState
from entity.messages import ToolResultMessage
from entry.base_agent_loop import BaseAgentLoop, ToolContext, IMainSessionLoop
from entry.tool_post_dispatch import PreparedToolResult, ToolPostprocessor, prepare_tool_result
from abstract.tools.tool import ToolExecution
from system.lifecycle import (
    ApplicationStoppingError, LifecycleFailure, contains_lifecycle_failure,
    requires_lifecycle_propagation,
)
from system.runtime import RuntimeSystem
from entry.tool_pairing import interrupted_tool_result as _interrupted_result
from collections.abc import Callable

logger = logging.getLogger(__name__)


async def cancel_tool_wait(
    task: asyncio.Future[Any],
    pending: set[asyncio.Future[Any]],
    on_failure: Callable[[BaseException], None],
) -> None:
    """解除工具等待；短窗口只约束调用方响应，不替代 System 的清理截止。"""
    if task not in pending:
        pending.add(task)
        was_running = not task.done()

        def observe(done: asyncio.Future[Any]) -> None:
            pending.discard(done)
            if done.cancelled():
                return
            error = done.exception()
            if error is None:
                return
            if contains_lifecycle_failure(error):
                on_failure(error)
                return
            normal_stop = isinstance(error, (ApplicationStoppingError, asyncio.CancelledError))
            if isinstance(error, BaseExceptionGroup):
                _, remaining = error.split((ApplicationStoppingError, asyncio.CancelledError))
                normal_stop = remaining is None
            if was_running and not normal_stop:
                failure = LifecycleFailure("Tool request wrapper failed during cancellation")
                failure.__cause__ = error
                on_failure(failure)

        task.add_done_callback(observe)
        if not task.done():
            if not isinstance(task, asyncio.Task) or not task.cancelling():
                task.cancel()
    done, _ = await asyncio.wait({task}, timeout=TOOL_TASK_CANCEL_CLEANUP_TIMEOUT)
    # 超过短窗口仍保留强引用。真实 handler 的十秒清理由所属 TaskOwner
    # 负责，不在一秒时将正常用户中断误报为整个应用失败。
    if done and not task.cancelled():
        error = task.exception()
        if error is not None and requires_lifecycle_propagation(error):
            raise error


class ToolInterrupted(Exception):
    """内部中断信号：可中断等待被 cancel_event 打断时抛出。

    携带 phase 字段（"approval" / "dispatch"），由调用方
    ``except ToolInterrupted as ti`` 捕获后用 ``ti.phase``
    构造统一的中断失败结果。
    """

    def __init__(self, phase: str) -> None:
        super().__init__(f"Tool call interrupted during {phase}")
        self.phase: str = phase


class ToolExecutor:
    """执行单个工具调用，处理审批、分发和事件推送。

    由 IMainSessionLoop 持有，每个 tool_call 调用一次 ``execute()``。
    """

    def __init__(self, loop: IMainSessionLoop) -> None:
        self._loop = loop
        self._tool_stats: dict[str, dict[str, int]] = {}
        self._turn_counter: RefWrapper[int] | None = None
        self._cancel_cleanup_tasks: set[asyncio.Future[Any]] = set()
        self._runtime = loop.loop.app.get_system(RuntimeSystem)
        self.postprocessor = ToolPostprocessor(loop.loop)

    # -- 公开 API ----------------------------------------------------------

    def get_tool_stats(self) -> dict[str, dict[str, int]]:
        return {name: dict(stats) for name, stats in self._tool_stats.items()}

    def set_turn_counter(self, counter: RefWrapper[int] | None) -> None:
        """注入或清除工具循环计数器引用。

        当计数器非 None 且执行的工具标记了 resets_turn_counter=True 时，
        execute() 会在工具成功执行后将计数器归零。
        """
        self._turn_counter = counter

    async def _cancel_child_task(
        self,
        task: asyncio.Future[Any],
        phase: str,
    ) -> None:
        """复用取消交接；迟到回调使用预先持有的 Runtime，不重新查架构。"""
        await cancel_tool_wait(task, self._cancel_cleanup_tasks, self._runtime.record_failure)

    async def _await_or_cancel(self, coro: Awaitable[Any], phase: str) -> Any:
        """等待工具协程完成，或在主会话中断时有界取消它。"""
        task = asyncio.ensure_future(coro)
        interrupt_wait = asyncio.ensure_future(self._loop.loop.cancel_event.wait())
        try:
            done, _ = await asyncio.wait(
                {task, interrupt_wait},
                return_when=asyncio.FIRST_COMPLETED,
            )
        except asyncio.CancelledError:
            await self._cancel_child_task(task, phase)
            raise
        finally:
            interrupt_wait.cancel()

        if task in done and not task.cancelled():
            try:
                return task.result()
            except BaseException as exc:
                if requires_lifecycle_propagation(exc) or not isinstance(exc, Exception):
                    raise
                # handler 异常通常已由 async_dispatch 转为错误结果；此处兜底。
                return {"error": f"{type(exc).__name__}: {exc}"}

        await self._cancel_child_task(task, phase)
        raise ToolInterrupted(phase)

    async def execute(
        self,
        tc: ToolCallRequest,
        session_id: str,
        *,
        round_id: str,
        character_name: str | None = None,
        llm_profile: LLMProfile | None = None,
        activity_id: str | None = None,
        stream_id: str = "",
    ) -> PreparedToolResult:
        """执行单个工具调用，只准备结果；调用方保存后再发送通知。

        Args:
            tc: 工具调用描述。
            session_id: 当前会话 ID。
            round_id: 当前 Agent 回复轮次的唯一 ID。
            character_name: 发起此工具调用的角色名；
                MultiAgent 模式下由 worker 传入对应 Agent 名称，
                默认回退到 loop.current_character_agent。
            llm_profile: 当前 agent 的 LLM 配置；多 agent 模式下由 worker 传入，
                None 时回退到 loop.active_llm_profile。
        """
        from entity.constant import LOG_PREVIEW_CHARS, TOOL_RESULT_LOG_ARGUMENT_CHARS
        from component.approval import execute_with_approval
        from system.application import Application
        from abstract.tools.registry import ToolRegistry

        char_name = character_name or self._loop.current_character_agent
        tool_registry = Application.current().get_system(ToolRegistry)

        # -- 记录申请时间（审批流程之前） --
        start_mono: float = time.monotonic()
        application_time_ms: int = int(time.time() * 1000)
        application_time: str = datetime.fromtimestamp(
            time.time()
        ).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]

        def prepare_early(result: dict) -> PreparedToolResult:
            return prepare_tool_result(
                result, tool_name=tc.name, application_time=application_time,
                application_time_ms=application_time_ms, approval_duration_ms=0,
                invocation_start_offset_ms=0, invocation_duration_ms=0, end_time_offset_ms=0,
                session_id=session_id, tool_call_id=tc.id, character_name=char_name,
            )

        args = dict(tc.arguments)

        # 取消检查：中断时返回统一强制中断失败结果（保证与 assistant tool_calls 配对）
        if self._loop.loop.is_interrupted() or self._runtime.state is not ApplicationState.RUNNING:
            return PreparedToolResult(message=_interrupted_result(tc, char_name, "pending"))

        args["_session_id"] = session_id

        # 厌恶检查：不中断 LLM 生成，但拦截所有工具调用
        if self._loop.loop.is_disgusted():
            logger.info("Tool call '%s' rejected — user disgust active", tc.name)
            # 仍推送 tool_call 和 tool_result 事件到前端（厌恶不抑制事件）
            await self._loop.loop.get_sink().emit_tool_call(
                session_id, tc.name, tc.id, args,
                character_name=char_name,
            )
            _meta = ToolCallMeta(
                application_time=application_time,
                application_time_ms=application_time_ms,
                approval_duration_ms=0,
                invocation_start_offset_ms=0,
                invocation_duration_ms=0,
                end_time_offset_ms=0,
            )
            _disgust_result = {
                "error": "Tool call rejected: the user has expressed strong dissatisfaction (disgust). Stop calling tools and address the user's concerns directly.",
                "_disgusted": True,
                "_meta": _meta.model_dump(),
            }
            # 统计
            if tc.name not in self._tool_stats:
                self._tool_stats[tc.name] = {"calls": 0, "errors": 0}
            self._tool_stats[tc.name]["calls"] += 1
            self._tool_stats[tc.name]["errors"] += 1
            return prepare_early(_disgust_result)

        # parse error
        if args.get("_parse_error"):
            logger.warning(
                "Tool call '%s' skipped — arguments JSON parse failed. Preview: %s",
                tc.name, args.get("_raw_preview", "")[:LOG_PREVIEW_CHARS],
            )
            _meta = ToolCallMeta(
                application_time=application_time,
                application_time_ms=application_time_ms,
                approval_duration_ms=0,
                invocation_start_offset_ms=0,
                invocation_duration_ms=0,
                end_time_offset_ms=0,
            )
            _result: dict = {
                "error": (
                    "Tool call parameter parsing failed. Your arguments JSON is incomplete or malformed "
                    "(possibly truncated due to content being too long). Please try: "
                    "1) Split content into multiple writes, "
                    "2) Use PatchEdit for incremental edits, "
                    "3) Or reduce the amount of data written in a single call."
                ),
                "_parse_failed": True,
                "_meta": _meta.model_dump(),
            }
            return prepare_early(_result)

        logtc_arguments_strs = []
        for k, v in tc.arguments.items():
            logtc_arguments_strs.append(f"{k}={str(v)[:TOOL_RESULT_LOG_ARGUMENT_CHARS]}")
        logger.info("Tool call: %s | %s", tc.name, "\n".join(logtc_arguments_strs))

        # 统计
        if tc.name not in self._tool_stats:
            self._tool_stats[tc.name] = {"calls": 0, "errors": 0}
        self._tool_stats[tc.name]["calls"] += 1

        # 通知前端 tool_call 事件
        await self._loop.loop.get_sink().emit_tool_call(
            session_id, tc.name, tc.id, args,
            character_name=char_name,
        )

        # 工具集加载检查：未加载工具在审批前拦截
        _entry = tool_registry.get_tool(tc.name)
        if _entry is not None:
            _toolset = _entry.toolset
            if not self._loop.loop.is_toolset_loaded(_toolset):
                logger.info(
                    "Tool %s blocked (toolset '%s' not loaded)",
                    tc.name, _toolset,
                )
                _meta = ToolCallMeta(
                    application_time=application_time,
                    application_time_ms=application_time_ms,
                    approval_duration_ms=0,
                    invocation_start_offset_ms=0,
                    invocation_duration_ms=0,
                    end_time_offset_ms=0,
                )
                _not_loaded_result: dict = {
                    "error": f"Tool '{tc.name}' belongs to toolset '{_toolset}' which is not loaded. Call LoadToolset with the toolset name first.",
                    "_toolset_not_loaded": True,
                    "_toolset": _toolset,
                    "_meta": _meta.model_dump(),
                }
                self._tool_stats[tc.name]["errors"] += 1
                return prepare_early(_not_loaded_result)

        # 参数规范化为纯操作；审批仍查看原始模型参数。
        declared_tool = tool_registry.get_tool(tc.name)
        normalized_args = dict(args)
        if declared_tool is not None:
            try:
                normalized_args = declared_tool.ensure_arguments(args)
            except (ValueError, TypeError) as exc:
                return prepare_early({"error": str(exc)})

        # 审批流程
        _hooks_ctx = self._loop.loop.get_hooks_context(session_id)
        if activity_id is not None:
            self._loop.loop.set_main_session_activity_phase(
                activity_id,
                MainSessionActivityPhase.waiting_approval,
                stream_id=None,
                character_name=char_name,
            )

        approval_start: float = time.monotonic()
        try:
            outcome = await self._await_or_cancel(
                execute_with_approval(
                    tool_name=tc.name,
                    args=args,
                    session_id=session_id,
                    sink=self._loop.loop.get_sink(),
                    hooks_context=_hooks_ctx,
                ),
                "approval",
            )
        except ApplicationStoppingError:
            return PreparedToolResult(message=_interrupted_result(tc, char_name, "approval"))
        except ToolInterrupted as ti:
            # 取消审批 task 触发 request_approval 的 CancelledError 分支，自行清理 pending confirms
            return PreparedToolResult(message=_interrupted_result(tc, char_name, ti.phase))
        approval_duration_ms: int = int((time.monotonic() - approval_start) * 1000)
        if activity_id is not None:
            self._loop.loop.set_main_session_activity_phase(
                activity_id,
                MainSessionActivityPhase.waiting_tool,
                stream_id=None,
                character_name=char_name,
            )

        _skip_dispatch = False
        ctx: ToolContext | None = None
        execution: ToolExecution | None = None
        result: dict = {}
        if outcome.denied:
            result = outcome.deny_result or {"error": "Tool denied"}
            _skip_dispatch = True

        if not _skip_dispatch:
            invocation_start: float = time.monotonic()
            invocation_start_offset_ms: int = int((invocation_start - start_mono) * 1000)

            # dispatch 前再次检查中断（缩短审批返回后→分发前的竞态窗口）
            if self._loop.loop.is_interrupted():
                return PreparedToolResult(message=_interrupted_result(tc, char_name, "pending"))

            # availability scope 校验：拦截不在当前 loop scope 内的工具
            _scope = self._loop.get_tool_availability_scope()
            try:
                _tool_availability = tool_registry.get_availability(tc.name)
            except KeyError:
                logger.warning("Tool %s not registered, blocking dispatch", tc.name)
                self._tool_stats[tc.name]["errors"] += 1
                result = {"error": f"Unknown tool: {tc.name}"}
                invocation_duration_ms = 0
                end_time_offset_ms = int((time.monotonic() - start_mono) * 1000)
            else:
                if (_tool_availability & _scope) == 0:
                    logger.warning(
                        "Tool %s blocked (availability=%s, scope=%s)",
                        tc.name, _tool_availability, _scope,
                    )
                    self._tool_stats[tc.name]["errors"] += 1
                    result = {"error": f"Tool '{tc.name}' is not available in the current mode."}
                    invocation_duration_ms = 0
                    end_time_offset_ms = int((time.monotonic() - start_mono) * 1000)
                else:
                    try:
                        ctx = ToolContext(
                            loop=self._loop.loop,
                            session_id=session_id,
                            round_id=round_id,
                            stream_id=stream_id,
                            character_name=char_name,
                            llm_profile=llm_profile,
                        )
                        try:
                            if declared_tool is not None:
                                from entity.constant import TOOL_INTERNAL_ARG_KEYS
                                normalized_args.update({
                                    key: value for key, value in args.items() if key in TOOL_INTERNAL_ARG_KEYS
                                })
                                execution = ToolExecution(
                                    tool=declared_tool,
                                    arguments=normalized_args,
                                    context=ctx,
                                    tool_call_id=tc.id,
                                )
                                dispatched = await self._await_or_cancel(
                                    tool_registry.async_dispatch(execution),
                                    "dispatch",
                                )
                                if not isinstance(dispatched, ToolExecution) or dispatched.result is None:
                                    raise LifecycleFailure("Object tool dispatch did not return an execution result")
                                execution = dispatched
                                result = execution.result
                            else:
                                raise LifecycleFailure(f"Tool {tc.name!r} disappeared before dispatch")
                        except ToolInterrupted as ti:
                            # 尽力 kill 子进程（run_command / run_python 登记的 Popen）
                            try:
                                from system.application import Application
                                from system.sandbox import Sandbox
                                Application.current().get_system(Sandbox).kill_active(session_id)
                            except Exception:
                                logger.warning(
                                    "kill_active failed for session=%s", session_id, exc_info=True,
                                )
                            return PreparedToolResult(message=_interrupted_result(tc, char_name, ti.phase))
                    except ApplicationStoppingError:
                        return PreparedToolResult(message=_interrupted_result(tc, char_name, "dispatch"))
                    except BaseException as exc:
                        if requires_lifecycle_propagation(exc):
                            raise
                        if not isinstance(exc, Exception):
                            raise
                        logger.exception("Tool %s dispatch error: %s", tc.name, exc)
                        self._tool_stats[tc.name]["errors"] += 1
                        result = {
                            "error": f"Tool execution failed: {type(exc).__name__}: {exc}",
                        }
                    invocation_duration_ms = int((time.monotonic() - invocation_start) * 1000)
                    end_time_offset_ms = int((time.monotonic() - start_mono) * 1000)
        else:
            # 审批拒绝：没有实际调用
            invocation_start_offset_ms = 0
            invocation_duration_ms = 0
            end_time_offset_ms = approval_duration_ms

        result_msg = prepare_tool_result(
            result,
            tool_name=tc.name,
            application_time=application_time,
            application_time_ms=application_time_ms,
            approval_duration_ms=approval_duration_ms,
            invocation_start_offset_ms=invocation_start_offset_ms,
            invocation_duration_ms=invocation_duration_ms,
            end_time_offset_ms=end_time_offset_ms,
            session_id=session_id,
            tool_call_id=tc.id,
            character_name=char_name,
            field_injector=self._loop.get_result_field_injector(),
            execution=execution,
        )

        # 工具成功执行后，检查是否需要重置循环计数器
        # 仅在实际分发（非审批拒绝）时触发，denied 路径不重置
        if self._turn_counter is not None and not _skip_dispatch:
            _entry = tool_registry.get_tool(tc.name)
            if _entry is not None and _entry.resets_turn_counter:
                self._turn_counter.value = 0

        return result_msg