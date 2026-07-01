"""统一审批模块 — 支持正常模式（前端审批）和脱手模式（小LLM自动审批）。

对外暴露的唯一接口：
    request_user_confirm(session_id, tool_name, args, reason, content) -> ApprovalResult

结果类型：
    ApprovalResult
        .action       — "allow_once" | "allow_always" | "deny"
        .deny_reason  — 拒绝时携带具体原因，通过时为 None

脱手模式通过 set_handsfree_mode() 开启/关闭，每次启动默认关闭。
审批后端支持两种模式（二选一）：
- 本地 GGUF：通过 approval_model_path 配置，启动 llama-server 推理。
- 远程 OpenAI 兼容 API：通过 approval_remote_* 配置，连接 LM Studio / 自定义服务商。
CUDA 可用时本地模型自动全卸载到 GPU。
"""
# TODO: 大量提示词没有独立成模板文件
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from abc import ABC, abstractmethod
from typing import Any, Awaitable, Callable, Dict, Optional, TYPE_CHECKING, cast

import dirtyjson
import openai
from openai.types.chat import ChatCompletion
from pydantic import BaseModel

from component.llm import LLMClient
from entity.constant import APPROVAL_MODEL_LOAD_TIMEOUT, APPROVAL_WAIT_TIMEOUT, CUSTOM_MODELS_DIR, LLM_RETRY_COUNT
from entity.puretype import Role

if TYPE_CHECKING:
    from third.llamaapis import InferenceEngine
    from system.context import RuntimeContext

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# ApprovalResult
# ---------------------------------------------------------------------------

class ApprovalResult(BaseModel):
    """审批结果。

    Attributes:
        action:      "allow_once" | "allow_always" | "deny"
        deny_reason: 拒绝原因，仅 action == "deny" 时有效
        denied_by:   拒绝来源 — "model"（脱手模式LLM）、"user"（人工）、"system"（超时/断开等）
    """
    action: str
    deny_reason: str | None = None
    denied_by: str = "system"


# ---------------------------------------------------------------------------
# 脱手模式 session 注册表
# ---------------------------------------------------------------------------

_handsfree_sessions: dict[str, bool] = {}

def set_handsfree_mode(session_id: str, enabled: bool) -> None:
    """开启/关闭脱手模式。"""
    _handsfree_sessions[session_id] = enabled
    logger.info("Handsfree mode %s for session=%s", "enabled" if enabled else "disabled", session_id)


def is_handsfree_mode(session_id: str) -> bool:
    """返回该 session 是否处于脱手模式。"""
    return _handsfree_sessions.get(session_id, False)


# ---------------------------------------------------------------------------
# 审批输出 JSON Schema
# ---------------------------------------------------------------------------

APPROVAL_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "approved": {"type": "boolean"},
        "reason": {"type": "string"},
        "ask": {"type": "string"},
    },
    "required": ["approved"],
}


# ---------------------------------------------------------------------------
# 后端抽象
# ---------------------------------------------------------------------------

class ApprovalBackend(ABC):
    """脱手模式审批后端抽象。"""

    @abstractmethod
    async def chat(self, messages: list[dict[str, Any]], json_schema: dict[str, Any] | None = None) -> str:
        """发送对话请求，返回模型生成的文本。"""
        ...

    @abstractmethod
    async def is_available(self) -> bool:
        """后端当前是否可用。"""
        ...


class FailedApprovalBackend(ApprovalBackend):
    """哨兵子类，表示审批后端已尝试初始化但失败。"""

    async def is_available(self) -> bool:
        return False

    async def chat(self, messages: list[dict[str, Any]], json_schema: dict[str, Any] | None = None) -> str:
        raise RuntimeError("Approval backend is in failed state")


# ---------------------------------------------------------------------------
# 本地 GGUF 后端
# ---------------------------------------------------------------------------

