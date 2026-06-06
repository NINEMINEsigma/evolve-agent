"""统一审批模块 — 支持正常模式（前端审批）和脱手模式（小LLM自动审批）。

对外暴露的唯一接口：
    request_user_confirm(session_id, tool_name, args, reason, content) -> ApprovalResult

结果类型：
    ApprovalResult
        .action       — "allow_once" | "allow_always" | "deny"
        .deny_reason  — 拒绝时携带具体原因，通过时为 None

脱手模式通过 set_handsfree_mode() 开启/关闭，每次启动默认关闭。
审批小模型路径通过 config.py 的 approval_model_path 配置。
CUDA 可用时自动全卸载到 GPU。
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
import dirtyjson
from pydantic import BaseModel
from typing import Any, Awaitable, Callable, Dict, Optional, TYPE_CHECKING, cast

from component.llm import LLMClient

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
    deny_reason: Optional[str] = None
    denied_by: str = "system"


# ---------------------------------------------------------------------------
# 脱手模式 session 注册表
# ---------------------------------------------------------------------------

_handsfree_sessions: Dict[str, bool] = {}


def set_handsfree_mode(session_id: str, enabled: bool) -> None:
    """开启/关闭脱手模式。"""
    _handsfree_sessions[session_id] = enabled
    logger.info("Handsfree mode %s for session=%s", "enabled" if enabled else "disabled", session_id)


def is_handsfree_mode(session_id: str) -> bool:
    """返回该 session 是否处于脱手模式。"""
    return _handsfree_sessions.get(session_id, False)


# ---------------------------------------------------------------------------
# 脱手模式：小 LLM 审批器（懒加载单例）
# ---------------------------------------------------------------------------

if TYPE_CHECKING:
    from third.llamaapis import InferenceEngine

_approver: InferenceEngine|None = None
_approver_lock = asyncio.Lock()
_APPROVER_FAILED = "__failed__"  # sentinel: 标记初始化失败，防止每次重试


def _detect_cuda(cuda: bool = False) -> bool:
    """是否启用 CUDA（由配置决定，不自动检测）。

    参数：
        cuda: 配置中指定的 CUDA 启用状态，默认 False。
    """
    if cuda:
        logger.info("CUDA enabled via config — approval model will use GPU")
    else:
        logger.info("CUDA disabled via config — approval model runs on CPU")
    return cuda


def _get_approver() -> InferenceEngine|None:
    """懒加载审批小模型的 InferenceEngine 单例。"""
    global _approver
    if _approver is not None and _approver != _APPROVER_FAILED:
        return _approver

    try:
        from system.context import get_runtime_context
        from system.pathutils import find_repo_root
        from pathlib import Path

        _root = find_repo_root()
        ctx = get_runtime_context()
        model_path = ctx.approval_model_path
        n_ctx = ctx.approval_model_n_ctx or 4096

        if not model_path:
            logger.warning("approval_model_path not configured — handsfree mode will deny all")
            return None

        # 文件存放在 custom_models/ 目录下
        p = _root / "custom_models" / model_path
        model_path = str(p.resolve())

        cuda_available = _detect_cuda(ctx.approval_model_cuda)
        n_gpu_layers = -1 if cuda_available else 0

        from third.llamaapis import InferenceEngine, ModelConfig

        _approver = InferenceEngine(ModelConfig(
            model_path=model_path,
            n_ctx=n_ctx,
            n_gpu_layers=n_gpu_layers,
            cuda=cuda_available,
            port=8081,  # 与主 LLM server 不同端口
            flash_attn=cuda_available,
            auto_build=True,
        ))
        logger.info("Handsfree approver loaded | model=%s cuda=%s", model_path, cuda_available)
        return _approver
    except Exception as exc:
        logger.warning("Failed to initialize handsfree approver: %s", exc)
        _approver = _APPROVER_FAILED # type: ignore
        return None


async def _handsfree_confirm(
    tool_name: str, args: dict, reason: str, content: str,
    ask_agent_callback: Optional[Callable[[str], Awaitable[str]]] = None,
    max_dialog_turns: int = 2,
    extra_context: Optional[str] = None,
) -> ApprovalResult:
    """脱手模式：将工具调用 JSON 发送给小 LLM 审批。

    支持 dialog 模式：当审批模型不确定时，可通过 ask_agent_callback
    向 Agent 主模型提问，获取更多上下文后重新评估。

    返回 ApprovalResult，deny 时携带 LLM 生成的拒绝原因。
    """
    engine = _get_approver()
    if engine is None:
        logger.warning("Approver not available — handsfree mode deny")
        return ApprovalResult(action="deny", deny_reason="Approval model unavailable, auto-denied", denied_by="system")

    # 等待模型加载完成（防止 health 200 但模型仍在 loading 导致的 502）
    if not engine.is_model_loaded():
        logger.info("Approval model loading — waiting | tool=%s", tool_name)
        for _ in range(120):
            await asyncio.sleep(1.0)
            if engine.is_model_loaded():
                logger.info("Approval model loaded | tool=%s", tool_name)
                break
        else:
            logger.warning("Approval model load timeout (120s) | tool=%s", tool_name)
            return ApprovalResult(action="deny", deny_reason="Approval model load timeout (120s)", denied_by="system")

    from system.pathutils import find_repo_root, get_templates_dir

    system_prompt = (get_templates_dir() / "approval" / "system_prompt.md").read_text(encoding="utf-8")

    cwd = str(find_repo_root().resolve())

    user_prompt_data: Dict[str, Any] = {
        "tool": tool_name,
        "args": args,
        "reason": reason,
        "description": content,
        "cwd": cwd,
    }
    if extra_context:
        user_prompt_data["context"] = extra_context
    user_prompt = json.dumps(user_prompt_data, ensure_ascii=False)

    from third.llamaapis import GenerationConfig, system_message, user_message

    dialog_turn = 0
    last_error: str | None = None
    max_attempts = 3

    while dialog_turn <= max_dialog_turns:
        current_prompt = user_prompt
        last_error = None
        resp_content: str | None = None

        for attempt in range(1, max_attempts + 1):
            try:
                messages = [system_message(system_prompt), user_message(current_prompt)]
                resp = await asyncio.to_thread(engine.chat, messages, GenerationConfig(temperature=0.1))
                resp_content = resp.choices[0].message.content
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
                        "Handsfree got agent answer (turn %d/%d) | tool=%s answer_len=%d",
                        dialog_turn + 1, max_dialog_turns, tool_name, len(agent_answer),
                    )

                    # 将Agent的回答追加到 user_prompt，下一轮循环重新审批
                    user_prompt += (
                        f"\n\n---\n"
                        f"[Dialog round {dialog_turn + 1}]\n"
                        f"Approval model's question: {ask_question}\n"
                        f"Agent's answer: {agent_answer}\n"
                        f"---\n"
                        f"Please re-evaluate the safety of this tool call "
                        f"based on the Agent's answer above.\n"
                    )
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
                    attempt, max_attempts, exc, resp_content,
                )
                if attempt < max_attempts:
                    _ct = (get_templates_dir() / "approval" / "correction_hint.md").read_text(encoding="utf-8")
                    current_prompt += "\n\n" + _ct.replace("{{error}}", str(exc)).replace("{{raw_output}}", resp_content or "<not available>")

        # 重试循环全部失败 → 退出 while，最终返回 deny
        if last_error:
            break

    logger.warning(
        "Handsfree approval exhausted — denying tool=%s | last_error=%s",
        tool_name, last_error,
    )
    return ApprovalResult(
        action="deny",
        deny_reason=f"审批模型连续解析失败: {last_error}" if last_error else "审批模型无法做出判断",
        denied_by="model",
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
    extra_context: Optional[str] = None,
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
    # 脱手模式：小 LLM 自动审批（不占用工具调用超时时间）
    if is_handsfree_mode(session_id):
        result = await _handsfree_confirm(
            tool_name, args, reason, content,
            ask_agent_callback=ask_agent_callback,
            extra_context=extra_context,
        )
        if result is not None:
            return result
        # approver 不可用 → 回退到人工审批

    # 正常模式：WebSocket 前端审批
    from gateway.server import _tool_ws_sinks, _pending_confirms, _register_confirm_session

    request_id: str = uuid.uuid4().hex[:8]

    loop: asyncio.AbstractEventLoop = asyncio.get_event_loop()
    fut: asyncio.Future[ApprovalResult] = loop.create_future()
    _pending_confirms[request_id] = fut
    _register_confirm_session(request_id, session_id)

    ws = _tool_ws_sinks.get(session_id)
    if ws:
        try:
            await ws.send_text(json.dumps({
                "type": "confirm_request",
                "session_id": session_id,
                "request_id": request_id,
                "content": content,
                "tool": tool_name,
                "args": args,
            }, ensure_ascii=False))
        except Exception:
            _pending_confirms.pop(request_id, None)
            return ApprovalResult(action="deny", deny_reason="WebSocket push confirm request failed", denied_by="system")

    try:
        result: ApprovalResult = await asyncio.wait_for(fut, timeout=120.0)
        return result
    except asyncio.CancelledError:
        _pending_confirms.pop(request_id, None)
        return ApprovalResult(action="deny", deny_reason="Approval request cancelled", denied_by="system")
    except asyncio.TimeoutError:
        _pending_confirms.pop(request_id, None)
        return ApprovalResult(action="deny", deny_reason="Approval wait timed out (120s)", denied_by="system")
    except Exception:
        _pending_confirms.pop(request_id, None)
        return ApprovalResult(action="deny", deny_reason="Approval handling error", denied_by="system")


# ---------------------------------------------------------------------------
# 脱手模式辅助 — 向 Agent 主模型提问以获取审批上下文
# ---------------------------------------------------------------------------


async def ask_agent_reason(
    llm: LLMClient,
    tool_name: str,
    tool_args: dict,
    question: str,
    extra_context: Optional[str] = None,
) -> str:
    """将审批模型的问题转发给 Agent 主模型，获取操作意图解释。

    当脱手模式的小 LLM 不确定时，通过此函数向主模型提问，
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
            [{"role": "user", "content": ask_prompt}],
            tools=[],
        )
        return resp.content or "(Agent did not provide an explanation)"
    except Exception as exc:
        logger.warning("Failed to ask agent for clarification: %s", exc)
        return f"(Failed to get agent explanation: {exc})"