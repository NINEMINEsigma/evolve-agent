"""子 Agent 的 LLM 调用 + 工具执行循环。

参考 ``AgentLoop._process_message_locked`` 的结构，但适配子 Agent 的特化需求：
- 工具调用分类处理（report_to_parent 立即执行不暂停，其他工具阻塞等审批）
- 独立 LLM 客户端（SubRuntimeContext）
- 收件箱/发件箱机制
"""

from __future__ import annotations

import asyncio
import json
import logging
import time as _time_module
from pathlib import Path
from typing import Any

from abstract.tools.registry import ToolEntry, registry as tool_registry
from component.llm import LLMClient, LLMResponse, ToolCall
from entity.puretype import Role

from .report_tool import current_subagent_loop

logger = logging.getLogger(__name__)

# 分隔符 — 用于合并多条消息
PARENT_MESSAGE_SEPARATOR = "[Main Agent Message]"
SUB_MESSAGE_SEPARATOR = "[Sub Session Message]"


class PendingToolCall:
    """挂起的工具调用条目。"""

    def __init__(self, tool_call: ToolCall) -> None:
        self.tool_call_id: str = tool_call.id
        self.name: str = tool_call.name
        self.arguments: dict[str, Any] = dict(tool_call.arguments) if tool_call.arguments else {}
        self.result: asyncio.Future = asyncio.get_event_loop().create_future()