class LocalApprovalBackend(ApprovalBackend):
    """基于 llama.cpp / llama-server 的本地审批后端。"""

    def __init__(self, ctx: RuntimeContext) -> None:
        self._ctx = ctx
        self._engine: InferenceEngine | None | object = None  # object sentinel for failed

    def _get_engine(self) -> InferenceEngine | None:
        """懒加载本地审批引擎。"""
        if self._engine is _ENGINE_FAILED:
            return None
        if self._engine is not None:
            return self._engine  # type: ignore[return-value]

        try:
            from system.pathutils import find_repo_root
            from third.llamaapis import InferenceEngine as LlamaEngine, ModelConfig

            root = find_repo_root()
            model_path = str((root / CUSTOM_MODELS_DIR / self._ctx.approval_model_path.strip()).resolve())
            cuda = bool(self._ctx.approval_model_cuda)
            n_gpu_layers = -1 if cuda else 0

            self._engine = LlamaEngine(ModelConfig(
                model_path=model_path,
                n_ctx=int(self._ctx.approval_model_n_ctx),
                n_gpu_layers=n_gpu_layers,
                cuda=cuda,
                port=int(self._ctx.approval_model_port),
                flash_attn=cuda,
                auto_build=True,
            ))
            logger.info("Local approval backend loaded | model=%s cuda=%s", model_path, cuda)
            return self._engine
        except Exception as exc:
            logger.exception("Failed to initialize local approval backend: %s", exc)
            self._engine = _ENGINE_FAILED
            return None

    async def is_available(self) -> bool:
        engine = self._get_engine()
        if engine is None:
            return False
        if not engine.is_model_loaded():
            if not engine.ensure_alive():
                return False
            for _ in range(APPROVAL_MODEL_LOAD_TIMEOUT):
                await asyncio.sleep(1.0)
                if engine.is_model_loaded():
                    return True
            return False
        return True

    async def chat(self, messages: list[dict[str, Any]], json_schema: dict[str, Any] | None = None) -> str:
        from third.llamaapis import GenerationConfig, system_message, user_message

        engine = self._get_engine()
        if engine is None:
            raise RuntimeError("Local approval engine not available")

        internal_messages = []
        for m in messages:
            role = m.get("role", "user")
            content = m.get("content", "")
            if role == "system":
                internal_messages.append(system_message(content))
            else:
                internal_messages.append(user_message(content))

        config = GenerationConfig(temperature=0.3, thinking=False)
        if json_schema is not None:
            config.json_schema = json_schema
        resp = await asyncio.to_thread(engine.chat, internal_messages, config)
        return resp.choices[0].message.content or ""


# ---------------------------------------------------------------------------
# 远程 OpenAI 兼容后端
# ---------------------------------------------------------------------------

class RemoteApprovalBackend(ApprovalBackend):
    """基于 OpenAI 兼容 API 的远程审批后端（如 LM Studio）。"""

    def __init__(self, ctx: RuntimeContext) -> None:
        self._ctx = ctx
        self._client: openai.AsyncOpenAI | None = None

    def _get_client(self) -> openai.AsyncOpenAI:
        if self._client is None:
            api_key = self._ctx.approval_remote_api_key or ""
            base_url = self._ctx.approval_remote_base_url or ""
            self._client = openai.AsyncOpenAI(api_key=api_key, base_url=base_url)
        return self._client

    async def is_available(self) -> bool:
        return bool(self._ctx.approval_remote_base_url and self._ctx.approval_remote_model)

    async def chat(self, messages: list[dict[str, Any]], json_schema: dict[str, Any] | None = None) -> str:
        client = self._get_client()
        model: str = self._ctx.approval_remote_model
        kwargs: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": 0.3,
        }
        if json_schema is not None:
            kwargs["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": "approval_decision",
                    "schema": json_schema,
                    "strict": True,
                },
            }

        try:
            resp: ChatCompletion = await client.chat.completions.create(**kwargs)
        except openai.APIStatusError as exc:
            # 若服务端不支持 json_schema（如部分旧 LM Studio），回退到普通请求
            if json_schema is not None and exc.status_code in (400, 422):
                logger.warning(
                    "Remote approval backend rejected json_schema (status=%s) — falling back to plain chat",
                    exc.status_code,
                )
                kwargs.pop("response_format", None)
                resp = await client.chat.completions.create(**kwargs)
            else:
                raise

        if not resp.choices:
            raise RuntimeError("Remote approval backend returned empty choices")
        return resp.choices[0].message.content or ""


# ---------------------------------------------------------------------------
# 后端工厂
# ---------------------------------------------------------------------------

_LOCAL_DISABLED_VALUES: set[str] = {"", "false", "0", "no"}


def is_local_approval_enabled(ctx: RuntimeContext) -> bool:
    """判定当前是否启用本地审批模型。"""
    raw = (ctx.approval_model_path or "").strip().lower()
    return raw not in _LOCAL_DISABLED_VALUES


def create_approval_backend(ctx: RuntimeContext) -> ApprovalBackend | None:
    """根据 RuntimeContext 创建对应的审批后端。"""
    if is_local_approval_enabled(ctx):
        return LocalApprovalBackend(ctx)
    if ctx.approval_remote_base_url and ctx.approval_remote_model:
        return RemoteApprovalBackend(ctx)
    return None


