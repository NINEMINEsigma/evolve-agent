"""基于 FastAPI 的 WebSocket 聊天端点。

提供：
  - ``GET /health`` — 存活检查
  - ``WS /ws/chat`` — 聊天 WebSocket（LLM 未配置时回退到 echo）
  - ``create_server(ctx)`` — uvicorn.Server 实例工厂

支持流式消息转发：将 ParentAgentLoop 产生的 ``stream_delta`` / ``stream_done``
事件实时透传给前端 WebSocket 客户端。
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import sys
from pathlib import Path
from typing import * # type: ignore
from urllib.parse import parse_qs, quote

import uvicorn
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from .chat import Message, MessageType
from .message_router import MessageRouter
from abstract.tools.registry import registry
from datetime import datetime, timezone
from entity.constant import CRON_STDOUT_PREVIEW_MAX_LENGTH, SUBPROCESS_TIMEOUT_DEFAULT, UPLOAD_FILENAME_TIME_FORMAT, USER_CHARACTER_NAME
from system.context import get_runtime_context
from entry.parent_agent_loop import IncompatibleHistoryError
from entry.base_agent_loop import IMainSessionLoop

if TYPE_CHECKING:
    from entry.parent_agent_loop import ParentAgentLoop
    from entry.base_agent_loop import BaseAgentLoop
    from entry.agent_sink import FrontendSink
    from gateway.session_manager import SessionManager

logger = logging.getLogger(__name__)


def _get_sm() -> SessionManager|None:
    """返回 Application 的 SessionManager。"""
    from system.application import Application
    return Application.current().session_manager


def _get_loop(session_id: str):
    """返回指定 session 的 BaseAgentLoop（可能是 ParentAgentLoop 或 MultiAgentLoop）。"""
    sm = _get_sm()
    return sm.get_loop(session_id) if sm else None


def _get_ws(session_id: str):
    """返回指定 session 的 WebSocket sink。"""
    from system.application import Application
    sink = Application.current().frontend_sink
    return sink.get_ws(session_id) if sink else None


# agentspace 路径 — 由 main.py 在 server 启动前设置。
_agentspace_path: Path | None = None


def set_agent_loop(loop: BaseAgentLoop) -> None:
    """将 BaseAgentLoop 注入 Application 的 session_manager。

    在启动流程中调用一次，之后所有 session 由 SessionManager 管理。
    """
    from system.application import Application
    from entry.agent_sink import FrontendSink

    app = Application.current()
    if app.session_manager is None:
        logger.error("SessionManager not initialized — call Application.setup() first")
        return

    # 创建 FrontendSink 并注册到 Application
    if app.frontend_sink is None:
        app.frontend_sink = FrontendSink()


async def shutdown_subagent_orchestrator() -> None:
    """优雅停止 SubAgentOrchestrator（供 shutdown 流程调用）。"""
    try:
        from system.application import Application
        orch = Application.current().subagent_orchestrator
        if orch is not None:
            await orch.shutdown_all()
    except Exception as exc:
        logger.warning("SubAgentOrchestrator shutdown skipped: %s", exc, exc_info=True)


def get_subagent_orchestrator():
    """返回 SubAgentOrchestrator 单例（供工具层调用）。"""
    from system.application import Application
    return Application.current().subagent_orchestrator


async def push_subagent_update(
    parent_session_id: str,
    subagent_session_id: str,
    subagent_name: str,
    status: str,
    feedback: list[dict[str, str]],
    pending_approvals: list[dict[str, Any]],
    removed: bool = False,
) -> None:
    """将子 Agent 状态更新推送到前端 WebSocket。

    前端 UnifiedPanel 接收此消息并更新子会话列表。
    feedback 每项为 {\"role\": \"assistant\"|\"tool\"|\"status\", \"content\": \"...\"}
    """
    ws = _get_ws(parent_session_id)
    if ws is None:
        return
    import json as _json
    try:
        await ws.send_text(
            Message(
                type=MessageType.SUBAGENT_UPDATE,
                session_id=parent_session_id,
                result=_json.dumps({
                    "session_id": subagent_session_id,
                    "name": subagent_name,
                    "status": status,
                    "feedback": feedback,
                    "pending_approvals": pending_approvals,
                    "_removed": removed,
                }, ensure_ascii=False),
            ).to_json()
        )
    except Exception as exc:
        logger.warning("Failed to push subagent update to session=%s: %s", parent_session_id, exc, exc_info=True)


def set_agentspace_path(path: str | Path) -> None:
    """设置文件上传的目标目录（ws: 命名空间的根）。"""
    global _agentspace_path
    _agentspace_path = Path(path)
    _agentspace_path.mkdir(parents=True, exist_ok=True)


def configure_sessions(store_path: str | None = None) -> None:
    """配置 session 存储目录并重新加载持久化的 session。"""
    if store_path:
        sm = _get_sm()
        if sm:
            sm.set_store_dir(store_path)


async def _send_tool_event(
    session_id: str, event_type: str, tool_name: str, payload: str,
) -> None:
    """向前端 WebSocket 推送 tool_call 或 tool_result 事件。

    对已中断的 session 静默丢弃事件，
    防止前端在用户点击停止后收到过期的工具通知。
    """
    if event_type not in ("stream_delta", "usage_update"):
        logger.info("[ws push] session=%s type=%s tool=%s payload_len=%d", session_id, event_type, tool_name, len(payload))
    # 如果 session 已被中断，跳过发送工具事件。
    loop = _get_loop(session_id)
    if loop is not None:
        if loop.loop.is_interrupted():
            return

    ws: WebSocket | None = _get_ws(session_id)
    if ws is None:
        return
    # Handle assistant_text event type specially via SYSTEM message
    if event_type == "assistant_text":
        msg = Message(
            type=MessageType.SYSTEM,
            session_id=session_id,
            content=json.dumps({"assistant_text": payload}),
        )
        try:
            await ws.send_text(msg.to_json())
        except Exception:
            logger.warning("Failed to push assistant_text to session=%s", session_id, exc_info=True)
        return

    # Handle usage update events
    if event_type == "usage_update":
        try:
            json.loads(payload)
        except json.JSONDecodeError:
            return
        msg = Message(
            type=MessageType.SYSTEM,
            session_id=session_id,
            content=payload,
        )
        try:
            await ws.send_text(msg.to_json())
        except Exception:
            logger.warning("Failed to push usage_update to session=%s", session_id, exc_info=True)
        return

    # Handle task_progress events
    data: dict | None
    if event_type == "task_progress":
        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            data = None
        msg = Message(
            type=MessageType.TASK_PROGRESS,
            session_id=session_id,
            tool=tool_name,
            result=(payload if data else None),
        )
        try:
            await ws.send_text(msg.to_json())
        except Exception:
            logger.warning("Failed to push task_progress to session=%s", session_id, exc_info=True)
        return

    # Handle clipboard_display events
    if event_type == "clipboard_display":
        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            data = None
        msg = Message(
            type=MessageType.CLIPBOARD_DISPLAY,
            session_id=session_id,
            tool=tool_name,
            result=(payload if data else None),
        )
        try:
            await ws.send_text(msg.to_json())
        except Exception:
            logger.warning("Failed to push clipboard_display to session=%s", session_id, exc_info=True)
        return

    # Handle stream delta events
    if event_type == "stream_delta":
        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            data = None
        msg = Message(
            type=MessageType.STREAM_DELTA,
            session_id=session_id,
            stream_id=(data.get("stream_id") if data else None),
            delta=(data.get("delta") if data else None),
            reasoning_delta=(data.get("reasoning_delta") if data else None),
            content=(json.dumps({"tool_call": data["tool_call"]}, ensure_ascii=False)
                     if data and data.get("tool_call") else None),
            character_name=(data.get("character_name") if data else None),
        )
        try:
            await ws.send_text(msg.to_json())
        except Exception:
            logger.warning("Failed to push stream_delta to session=%s", session_id, exc_info=True)
        return

    # Handle stream done events
    if event_type == "stream_done":
        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            data = None
        msg = Message(
            type=MessageType.STREAM_DONE,
            session_id=session_id,
            stream_id=(data.get("stream_id") if data else None),
            finish_reason=(data.get("finish_reason") if data else None),
        )
        try:
            await ws.send_text(msg.to_json())
        except Exception:
            logger.warning("Failed to push stream_done to session=%s", session_id, exc_info=True)
        return

    msg_type: MessageType = MessageType.TOOL_CALL if event_type == "tool_call" else MessageType.TOOL_RESULT
    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        data = None

    # tool_result 当前会被完整发送
    msg: Message = Message(
        type=msg_type,
        session_id=session_id,
        tool=tool_name,
        args=data if event_type == "tool_call" else None,
        result=(payload if event_type == "tool_result" else None),
        emoji=registry.get_emoji(tool_name) if event_type == "tool_call" else None,
    )
    try:
        await ws.send_text(msg.to_json())
        if event_type not in ("stream_delta", "usage_update"):
            logger.info("[ws push ok] session=%s type=%s tool=%s", session_id, event_type, tool_name)
    except Exception:
        if event_type not in ("stream_delta", "usage_update"):
            logger.warning("[ws push fail] session=%s type=%s tool=%s", session_id, event_type, tool_name)
        logger.warning("Failed to push %s event to session=%s", event_type, session_id, exc_info=True)  # 客户端已断开 — 忽略

# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------


import asyncio
from contextlib import asynccontextmanager


@asynccontextmanager
async def _app_lifespan(app: FastAPI):
    """FastAPI 生命周期管理：启动 session 清理任务，关闭时取消。

    Note: 进化关闭（exit -1）期间，uvicorn 会取消所有待处理
    handler task。日志中出现的 asyncio.CancelledError 噪声
    是无害且预期的 — 仅表示 gateway 正在拆除其事件循环。
    """
    yield


app: FastAPI = FastAPI(title="Evolve Agent Gateway", lifespan=_app_lifespan)

# ---------------------------------------------------------------------------
# 构建前端产物发现
# ---------------------------------------------------------------------------

_FRONTEND_DIST: Path = Path(__file__).resolve().parent.parent / "frontend" / "dist"


def _compute_build_hash() -> str:
    """计算构建后 index.html 的哈希值，用于缓存破坏检测。"""
    idx: Path = _FRONTEND_DIST / "index.html"
    if not idx.exists():
        return ""
    try:
        return hashlib.md5(idx.read_bytes()).hexdigest()[:12]
    except Exception:
        logger.warning("Failed to compute frontend build hash", exc_info=True)
        return ""


_BUILD_HASH: str = _compute_build_hash()

if _FRONTEND_DIST.is_dir():
    assets_dir: Path = _FRONTEND_DIST / "assets"
    if assets_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")
    logger.info("Frontend dist found at %s (build=%s)", _FRONTEND_DIST, _BUILD_HASH or "unknown")

# ---------------------------------------------------------------------------
# Agentspace lock & operation log
# ---------------------------------------------------------------------------

import time as _time

_agentspace_lock: dict = {"locked": False, "locked_by": None, "locked_at": None}
"""agentspace 互斥锁状态。agent 工具调用链通过 acquire/release 管理。"""

_agentspace_pending_changes: dict[str, str] = {}
"""用户操作日志（内存中维护最终状态）: path -> operation (edit/create/delete/rename)"""


def _to_logical_path(relative: str) -> str:
    """将 API 传入的相对路径转换为 Sandbox 逻辑路径。

    去除首尾 /，拒绝包含 .. 或绝对路径的输入，返回 ws:{relative}。
    """
    if not relative:
        return "ws:"
    cleaned = relative.strip("/")
    if ".." in cleaned.split("/") or cleaned.startswith("/"):
        raise ValueError(f"Invalid path: {relative!r}")
    return f"ws:{cleaned}"


def _record_agentspace_change(operation: str, path: str, old_path: str | None = None) -> None:
    """记录用户对 agentspace 的操作。按路径合并最终状态。

    规则：
    - 同路径后操作覆盖前操作
    - 创建后被删除可抵消
    - 重命名清除旧路径
    """
    # TODO: 需要检查当前逻辑是否正确
    global _agentspace_pending_changes
    if _agentspace_lock["locked"]:
        return
    op = operation
    if op == "rename" and old_path:
        _agentspace_pending_changes.pop(old_path, None)
        _agentspace_pending_changes[path] = "edit"
    elif op == "delete":
        existing = _agentspace_pending_changes.get(path)
        if existing == "create":
            _agentspace_pending_changes.pop(path, None)
        else:
            _agentspace_pending_changes[path] = "delete"
    elif op == "create":
        _agentspace_pending_changes[path] = "create"
    elif op == "edit":
        existing = _agentspace_pending_changes.get(path)
        if existing != "create":
            _agentspace_pending_changes[path] = "edit"


def _flush_pending_changes() -> str | None:
    """将操作日志写入 ws:.agentspace/operations.jsonl，返回变更摘要，清空内存。"""
    global _agentspace_pending_changes
    if not _agentspace_pending_changes:
        return None
    lines: list[str] = ["User changes in agentspace:"]
    label_map = {"edit": "modified", "create": "created", "delete": "deleted", "rename": "renamed"}
    for path, op in _agentspace_pending_changes.items():
        label = label_map.get(op, op)
        lines.append(f"- {label}: {path}")
    summary = "\n".join(lines)
    try:
        from system.context import get_runtime_context
        from system.sandbox import Sandbox
        ctx = get_runtime_context()
        sandbox = Sandbox(ctx)
        sandbox.write("ws:.agentspace/operations.jsonl", summary)
    except Exception as exc:
        logger.warning("Failed to flush agentspace changes to disk: %s", exc)
    _agentspace_pending_changes = {}
    return summary


def acquire_agentspace_lock(locked_by: str) -> None:
    """获取 agentspace 锁。由 agent 工具调用链入口调用。"""
    global _agentspace_lock
    _agentspace_lock["locked"] = True
    _agentspace_lock["locked_by"] = locked_by
    _agentspace_lock["locked_at"] = _time.time()
    _push_agentspace_lock_state()


def release_agentspace_lock() -> None:
    """释放 agentspace 锁。由 agent 工具调用链结束时调用。"""
    global _agentspace_lock
    _agentspace_lock["locked"] = False
    _agentspace_lock["locked_by"] = None
    _agentspace_lock["locked_at"] = None
    _push_agentspace_lock_state()


def _push_agentspace_lock_state() -> None:
    """向所有连接的 WebSocket 推送当前锁状态。"""
    try:
        from system.application import Application
        from gateway.chat import Message, MessageType
        import asyncio as _asyncio
        sink = Application.current().frontend_sink
        if sink is None:
            return
        payload = json.dumps({"locked": _agentspace_lock["locked"], "locked_by": _agentspace_lock["locked_by"]})
        for sid, ws in sink.get_all_ws().items():
            if ws is None:
                continue
            try:
                _asyncio.ensure_future(ws.send_text(
                    Message(type=MessageType.AGENTSPACE_LOCK, session_id=sid, content=payload).to_json()
                ))
            except Exception:
                pass
    except Exception as exc:
        logger.warning("Failed to push agentspace lock state: %s", exc)

# ---------------------------------------------------------------------------
# 路由
# ---------------------------------------------------------------------------


_NO_CACHE: dict[str, str] = {"Cache-Control": "no-cache, no-store, must-revalidate", "Pragma": "no-cache"}


@app.get("/")
async def index():
    """返回构建后的 React 前端，未构建时返回 HTTP 500 错误。"""
    index_html: Path = _FRONTEND_DIST / "index.html"
    if not index_html.exists():
        logger.error("Frontend not built: %s missing", index_html)
        return HTMLResponse(
            "Frontend not built. Please run the build first.",
            status_code=500,
        )
    return HTMLResponse(
        index_html.read_text(encoding="utf-8"),
        headers=_NO_CACHE,
    )


@app.get("/health")
async def health():
    return {"status": "ok", "sessions": _get_sm().count}


@app.get("/api/sessions")
async def list_sessions():
    """返回所有活跃 session 及其元数据。"""
    return {"sessions": _get_sm().get_all()}


@app.get("/api/tags")
async def list_tags():
    """返回全局已有标签列表。"""
    return {"tags": _get_sm().get_all_tags()}


@app.put("/api/sessions/{session_id}/tags")
async def update_session_tags(session_id: str, req: Request):
    """更新 session 的标签列表。"""
    body: dict = {}
    try:
        body = await req.json()
    except Exception:
        logger.warning("Failed to parse tags request body for session=%s", session_id, exc_info=True)
        body = {}
    raw_tags = body.get("tags", [])
    if not isinstance(raw_tags, list):
        return {"updated": False, "error": "tags must be an array", "session_id": session_id}
    tags: list[str] = [str(t).strip() for t in raw_tags]
    valid = _get_sm().set_session_tags(session_id, tags)
    return {"updated": True, "session_id": session_id, "tags": valid}


@app.get("/api/sessions/{session_id}/tool-resources")
async def get_session_tool_resources(session_id: str):
    """返回 session 的可恢复工具副作用资源快照。"""
    loop = _get_loop(session_id)
    if loop is None:
        return {"session_id": session_id, "task_progress": {}, "clipboard_display": {}}
    resources = loop.loop.get_tool_resources()
    return {
        "session_id": session_id,
        "task_progress": resources.get("task_progress", {}),
        "clipboard_display": resources.get("clipboard_display", {}),
    }


@app.get("/api/sessions/{session_id}/subagents")
async def get_session_subagents(session_id: str):
    """返回当前活跃子会话的快照。"""
    try:
        from system.application import Application
        orch = Application.current().subagent_orchestrator
        return {"session_id": session_id, "subagents": orch.get_snapshot(parent_session_id=session_id)}
    except Exception:
        return {"session_id": session_id, "subagents": {}}


@app.post("/api/confirm/{request_id}")
async def http_confirm(request_id: str, req: Request):
    """通过 HTTP 处理确认响应（独立于 WebSocket 连接状态）。"""
    body: dict = {}
    try:
        body = await req.json()
    except Exception:
        logger.warning("Failed to parse confirm request body for request_id=%s", request_id, exc_info=True)
        body = {}
    action: str = str(body.get("action", "deny"))
    if action not in ("allow_once", "allow_always", "deny"):
        action = "deny"
    deny_reason: str | None = str(body.get("deny_reason", "")) or None
    denied_by: str = str(body.get("denied_by", "user"))
    if action != "deny":
        deny_reason = None
    from system.application import Application
    sink = Application.current().frontend_sink
    if sink:
        sink.resolve_confirm(request_id, action, deny_reason=deny_reason, denied_by=denied_by)
    return {"resolved": True, "request_id": request_id, "action": action}


@app.post("/api/ask/{request_id}")
async def http_ask(request_id: str, req: Request):
    """通过 HTTP 处理提问响应（独立于 WebSocket 连接状态）。"""
    body: dict = {}
    try:
        body = await req.json()
    except Exception:
        logger.warning("Failed to parse ask request body for request_id=%s", request_id, exc_info=True)
        body = {}
    option: str | None = str(body.get("option")) if body.get("option") is not None else None
    custom_text: str | None = str(body.get("custom_text")) if body.get("custom_text") is not None else None
    from system.application import Application
    sink = Application.current().frontend_sink
    if sink:
        sink.resolve_ask(request_id, option=option, custom_text=custom_text)
    return {"resolved": True, "request_id": request_id, "option": option, "custom_text": custom_text}


@app.post("/api/interrupt/{session_id}")
async def http_interrupt(session_id: str):
    """通过 HTTP 处理中断请求，使其在 WS handler 被
    ``process_message()`` 阻塞时仍能生效。"""
    loop = _get_loop(session_id)
    if loop is not None:
        loop.loop.interrupt()
    return {"interrupted": True, "session_id": session_id}


@app.delete("/api/sessions/{session_id}")
async def delete_session(session_id: str):
    """删除 session 及其持久化数据。"""
    _get_sm().remove(session_id)
    loop = _get_loop(session_id)
    if loop is not None:
        loop.loop.clear_session()
    # 停止该主会话下的所有子 Agent 并清理上下文
    try:
        orch = get_subagent_orchestrator()
        await orch.shutdown_parent(session_id)
    except Exception:
        logger.warning("Failed to shutdown subagents for session=%s", session_id, exc_info=True)
    return {"deleted": True, "session_id": session_id}


@app.put("/api/sessions/{session_id}/messages/{message_index}")
async def update_session_message(session_id: str, message_index: int, req: Request):
    """编辑指定 session 中一条历史消息的正文或 visible_characters，不触发重新生成。"""
    body: dict = {}
    try:
        body = await req.json()
    except Exception:
        logger.warning("Failed to parse edit message request body for session=%s", session_id, exc_info=True)
        body = {}
    content = body.get("content")
    visible_characters = body.get("visible_characters")
    info = _get_sm().get(session_id)
    if info and info.get("status") == "archived":
        result = {"updated": False, "error": "archived session cannot be edited", "session_id": session_id}
        return HTMLResponse(
            json.dumps(result, ensure_ascii=False),
            media_type="application/json",
            status_code=403,
        )
    loop = _get_loop(session_id)
    if loop is None:
        return {"updated": False, "error": "agent loop not ready", "session_id": session_id}
    result = loop.loop.edit_session_message(message_index, content, visible_characters)
    status_code = 200 if result.get("updated") else 400
    return HTMLResponse(
        json.dumps(result, ensure_ascii=False),
        media_type="application/json",
        status_code=status_code,
    )


@app.delete("/api/sessions/{session_id}/messages")
async def delete_session_messages(session_id: str, count: int = 1):
    """删除最后 count 个逻辑轮次的消息（从倒数第 count 条 user 起，覆盖其后所有 tool/assistant）。"""
    info = _get_sm().get(session_id)
    if info and info.get("status") == "archived":
        result = {"deleted": False, "error": "archived session"}
        return HTMLResponse(
            json.dumps(result, ensure_ascii=False),
            media_type="application/json",
            status_code=403,
        )
    loop = _get_loop(session_id)
    if loop is None:
        return {"deleted": False, "error": "agent loop not ready"}
    result = loop.loop.delete_session_messages(count)
    status_code = 200 if result.get("deleted") else 400
    return HTMLResponse(
        json.dumps(result, ensure_ascii=False),
        media_type="application/json",
        status_code=status_code,
    )


@app.post("/api/sessions/{session_id}/regenerate")
async def regenerate_response(session_id: str):
    """重新生成最后一条 user 消息的响应：截断历史，重新调用 process_message。"""
    info = _get_sm().get(session_id)
    if info and info.get("status") == "archived":
        result = {"regenerate": False, "error": "archived session"}
        return HTMLResponse(
            json.dumps(result, ensure_ascii=False),
            media_type="application/json",
            status_code=403,
        )
    loop = _get_loop(session_id)
    if loop is None:
        return {"regenerate": False, "error": "agent loop not ready"}
    # 先截断历史
    result = loop.loop.regenerate_response()
    if not result.get("regenerate"):
        return HTMLResponse(
            json.dumps(result, ensure_ascii=False),
            media_type="application/json",
            status_code=400,
        )
    content: str = result.get("last_user_content", "")
    # 通知前端裁剪本地消息
    ws = _get_ws(session_id)
    if ws:
        try:
            await ws.send_text(
                Message(
                    type=MessageType.SYSTEM,
                    session_id=session_id,
                    content=json.dumps({
                        "regenerate_trim": True,
                        "keep_count": result.get("remaining_count", 0),
                    }),
                ).to_json()
            )
        except Exception:
            logger.warning("Failed to send regenerate_trim to session=%s", session_id, exc_info=True)
        # 复用 process_message 流程（流式事件自动推送到 ws）
        # 历史已包含最后一条 user 消息，避免重复追加
        reply: str = await loop.loop.process_message(
            content,
            skip_append=True,
            visible_characters=result.get("visible_characters"),
            response_characters=result.get("response_characters"),
        )
        from system.application import Application
        sink = Application.current().frontend_sink
        if sink is not None and reply:
            await sink.emit_assistant_message(
                session_id, reply, loop.current_character_agent,
            )
    return {"regenerate": True, "session_id": session_id}


@app.put("/api/sessions/{session_id}/title")
async def update_session_title(session_id: str, req: Request):
    """手动重命名 session。"""
    title: str = ""
    try:
        body = await req.json()
        title = str(body.get("title", "")).strip()[:50]
    except Exception:
        logger.warning("Failed to parse title request body for session=%s", session_id, exc_info=True)
        title = ""
    _get_sm().update_title(session_id, title)
    return {"updated": True, "session_id": session_id, "title": title}


@app.post("/api/sessions/{session_id}/auto-title")
async def auto_title_session(session_id: str):
    """请求 LLM 根据 session 消息自动生成标题。"""
    title: str = ""
    loop = _get_loop(session_id)
    if loop is not None:
        title = await loop.auto_generate_title()
    else:
        logger.warning("Failed to auto-generate title for session=%s", session_id)
    if title:
        _get_sm().update_title(session_id, title)
    return {"title": title, "session_id": session_id}


@app.post("/api/sessions/{session_id}/auto-tags")
async def auto_tags_session(session_id: str):
    """请求根据 session 摘要重新生成标签并持久化。"""
    tags: list[str] = []
    loop = _get_loop(session_id)
    if loop is not None:
        tags = await loop.regenerate_session_tags()
    else:
        logger.warning("Failed to auto-generate tags for session=%s", session_id)
    return {"tags": tags, "session_id": session_id}


@app.post("/api/sessions/{session_id}/regenerate-summary")
async def regenerate_summary_endpoint(session_id: str):
    """重新生成指定会话的摘要。"""
    loop = _get_loop(session_id)
    if loop is not None:
        summary = await loop.regenerate_summary_for_session(session_id)
        return {"success": bool(summary), "summary": summary}
    return {"success": False, "error": "agent loop not ready", "session_id": session_id}


@app.post("/api/sessions/{session_id}/terminate")
async def terminate_session_endpoint(session_id: str):
    """手动终结指定会话：归档 + 压缩（生成摘要），不旋转。"""
    # 先停止该父会话的所有子 Agent 会话
    try:
        orch = get_subagent_orchestrator()
        await orch.terminate_parent(parent_session_id=session_id)
    except Exception:
        logger.warning("Failed to terminate subagents for session=%s", session_id, exc_info=True)
    loop = _get_loop(session_id)
    if loop is not None:
        result = await loop.loop.terminate_session()
        return result
    return {"terminated": False, "error": "agent loop not ready", "session_id": session_id}


@app.post("/api/sessions/{session_id}/pin")
async def pin_session_endpoint(session_id: str):
    """切换 session 置顶状态。"""
    pinned: bool = _get_sm().toggle_pin(session_id)
    return {"pinned": pinned, "session_id": session_id}


@app.post("/api/sessions/merge")
async def merge_sessions_endpoint(req: Request):
    """合并多个会话（或单源分支）。

    Body: {"sources": ["sid1", "sid2", ...]}
    """
    body: dict = {}
    try:
        body = await req.json()
    except Exception:
        logger.warning("Failed to parse merge request body", exc_info=True)
    sources: list[str] = body.get("sources", [])
    if not sources:
        return {"error": "sources array required", "merged": False}
    err = _get_sm().validate_merge_sources(sources)
    if err:
        return {"error": err, "merged": False}
    sm = _get_sm()
    if sm is not None:
        for _, loop in sm.get_all_loops().items():
            result = await loop.loop.merge_sessions(sources)
            return result
    return {"error": "agent loop not ready", "merged": False}


@app.post("/api/sessions/{session_id}/branch")
async def branch_session_endpoint(session_id: str):
    """从指定会话创建分支延续（单源 merge 的快捷端点）。"""
    err = _get_sm().validate_merge_sources([session_id])
    if err:
        return {"error": err, "merged": False}
    loop = _get_loop(session_id)
    if loop is not None:
        result = await loop.loop.merge_sessions([session_id])
        return result
    return {"error": "agent loop not ready", "session_id": session_id}


@app.get("/api/sessions/{session_id}/background-tasks")
async def list_background_tasks_endpoint(session_id: str):
    """列出指定会话的所有后台任务。"""
    from component.extools.background_service import list_background_tasks
    tasks = list_background_tasks(session_id)
    return {"tasks": tasks}


@app.post("/api/sessions/{session_id}/background-tasks/{task_id}/stop")
async def stop_background_task_endpoint(session_id: str, task_id: str):
    """停止指定的后台任务。"""
    from component.extools.background_service import stop_background_task
    result = stop_background_task(task_id)
    return result


@app.get("/api/sessions/{session_id}/cron-tasks")
async def list_cron_tasks_endpoint(session_id: str):
    """列出指定会话的所有定时任务。"""
    from component.extools.cron_tools import list_cron_tasks_for_session
    tasks = list_cron_tasks_for_session(session_id)
    return {"tasks": tasks}


@app.post("/api/sessions/{session_id}/cron-tasks/{task_id}/trigger")
async def trigger_cron_task_endpoint(session_id: str, task_id: str):
    """立即触发指定的定时任务执行一次。"""
    from component.extools.cron_tools import trigger_cron_task
    result = trigger_cron_task(session_id, task_id)
    return result


@app.post("/api/sessions/{session_id}/cron-tasks/{task_id}/cancel")
async def cancel_cron_task_endpoint(session_id: str, task_id: str):
    """取消指定的定时任务。"""
    from component.extools.cron_tools import cancel_cron_task
    result = cancel_cron_task(session_id, task_id)
    return result


@app.post("/api/file-picker")
async def file_picker():
    """打开原生 Windows 文件选择对话框（仅本地 localhost 有效），
    选中的文件通过硬链接（同盘）或复制（跨盘）放入 uploads 目录。"""
    import json
    import os
    import shutil
    import subprocess
    import sys
    import textwrap
    import uuid
    from pathlib import Path

    script: str = textwrap.dedent("""\
    import json, tkinter as tk
    from tkinter import filedialog
    root = tk.Tk()
    root.withdraw()
    root.attributes('-topmost', True)
    files = filedialog.askopenfilenames(title="选择要上传的文件")
    root.destroy()
    print(json.dumps(list(files)))
    """)

    loop = asyncio.get_event_loop()
    try:
        result = await loop.run_in_executor(
            None,
            lambda: subprocess.run(
                [sys.executable, "-c", script],
                capture_output=True,
                text=True,
                timeout=SUBPROCESS_TIMEOUT_DEFAULT,
            ),
        )
        if result.returncode != 0:
            logger.warning("File dialog subprocess failed: %s", result.stderr.strip())
            return {"uploaded": False, "error": "dialog_failed"}
        paths: list[str] = json.loads(result.stdout.strip())
    except subprocess.TimeoutExpired:
        logger.warning("File dialog subprocess timed out")
        return {"uploaded": False, "error": "dialog_timeout"}
    except Exception as exc:
        logger.warning("File dialog exception: %s", exc)
        return {"uploaded": False, "error": f"dialog_exception: {exc}"}

    if not paths:
        return {"uploaded": False, "files": []}

    if not _agentspace_path:
        logger.error("agentspace path not set, cannot accept file picker uploads")
        return {"uploaded": False, "error": "agentspace_not_configured"}

    upload_dir: Path = _agentspace_path / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)

    results: list[dict] = []
    for p in paths:
        src: Path = Path(p)
        if not src.is_file():
            continue
        safe_name: str = src.name
        timestamp: str = datetime.now(timezone.utc).strftime(UPLOAD_FILENAME_TIME_FORMAT)
        unique_name: str = f"{timestamp}_{uuid.uuid4().hex[:8]}_{safe_name}"
        dest: Path = upload_dir / unique_name
        method: str = "hardlink"
        try:
            os.link(str(src), str(dest))
        except OSError:
            try:
                shutil.copy2(str(src), str(dest))
                method = "copy"
            except OSError as exc:
                results.append({"uploaded": False, "filename": safe_name, "error": str(exc)})
                continue

        logger.info("File %s | picker src=%s dest=%s", method, src, dest)
        results.append({
            "uploaded": True,
            "path": f"ws:uploads/{unique_name}",
            "filename": safe_name,
            "size": dest.stat().st_size,
            "method": method,
        })

    return {"uploaded": True, "files": results}


@app.get("/uploads/{file_path:path}")
async def serve_workspace_file(file_path: str):
    """提供 ws: 命名空间下文件的 HTTP 访问，供前端展示图片等静态文件。"""
    if not _agentspace_path:
        return HTMLResponse("Upload service not available", status_code=503)
    # 防止路径遍历
    resolved = (_agentspace_path / file_path).resolve()
    if not str(resolved).startswith(str(_agentspace_path.resolve())):
        return HTMLResponse("Forbidden", status_code=403)
    if not resolved.exists() or not resolved.is_file():
        return HTMLResponse("File not found", status_code=404)
    return FileResponse(str(resolved))


@app.get("/downloads/{file_path:path}")
async def download_workspace_file(file_path: str):
    """提供 ws: 命名空间下文件的 HTTP 下载（强制 Content-Disposition: attachment）。"""
    if not _agentspace_path:
        return HTMLResponse("Download service not available", status_code=503)
    # 防止路径遍历
    resolved = (_agentspace_path / file_path).resolve()
    if not str(resolved).startswith(str(_agentspace_path.resolve())):
        return HTMLResponse("Forbidden", status_code=403)
    if not resolved.exists() or not resolved.is_file():
        return HTMLResponse("File not found", status_code=404)
    filename = resolved.name
    # RFC 5987: non-ASCII filename needs filename* with UTF-8 encoding
    safe_ascii = re.sub(r'[^\x20-\x7e]', '_', filename)
    return FileResponse(
        str(resolved),
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": (
                f'attachment; filename="{safe_ascii}"; '
                f"filename*=UTF-8''{quote(filename, safe='')}"
            ),
        },
    )


@app.post("/api/shutdown-approval-model")
async def shutdown_approval_model_endpoint():
    """关闭本地审批模型 (llama-server) 以释放显存。"""
    try:
        from system.application import Application
        mgr = Application.current().approval_backend_manager
        if mgr is not None:
            await mgr.shutdown()
            return {"ok": True}
        return {"ok": False, "error": "approval_backend_manager not available"}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


# ---------------------------------------------------------------------------
# Agentspace file API
# ---------------------------------------------------------------------------


@app.get("/api/agentspace/list")
async def agentspace_list(path: str = ""):
    """列出 agentspace 目录内容。

    返回 { entries: [{ name: string, type: "file"|"dir" }] }。
    目录不存在时返回空列表。
    """
    try:
        logical = _to_logical_path(path)
        from system.context import get_runtime_context
        from system.sandbox import Sandbox
        sandbox = Sandbox(get_runtime_context())
        names = sandbox.list_dir(logical)
        entries: list[dict[str, str]] = []
        for name in names:
            entry_path = f"{logical}/{name}" if logical != "ws:" else f"ws:{name}"
            entry_type = "dir" if sandbox.is_dir(entry_path) else "file"
            entries.append({"name": name, "type": entry_type})
        return {"entries": entries}
    except (ValueError, PermissionError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.warning("agentspace list failed for path=%r: %s", path, exc)
        raise HTTPException(status_code=500, detail="Internal error")


@app.get("/api/agentspace/read")
async def agentspace_read(path: str = ""):
    """读取 agentspace 文件内容。

    返回 { content: string }。文件不存在时返回 404。
    """
    if not path:
        raise HTTPException(status_code=400, detail="path required")
    try:
        logical = _to_logical_path(path)
        from system.context import get_runtime_context
        from system.sandbox import Sandbox
        sandbox = Sandbox(get_runtime_context())
        content = sandbox.read(logical, limit=0)
        return {"content": content}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except PermissionError as exc:
        if "not found" in str(exc).lower():
            raise HTTPException(status_code=404, detail=str(exc))
        raise HTTPException(status_code=403, detail=str(exc))
    except Exception as exc:
        logger.warning("agentspace read failed for path=%r: %s", path, exc)
        raise HTTPException(status_code=500, detail="Internal error")


@app.post("/api/agentspace/write")
async def agentspace_write(req: Request):
    """写入/覆盖 agentspace 文件。

    body: { path: string, content: string } → { success: true }
    锁定时禁止写入。
    """
    body = await req.json()
    path = body.get("path", "")
    content = body.get("content", "")
    if not path:
        raise HTTPException(status_code=400, detail="path required")
    if _agentspace_lock["locked"]:
        raise HTTPException(status_code=423, detail="Agentspace is locked by agent")
    try:
        logical = _to_logical_path(path)
        from system.context import get_runtime_context
        from system.sandbox import Sandbox
        sandbox = Sandbox(get_runtime_context())
        sandbox.write(logical, content)
        _record_agentspace_change("edit", path)
        return {"success": True}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except Exception as exc:
        logger.warning("agentspace write failed for path=%r: %s", path, exc)
        raise HTTPException(status_code=500, detail="Internal error")


@app.post("/api/agentspace/mkdir")
async def agentspace_mkdir(req: Request):
    """创建 agentspace 目录（含父目录）。

    body: { path: string } → { success: true }
    锁定时禁止创建。
    """
    body = await req.json()
    path = body.get("path", "")
    if not path:
        raise HTTPException(status_code=400, detail="path required")
    if _agentspace_lock["locked"]:
        raise HTTPException(status_code=423, detail="Agentspace is locked by agent")
    try:
        logical = _to_logical_path(path)
        from system.context import get_runtime_context
        from system.sandbox import Sandbox
        sandbox = Sandbox(get_runtime_context())
        sandbox.create_folder(logical, parents=True)
        _record_agentspace_change("create", path)
        return {"success": True}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except Exception as exc:
        logger.warning("agentspace mkdir failed for path=%r: %s", path, exc)
        raise HTTPException(status_code=500, detail="Internal error")


@app.post("/api/agentspace/delete")
async def agentspace_delete(req: Request):
    """删除 agentspace 文件或空目录。

    body: { path: string } → { success: true }
    锁定时禁止删除。
    """
    body = await req.json()
    path = body.get("path", "")
    if not path:
        raise HTTPException(status_code=400, detail="path required")
    if _agentspace_lock["locked"]:
        raise HTTPException(status_code=423, detail="Agentspace is locked by agent")
    try:
        logical = _to_logical_path(path)
        from system.context import get_runtime_context
        from system.sandbox import Sandbox
        sandbox = Sandbox(get_runtime_context())
        if sandbox.is_dir(logical):
            sandbox.delete_folder(logical)
        else:
            sandbox.delete(logical)
        _record_agentspace_change("delete", path)
        return {"success": True}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except Exception as exc:
        logger.warning("agentspace delete failed for path=%r: %s", path, exc)
        raise HTTPException(status_code=500, detail="Internal error")


@app.post("/api/agentspace/rename")
async def agentspace_rename(req: Request):
    """重命名/移动 agentspace 文件或目录。

    body: { oldPath: string, newPath: string } → { success: true }
    锁定时禁止重命名。
    """
    body = await req.json()
    old_path = body.get("oldPath", "")
    new_path = body.get("newPath", "")
    if not old_path or not new_path:
        raise HTTPException(status_code=400, detail="oldPath and newPath required")
    if _agentspace_lock["locked"]:
        raise HTTPException(status_code=423, detail="Agentspace is locked by agent")
    try:
        old_logical = _to_logical_path(old_path)
        new_logical = _to_logical_path(new_path)
        from system.context import get_runtime_context
        from system.sandbox import Sandbox
        sandbox = Sandbox(get_runtime_context())
        sandbox.move(old_logical, new_logical)
        _record_agentspace_change("rename", new_path, old_path=old_path)
        return {"success": True}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except Exception as exc:
        logger.warning("agentspace rename failed old=%r new=%r: %s", old_path, new_path, exc)
        raise HTTPException(status_code=500, detail="Internal error")


@app.get("/api/agentspace/lock")
async def agentspace_lock_status():
    """查询 agentspace 锁状态。

    返回 { locked: bool, locked_by: string|null }
    """
    return {
        "locked": _agentspace_lock["locked"],
        "locked_by": _agentspace_lock["locked_by"],
    }


@app.get("/{full_path:path}")
async def spa_fallback(full_path: str):
    """SPA 客户端路由的兜底处理。

    必须在所有 API 路由之后定义，确保 API 优先匹配。
    返回构建后的 index.html，前端未构建时返回 404。
    """
    index_html: Path = _FRONTEND_DIST / "index.html"
    if index_html.exists():
        return HTMLResponse(
            index_html.read_text(encoding="utf-8"),
            headers=_NO_CACHE,
        )
    from fastapi import HTTPException
    raise HTTPException(status_code=404, detail=f"Not found: {full_path}")


@app.websocket("/ws/chat")
async def ws_chat(ws: WebSocket) -> None:
    """WebSocket 聊天端点：接收用户消息，转发给 AgentLoop，返回回复。"""
    await ws.accept()
    # 如果客户端请求恢复之前的 session
    qs: dict[str, list[str]] = parse_qs(ws.scope.get("query_string", b"").decode())
    resume: str | None = qs.get("resume", [None])[0]
    sid: str
    if resume and _get_sm().exists(resume):
        sid = resume
    else:
        # 尝试从磁盘加载（server 重启后恢复）
        if resume:
            _get_sm().load_from_disk()
            if _get_sm().exists(resume):
                sid = resume
            else:
                sid = _get_sm().create()
        else:
            sid = _get_sm().create()

    from system.application import Application as _AppInnerNew
    _AppInnerNew.current().frontend_sink.register_ws(sid, ws)  # 注册用于工具事件流推送
    logger.info("WebSocket connected | session=%s", sid)

    # 为当前 session 创建专属 ParentAgentLoop，使 proxy 能正确路由调用
    try:
        from system.application import Application as _AppInner
        _app_inner = _AppInner.current()
        if _app_inner.session_manager and _app_inner.frontend_sink:
            _store_inner = _app_inner.runtime_context.workspace / "sessions"
            _app_inner.session_manager.create_session(
                session_id=sid,
                frontend_sink=_app_inner.frontend_sink,
                history_store_dir=_store_inner,
            )
    except IncompatibleHistoryError as exc:
        logger.warning("Removing incompatible session from index: %s", exc.session_id)
        _sm = _get_sm()
        if _sm is not None:
            _sm.remove_from_index(exc.session_id)
        try:
            await ws.send_text(
                Message(
                    type=MessageType.ERROR,
                    session_id=sid,
                    message=f"会话 {exc.session_id} 的历史格式不兼容，已从索引移除。请运行迁移脚本后重连。",
                ).to_json()
            )
            await ws.close()
        except Exception:
            logger.exception("Failed to notify frontend about incompatible history for session=%s", exc.session_id)
        return
    except Exception as exc:
        logger.warning("Failed to create session loop for %s: %s", sid, exc)

    try:
        # 发送欢迎消息
        await ws.send_text(
            Message(
                type=MessageType.SYSTEM,
                session_id=sid,
                content="Connected to Evolve Agent",
            ).to_json()
        )

        # 发送构建哈希，使前端能检测进化并自动重载
        if _BUILD_HASH:
            await ws.send_text(
                Message(
                    type=MessageType.SYSTEM,
                    session_id=sid,
                    content=json.dumps({"build_hash": _BUILD_HASH}),
                ).to_json()
            )

        # 发送服务端信息：上下文窗口、审批模型配置
        try:
            from system.context import get_runtime_context
            ctx = get_runtime_context()
            _local_disabled = {"", "false", "0", "no"}
            _local_raw = (ctx.approval_model_path or "").strip().lower()
            if _local_raw not in _local_disabled:
                model_name: str = Path(ctx.approval_model_path).name if ctx.approval_model_path else ""
                model_available: bool = bool(ctx.approval_model_path)
            else:
                model_name = ctx.approval_remote_model or ""
                model_available = bool(ctx.approval_remote_base_url and ctx.approval_remote_model)
            await ws.send_text(
                Message(
                    type=MessageType.SYSTEM,
                    session_id=sid,
                    content=json.dumps({
                        "server_info": {
                            "llm_max_context_tokens": ctx.llm_max_context_tokens,
                            "llm_model": ctx.llm_model,
                            "approval_model_name": model_name,
                            "approval_model_available": model_available,
                        },
                    }),
                ).to_json()
            )
        except Exception:
            logger.warning("RuntimeContext not initialized, skipping server_info push", exc_info=True)  # fallback 模式可能无 LLM

        # 恢复 session 时回放会话历史，使前端不为空白
        loop = _get_loop(resume)
        if resume and _get_sm().exists(resume) and loop is not None:
            history: list[dict] = loop.get_session_messages()
            usage: int = loop.get_token_usage()
            context: int = loop.get_context_tokens()
            processing: bool = loop.is_processing()
            # 检查是否多 agent 模式，携带 agents 列表
            agents_info: list[str] | None = None
            from entry.multi_agent_loop import MultiAgentLoop
            if isinstance(loop, MultiAgentLoop):
                agents_info = list(loop._agent_names)
            await ws.send_text(
                Message(
                    type=MessageType.SYSTEM,
                    session_id=sid,
                    content=json.dumps({
                        "session_history": history,
                        "token_usage": usage,
                        "context_tokens": context,
                        "processing": processing,
                        "agents": agents_info,
                    }, ensure_ascii=False),
                ).to_json()
            )

        # 创建消息路由器 — 所有消息处理委托给 MessageRouter
        router = MessageRouter(ws, sid, agentspace_path=_agentspace_path)

        while True:
            # Note: 进化关闭（exit -1）期间，uvicorn 会取消所有待处理
            # handler task。从 receive_text() 传播的 asyncio.CancelledError
            # 是无害且预期的 — 仅表示 gateway 正在拆除其事件循环。
            raw: str = await ws.receive_text()

            # 解析接收到的消息
            msg: Message
            try:
                msg = Message.from_json(raw)
            except (ValueError, KeyError) as exc:
                await ws.send_text(
                    Message(
                        type=MessageType.ERROR,
                        session_id=sid,
                        message=f"Invalid message: {exc}",
                    ).to_json()
                )
                continue

            ok: bool = await router.route(msg)
            if not ok:
                return
            # session 旋转后同步 sid
            sid = router.sid

    except WebSocketDisconnect:
        logger.info("WebSocket disconnected | session=%s", sid)
    except asyncio.CancelledError:
        # uvicorn 关闭时取消 handler task，属于正常退出，无需记录为错误
        logger.debug("WebSocket handler cancelled for session=%s (server shutting down)", sid)
    except RuntimeError as exc:
        # 收到非 text 消息（如 binary）或连接已关闭时仍尝试读写
        logger.info("WebSocket runtime error for session=%s: %s", sid, exc)
    finally:
        from system.application import Application
        _sink = Application.current().frontend_sink
        if _sink:
            _sink._deny_session_confirms(sid)
            _sink._deny_session_asks(sid)
        # 修复：只有当前 sink 仍是本 ws 实例时才清理，避免切换会话时旧 ws 关闭 pop 掉新 ws
        if _get_ws(sid) is ws:
            from system.application import Application as _FSAppEnd
            _FSAppEnd.current().frontend_sink.unregister_ws(sid)


# ---------------------------------------------------------------------------
# Server 工厂
# ---------------------------------------------------------------------------


def create_server(host: str | None = None, port: int | None = None) -> uvicorn.Server:
    """创建 uvicorn Server 实例。

    *host* 和 *port* 优先使用传入值，否则从 RuntimeContext 获取。
    后者通过编排器（run.py）传递的 CLI 参数接收。

    不会启动 server — 调用方应 ``await server.serve()``
    作为 asyncio task 运行。
    """
    ctx = get_runtime_context()
    host = host or ctx.gateway_host
    port = port or ctx.gateway_port
    config: uvicorn.Config = uvicorn.Config(
        app=app,
        host=host,
        port=port,
        log_level="warning",  # 抑制 uvicorn 自身的访问日志
    )
    return uvicorn.Server(config)