class SubAgentLoop:
    """单个子 Agent 会话的 LLM 循环。

    每个子 Agent 在独立的 asyncio.Task 中运行 ``run()``。
    """

    def __init__(
        self,
        ctx: Any,  # SubRuntimeContext
        session_id: str,
        tools: list[dict[str, Any]],
        max_turns: int,
        on_message: Any = None,  # Callable[[dict], None] — 推送一条结构化事件给前端
    ) -> None:
        self._ctx = ctx
        self._session_id: str = session_id
        self._tools: list[dict[str, Any]] = tools

        # 当前子 Agent 被授权的工具名集合 — 用于运行时强制隔离
        self._allowed_tool_names: set[str] = {
            (t.get("function") or {}).get("name") or t.get("name", "")
            for t in tools
        }
        self._allowed_tool_names.discard("")

        # 用 SubRuntimeContext 初始化独立的 LLM 客户端
        self._llm: LLMClient = self._build_llm_client(ctx)

        # 消息回调 — 每轮 LLM 响应/工具调用/工具结果都即时推送到前端
        self._on_message = on_message

        # 内部状态
        self._history: list[dict[str, Any]] = []
        self._outbox: list[str] = []
        self._inbox: list[str] = []
        self._pending_approvals: list[PendingToolCall] = []
        self._max_turns: int = max_turns

        # 控制事件
        self._cancel_event: asyncio.Event = asyncio.Event()
        self._paused_event: asyncio.Event = asyncio.Event()
        self._paused_event.set()  # 初始非暂停
        self._wake_event: asyncio.Event = asyncio.Event()
        self._wake_event.set()  # 初始允许首轮 LLM 调用

        # 标记
        self._completed: bool = False
        self._terminated: bool = False

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
                pass

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
            pass

    @staticmethod
    def _is_readonly_tool(name: str) -> bool:
        entry = tool_registry.get_entry(name)
        if entry is None:
            return False
        return getattr(entry, "danger_level", "readonly") == "readonly"

    @staticmethod
    def _is_auto_approved_tool(tc: ToolCall) -> bool:
        """检查工具调用是否在 allowlist 中（始终自动批准）。"""
        try:
            from component.approval_allowlist import is_allowed
            return is_allowed(tc.name, dict(tc.arguments) if tc.arguments else {})
        except Exception:
            return False

    async def run(self, initial_prompt: str) -> None:
        """子 Agent 主循环。"""
        try:
            # 添加系统提示词（首条消息）
            self._history.append({
                "role": Role.SYSTEM,
                "content": self._ctx.system_prompt,
            })
            # 添加初始用户消息
            self._history.append({
                "role": Role.USER,
                "content": initial_prompt,
            })

            turn: int = 0
            while turn < self._max_turns:
                if self._cancel_event.is_set():
                    return
                turn += 1

                # 调用 LLM
                messages: list[dict[str, Any]] = self._build_messages()
                resp: LLMResponse = await self._llm.chat(messages, self._tools)

                if self._cancel_event.is_set():
                    return

                # 记录本轮是否调用了 report_to_parent
                self._called_report_this_chain = False

                # 推送 reasoning（若有）
                reasoning_text = getattr(resp, "reasoning_content", None)
                if reasoning_text:
                    self._emit("reasoning", reasoning=reasoning_text)

                if not resp.tool_calls:
                    # 文本回复 — 推入发件箱并发给前端
                    text = resp.content or ""
                    self._history.append({
                        "role": Role.ASSISTANT,
                        "content": text,
                    })
                    self._outbox.append(text)
                    self._emit("assistant", content=text)
                    # LLM 给出纯文本即视作本轮对话结束，等待父 Agent 消息或取消
                    self._wake_event.clear()
                    await self._wake_event.wait()
                    self._maybe_inject_inbox()
                    continue

                # 推送 assistant 文本（若与 tool_calls 同帧）
                if resp.content:
                    self._emit("assistant", content=resp.content)

                # 存储带 tool_calls 的 assistant 消息
                assistant_entry: dict[str, Any] = {
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

                # 工具结果已收集，注入收件箱（若有）后立刻进入下一轮 LLM 推理
                self._maybe_inject_inbox()

        except Exception as exc:
            logger.exception("SubAgentLoop error for session=%s: %s", self._session_id, exc)
        finally:
            self._terminated = True

    def inject_parent_message(self, text: str) -> None:
        """父 Agent 通过 chat_subagent 发来的消息，追加到收件箱。

        消息在下一轮 tool 链结束时由 _maybe_inject_inbox 统一注入 _history，
        确保不会插入到 assistant(tool_calls) 与 tool(result) 之间，
        避免破坏 LLM API 要求的消息顺序。
        """
        self._inbox.append(text)
        self._wake_event.set()  # 唤醒正在等收件箱的循环

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
        """将完整会话历史写入 JSONL 文件。"""
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            for entry in self._history:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    @property
    def completed(self) -> bool:
        return self._completed

    @property
    def terminated(self) -> bool:
        return self._terminated

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
        return list(self._history)

    def _maybe_inject_inbox(self) -> bool:
        """若有收件箱消息，注入到历史。"""
        if self._inbox:
            merged = PARENT_MESSAGE_SEPARATOR.join(self._inbox)
            self._inbox.clear()
            self._history.append({
                "role": Role.USER,
                "content": f"[Parent Agent Message]\n{merged}",
            })
            return True
        return False

    async def _execute_report(self, tc: ToolCall) -> dict[str, Any]:
        """执行 report_to_parent 工具调用。"""
        try:
            current_subagent_loop.set(self)
            result = tool_registry.dispatch(tc.name, dict(tc.arguments))
            return self._make_tool_msg(tc.id, json.dumps(result, ensure_ascii=False))
        except Exception as exc:
            return self._make_tool_msg(tc.id, f"report_to_parent failed: {exc}")
        finally:
            current_subagent_loop.set(None)

    async def _queue_for_approval(self, tc: ToolCall) -> dict[str, Any]:
        """将工具调用加入待审批队列并阻塞等待结果。

        子 Agent 进入暂停状态，直到父 Agent 通过 approve_tools() 审批。
        """
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
        try:
            if tool_registry.get_entry(tc.name) is None:
                return self._make_tool_msg(tc.id, f"Tool '{tc.name}' not found in registry")

            args: dict[str, Any] = dict(tc.arguments) if tc.arguments else {}
            args["_session_id"] = self._session_id

            current_subagent_loop.set(self)
            entry = tool_registry.get_entry(tc.name)
            if entry is not None and entry.is_async:
                result = await entry.handler(args)
            else:
                result = tool_registry.dispatch(tc.name, args)
            return self._make_tool_msg(tc.id, json.dumps(result, ensure_ascii=False))
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