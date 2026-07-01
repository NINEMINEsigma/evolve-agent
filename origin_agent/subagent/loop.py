"""子 Agent 的 LLM 调用 + 工具执行循环。

参考 ``AgentLoop._process_message_locked`` 的结构，但适配子 Agent 的特化需求：
- 工具调用分类处理（readonly 立即执行，其他工具阻塞等审批）
- 独立 LLM 客户端（SubRuntimeContext）
- 收件箱/发件箱机制
"""

from __future__ import annotations

import asyncio
import json
import logging
import time as _time_module
from contextvars import ContextVar
from pathlib import Path
from typing import * # type: ignore

from abstract.tools.registry import ToolEntry, registry as tool_registry
from component.llm import LLMClient, LLMResponse, ToolCall
from entity.puretype import Role, ToolDangerLevel
from subagent.context import SubRuntimeContext
from entry.base_agent_loop import BaseAgentLoop, UserMessage, ContextLimitMessage, ToolContext
from entry.agent_sink import ParentAgentSink

logger = logging.getLogger(__name__)

# 由 SubAgentLoop 在每次工具执行前设置，供沙箱隔离（list_tools）及工具 handler 使用。
# 类型标注为 Any 以避免循环导入；实际类型为 subagent.loop.SubAgentLoop。
current_subagent_loop: ContextVar[Any] = ContextVar("current_subagent_loop")

# 分隔符 — 用于合并多条消息
SUB_MESSAGE_SEPARATOR = "[Sub Session Message]"


def format_user_message(user_name: str, message_type: str, content: str, co_recipients: list[str] | None = None) -> str:
    """包装进入子 Agent 的用户消息，明确标识真实发送者身份。"""
    if message_type == "direct":
        header = f"[your direct conversation partner in this turn: {user_name}]"
        description = (
            f'The following message is addressed to you directly by "{user_name}".\n'
            f'Even if the content mentions or quotes someone else, that other person is being relayed by {user_name}.\n'
            f'Respond to {user_name}, not to anyone mentioned inside the message.'
        )
    elif message_type == "overheard":
        header = f"[The speaker of this message in this turn: {user_name}]"
        description = (
            f'You are hearing a message that was spoken by "{user_name}".\n'
            f'This message may not be addressed to you; {user_name} may be talking to someone else or simply being quoted.\n'
            f'Do not assume you must reply unless the content explicitly asks something of you.'
        )
    elif message_type == "user_direct":
        header = f"[Direct message from the end user: {user_name}]"
        description = (
            f'The following message is sent directly to you by the end user "{user_name}", '
            f'not relayed by the parent agent. Respond to {user_name} directly.'
        )
    else:
        raise ValueError(f"Unknown message_type: {message_type}")
    if co_recipients:
        description += f"\n\n(This message is also shared with: {', '.join(co_recipients)}.)"
    # TODO: 使用---作为分割, 当前并不统一
    return f"{header}\n\n{description}\n\n---\n\n{content}"


class PendingToolCall:
    """挂起的工具调用条目。"""

    def __init__(self, tool_call: ToolCall) -> None:
        self.tool_call_id: str = tool_call.id
        self.name: str = tool_call.name
        self.arguments: dict[str, Any] = dict(tool_call.arguments) if tool_call.arguments else {}
        self.result: asyncio.Future = asyncio.get_event_loop().create_future()


