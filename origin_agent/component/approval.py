"""统一审批模块 — 支持正常模式（前端审批）和冒险模式（小LLM自动审批）。

对外暴露的唯一接口：
    request_user_confirm(session_id, tool_name, args, reason, content) -> ApprovalResult

结果类型：
    ApprovalResult
        .action       — "allow_once" | "allow_always" | "deny"
        .deny_reason  — 拒绝时携带具体原因，通过时为 None

冒险模式通过 set_adventure_mode() 开启/关闭，每次启动默认关闭。
审批小模型路径通过 config.py 的 approval_model_path 配置。
CUDA 可用时自动全卸载到 GPU。
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from typing import Any, Dict, Optional, TYPE_CHECKING

from pydantic import BaseModel
import dirtyjson

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# ApprovalResult
# ---------------------------------------------------------------------------

class ApprovalResult(BaseModel):
    """审批结果。

    Attributes:
        action:      "allow_once" | "allow_always" | "deny"
        deny_reason: 拒绝原因，仅 action == "deny" 时有效
        denied_by:   拒绝来源 — "model"（冒险模式LLM）、"user"（人工）、"system"（超时/断开等）
    """
    action: str
    deny_reason: Optional[str] = None
    denied_by: str = "system"


# ---------------------------------------------------------------------------
# 冒险模式 session 注册表
# ---------------------------------------------------------------------------

_adventure_sessions: Dict[str, bool] = {}


def set_adventure_mode(session_id: str, enabled: bool) -> None:
    """开启/关闭冒险模式。"""
    _adventure_sessions[session_id] = enabled
    logger.info("Adventure mode %s for session=%s", "enabled" if enabled else "disabled", session_id)


def is_adventure_mode(session_id: str) -> bool:
    """返回该 session 是否处于冒险模式。"""
    return _adventure_sessions.get(session_id, False)


# ---------------------------------------------------------------------------
# 冒险模式：小 LLM 审批器（懒加载单例）
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
    if _approver is not None:
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
            logger.warning("approval_model_path not configured — adventure mode will deny all")
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
        logger.info("Adventure approver loaded | model=%s cuda=%s", model_path, cuda_available)
        return _approver
    except Exception as exc:
        logger.warning("Failed to initialize adventure approver: %s", exc)
        _approver = _APPROVER_FAILED # type: ignore
        return None


async def _adventure_confirm(tool_name: str, args: dict, reason: str, content: str) -> ApprovalResult:
    """冒险模式：将工具调用 JSON 发送给小 LLM 审批。

    返回 ApprovalResult，deny 时携带 LLM 生成的拒绝原因。
    """
    engine = _get_approver()
    if engine is None:
        logger.warning("Approver not available — adventure mode deny")
        return ApprovalResult(action="deny", deny_reason="审批模型不可用，自动拒绝", denied_by="system")

    system_prompt = (
        "你是进化式AI Agent的安全审查器。Agent运行在沙箱环境中。\n\n"
        "沙箱路径前缀及含义：\n"
        "- fork: → slow_agent_space/（Agent的源代码工作区，可读写）\n"
        "- ws:   → agentspace/（Agent的I/O工作区，可读写）\n"
        "- fix:  → .fallback/（故障恢复目录，可读写）\n\n"
        "注意：写入沙箱的代码文件（.py/.js/.ts等）将来会被执行，所以代码本身可能危险。\n\n"
        "判断原则：\n"
        "- 写沙箱内的配置文件、JSON、日志、文本 → 安全，批准\n"
        "- 写可执行代码（.py/.js/.sh等），代码看起来是正常功能实现 → 批准\n"
        "- 写可执行代码，但内容明显恶意（删除文件、加密数据、反弹shell、窃取凭据等）→ 拒绝\n"
        "- 读取文件操作 → 安全，批准\n"
        '仅返回JSON：{"approved":true/false,"reason":"简短原因"}'
    )

    from system.pathutils import find_repo_root

    cwd = str(find_repo_root().resolve())

    user_prompt = json.dumps({
        "tool": tool_name,
        "args": args,
        "reason": reason,
        "description": content,
        "cwd": cwd,
    }, ensure_ascii=False)

    from third.llamaapis import GenerationConfig, system_message, user_message

    max_attempts = 3
    last_error: str | None = None

    for attempt in range(1, max_attempts + 1):
        try:
            messages = [system_message(system_prompt), user_message(user_prompt)]
            resp = engine.chat(messages, GenerationConfig(temperature=0.1, max_tokens=4096))
            resp_content = resp.choices[0].message.content
            result: dict = dirtyjson.loads(resp_content)
            approved: bool = result["approved"]  # type: ignore
            reason_text: str = result.get("reason", "")  # type: ignore
            if approved:
                logger.info("Adventure approved | tool=%s reason=%s", tool_name, reason_text)
                return ApprovalResult(action="allow_once")
            logger.info("Adventure denied | tool=%s reason=%s", tool_name, reason_text)
            return ApprovalResult(action="deny", deny_reason=reason_text or "安全性审查未通过", denied_by="model")
        except Exception as exc:
            last_error = str(exc)
            resp_content = locals().get("resp_content", "<not available>")
            logger.warning(
                "Adventure approval attempt %d/%d failed: %s | resp=%r",
                attempt, max_attempts, exc, resp_content,
            )
            if attempt < max_attempts:
                # 将上次的原始输出和解析错误附加到 prompt，引导模型修正格式
                correction_hint = (
                    f"\n\n[系统提示] 你上次的返回格式有误，无法解析。错误: {exc}\n"
                    f"你上次的原始输出:\n```\n{resp_content}\n```\n"
                    "请严格按 JSON 格式重新返回: {\"approved\":true/false,\"reason\":\"简短原因\"}"
                )
                user_prompt += correction_hint

    logger.warning(
        "Adventure approval exhausted %d attempts — denying tool=%s | last_error=%s",
        max_attempts, tool_name, last_error,
    )
    return ApprovalResult(action="deny", deny_reason=f"审批模型连续{max_attempts}次解析失败: {last_error}", denied_by="model")


# ---------------------------------------------------------------------------
# 统一审批入口
# ---------------------------------------------------------------------------


async def request_user_confirm(
    session_id: str,
    tool_name: str,
    args: dict,
    reason: str,
    content: str,
) -> ApprovalResult:
    """统一审批入口。

    参数：
        session_id: WebSocket session ID
        tool_name:  工具名（如 "run_command"、"install_package"）
        args:       工具调用参数字典
        reason:     agent 给出的执行原因
        content:    展示给审批者的描述文本

    返回 ApprovalResult(action, deny_reason)。
    """
    # 冒险模式：小 LLM 自动审批
    if is_adventure_mode(session_id):
        result = await _adventure_confirm(tool_name, args, reason, content)
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
            return ApprovalResult(action="deny", deny_reason="WebSocket 推送确认请求失败", denied_by="system")

    try:
        result: ApprovalResult = await asyncio.wait_for(fut, timeout=120.0)
        return result
    except asyncio.CancelledError:
        _pending_confirms.pop(request_id, None)
        return ApprovalResult(action="deny", deny_reason="审批请求被取消", denied_by="system")
    except asyncio.TimeoutError:
        _pending_confirms.pop(request_id, None)
        return ApprovalResult(action="deny", deny_reason="审批等待超时 (120s)", denied_by="system")
    except Exception:
        _pending_confirms.pop(request_id, None)
        return ApprovalResult(action="deny", deny_reason="审批处理异常", denied_by="system")