_ENGINE_FAILED = object()


# ---------------------------------------------------------------------------
# 脱手模式：LLM 审批
# ---------------------------------------------------------------------------

async def _handsfree_confirm(
    tool_name: str, args: dict, reason: str, content: str,
    ask_agent_callback: Optional[Callable[[str], Awaitable[str]]] = None,
    max_dialog_turns: int = 2,
    extra_context: str | None = None,
) -> ApprovalResult:
    """脱手模式：将工具调用 JSON 发送给LLM 审批。

    支持 dialog 模式：当审批模型不确定时，可通过 ask_agent_callback
    向 Agent 主模型提问，获取更多上下文后重新评估。

    返回 ApprovalResult，deny 时携带 LLM 生成的拒绝原因。
    """
    backend = None
    try:
        from system.application import Application
        mgr = Application.current().approval_backend_manager
        if mgr is not None:
            backend = await mgr.get_backend()
    except Exception as exc:
        logger.warning("Failed to resolve approval backend: %s", exc, exc_info=True)
        backend = None
    if backend is None:
        logger.warning("Approver not available — handsfree mode deny")
        return ApprovalResult(action="deny", deny_reason="Approval backend unavailable, auto-denied", denied_by="system")

    from system.pathutils import find_repo_root, get_templates_dir

    system_prompt = (get_templates_dir() / "approval" / "system_prompt.md").read_text(encoding="utf-8")
    cwd = str(find_repo_root().resolve())

    user_prompt_data: dict[str, Any] = {
        "tool": tool_name,
        "args": args,
        "reason": reason,
        "cwd": cwd,
    }
    if extra_context:
        user_prompt_data["context"] = extra_context
    user_prompt = json.dumps(user_prompt_data, ensure_ascii=False)

    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    dialog_turn = 0
    last_error: str | None = None

    while dialog_turn <= max_dialog_turns:
        current_messages = list(messages)
        last_error = None
        resp_content: str | None = None

        for attempt in range(1, LLM_RETRY_COUNT + 1):
            try:
                resp_content = await backend.chat(current_messages, json_schema=APPROVAL_JSON_SCHEMA)
                result: dict = cast(dict, dirtyjson.loads(resp_content))

                # ---- 处理「ask」响应：审批模型不确定，向Agent提问 ----
                ask_question: str | None = result.get("ask")
                if ask_question and isinstance(ask_question, str) and ask_question.strip():
                    if ask_agent_callback is None or dialog_turn >= max_dialog_turns:
                        reason_text: str = cast(str, result.get("reason", ""))
                        logger.info(
                            "Handsfree ask but cannot continue | tool=%s question=%s",
                            tool_name, ask_question,
                        )
                        return ApprovalResult(
                            action="deny",
                            deny_reason=f"Approval model uncertain: {reason_text}" if reason_text else "Approval model needs more info but cannot continue dialog",
                            denied_by="model",
                        )

                    logger.info(
                        "Handsfree asking agent (turn %d/%d) | tool=%s question=%s",
                        dialog_turn + 1, max_dialog_turns, tool_name, ask_question,
                    )
                    agent_answer = await ask_agent_callback(ask_question)
                    logger.info(
                        "Handsfree got agent answer (turn %d/%d) | tool=%s answer: %s",
                        dialog_turn + 1, max_dialog_turns, tool_name, agent_answer,
                    )

                    # 将Agent的回答追加到 messages，下一轮循环重新审批
                    current_messages.append({"role": "assistant", "content": resp_content or ""})
                    current_messages.append({
                        "role": "user",
                        "content": (
                            f"[Dialog round {dialog_turn + 1}]\n"
                            f"Approval model's question: {ask_question}\n"
                            f"Agent's answer: {agent_answer}\n\n"
                            f"Please re-evaluate the safety of this tool call based on the Agent's answer above."
                        ),
                    })
                    messages.extend(current_messages[2:])  # 保留 system + 原始 user，追加对话
                    dialog_turn += 1
                    break  # 跳出重试循环，进入 while 下一轮

                # Process approve / deny
                approved: bool = result["approved"]
                reason_text = cast(str, result.get("reason", ""))
                if approved:
                    logger.info("Handsfree approved | tool=%s reason=%s", tool_name, reason_text)
                    return ApprovalResult(action="allow_once")
                logger.info("Handsfree denied | tool=%s reason=%s", tool_name, reason_text)
                return ApprovalResult(action="deny", deny_reason=reason_text or "Security review failed", denied_by="model")

            except Exception as exc:
                last_error = str(exc)
                resp_content = locals().get("resp_content", "<not available>")
                logger.warning(
                    "Handsfree approval attempt %d/%d failed: %s | resp=%r",
                    attempt, LLM_RETRY_COUNT, exc, resp_content,
                )
                if attempt < LLM_RETRY_COUNT:
                    _ct = (get_templates_dir() / "approval" / "correction_hint.md").read_text(encoding="utf-8")
                    current_messages.append({
                        "role": "user",
                        "content": _ct.replace("{{error}}", str(exc)).replace("{{raw_output}}", resp_content or "<not available>"),
                    })

        # 重试循环全部失败 → 退出 while，最终返回 deny
        if last_error:
            break

    logger.warning(
        "Handsfree approval exhausted — denying tool=%s | last_error=%s",
        tool_name, last_error,
    )
    return ApprovalResult(
        action="deny",
        deny_reason=f"approval model continuous parsing failed: {last_error}" if last_error else "approval model cannot make a decision",
        denied_by="approval model",
    )