class SubAgentLoop(BaseAgentLoop):
    """单个子 Agent 会话的 LLM 循环。

    继承 BaseAgentLoop，实现子 Agent 特化的 LLM 客户端、收件箱和工具审批。
    每个子 Agent 在独立的 asyncio.Task 中运行 ``run()``。
    """

    def __init__(
        self,
        ctx: SubRuntimeContext,
        session_id: str,
        tools: list[dict[str, Any]],
        max_turns: int,
        # TODO: 真的可能为空吗
        on_message: Callable[[dict], None]|None = None, 
        parent_session_id: str = "",
        name: str = "",
    ) -> None:
        from system.application import Application
        app = Application.current()
        super().__init__(app, session_id)

        self._name: str = name                              # 子 Agent 注册名，用于历史保存路径
        self._ctx: SubRuntimeContext = ctx                   # 子 Agent 的独立运行时上下文（LLM 配置、system prompt）
        self._parent_session_id: str = parent_session_id     # 父 Agent 的 session ID，用于审批回源
        self._tools: list[dict[str, Any]] = tools            # OpenAI function-calling 格式的工具 schema 列表

        # 当前子 Agent 被授权的工具名集合 — 用于运行时强制隔离
        self._allowed_tool_names: set[str] = {
            (t.get("function") or {}).get("name") or t.get("name", "")
            for t in tools
        }
        self._allowed_tool_names.discard("")

        self._llm: LLMClient = self._build_llm_client(ctx)   # 子 Agent 独立的 LLM 客户端
        self._on_message: Callable[[dict], None] | None = on_message  # 每轮 LLM 响应/工具调用即时推送回调

        # 内部状态（_history / _inbox / _cancel_event 由 BaseAgentLoop 提供）
        self._outbox: list[str] = []                         # 发件箱：子 Agent 文本回复，父 Agent 通过 get_outbox() 收集
        self._pending_approvals: list[PendingToolCall] = []   # 等待父 Agent 审批的工具调用队列
        self._max_turns: int = max_turns                     # 最大工具调用轮次上限

        self._last_message_from_parent: bool = True          # 上一条消息是否来自父 Agent（用于决定是否入 outbox）

        # 控制事件
        self._paused_event: asyncio.Event = asyncio.Event()  # 暂停信号：设置后 run() 等待恢复
        self._paused_event.set()
        self._wake_event: asyncio.Event = asyncio.Event()    # 唤醒信号：新消息到达时触发
        self._wake_event.set()

        # 生命周期标记
        self._completed: bool = False                        # run() 正常结束（非中断/异常）
        self._terminated: bool = False                       # 被外部请求终止
        self._round_active: bool = True                      # 当前是否正在执行 LLM 推理或工具链

    # ── 构造 LLM 客户端 ────────────────────────────────────────────

    def _build_llm_client(self, ctx: Any) -> LLMClient:
        """用 SubRuntimeContext 构建独立的 LLM 客户端。

        通过设置环境变量 + 临时 RuntimeContext 的技巧复用 LLMClient。
        更好的方式是直接传参，但 LLMClient 构造函数依赖 RuntimeContext。
        这里创建一个最小化的模拟对象。
        """
        # 获取父 Agent 的 API key 作为兜底
        import os
        parent_api_key = os.environ.get("OPENAI_API_KEY", "")
        if not parent_api_key:
            try:
                from system.context import get_runtime_context
                parent_api_key = get_runtime_context().llm_api_key
            except Exception:
                logger.warning("Failed to load parent API key for subagent; using empty fallback", exc_info=True)

        class _MockCtx:
            llm_api_key = ctx.api_key or parent_api_key or os.environ.get("OPENAI_API_KEY", "")
            llm_base_url = ctx.base_url
            llm_model = ctx.model
            llm_temperature = ctx.temperature
            llm_max_output_tokens = ctx.max_output_tokens
            llm_max_context_tokens = ctx.max_context_tokens
            llm_reasoning_effort = ""

        return LLMClient(_MockCtx())  # type: ignore[arg-type]

    # ── 公共接口 ─────────────────────────────────────────────────────

    def _emit(self, role: str, **fields: Any) -> None:
        """向前端推送一条结构化事件。

        ``role`` 取值：``user`` / ``assistant`` / ``reasoning`` / ``tool_call`` /
        ``tool_result`` / ``status`` / ``approval_pending`` / ``approval_decision``。
        其余字段（``content``/``tool_name``/``tool_call_id``/``tool_args``/``reasoning``）
        按需透传。
        """
        if not self._on_message:
            return
        try:
            payload: dict[str, Any] = {"role": role}
            payload.update({k: v for k, v in fields.items() if v is not None})
            self._on_message(payload)
        except Exception:
            logger.warning("Failed to emit subagent event role=%s", role, exc_info=True)

    @staticmethod
    def _is_readonly_tool(name: str) -> bool:
        entry = tool_registry.get_entry(name)
        if entry is None:
            return False
        return entry.danger_level == ToolDangerLevel.readonly

    @staticmethod
    def _is_auto_approved_tool(tc: ToolCall) -> bool:
        """检查工具调用是否在 allowlist 中（始终自动批准）。"""
        try:
            from component.approval_allowlist import is_allowed
            return is_allowed(tc.name, dict(tc.arguments) if tc.arguments else {})
        except Exception:
            logger.warning("Failed to check approval allowlist for subagent tool=%s", tc.name, exc_info=True)
            return False

    async def run(self, initial_prompt: str, user_name: str, message_type: str) -> None:
        """子 Agent 主循环。"""
        # 注册到 CronRouter，使 cron 结果能投递到 inbox
        from system.application import Application
        _cron = Application.current().cron_router
        if _cron is not None:
            _cron.register(self.session_id, self)
        try:
            # 注入初始用户消息（system prompt 由 _build_history_messages 通过 _build_system_prompt 处理）
            self._history.append({
                "role": Role.USER,
                "content": format_user_message(user_name, message_type, initial_prompt),
            })

            turn: int = 0
            while turn < self._max_turns:
                if self._cancel_event.is_set():
                    return
                turn += 1
                self._round_active = True  # 新一轮响应开始

                # 调用 LLM（_build_messages 通过 _build_history_messages 处理 system prompt + hooks）
                messages: list[dict[str, Any]] = self._build_messages()
                resp: LLMResponse = await self._llm.chat(messages, self._tools)

                if self._cancel_event.is_set():
                    return

                reasoning_text = resp.reasoning_content

                if not resp.tool_calls:
                    # 文本回复 — 推入发件箱并发给前端
                    text = resp.content or ""
                    assistant_entry: dict[str, Any] = {
                        "role": Role.ASSISTANT,
                        "content": text,
                    }
                    if reasoning_text:
                        assistant_entry["reasoning_content"] = reasoning_text
                    self._history.append(assistant_entry)
                    if self._last_message_from_parent:
                        self._outbox.append(text)
                    self._emit("assistant", content=text, reasoning=reasoning_text)
                    # LLM 给出纯文本即视作本轮对话结束，等待父 Agent 消息或取消
                    self._round_active = False
                    self._wake_event.clear()
                    await self._wake_event.wait()
                    self._maybe_inject_inbox()
                    continue

                # 推送 assistant 文本（若与 tool_calls 同帧）
                if resp.content:
                    self._emit("assistant", content=resp.content, reasoning=reasoning_text)

                # 存储带 tool_calls 的 assistant 消息
                assistant_entry = {
                    "role": Role.ASSISTANT,
                    "content": resp.content or "",
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.name,
                                "arguments": json.dumps(tc.arguments, ensure_ascii=False),
                            },
                        }
                        for tc in resp.tool_calls
                    ],
                }
                self._history.append(assistant_entry)

                # 处理工具调用 — readonly 直接执行；其它工具入审批队列阻塞等待
                for tc in resp.tool_calls:
                    if self._cancel_event.is_set():
                        return

                    # 推送 tool_call 事件
                    self._emit(
                        "tool_call",
                        tool_call_id=tc.id,
                        tool_name=tc.name,
                        tool_args=dict(tc.arguments) if tc.arguments else {},
                    )

                    if self._is_readonly_tool(tc.name) or self._is_auto_approved_tool(tc):
                        tool_msg = await self._execute_approved_tool(tc)
                    else:
                        tool_msg = await self._queue_for_approval(tc)

                    # 推送 tool_result 事件
                    raw_content = str(tool_msg.get("content", ""))
                    self._emit(
                        "tool_result",
                        tool_call_id=tc.id,
                        tool_name=tc.name,
                        content=raw_content,
                    )

                    # 检测工具失败并放入 outbox，让父 Agent 知道（防止默认成功假设）
                    self._maybe_record_tool_failure(tc.name, raw_content)

                    messages.append(tool_msg)
                    self._history.append(tool_msg)

                # 工具结果已收集，本轮响应结束；注入收件箱（若有）后立刻进入下一轮 LLM 推理
                self._round_active = False
                self._maybe_inject_inbox()

        except Exception as exc:
            logger.exception("SubAgentLoop error for session=%s: %s", self.session_id, exc)
        finally:
            if _cron is not None:
                _cron.unregister(self.session_id)
            self._terminated = True

    def inject_parent_message(self, text: str, user_name: str, message_type: str, co_recipients: list[str] | None = None) -> None:
        """父 Agent 或用户直接发送来的消息，投递到收件箱。"""
        self._last_message_from_parent = (message_type != "user_direct")
        content = format_user_message(user_name, message_type, text, co_recipients)
        self._inbox.put(UserMessage(content=content))
        self._wake_event.set()

    def approve_tools(self, decisions: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """父 Agent 审批结果，触发工具执行并解除阻塞。

        Returns:
            审批处理结果列表，每项包含 tool_call_id, approved, error（如有）。
        """
        results: list[dict[str, Any]] = []
        decision_map: dict[str, dict[str, Any]] = {
            d["tool_call_id"]: d for d in decisions
        }

        for pending in self._pending_approvals:
            decision = decision_map.get(pending.tool_call_id)
            if decision is None:
                # 未匹配 — 跳过（可能已被其他决策处理）
                continue

            if decision["approved"]:
                # 同意：设置 Future 结果
                if not pending.result.done():
                    pending.result.set_result({"approved": True})
                results.append({"tool_call_id": pending.tool_call_id, "approved": True})
            else:
                # 拒绝：设置 Future 异常
                reason = decision.get("reason", "Rejected by parent agent.")
                if not pending.result.done():
                    pending.result.set_exception(RuntimeError(reason))
                results.append({
                    "tool_call_id": pending.tool_call_id,
                    "approved": False,
                    "reason": reason,
                })

        # 清空待审批队列
        self._pending_approvals.clear()

        # 解除阻塞
        self._paused_event.set()

        return results

    def stop(self) -> None:
        """强制终止子 Agent。"""
        self._cancel_event.set()

    def save_history(self, path: Path) -> None:
        """将会话历史写入 JSONL 文件（不含 system message，重启后会重新注入）。"""
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            for entry in self._history:
                if entry.get("role") == Role.SYSTEM:
                    continue
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    @property
    def completed(self) -> bool:
        return self._completed

    @property
    def terminated(self) -> bool:
        return self._terminated

    @property
    def round_active(self) -> bool:
        return self._round_active

    @property
    def outbox(self) -> list[str]:
        return list(self._outbox)

    @property
    def pending_approvals_info(self) -> list[dict[str, Any]]:
        return [
            {
                "tool_call_id": p.tool_call_id,
                "tool_name": p.name,
                "arguments": p.arguments,
            }
            for p in self._pending_approvals
        ]

    # ── 内部方法 ─────────────────────────────────────────────────────

    def _build_messages(self) -> list[dict[str, Any]]:
        """构建 LLM 消息列表，通过基类 _build_history_messages() 处理 system prompt + hooks。"""
        return self._build_history_messages()

    def _maybe_inject_inbox(self) -> bool:
        """若有收件箱消息，注入到历史。"""
        msgs = self._inbox.get_pending()
        if not msgs:
            return False
        merged = "\n\n".join(msg.to_text() for msg in msgs)
        self._history.append({"role": Role.USER, "content": merged})
        return True

    async def _queue_for_approval(self, tc: ToolCall) -> dict[str, Any]:
        """将工具调用加入待审批队列并阻塞等待结果。

        子 Agent 进入暂停状态，直到父 Agent 通过 approve_tools() 审批。
        """
        from component.approval import is_handsfree_mode, request_user_confirm

        if is_handsfree_mode(self._parent_session_id):
            result = await request_user_confirm(
                session_id=self._parent_session_id,
                tool_name=tc.name,
                args=dict(tc.arguments) if tc.arguments else {},
                reason="Sub-agent initiated tool call",
                content=f"Sub-agent {tc.name} tool call",
                ask_agent_callback=None,
            )
            if result.action in ("allow_once", "allow_always"):
                self._emit(
                    "approval_decision",
                    tool_call_id=tc.id,
                    tool_name=tc.name,
                    content="approved",
                )
                return await self._execute_approved_tool(tc)
            self._emit(
                "approval_decision",
                tool_call_id=tc.id,
                tool_name=tc.name,
                content=f"rejected: {result.deny_reason}",
            )
            return self._make_tool_msg(tc.id, f"Tool call denied: {result.deny_reason}")

        pending = PendingToolCall(tc)
        self._pending_approvals.append(pending)

        # 暂停
        self._paused_event.clear()

        # 推送 pending 事件到前端
        self._emit(
            "approval_pending",
            tool_call_id=tc.id,
            tool_name=tc.name,
            tool_args=dict(tc.arguments) if tc.arguments else {},
        )

        try:
            result = await pending.result  # 永不超时，阻塞等待
            if result["approved"]:
                self._emit(
                    "approval_decision",
                    tool_call_id=tc.id,
                    tool_name=tc.name,
                    content="approved",
                )
                return await self._execute_approved_tool(tc)
            else:
                self._emit(
                    "approval_decision",
                    tool_call_id=tc.id,
                    tool_name=tc.name,
                    content="approved",
                )
                return self._make_tool_msg(
                    tc.id,
                    json.dumps({"approved": True, "result": result}),
                )
        except RuntimeError as exc:
            self._emit(
                "approval_decision",
                tool_call_id=tc.id,
                tool_name=tc.name,
                content=f"rejected: {exc}",
            )
            return self._make_tool_msg(tc.id, f"Tool call rejected: {exc}")

    async def _execute_approved_tool(self, tc: ToolCall) -> dict[str, Any]:
        """执行已获批准的工具调用。"""
        # 沙箱隔离：拒绝授权清单之外的工具
        if tc.name not in self._allowed_tool_names:
            return self._make_tool_msg(
                tc.id,
                json.dumps(
                    {
                        "success": False,
                        "error": (
                            f"Tool '{tc.name}' is not authorized for this sub-agent. "
                            f"Allowed tools: {sorted(self._allowed_tool_names)}"
                        ),
                    },
                    ensure_ascii=False,
                ),
            )
        timeout: int = self._ctx.tool_timeout
        try:
            if tool_registry.get_entry(tc.name) is None:
                return self._make_tool_msg(tc.id, f"Tool '{tc.name}' not found in registry")

            args: dict[str, Any] = dict(tc.arguments) if tc.arguments else {}
            args["_session_id"] = self.session_id

            current_subagent_loop.set(self)
            entry = tool_registry.get_entry(tc.name)
            if entry and entry.no_timeout:
                timeout = 0

            # 通过 registry.async_dispatch 执行，正确传递 ToolContext
            tool_ctx = ToolContext(loop=self, session_id=self.session_id)
            coro = tool_registry.async_dispatch(tc.name, args, context=tool_ctx)

            if timeout:
                result = await asyncio.wait_for(coro, timeout=timeout)
            else:
                result = await coro

            return self._make_tool_msg(tc.id, json.dumps(result, ensure_ascii=False))
        except asyncio.TimeoutError:
            return self._make_tool_msg(
                tc.id,
                json.dumps(
                    {"success": False, "error": f"Tool execution timed out ({timeout}s)"},
                    ensure_ascii=False,
                ),
            )
        except Exception as exc:
            return self._make_tool_msg(
                tc.id,
                json.dumps(
                    {"success": False, "error": f"Tool execution failed: {exc}"},
                    ensure_ascii=False,
                ),
            )
        finally:
            current_subagent_loop.set(None)

    @property
    def allowed_tool_names(self) -> set[str]:
        return set(self._allowed_tool_names)

    def _maybe_record_tool_failure(self, tool_name: str, content: str) -> None:
        """检测工具失败并写入 outbox，让父 Agent 在下一次 [subagent-result] 中收到。

        工具结果约定为 JSON ``{"success": bool, ...}``；当 ``success`` 为 false
        或包含明显错误标记时记录为失败。普通文本/异常字符串也按失败处理。
        """
        snippet = content.strip()
        if not snippet:
            return
        is_failure: bool = False
        summary: str = snippet
        try:
            parsed = json.loads(snippet)
            if isinstance(parsed, dict):
                if parsed.get("success") is False:
                    is_failure = True
                    summary = str(
                        parsed.get("error")
                        or parsed.get("message")
                        or parsed
                    )
                elif "error" in parsed and parsed.get("success") is None:
                    is_failure = True
                    summary = str(parsed.get("error"))
        except json.JSONDecodeError:
            lowered = snippet.lower()
            if (
                lowered.startswith("tool execution failed")
                or lowered.startswith("tool call rejected")
                or "traceback" in lowered
            ):
                is_failure = True
                summary = snippet

        if not is_failure:
            return
        max_len = 500
        if len(summary) > max_len:
            summary = summary[:max_len] + "...(truncated)"
        self._outbox.append(
            f"[tool-failure] {tool_name}: {summary}"
        )

    @staticmethod
    def _make_tool_msg(tool_call_id: str, content: str) -> dict[str, Any]:
        return {
            "role": Role.TOOL,
            "tool_call_id": tool_call_id,
            "content": content,
        }

    # -- BaseAgentLoop 抽象方法实现 ------------------------------------------

    def _get_llm_client(self):
        return self._llm

    def _get_context(self):
        return self._ctx

    def _get_sink(self):
        return ParentAgentSink(self)

    def _get_tool_definitions(self) -> list[dict]:
        return self._tools

    async def _on_context_over_limit(self) -> None:
        """上下文超限时保存历史并通知 inbox，下次轮次 LLM 会收到 ContextLimitMessage。"""
        path = self._get_history_path()
        try:
            self.save_history(path)
            self._inbox.put(ContextLimitMessage(saved_path=str(path)))
            logger.warning(
                "SubAgentLoop context over limit for session=%s, saved to %s",
                self.session_id, path,
            )
        except Exception as exc:
            logger.warning(
                "SubAgentLoop context over limit for session=%s, failed to save: %s",
                self.session_id, exc,
            )

    def _get_history_path(self) -> Path:
        """返回历史保存路径：agentspace/subagents/{name}/{session_id}.jsonl。"""
        from system.context import get_runtime_context
        ctx = get_runtime_context()
        dir = ctx.agentspace / "subagents"
        if self._name:
            dir = dir / self._name
        dir.mkdir(parents=True, exist_ok=True)
        return dir / f"{self.session_id}.jsonl"

    def _build_system_prompt(self) -> list[str]:
        return self._ctx.system_prompts