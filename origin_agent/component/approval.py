"""统一审批模块 — 支持正常模式（前端审批）和冒险模式（小LLM自动审批）。

对外暴露的唯一接口：
    request_user_confirm(session_id, tool_name, args, reason, content) -> str

冒险模式通过 set_adventure_mode() 开启/关闭，每次启动默认关闭。
审批小模型路径通过 config.py 的 approval_model_path 配置。
CUDA 可用时自动全卸载到 GPU。
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from typing import Any, Dict, TYPE_CHECKING
import dirtyjson

logger = logging.getLogger(__name__)

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


async def _adventure_confirm(tool_name: str, args: dict, reason: str, content: str) -> str:
    """冒险模式：将工具调用 JSON 发送给小 LLM 审批。

    返回 "allow_once" 或 "deny"。
    """
    engine = _get_approver()
    if engine is None:
        logger.warning("Approver not available — falling back to human approval")
        return "deny"

    system_prompt = (
        "你是命令安全审查器, 判断工具调用是否危险, 只有合法且安全时才允许执行."
        '仅返回JSON：{"approved":true/false,"reason":"简短原因"}'
    )

    user_prompt = json.dumps({
        "tool": tool_name,
        "args": args,
        "reason": reason,
    }, ensure_ascii=False)

    try:
        from third.llamaapis import GenerationConfig, system_message, user_message

        resp = engine.chat(
            [system_message(system_prompt), user_message(user_prompt)],
            GenerationConfig(temperature=0.1, max_tokens=4096),
        )
        resp_content = resp.choices[0].message.content
        result: dict = dirtyjson.loads(resp_content)
        approved: bool = result["approved"] # type: ignore
        reason_text: str = result["reason"] # type: ignore
        if approved:
            logger.info("Adventure approved | tool=%s reason=%s", tool_name, reason_text)
            return "allow_once"
        logger.info("Adventure denied | tool=%s reason=%s", tool_name, reason_text)
        return "deny"
    except Exception as exc:
        resp_content = locals().get("resp_content", "<not available>")
        logger.warning(
            "Adventure approval failed: %s — denying tool=%s | resp=%r",
            exc, tool_name, resp_content,
            exc_info=True,
        )
        return "deny"


# ---------------------------------------------------------------------------
# 统一审批入口
# ---------------------------------------------------------------------------


async def request_user_confirm(
    session_id: str,
    tool_name: str,
    args: dict,
    reason: str,
    content: str,
) -> str:
    """统一审批入口。

    参数：
        session_id: WebSocket session ID
        tool_name:  工具名（如 "run_command"、"install_package"）
        args:       工具调用参数字典
        reason:     agent 给出的执行原因
        content:    展示给审批者的描述文本

    返回 "allow_once" / "allow_always" / "deny"。
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
    fut: asyncio.Future[str] = loop.create_future()
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
            return "deny"

    try:
        action: str = await asyncio.wait_for(fut, timeout=120.0)
        if action in ("allow_once", "allow_always"):
            return action
        return "deny"
    except asyncio.CancelledError:
        _pending_confirms.pop(request_id, None)
        return "deny"
    except asyncio.TimeoutError:
        _pending_confirms.pop(request_id, None)
        return "deny"
    except Exception:
        _pending_confirms.pop(request_id, None)
        return "deny"