# ---------------------------------------------------------------------------
# 统一审批入口
# ---------------------------------------------------------------------------


async def request_user_confirm(
    session_id: str,
    tool_name: str,
    args: dict,
    reason: str,
    content: str,
    ask_agent_callback: Optional[Callable[[str], Awaitable[str]]] = None,
    extra_context: str | None = None,
) -> ApprovalResult:
    """统一审批入口。

    参数：
        session_id: WebSocket session ID
        tool_name:  工具名（如 "run_command"、"install_package"）
        args:       工具调用参数字典
        reason:     agent 给出的执行原因
        content:    展示给审批者的描述文本
        ask_agent_callback: 可选 — 脱手模式专用。当审批模型不确定时，
                            通过此回调向 Agent 主模型提问，获取更多上下文。
        extra_context: 可选 — custom_hooks 等额外上下文，供审批模型参考。

    返回 ApprovalResult(action, deny_reason)。
    """
    # 脱手模式：LLM 自动审批（不占用工具调用超时时间）
    if is_handsfree_mode(session_id):
        result = await _handsfree_confirm(
            tool_name, args, reason, content,
            ask_agent_callback=ask_agent_callback,
            extra_context=extra_context,
        )
        if result is not None:
            return result
        # approver 不可用 → 回退到人工审批

    # 正常模式：通过 FrontendSink 请求审批
    from system.application import Application
    return await Application.current().frontend_sink.request_approval(
        tool_name=tool_name,
        args=args,
        reason=reason,
        content=content,
        session_id=session_id,
    )


# ---------------------------------------------------------------------------
# 脱手模式辅助 — 向 Agent 主模型提问以获取审批上下文
# ---------------------------------------------------------------------------


async def ask_agent_reason(
    llm: LLMClient,
    tool_name: str,
    tool_args: dict,
    question: str,
    extra_context: str | None = None,
) -> str:
    """将审批模型的问题转发给 Agent 主模型，获取操作意图解释。

    当脱手模式的 LLM 不确定时，通过此函数向主模型提问，
    主模型的回答会追加到提示词中供审批模型重新评估。

    参数：
        llm:       Agent 主模型 LLMClient 实例
        tool_name: 被审批的工具名
        tool_args: 工具参数字典
        question:  审批模型提出的问题
        extra_context: 可选 — custom_hooks 等额外上下文

    返回：
        主模型的回答文本
    """
    from system.pathutils import get_templates_dir

    ask_prompt = (
        (get_templates_dir() / "approval" / "ask_agent_prompt.md").read_text(encoding="utf-8")
        .replace("{{tool_name}}", tool_name)
        .replace("{{question}}", question)
        .replace("{{tool_args_json}}", json.dumps(tool_args, ensure_ascii=False, indent=2))
    )
    if extra_context:
        ask_prompt += (
            f"\n\n[Additional Context]\n"
            f"The following context was attached to the user's latest message "
            f"and may be relevant to answering the approval model's question:\n"
            f"{extra_context}"
        )
    try:
        resp = await llm.chat(
            [{"role": Role.USER, "content": ask_prompt}],
            tools=[],
        )
        return resp.content or "(Agent did not provide an explanation)"
    except Exception as exc:
        logger.exception("Failed to ask agent for clarification: %s", exc)
        return f"(Failed to get agent explanation: {exc})"
