"""ToolExecutor — 统一工具调用执行器。

封装单个工具调用的完整流程：取消检查、parse error 处理、审批、
registry 分发、异常转换、前端事件推送和 UI 事件路由。

审批流程直接复用 ``component.approval.executor.execute_with_approval``。
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime
from typing import Any, Awaitable

from entity.puretype import Role, ToolCallMeta, ToolCallRequest, LLMProfile
from entity.gentype import RefWrapper
from entity.messages import ToolResultMessage
from entry.base_agent_loop import BaseAgentLoop, ToolContext, IMainSessionLoop
from entry.tool_post_dispatch import finalize_tool_result

logger = logging.getLogger(__name__)


class ToolInterrupted(Exception):
    """内部中断信号：可中断等待被 cancel_event 打断时抛出。

    携带 phase 字段（"approval" / "dispatch"），由调用方
    ``except ToolInterrupted as ti`` 捕获后用 ``ti.phase``
    构造统一的中断失败结果。
    """

    def __init__(self, phase: str) -> None:
        super().__init__(f"Tool call interrupted during {phase}")
        self.phase: str = phase


def _interrupted_result(tc: ToolCallRequest, char_name: str, phase: str) -> ToolResultMessage:
    """构造强制中断失败消息，作为未完成工具调用的占位结果。

    phase 取值：pending（入口/审批前）、approval、dispatch、unexpected（异常兜底）。
    该结果写入 History 后与 assistant 的 tool_calls 配对，保证消息序列合法。
    """
    return ToolResultMessage(
        role=Role.TOOL,
        character_name=char_name,
        tool_call_id=tc.id,
        content={
            "error": "Tool call interrupted by user",
            "_interrupted": True,
            "_interrupted_phase": phase,
        },
    )


class ToolExecutor:
    """执行单个工具调用，处理审批、分发和事件推送。

    由 IMainSessionLoop 持有，每个 tool_call 调用一次 ``execute()``。
    """

    def __init__(self, loop: IMainSessionLoop) -> None:
        self._loop = loop
        self._tool_stats: dict[str, dict[str, int]] = {}
        self._turn_counter: RefWrapper[int] | None = None

    # -- 公开 API ----------------------------------------------------------

    def get_tool_stats(self) -> dict[str, dict[str, int]]:
        return {name: dict(stats) for name, stats in self._tool_stats.items()}

    def set_turn_counter(self, counter: RefWrapper[int] | None) -> None:
        """注入或清除工具循环计数器引用。

        当计数器非 None 且执行的工具标记了 resets_turn_counter=True 时，
        execute() 会在工具成功执行后将计数器归零。
        """
        self._turn_counter = counter

    async def _await_or_cancel(self, coro: Awaitable[Any], phase: str) -> Any:
        """等待 coro 完成或中断触发。

        - 正常完成：返回 coro 结果（内部异常由 async_dispatch 等已转为错误结果）。
        - 中断触发（cancel_event 置位）：取消 coro 任务并抛 ToolInterrupted(phase)，
          由调用方捕获后转统一中断失败结果。
        """
        task = asyncio.ensure_future(coro)
        interrupt_wait = asyncio.ensure_future(self._loop.loop.cancel_event.wait())
        try:
            done, _ = await asyncio.wait(
                {task, interrupt_wait},
                return_when=asyncio.FIRST_COMPLETED,
            )
        finally:
            interrupt_wait.cancel()
        if task in done and not task.cancelled():
            try:
                return task.result()
            except Exception as exc:
                # 正常完成路径防御：handler 异常已由 async_dispatch 转为错误结果，
                # 此处仅兜底非常规异常；SystemExit/KeyboardInterrupt 放行
                return {"error": f"{type(exc).__name__}: {exc}"}
        # 中断分支：取消任务并吞掉 CancelledError
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass
        raise ToolInterrupted(phase)

    async def execute(
        self,
        tc: ToolCallRequest,
        session_id: str,
        *,
        round_id: str,
        character_name: str | None = None,
        llm_profile: LLMProfile | None = None,
    ) -> ToolResultMessage:
        """执行单个工具调用，返回 ToolResultMessage。

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
        from abstract.tools.registry import registry as tool_registry

        char_name = character_name or self._loop.current_character_agent

        # -- 记录申请时间（审批流程之前） --
        start_mono: float = time.monotonic()
        application_time_ms: int = int(time.time() * 1000)
        application_time: str = datetime.fromtimestamp(
            time.time()
        ).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]

        args = dict(tc.arguments)

        # 取消检查：中断时返回统一强制中断失败结果（保证与 assistant tool_calls 配对）
        if self._loop.loop.is_interrupted():
            return _interrupted_result(tc, char_name, "pending")

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
            await self._loop.loop.get_sink().emit_tool_result(
                session_id, tc.name, tc.id,
                json.dumps(_disgust_result, ensure_ascii=False),
                character_name=char_name,
                tool_call_meta=_meta.model_dump(),
            )
            # 统计
            if tc.name not in self._tool_stats:
                self._tool_stats[tc.name] = {"calls": 0, "errors": 0}
            self._tool_stats[tc.name]["calls"] += 1
            self._tool_stats[tc.name]["errors"] += 1
            return ToolResultMessage(
                role=Role.TOOL,
                character_name=char_name,
                tool_call_id=tc.id,
                content=_disgust_result,
            )

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
            await self._loop.loop.get_sink().emit_tool_result(
                session_id, tc.name, tc.id,
                json.dumps(_result, ensure_ascii=False),
                character_name=char_name,
                tool_call_meta=_meta.model_dump(),
            )
            return ToolResultMessage(
                role=Role.TOOL,
                character_name=char_name,
                tool_call_id=tc.id,
                content=_result,
            )

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
        _entry = tool_registry.get_entry(tc.name)
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
                await self._loop.loop.get_sink().emit_tool_result(
                    session_id, tc.name, tc.id,
                    json.dumps(_not_loaded_result, ensure_ascii=False),
                    character_name=char_name,
                    tool_call_meta=_meta.model_dump(),
                )
                self._tool_stats[tc.name]["errors"] += 1
                return ToolResultMessage(
                    role=Role.TOOL,
                    character_name=char_name,
                    tool_call_id=tc.id,
                    content=_not_loaded_result,
                )

        # 审批流程
        _hooks_ctx = self._loop.loop.get_hooks_context(session_id)

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
        except ToolInterrupted as ti:
            # 取消审批 task 触发 request_approval 的 CancelledError 分支，自行清理 pending confirms
            return _interrupted_result(tc, char_name, ti.phase)
        approval_duration_ms: int = int((time.monotonic() - approval_start) * 1000)

        _skip_dispatch = False
        result: dict | str = {}
        if outcome.denied:
            result = outcome.deny_result or {"error": "Tool denied"}
            _skip_dispatch = True

        if not _skip_dispatch:
            invocation_start: float = time.monotonic()
            invocation_start_offset_ms: int = int((invocation_start - start_mono) * 1000)

            # dispatch 前再次检查中断（缩短审批返回后→分发前的竞态窗口）
            if self._loop.loop.is_interrupted():
                return _interrupted_result(tc, char_name, "pending")

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
                            character_name=char_name,
                            llm_profile=llm_profile,
                        )
                        try:
                            result = await self._await_or_cancel(
                                tool_registry.async_dispatch(
                                    tc.name, args, context=ctx,
                                ),
                                "dispatch",
                            )
                        except ToolInterrupted as ti:
                            # 尽力 kill 子进程（run_command / run_python 登记的 Popen）
                            try:
                                from system.application import Application
                                Application.current().sandbox.kill_active(session_id)
                            except Exception:
                                logger.warning(
                                    "kill_active failed for session=%s", session_id, exc_info=True,
                                )
                            return _interrupted_result(tc, char_name, ti.phase)
                    except Exception as exc:
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

        try:
            result_msg = await finalize_tool_result(
                result,
                tool_name=tc.name,
                application_time=application_time,
                application_time_ms=application_time_ms,
                approval_duration_ms=approval_duration_ms,
                invocation_start_offset_ms=invocation_start_offset_ms,
                invocation_duration_ms=invocation_duration_ms,
                end_time_offset_ms=end_time_offset_ms,
                sink=self._loop.loop.get_sink(),
                session_id=session_id,
                tool_call_id=tc.id,
                character_name=char_name,
                field_injector=self._loop.get_result_field_injector(),
            )
        except BaseException:
            # finalize（content 转换/事件推送）异常时以中断结果兜底，保证 execute 不向调用方抛异常
            logger.exception(
                "finalize_tool_result failed | session=%s tool=%s", session_id, tc.name,
            )
            return _interrupted_result(tc, char_name, "unexpected")

        # 工具成功执行后，检查是否需要重置循环计数器
        # 仅在实际分发（非审批拒绝）时触发，denied 路径不重置
        if self._turn_counter is not None and not _skip_dispatch:
            _entry = tool_registry.get_entry(tc.name)
            if _entry is not None and _entry.resets_turn_counter:
                self._turn_counter.value = 0

        return result_msg