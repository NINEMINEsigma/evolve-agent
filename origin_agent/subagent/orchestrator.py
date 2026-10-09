"""子 Agent 编排器 — 按主会话管理子 Agent 生命周期。

职责：
- 每个主会话拥有独立的子 Agent 上下文
- 管理子 Agent 启动、运行和停止生命周期
- 事件驱动 waiter（结果收集 + 消息注入，由 _start_subagent/_start_taskagent 启动）
- 工具操作代理（chat / approve / stop）
- 优雅关闭
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from pathlib import Path
from typing import Any, Coroutine

from entity.constant import (
    MAX_TOOL_TURNS,
    SYSTEM_CHARACTER_NAME,
    USER_CHARACTER_NAME,
    History_Version as __History_Version__,
    SUBAGENT_TEMP_DIR_NAME,
    SUBAGENT_HISTORY_SUFFIX,
)
from entity.messages import CharacterMessage, CharacterConversationMessage, ToolResultMessage
from entity.puretype import (
    Role,
    ToolAvailability,
    ToolDangerLevel,
    LLMProfile,
    CharacterProfile,
    SubAgentStatus,
    SubAgentFeedback,
    SubAgentLaunchResult,
    SubAgentChatResult,
    SubAgentApprovalResult,
    SubAgentStopResult,
    SubAgentSnapshot,
    SubAgentSnapshotResponse,
    SubAgentUpdate,
    QueuedMessage,
)
from framework import AsyncSystem
from component.approval.system import ApprovalSystem
from abstract.tools.registry import ToolRegistry
from abstract.tools.ui_event_router import UIEventRouter
from component.cron_router import CronRouter
from system.agentspace import AgentspaceService
from system.sandbox import Sandbox
from system.llm_profile_store import LLMProfileStore
from system.session_metadata import SessionMetadataService
from system.shell_manager import ShellManager
from system.modality_capability import ModalityCapabilitySystem
from gateway.session_manager import SessionManager
from system.runtime import RuntimeSystem
from system.templates import read_template
from entry.agent_sink import FrontendSink
from entry.base_agent_loop import IMainSessionLoop
from entity.puretype import SubAgentFeedbackDelivery

from .context import build_subagent_context, build_taskagent_context
from .loop import SUB_MESSAGE_SEPARATOR, SubAgentLoop, format_user_message
from .taskloop import TaskAgentLoop

logger = logging.getLogger(__name__)


def _parse_tool_arguments(arguments: str) -> dict[str, Any]:
    """解析 History 中的工具参数；非法 JSON 或非对象参数直接抛出异常。"""
    parsed = json.loads(arguments)
    if not isinstance(parsed, dict):
        raise ValueError("Tool arguments must be a JSON object")
    return parsed


class _OrchestratorContext:
    """单个主会话的子 Agent 上下文。"""

    def __init__(self, parent_session_id: str, session_manager: SessionManager) -> None:
        self._parent_session_id: str = parent_session_id
        self._session_manager = session_manager
        self._active: dict[str, SubAgentLoop] = {}
        self._active_task: dict[str, asyncio.Task] = {}
        self._subagent_names: dict[str, str] = {}  # session_id -> registry_name
        self._starting: dict[str, str] = {}  # session_id -> registry_name, startup registration
        self._startup_tasks: dict[str, asyncio.Task] = {}
        self._waiter_tasks: dict[str, asyncio.Task] = {}  # SP-5 D4：per-subagent event waiter
        self._background_tasks: set[asyncio.Task[Any]] = set()
        self._interrupted: bool = False
        self._shutting_down: bool = False

    def _create_background(self, coro: Coroutine[Any, Any, Any], *, name: str) -> asyncio.Task[Any]:
        if self._shutting_down:
            coro.close()
            raise ApplicationStoppingError("Sub-agent context is shutting down")
        task = asyncio.create_task(coro, name=name)
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)
        return task

    # ── 启动 ────────────────────────────────────────────────────────

    async def launch(
        self,
        name: str,
        profile: CharacterProfile,
        temperature: float,
        initial_prompt: str,
        user_name: str,
        message_type: str,
        parent_session_id: str,
        history_path: str | None = None,
    ) -> SubAgentLaunchResult:
        """启动一个子 Agent 会话。"""
        if self._shutting_down:
            return SubAgentLaunchResult(
                success=False,
                error="Sub-agent context is shutting down.",
            )
        # 同一主会话下同一 subagent 只能有一个活跃或启动中实例。
        for active_sid, active_name in self._subagent_names.items():
            if active_name == name:
                sub = self._active.get(active_sid)
                if sub is not None and not sub.completed and not sub.terminated:
                    return SubAgentLaunchResult(
                        success=False,
                        error=f"Sub-agent '{name}' is already active in this parent session.",
                    )
        if name in self._starting.values():
            return SubAgentLaunchResult(
                success=False,
                error=f"Sub-agent '{name}' is still starting in this parent session.",
            )
        session_id = f"{parent_session_id}_{uuid.uuid4().hex[:12]}"

        self._starting[session_id] = name
        try:
            await self._run_startup(
                session_id,
                self._start_subagent(
                    session_id, name, profile, temperature,
                    initial_prompt, user_name, message_type, history_path,
                ),
                task_name=f"subagent-start-{session_id[:16]}",
            )
        except Exception as exc:
            error = f"Failed to start sub-agent '{name}': {type(exc).__name__}: {exc}"
            logger.exception("Subagent startup failed | session=%s name=%s", session_id, name)
            await self._notify_start_failure(session_id, name, error)
            return SubAgentLaunchResult(
                success=False,
                session_id=session_id,
                error=error,
            )
        finally:
            self._starting.pop(session_id, None)

        return SubAgentLaunchResult(
            success=True,
            session_id=session_id,
        )

    # ── taskagent 启动/停止 ─────────────────────────────────────────

    async def launch_taskagent(
        self,
        parent_session_id: str,
        prompt: str,
        profile: LLMProfile,
    ) -> SubAgentLaunchResult:
        """使用调用时活动 Profile快照启动一次性临时Agent。"""
        if self._shutting_down:
            return SubAgentLaunchResult(
                success=False,
                error="Sub-agent context is shutting down.",
            )
        session_id = f"{parent_session_id}_{uuid.uuid4().hex[:12]}"

        self._starting[session_id] = "taskagent"
        try:
            await self._run_startup(
                session_id,
                self._start_taskagent(session_id, prompt, profile),
                task_name=f"taskagent-start-{session_id[:16]}",
            )
        except Exception as exc:
            error = f"Failed to start task-agent: {type(exc).__name__}: {exc}"
            logger.exception("Taskagent startup failed | session=%s", session_id)
            await self._notify_start_failure(session_id, "taskagent", error)
            return SubAgentLaunchResult(
                success=False,
                session_id=session_id,
                error=error,
            )
        finally:
            self._starting.pop(session_id, None)

        return SubAgentLaunchResult(
            success=True,
            session_id=session_id,
        )

    async def _start_taskagent(
        self,
        session_id: str,
        prompt: str,
        profile: LLMProfile,
    ) -> None:
        """创建 TaskAgentLoop 并以 asyncio.Task 启动。"""
        parent_ctx = self._require_agent_loop().loop.app.get_system(RuntimeSystem).context
        ctx = await build_taskagent_context(profile, parent_ctx)

        tools = self._build_task_tool_set()

        def _push_msg(event: dict[str, Any]) -> None:
            self._create_background(self._push_subagent_ws(
                session_id, "taskagent", event,
                interactive=False,
            ), name=f"subagent-ws-{session_id[:16]}")

        loop = TaskAgentLoop(
            ctx, session_id, tools, MAX_TOOL_TURNS,
            on_message=_push_msg,
            parent_session_id=self._parent_session_id,
            parent_character_agent=self._require_agent_loop().current_character_agent,
            name="taskagent",
        )
        # TODO: 后续可按任务类型或调用方声明为临时Agent预加载工具集，
        # 减少先调用 LoadToolset 再执行任务所占用的工具循环轮次；
        # 预加载不得绕过“已加载工具集 ∩ TASKAGENT ∩ safe”权限过滤。
        self._active[session_id] = loop
        self._subagent_names[session_id] = "taskagent"
        try:
            # 推送 WS 通知前端面板
            await self._push_subagent_ws(
                session_id,
                "taskagent",
                {"role": "status", "content": "started"},
                status_override="running",
                interactive=False,
            )

            # 推送 initial_prompt 到前端面板
            wrapped_initial = format_user_message(
                self._require_agent_loop().current_character_agent, "direct", prompt,
            )
            await self._push_subagent_ws(
                session_id,
                "taskagent",
                {"role": "user", "content": wrapped_initial,
                 "character_name": self._require_agent_loop().current_character_agent},
                interactive=False,
            )

            task = asyncio.create_task(
                loop.run(prompt, self._require_agent_loop().current_character_agent, "direct"),
                name=f"taskagent-{session_id[:16]}",
            )
            self._active_task[session_id] = task
            # SP-5 D4：启动 per-subagent 事件驱动 waiter
            self._waiter_tasks[session_id] = asyncio.create_task(
                self._subagent_waiter(session_id, loop),
                name=f"subagent-waiter-{session_id[:16]}",
            )
        except BaseException:
            self._rollback_startup(session_id, loop)
            raise

        logger.info(
            "Taskagent started | parent=%s session=%s model=%s tools=%d",
            self._parent_session_id, session_id, ctx.model, len(tools),
        )

    async def stop_taskagent(self, session_id: str) -> SubAgentStopResult:
        """强制停止 taskagent — 不保存历史。"""
        if session_id in self._starting:
            return SubAgentStopResult(
                success=False,
                session_id=session_id,
                error="Task-agent is still starting. Please wait for startup to finish.",
            )
        sub = self._active.get(session_id)
        if sub is None:
            return SubAgentStopResult(
                success=False,
                session_id=session_id,
                error="Task-agent not found.",
            )

        if sub.completed:
            return SubAgentStopResult(
                success=False,
                session_id=session_id,
                error="Task-agent already completed.",
            )

        sub.freeze_inputs()
        sub.stop()
        task = self._active_task.get(session_id)
        if task is not None and not task.done():
            await task
        await sub.flush_pending_inputs(persist=False)

        self._active.pop(session_id, None)
        self._active_task.pop(session_id, None)
        self._subagent_names.pop(session_id, None)
        waiter = self._waiter_tasks.pop(session_id, None)
        if waiter is not None and not waiter.done():
            waiter.cancel()
            await asyncio.gather(waiter, return_exceptions=True)

        logger.info("Taskagent stopped | session=%s", session_id)

        # 推送 terminated 状态到前端
        await self._push_subagent_ws(
            session_id,
            "taskagent",
            {"role": "terminated", "content": "task-agent stopped"},
            status_override="terminated",
            interactive=False,
        )

        return SubAgentStopResult(
            success=True,
            session_id=session_id,
        )

    # ── 交互 ────────────────────────────────────────────────────────

    def _drain_outbox(self, sub: SubAgentLoop) -> list[str]:
        """将反馈作为显式交付返回给调用方并确认一次。"""
        items = sub.get_pending_feedback()
        if not items:
            return []
        sub.mark_feedback_delivered([item.sequence for item in items])
        return [item.text for item in items]

    def enqueue_user_input(self, session_id: str, message: QueuedMessage) -> int:
        sub = self._active.get(session_id)
        if sub is None:
            raise LookupError(f"Sub-agent does not exist: {session_id}")
        if sub.completed or sub.terminated or sub.inbox.frozen:
            raise ApplicationStoppingError(f"Sub-agent no longer accepts input: {session_id}")
        content = message.content if isinstance(message.content, str) else str(message.content)
        from entry.base_agent_loop import UserMessage
        return sub.enqueue_inbox_message(
            UserMessage(
                content=content,
                character_name=message.character_name or USER_CHARACTER_NAME,
            ),
            from_parent=message.source != "user",
        )

    async def chat_user_direct(self, session_id: str, message: str, co_recipients: list[str] | None = None) -> SubAgentChatResult:
        """最终用户直接向子会话发送消息。"""
        if session_id in self._starting:
            return SubAgentChatResult(
                success=False,
                session_id=session_id,
                error="Sub-agent is still starting. Please wait for startup to finish.",
            )
        sub = self._active.get(session_id)
        if sub is None:
            return SubAgentChatResult(
                success=False,
                session_id=session_id,
                error="Sub-agent not found (may have been stopped or completed).",
            )
        sub.inject_parent_message(
            message, "User", "user_direct", co_recipients, character_name=USER_CHARACTER_NAME
        )
        wrapped = format_user_message("User", "user_direct", message, co_recipients)
        await self._push_subagent_ws(
            session_id,
            self._subagent_names.get(session_id, ""),
            {"role": "user", "content": wrapped, "character_name": USER_CHARACTER_NAME},
        )
        return SubAgentChatResult(success=True, session_id=session_id)

    async def chat(
        self,
        session_id: str,
        message: str,
        user_name: str,
        message_type: str,
        co_recipients: list[str] | None = None,
    ) -> SubAgentChatResult:
        """父 Agent 向子 Agent 发送消息。"""
        if session_id in self._starting:
            return SubAgentChatResult(
                success=False,
                session_id=session_id,
                error="Sub-agent is still starting. Please wait for startup to finish.",
            )
        sub = self._active.get(session_id)
        if sub is None:
            return SubAgentChatResult(
                success=False,
                session_id=session_id,
                error="Sub-agent not found (may have been stopped or completed).",
            )
        # 硬拦截：本轮响应尚未完成时禁止 chat（防止父 Agent 疯狂催促）
        if sub.round_active:
            return SubAgentChatResult(
                success=False,
                session_id=session_id,
                error="Sub-agent is still generating its current response. Wait for [subagent-result] before calling chat_subagent.",
            )
        # 先收取子 Agent 的反馈；如果还有未送达的反馈，让父 Agent 先查看，不要急于发新消息
        outbox = self._drain_outbox(sub)
        if outbox:
            return SubAgentChatResult(
                success=False,
                session_id=session_id,
                feedback=outbox,
                note="Sub-agent has already produced feedback that you have not yet received. Please review the feedback first, then decide whether and how to reply via chat_subagent.",
            )
        # 没有未送达反馈，正常发送
        character_name = self._require_agent_loop().current_character_agent
        sub.inject_parent_message(
            message, user_name, message_type, co_recipients, character_name=character_name
        )
        # 推送父→子消息到前端子会话面板
        wrapped = format_user_message(user_name, message_type, message, co_recipients)
        await self._push_subagent_ws(
            session_id,
            self._subagent_names.get(session_id, ""),
            {"role": "user", "content": wrapped, "character_name": character_name},
        )
        return SubAgentChatResult(success=True, session_id=session_id)

    async def approve(self, session_id: str, decisions: list[dict[str, Any]]) -> SubAgentApprovalResult:
        """审批子 Agent 的工具调用。"""
        if session_id in self._starting:
            return SubAgentApprovalResult(
                success=False,
                session_id=session_id,
                error="Sub-agent is still starting. Please wait for startup to finish.",
            )
        sub = self._active.get(session_id)
        if sub is None:
            return SubAgentApprovalResult(
                success=False,
                session_id=session_id,
                error="Sub-agent not found (may have been stopped or completed).",
            )
        results = sub.approve_tools(decisions)
        # 审批后顺手收集一次 outbox
        outbox = self._drain_outbox(sub)
        return SubAgentApprovalResult(
            success=True,
            session_id=session_id,
            processed=len(results),
            results=results,
            feedback=outbox,
        )

    async def stop(self, session_id: str) -> SubAgentStopResult:
        """先停止并等待子Agent任务，再刷新Inbox并保存普通子Agent历史。"""
        if session_id in self._starting:
            return SubAgentStopResult(
                success=False,
                session_id=session_id,
                error="Sub-agent is still starting. Please wait for startup to finish.",
            )
        sub = self._active.get(session_id)
        if sub is None:
            return SubAgentStopResult(success=False, session_id=session_id, error="Sub-agent not found.")
        if sub.completed:
            return SubAgentStopResult(success=False, session_id=session_id, error="Sub-agent has already completed.")

        name = self._subagent_names.get(session_id, "")
        session_path = self._history_path(session_id)
        history_logical_path = f"ws:{SUBAGENT_TEMP_DIR_NAME}/{session_id}{SUBAGENT_HISTORY_SUFFIX}"
        sub.freeze_inputs()
        sub.stop()
        task = self._active_task.get(session_id)
        if task is not None and not task.done():
            await task
        await sub.flush_pending_inputs(persist=True, history_path=session_path)

        self._active.pop(session_id, None)
        self._active_task.pop(session_id, None)
        waiter = self._waiter_tasks.pop(session_id, None)
        if waiter is not None and not waiter.done():
            waiter.cancel()
            await asyncio.gather(waiter, return_exceptions=True)
        self._subagent_names.pop(session_id, None)

        logger.info("Subagent stopped | session=%s path=%s", session_id, history_logical_path)
        await self._push_subagent_ws(
            session_id, name,
            {"role": "terminated", "content": "sub-agent stopped"},
            status_override="terminated",
        )
        return SubAgentStopResult(
            success=True,
            session_id=session_id,
            session_path=history_logical_path,
        )

    # ── 生命周期 ────────────────────────────────────────────────────

    def interrupt(self) -> None:
        self._interrupted = True

    def resume(self) -> None:
        self._interrupted = False

    def get_snapshot(self) -> SubAgentSnapshotResponse:
        # TODO: msg.content没有多模态
        """返回所有活跃子会话的快照（供前端刷新时拉取）。"""
        snapshots: dict[str, SubAgentSnapshot] = {}
        for session_id, sub in self._active.items():
            feedback: list[SubAgentFeedback] = []
            for msg in sub.history.iter_messages():
                if msg.role == Role.SYSTEM:
                    continue
                character_name = msg.character_name if isinstance(msg, CharacterMessage) else None
                if msg.role == Role.USER:
                    feedback.append(SubAgentFeedback(
                        role="user",
                        content=str(msg.content),
                        character_name=character_name or USER_CHARACTER_NAME,
                    ))
                elif msg.role == Role.ASSISTANT:
                    content = str(msg.content)
                    reasoning = msg.reasoning if isinstance(msg, CharacterConversationMessage) else None
                    if content:
                        feedback.append(SubAgentFeedback(
                            role="assistant",
                            content=content,
                            character_name=character_name,
                            reasoning=str(reasoning) if reasoning else None,
                        ))
                    elif reasoning:
                        feedback.append(SubAgentFeedback(
                            role="reasoning",
                            reasoning=str(reasoning),
                            character_name=character_name,
                        ))
                    if isinstance(msg, CharacterConversationMessage) and msg.tool_calls:
                        for tc in msg.tool_calls:
                            feedback.append(SubAgentFeedback(
                                role="tool_call",
                                tool_call_id=tc.id,
                                tool_name=tc.function.name,
                                tool_args=_parse_tool_arguments(tc.function.arguments),
                                character_name=character_name,
                            ))
                elif msg.role == Role.TOOL and isinstance(msg, ToolResultMessage):
                    feedback.append(SubAgentFeedback(
                        role="tool_result",
                        tool_call_id=msg.tool_call_id,
                        content=str(msg.content),
                        character_name=character_name,
                    ))
            status = (
                SubAgentStatus.completed if sub.completed
                else SubAgentStatus.terminated if sub.terminated
                else SubAgentStatus.running
            )
            snapshots[session_id] = SubAgentSnapshot(
                session_id=session_id,
                name=self._subagent_names.get(session_id, ""),
                status=status,
                feedback=feedback,
                pending_approvals=sub.pending_approvals_info,
                interactive=not isinstance(sub, TaskAgentLoop),
            )
        return SubAgentSnapshotResponse(
            session_id=self._parent_session_id,
            subagents=snapshots,
        )

    def freeze_inputs(self) -> None:
        self._shutting_down = True
        for sub in self._active.values():
            sub.freeze_inputs()

    async def stop_rounds(self) -> None:
        """先请求所有子Agent收尾，再等待其真实运行任务结束。"""
        tasks: list[asyncio.Task[Any]] = []
        for sub in tuple(self._active.values()):
            sub.stop()
        for task in self._active_task.values():
            if not task.done():
                tasks.append(task)
        if tasks:
            await asyncio.gather(*tasks)
        waiters = tuple(self._waiter_tasks.values())
        for waiter in waiters:
            if not waiter.done():
                waiter.cancel()
        if waiters:
            await asyncio.gather(*waiters, return_exceptions=True)
        self._waiter_tasks.clear()

    async def flush_inputs(self) -> None:
        """运行任务完全结束后，提交普通子Agent Inbox并保存历史。"""
        for session_id, sub in tuple(self._active.items()):
            await sub.flush_pending_inputs(
                persist=not isinstance(sub, TaskAgentLoop),
                history_path=None if isinstance(sub, TaskAgentLoop) else self._history_path(session_id),
            )

    async def transfer_shutdown_feedback(self) -> None:
        """把已生成但尚未交接的反馈一次性交给父会话关闭批次。"""
        items: list[SubAgentFeedbackDelivery] = []
        for sub in self._active.values():
            items.extend(sub.get_pending_feedback())
        if items:
            self._session_manager.accept_shutdown_feedback(self._parent_session_id, items)

    async def shutdown(self) -> None:
        """冻结输入、等待任务、刷新历史并完成反馈交接。"""
        self.freeze_inputs()

        startup_tasks = tuple(self._startup_tasks.values())
        for task in startup_tasks:
            if not task.done():
                task.cancel()
        if startup_tasks:
            await asyncio.gather(*startup_tasks, return_exceptions=True)
        self._starting.clear()

        await self.stop_rounds()
        await self.flush_inputs()
        await self.transfer_shutdown_feedback()

        for task in tuple(self._background_tasks):
            if not task.done():
                task.cancel()
        if self._background_tasks:
            await asyncio.gather(*tuple(self._background_tasks), return_exceptions=True)
        self._background_tasks.clear()
        logger.info("Subagent context shutdown | parent=%s active=%d", self._parent_session_id, len(self._active))

    # ── 内部 ────────────────────────────────────────────────────────
    async def _push_subagent_ws(
        self,
        session_id: str,
        name: str,
        event: SubAgentFeedback | dict[str, Any] | None = None,
        *,
        status_override: str | None = None,
        interactive: bool | None = None,
    ) -> None:
        """推送一条结构化事件到前端面板。

        interactive 为 None 时自动推断：TaskAgentLoop → False，其他 → True。
        """
        try:
            from gateway.server import push_subagent_update
            sub = self._active.get(session_id)
            if interactive is None:
                interactive = not isinstance(sub, TaskAgentLoop)
            if status_override is not None:
                status = status_override
            elif sub is None:
                status = "terminated"
            elif sub.completed:
                status = "completed"
            elif sub.terminated:
                status = "terminated"
            else:
                status = "running"
            feedback = []
            if event is not None:
                feedback.append(
                    event if isinstance(event, SubAgentFeedback)
                    else SubAgentFeedback.model_validate(event)
                )
            pending = sub.pending_approvals_info if sub is not None else []
            update = SubAgentUpdate(
                session_id=session_id,
                name=name,
                status=SubAgentStatus(status),
                feedback=feedback,
                pending_approvals=pending,
                removed=sub is None,
                interactive=bool(interactive),
            )
            await push_subagent_update(
                parent_session_id=self._parent_session_id,
                update=update,
            )
        except Exception as exc:
            logger.warning("WS push for subagent %s failed: %s", session_id, exc, exc_info=True)

    async def _run_startup(
        self,
        session_id: str,
        startup: Coroutine[Any, Any, None],
        *,
        task_name: str,
    ) -> None:
        """在可取消的独立任务中运行一次启动流程。"""
        task = asyncio.create_task(startup, name=task_name)
        self._startup_tasks[session_id] = task
        try:
            await task
        finally:
            if self._startup_tasks.get(session_id) is task:
                self._startup_tasks.pop(session_id, None)

    def _rollback_startup(self, session_id: str, loop: SubAgentLoop) -> None:
        """回滚已经提交但尚未完成的子Agent启动。"""
        if self._active.get(session_id) is loop:
            self._active.pop(session_id, None)
        if self._subagent_names.get(session_id) == loop.current_character_agent:
            self._subagent_names.pop(session_id, None)

        task = self._active_task.pop(session_id, None)
        if task is not None and not task.done():
            task.cancel()
        waiter = self._waiter_tasks.pop(session_id, None)
        if waiter is not None and not waiter.done():
            waiter.cancel()
        loop.stop()

    async def _notify_start_failure(
        self,
        session_id: str,
        name: str,
        error: str,
    ) -> None:
        """向前端报告启动失败。"""
        await self._push_subagent_ws(
            session_id,
            name,
            {"role": "error", "content": error},
            status_override="terminated",
        )

    async def _start_subagent(
        self,
        session_id: str,
        name: str,
        profile: CharacterProfile,
        temperature: float,
        initial_prompt: str,
        user_name: str,
        message_type: str,
        history_path: str | None = None,
    ) -> None:
        """创建 SubAgentLoop 并以 asyncio.Task 启动。

        历史文件与前端回放事件先在未提交状态中准备；只有全部准备成功后，
        才将实例登记为 active。登记后若启动阶段失败，则统一回滚运行态对象。
        """
        parent_ctx = self._require_agent_loop().loop.app.get_system(RuntimeSystem).context
        ctx = await build_subagent_context(profile, temperature, parent_ctx)
        tools = self._build_tool_set()

        def _push_msg(event: dict[str, Any]) -> None:
            self._create_background(self._push_subagent_ws(
                session_id, name, event,
            ), name=f"subagent-ws-{session_id[:16]}")

        loop = SubAgentLoop(
            ctx, session_id, tools, MAX_TOOL_TURNS,
            on_message=_push_msg,
            parent_session_id=self._parent_session_id,
            parent_character_agent=self._require_agent_loop().current_character_agent,
            name=name,
        )

        history_events: list[dict[str, Any]] = []
        if history_path:
            from easysave import load
            from entity.typeref import make_config
            from entity.messages import History, CharacterConversationMessage, ToolResultMessage

            path = Path(history_path)
            if not path.exists():
                raise FileNotFoundError(f"History file not found: {history_path}")

            loaded_history = load(
                __History_Version__,
                make_config(path),
                History,
                ignore_missing_fields=True,
            )
            if not isinstance(loaded_history, History):
                raise TypeError(
                    f"Loaded subagent history must be History, got {type(loaded_history).__name__}"
                )
            loaded_history.remove_unpaired_tool_calls()
            loop.load_history(loaded_history)

            for msg in loop.history.iter_messages():
                if msg.role == Role.USER:
                    history_events.append({
                        "role": "user",
                        "content": str(msg.content),
                    })
                elif msg.role == Role.ASSISTANT:
                    content = str(msg.content)
                    if content:
                        history_events.append({
                            "role": "assistant",
                            "content": content,
                        })
                    if isinstance(msg, CharacterConversationMessage) and msg.tool_calls:
                        for tc in msg.tool_calls:
                            history_events.append({
                                "role": "tool_call",
                                "tool_call_id": tc.id,
                                "tool_name": tc.function.name,
                                "tool_args": _parse_tool_arguments(tc.function.arguments),
                            })
                elif msg.role == Role.TOOL and isinstance(msg, ToolResultMessage):
                    history_events.append({
                        "role": "tool_result",
                        "tool_call_id": msg.tool_call_id,
                        "content": str(msg.content),
                    })
            logger.info(
                "Subagent history loaded | session=%s entries=%d",
                session_id, loop.history.count,
            )

        self._active[session_id] = loop
        self._subagent_names[session_id] = name
        try:
            # 先建立 running 状态，再回放历史，避免前端把历史事件判定为 removed。
            await self._push_subagent_ws(
                session_id,
                name,
                {"role": "status", "content": "started"},
                status_override="running",
            )
            for event in history_events:
                await self._push_subagent_ws(session_id, name, event)

            wrapped_initial = format_user_message(user_name, message_type, initial_prompt)
            initial_character_name = (
                USER_CHARACTER_NAME
                if message_type == "user_direct"
                else self._require_agent_loop().current_character_agent
            )
            await self._push_subagent_ws(
                session_id,
                name,
                {
                    "role": "user",
                    "content": wrapped_initial,
                    "character_name": initial_character_name,
                },
            )

            task = asyncio.create_task(
                loop.run(initial_prompt, user_name, message_type),
                name=f"subagent-{session_id[:16]}",
            )
            self._active_task[session_id] = task
            # SP-5 D4：启动 per-subagent 事件驱动 waiter
            self._waiter_tasks[session_id] = asyncio.create_task(
                self._subagent_waiter(session_id, loop),
                name=f"subagent-waiter-{session_id[:16]}",
            )
        except BaseException:
            self._rollback_startup(session_id, loop)
            raise

        logger.info(
            "Subagent started | parent=%s session=%s model=%s tools=%d",
            self._parent_session_id, session_id, ctx.model, len(tools),
        )

    def _build_tool_set(self) -> list[dict[str, Any]]:
        """构建子 Agent 的工具集 — 仅包含 availability 包含 SUBAGENT 或 EVERY 的工具。"""
        from system.application import Application
        from abstract.tools.registry import ToolRegistry
        tool_registry = Application.current().get_system(ToolRegistry)
        return tool_registry.get_definitions_for_availability(ToolAvailability.SUBAGENT)

    def _build_task_tool_set(self) -> list[dict[str, Any]]:
        """构建 taskagent 工具集 — 仅 TASKAGENT 作用域 + safe 等级。

        复用 get_definitions_for_availability 获取 OpenAI 包装格式的 schema，
        然后按 danger_level 过滤为 safe。
        """
        from system.application import Application
        from abstract.tools.registry import ToolRegistry
        tool_registry = Application.current().get_system(ToolRegistry)
        all_defs: list[dict] = tool_registry.get_definitions_for_availability(
            ToolAvailability.TASKAGENT,
        )
        result: list[dict] = []
        for schema in all_defs:
            func: dict = schema.get("function") or {}
            name: str = func.get("name", "")
            entry = tool_registry.get_entry(name)
            if entry is not None and entry.danger_level == ToolDangerLevel.safe:
                result.append(schema)
        return result

    def _get_agent_loop(self) -> IMainSessionLoop | None:
        """只从SessionManager取得当前仍存在的真实父会话Loop。"""
        return self._session_manager.get_loop(self._parent_session_id)

    def _require_agent_loop(self) -> IMainSessionLoop:
        loop = self._get_agent_loop()
        if loop is None:
            raise LookupError(
                f"Parent session does not exist: {self._parent_session_id}"
            )
        return loop

    # ── SP-5 D4：事件驱动子→主投递 ──────────────────────────────────

    async def _subagent_waiter(self, session_id: str, sub: SubAgentLoop) -> None:
        """per-subagent 事件驱动 waiter：outbox/pending 变化时即时投递父队列。

        R1 修复：循环头 while True，body 内 flush 先于 break-check——
        taskagent 正常完成时 outbox.append→completed 之间无 await，waiter 唤醒
        时 completed=True，若 break-check 在 flush 之前则最终 outbox 永久丢失。
        """
        try:
            while True:
                await sub.feedback_event.wait()
                sub.feedback_event.clear()
                if self._shutting_down:
                    break
                # 正常运行期间才把反馈投递到父队列；关闭阶段由专用交接处理。
                await self._flush_subagent_message(session_id, sub)
                if sub.completed or sub.terminated:
                    if isinstance(sub, TaskAgentLoop) and sub.completed:
                        await sub.flush_pending_inputs(persist=False)
                        self._cleanup_taskagent(session_id)
                    self._waiter_tasks.pop(session_id, None)
                    break
        except asyncio.CancelledError:
            raise

    async def _flush_subagent_message(self, session_id: str, sub: SubAgentLoop) -> None:
        """收集单个子 Agent 的 outbox + pending 快照，格式化为 [subagent-result] 并 push 父队列。"""
        feedback = sub.get_pending_feedback()
        pending = sub.pending_approvals_info
        if not feedback and not pending:
            return
        parts: list[str] = []
        parts.append(f"session_id: {session_id}")
        if feedback:
            merged = SUB_MESSAGE_SEPARATOR.join(item.text for item in feedback)
            parts.append(f"feedback:\n  {merged}")
        if pending:
            parts.append("pending_approvals:")
            for p in pending:
                parts.append(f"  - tool_call_id: {p.tool_call_id}")
                parts.append(f"    tool_name: {p.tool_name}")
                parts.append(f"    arguments: {json.dumps(p.arguments, ensure_ascii=False)}")
        full_message = read_template("subagent/result_message.txt") + "\n\n" + "\n".join(parts)
        loop = self._get_agent_loop()
        if loop is None or loop.loop.message_queue is None:
            logger.warning("Cannot flush subagent message: parent queue unavailable | session=%s", session_id)
            return
        loop.loop.message_queue.push(
            full_message, character_name=SYSTEM_CHARACTER_NAME, source="subagent",
        )
        if feedback:
            sub.mark_feedback_delivered([item.sequence for item in feedback])
        logger.debug("Subagent result pushed to parent queue | parent=%s session=%s", self._parent_session_id, session_id)

    def _cleanup_taskagent(self, session_id: str) -> None:
        """清理已完成的 taskagent。"""
        self._active.pop(session_id, None)
        task = self._active_task.pop(session_id, None)
        if task and not task.done():
            task.cancel()
        self._subagent_names.pop(session_id, None)
        logger.info("Taskagent cleaned up | session=%s", session_id)

    @staticmethod
    def _history_path(session_id: str) -> Path:
        """普通子Agent历史的临时 easysave 路径。"""
        from system.application import Application
        ctx = Application.current().get_system(RuntimeSystem).context
        directory = ctx.agentspace / SUBAGENT_TEMP_DIR_NAME
        directory.mkdir(parents=True, exist_ok=True)
        return directory / f"{session_id}{SUBAGENT_HISTORY_SUFFIX}"


class SubAgentOrchestrator(AsyncSystem):
    """按主会话管理多个子Agent上下文，并拥有其全部后台任务。"""

    def __init__(self) -> None:
        super().__init__(dependencies=(
            RuntimeSystem, SessionManager, ApprovalSystem, FrontendSink,
            ToolRegistry, UIEventRouter, CronRouter, AgentspaceService,
            Sandbox, LLMProfileStore, ModalityCapabilitySystem,
        ))
        self._runtime: RuntimeSystem | None = None
        self._session_manager: SessionManager | None = None
        self._contexts: dict[str, _OrchestratorContext] = {}
        self._background_tasks: set[asyncio.Task[Any]] = set()
        self._frozen = False

    async def virtual_awake(self) -> None:
        self._runtime = self.get_system(RuntimeSystem)
        self._session_manager = self.get_system(SessionManager)

    async def virtual_shotdown(self) -> None:
        await self.shutdown_all()
        if self._background_tasks:
            await asyncio.gather(*tuple(self._background_tasks))
        self._runtime = None
        self._session_manager = None

    @property
    def runtime(self) -> RuntimeSystem:
        if self._runtime is None:
            raise LifecycleFailure("SubAgentOrchestrator has not been awakened")
        return self._runtime

    @property
    def session_manager(self) -> SessionManager:
        if self._session_manager is None:
            raise LifecycleFailure("SubAgentOrchestrator has not been awakened")
        return self._session_manager

    def _track_background(self, task: asyncio.Task[Any]) -> None:
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)

    def _create_background(self, coro: Coroutine[Any, Any, Any], *, name: str) -> asyncio.Task[Any]:
        if self._frozen:
            coro.close()
            raise ApplicationStoppingError("SubAgentOrchestrator has frozen input")
        task = asyncio.create_task(coro, name=name)
        self._track_background(task)
        return task

    def _get_context(self, parent_session_id: str) -> _OrchestratorContext:
        if self._frozen:
            raise ApplicationStoppingError("SubAgentOrchestrator has frozen input")
        if not self.session_manager.exists(parent_session_id):
            raise LookupError(f"Parent session does not exist: {parent_session_id}")
        context = self._contexts.get(parent_session_id)
        if context is None:
            context = _OrchestratorContext(parent_session_id, self.session_manager)
            self._contexts[parent_session_id] = context
        return context

    # ── 公共代理方法 ─────────────────────────────────────────────────

    async def launch(self, parent_session_id: str, **kwargs: Any) -> SubAgentLaunchResult:
        return await self._get_context(parent_session_id).launch(parent_session_id=parent_session_id, **kwargs)

    async def chat_user_direct(self, parent_session_id: str, session_id: str, message: str, co_recipients: list[str] | None = None) -> SubAgentChatResult:
        return await self._get_context(parent_session_id).chat_user_direct(session_id, message, co_recipients)

    async def chat(self, parent_session_id: str, session_id: str, message: str, user_name: str, message_type: str, co_recipients: list[str] | None = None) -> SubAgentChatResult:
        return await self._get_context(parent_session_id).chat(session_id, message, user_name, message_type, co_recipients)

    async def approve(self, parent_session_id: str, session_id: str, decisions: list[dict[str, Any]]) -> SubAgentApprovalResult:
        return await self._get_context(parent_session_id).approve(session_id, decisions)

    async def stop(self, parent_session_id: str, session_id: str) -> SubAgentStopResult:
        return await self._get_context(parent_session_id).stop(session_id)

    async def launch_taskagent(
        self,
        parent_session_id: str,
        prompt: str,
        profile: LLMProfile,
    ) -> SubAgentLaunchResult:
        return await self._get_context(parent_session_id).launch_taskagent(
            parent_session_id, prompt, profile
        )

    async def stop_taskagent(self, parent_session_id: str, session_id: str) -> SubAgentStopResult:
        return await self._get_context(parent_session_id).stop_taskagent(session_id)

    def interrupt(self, parent_session_id: str) -> None:
        self._get_context(parent_session_id).interrupt()

    def resume(self, parent_session_id: str) -> None:
        self._get_context(parent_session_id).resume()

    def get_snapshot(self, parent_session_id: str) -> SubAgentSnapshotResponse:
        ctx = self._contexts.get(parent_session_id)
        if ctx is None:
            return SubAgentSnapshotResponse(session_id=parent_session_id)
        return ctx.get_snapshot()

    def enqueue_user_input(self, parent_session_id: str, session_id: str, message: QueuedMessage) -> int:
        return self._get_context(parent_session_id).enqueue_user_input(session_id, message)

    def freeze_inputs(self) -> None:
        self._frozen = True
        for context in self._contexts.values():
            context.freeze_inputs()

    async def stop_rounds(self) -> None:
        self.freeze_inputs()
        await asyncio.gather(*(context.stop_rounds() for context in self._contexts.values()))

    async def flush_inputs(self):
        await asyncio.gather(*(context.flush_inputs() for context in self._contexts.values()))

    async def transfer_shutdown_feedback(self) -> None:
        await asyncio.gather(*(context.transfer_shutdown_feedback() for context in self._contexts.values()))

    async def shutdown_all(self) -> None:
        """按冻结→停止→刷新→反馈交接顺序关闭所有上下文。"""
        self.freeze_inputs()
        contexts = tuple(self._contexts.values())
        await asyncio.gather(*(context.shutdown() for context in contexts))
        self._contexts.clear()

    async def shutdown(self, parent_session_id: str) -> None:
        """关闭指定父会话的所有子Agent并清理上下文。"""
        context = self._contexts.pop(parent_session_id, None)
        if context is not None:
            await context.shutdown()
