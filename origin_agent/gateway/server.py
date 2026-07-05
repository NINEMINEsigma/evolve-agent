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
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from .chat import Message, MessageType
from datetime import datetime, timezone
from entity.constant import CRON_STDOUT_PREVIEW_MAX_LENGTH, SUBPROCESS_TIMEOUT_DEFAULT, UPLOAD_FILENAME_TIME_FORMAT, USER_CHARACTER_NAME
from system.context import get_runtime_context
from entry.parent_agent_loop import IncompatibleHistoryError

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


def _extract_text(content: Any) -> str:
    """从消息 content 中提取纯文本（处理 string 和 list 两种格式）。"""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(str(block.get("text", "")))
        return "\n".join(parts)
    return str(content or "")



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
    if loop is not None and hasattr(loop, "is_interrupted"):
        try:
            if loop.is_interrupted():
                return
        except Exception:
            logger.warning("Failed to check interrupt state for session=%s", session_id, exc_info=True)

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
    if event_type == "task_progress":
        data: dict | None
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
        data: dict | None
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
        data: dict | None
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
    data: dict | None
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

# ---- dashboard 路由 ----
try:
    from dashboard.server import register_dashboard_routes
    register_dashboard_routes(app)
    logger.info("Dashboard routes registered → /dashboard")
except Exception as exc:
    logger.warning("Dashboard unavailable: %s", exc)

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
# 路由
# ---------------------------------------------------------------------------


_NO_CACHE: dict[str, str] = {"Cache-Control": "no-cache, no-store, must-revalidate", "Pragma": "no-cache"}


@app.get("/")
async def index():
    """返回构建后的 React 前端，未构建时报错并退出。"""
    index_html: Path = _FRONTEND_DIST / "index.html"
    if not index_html.exists():
        logger.error("Frontend not built: %s missing", index_html)
        sys.exit(0)
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
    resources = loop.get_tool_resources()
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
        loop.interrupt()
    return {"interrupted": True, "session_id": session_id}


@app.delete("/api/sessions/{session_id}")
async def delete_session(session_id: str):
    """删除 session 及其持久化数据。"""
    _get_sm().remove(session_id)
    loop = _get_loop(session_id)
    if loop is not None:
        loop.clear_session()
    # 停止该主会话下的所有子 Agent 并清理上下文
    try:
        orch = get_subagent_orchestrator()
        await orch.shutdown_parent(session_id)
    except Exception:
        logger.warning("Failed to shutdown subagents for session=%s", session_id, exc_info=True)
    return {"deleted": True, "session_id": session_id}


@app.put("/api/sessions/{session_id}/messages/{message_index}")
async def update_session_message(session_id: str, message_index: int, req: Request):
    """编辑指定 session 中一条历史消息的正文，不触发重新生成。"""
    body: dict = {}
    try:
        body = await req.json()
    except Exception:
        logger.warning("Failed to parse edit message request body for session=%s", session_id, exc_info=True)
        body = {}
    content = body.get("content")
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
    result = loop.edit_session_message(message_index, content)
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
    result = loop.delete_session_messages(count)
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
    result = loop.regenerate_response()
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
        reply: str = await loop.process_message(content)
        from system.application import Application
        sink = Application.current().frontend_sink
        if sink is not None:
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
    return {"tags": tags, "session_id": session_id}


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
        result = await loop.terminate_session()
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
            result = await loop.merge_sessions(sources)
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
        result = await loop.merge_sessions([session_id])
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


# -- 文件上传处理 --------------------------------------------------------


async def _handle_file_upload(ws: WebSocket, sid: str, msg: Message) -> None:
    """处理 FILE_UPLOAD 消息：优先硬链接，fallback 到复制或 base64 解码。"""
    import base64
    import os
    import shutil
    import uuid

    filename: str = (msg.filename or "uploaded_file").strip()
    mime_type: str = (msg.mime_type or "application/octet-stream").strip()
    file_data: str = (msg.file_data or "").strip()
    local_path: str | None = msg.local_path

    # 清理文件名中的路径遍历字符
    safe_name: str = filename.replace("\\", "/").split("/")[-1]
    if not safe_name:
        safe_name = "uploaded_file"

    timestamp: str = datetime.now(timezone.utc).strftime(UPLOAD_FILENAME_TIME_FORMAT)
    unique_name: str = f"{timestamp}_{uuid.uuid4().hex[:8]}_{safe_name}"
    if not _agentspace_path:
        logger.error("agentspace path not set, cannot accept file uploads")
        await ws.send_text(
            Message(
                type=MessageType.SYSTEM,
                session_id=sid,
                content=json.dumps({"uploaded": False, "error": "agentspace_not_configured"}),
            ).to_json()
        )
        return
    upload_dir: Path = _agentspace_path / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    dest: Path = upload_dir / unique_name

    # -- 硬链接优先 ---------------------------------------------------------
    if local_path:
        src: Path = Path(local_path)
        if src.is_file():
            try:
                os.link(str(src), str(dest))
                logger.info("File hard-linked | session=%s src=%s dest=%s", sid, src, dest)
                await ws.send_text(
                    Message(
                        type=MessageType.SYSTEM,
                        session_id=sid,
                        content=json.dumps({
                            "uploaded": True,
                            "path": f"ws:uploads/{unique_name}",
                            "filename": safe_name,
                            "size": src.stat().st_size,
                            "method": "hardlink",
                        }),
                    ).to_json()
                )
                return
            except OSError as exc:
                # 跨设备等 -> 回退到复制
                logger.info("Hard link failed, fallback to copy | session=%s err=%s", sid, exc)
                try:
                    shutil.copy2(str(src), str(dest))
                    logger.info("File copied (hardlink fallback) | session=%s src=%s dest=%s", sid, src, dest)
                    await ws.send_text(
                        Message(
                            type=MessageType.SYSTEM,
                            session_id=sid,
                            content=json.dumps({
                                "uploaded": True,
                                "path": f"ws:uploads/{unique_name}",
                                "filename": safe_name,
                                "size": src.stat().st_size,
                                "method": "copy",
                            }),
                        ).to_json()
                    )
                    return
                except OSError as exc2:
                    logger.error("File copy also failed | session=%s err=%s", sid, exc2)
                    await ws.send_text(
                        Message(
                            type=MessageType.ERROR,
                            session_id=sid,
                            message=f"File link/copy failed: {exc2}",
                        ).to_json()
                    )
                    return

    # -- Base64 写入 --------------------------------------------------------
    if not file_data:
        await ws.send_text(
            Message(
                type=MessageType.ERROR,
                session_id=sid,
                message="File upload failed: file content is empty",
            ).to_json()
        )
        return

    try:
        raw_bytes: bytes = base64.b64decode(file_data)
        dest.write_bytes(raw_bytes)
    except Exception as exc:
        logger.exception("File upload failed for session=%s", sid)
        await ws.send_text(
            Message(
                type=MessageType.ERROR,
                session_id=sid,
                message=f"File save failed: {exc}",
            ).to_json()
        )
        return

    logical_path: str = f"ws:uploads/{unique_name}"
    logger.info("File uploaded (base64) | session=%s path=%s size=%d", sid, logical_path, len(raw_bytes))

    await ws.send_text(
        Message(
            type=MessageType.SYSTEM,
            session_id=sid,
            content=json.dumps({
                "uploaded": True,
                "path": logical_path,
                "filename": safe_name,
                "mime_type": mime_type,
                "size": len(raw_bytes),
            }, ensure_ascii=False),
        ).to_json()
    )


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
            await ws.send_text(
                Message(
                    type=MessageType.SYSTEM,
                    session_id=sid,
                    content=json.dumps({
                        "session_history": history,
                        "token_usage": usage,
                        "context_tokens": context,
                        "processing": processing,
                    }, ensure_ascii=False),
                ).to_json()
            )

        async def _handle_user_message(msg: Message) -> None:
            """后台处理用户消息，不阻塞 WebSocket 消息循环。"""
            nonlocal sid
            try:
                # 从首条用户消息自动生成标题
                session_info: dict | None = _get_sm().get(sid)
                if session_info and not session_info.get("title") and msg.content:
                    text_content: str = _extract_text(msg.content)
                    title: str = text_content.strip()[:30]
                    if len(text_content.strip()) > 30:
                        title += "..."
                    _get_sm().update_title(sid, title)
                _get_sm().update_last_activity(sid)
                # 拦截 archived 会话的新消息
                _session_info = _get_sm().get(sid)
                if _session_info and _session_info.get("status") == "archived":
                    await ws.send_text(
                        Message(
                            type=MessageType.ERROR,
                            session_id=sid,
                            message="This session has been archived. Please switch to the continuation session or create a new one.",
                        ).to_json()
                    )
                    return
                loop = _get_loop(sid)
                if loop is not None:
                    target_sessions: list[str] = msg.target_sessions or ["main"]
                    content = msg.content or ""

                    # 把原始用户消息追加到历史（回显由 append_user_message 内部统一完成）
                    try:
                        await loop.append_user_message(content)
                    except Exception as exc:
                        logger.warning("Failed to append user message for session=%s: %s", sid, exc)

                    # 先并行/异步转发到选中的子会话（用户直接发送）
                    subagent_tasks: list[asyncio.Task] = []
                    sub_ids: list[str] = []
                    name_map: dict[str, str] = {}
                    if any(t != "main" for t in target_sessions):
                        try:
                            orch = get_subagent_orchestrator()
                            sub_ids = [t for t in target_sessions if t != "main"]
                            also_main = "main" in target_sessions
                            # 建立 session_id -> name 映射
                            try:
                                snapshot = orch.get_snapshot(parent_session_id=sid)
                                for sess_id, info in snapshot.items():
                                    name_map[sess_id] = info.get("name", "")
                            except Exception:
                                logger.warning("Failed to get subagent snapshot for session=%s", sid, exc_info=True)
                            for sub_id in sub_ids:
                                other_ids = [o for o in sub_ids if o != sub_id]
                                other_names: list[str] = []
                                for o in other_ids:
                                    name = name_map.get(o)
                                    if name:
                                        other_names.append(name)
                                    else:
                                        logger.warning(
                                            "Skipping unnamed co-recipient session | parent=%s target=%s co_recipient=%s",
                                            sid, sub_id, o,
                                        )
                                if also_main:
                                    other_names.append("the Parent Agent (main session)")
                                subagent_tasks.append(
                                    asyncio.create_task(
                                        orch.chat_user_direct(parent_session_id=sid, session_id=sub_id, message=str(content), co_recipients=other_names),
                                        name=f"user-to-subagent-{sub_id[:16]}",
                                    )
                                )
                        except Exception as exc:
                            logger.warning("Failed to dispatch subagent messages: %s", exc)

                    # 主会话处理
                    reply: str
                    if "main" in target_sessions:
                        main_content = content
                        sub_names: list[str] = []
                        for s in sub_ids:
                            name = name_map.get(s)
                            if name:
                                sub_names.append(name)
                            else:
                                logger.warning(
                                    "Skipping unnamed sub-agent target for main session | parent=%s target=%s",
                                    sid, s,
                                )
                        if sub_names:
                            main_content = (
                                f"[This message is also shared with sub-agents: {', '.join(sub_names)}]\n\n"
                                f"{content}"
                            )
                        try:
                            reply = await loop.process_message(
                                main_content, skip_append=True
                            )
                        except Exception as exc:
                            logger.exception("Agent loop error for session=%s", sid)
                            reply = f"Internal error: {exc}"
                    else:
                        reply = "Message forwarded to sub-agent(s)."

                    # 等待子会话转发完成（不阻塞主会话回复已生成）
                    if subagent_tasks:
                        results = await asyncio.gather(*subagent_tasks, return_exceptions=True)
                        for idx, res in enumerate(results):
                            if isinstance(res, Exception):
                                logger.warning("Subagent forward failed: %s", res)

                    # 检查 ParentAgentLoop 是否旋转了会话（归档+新会话）
                    _old: str = sid
                    _rotated: str | None = loop.pop_session_rotated()
                    if _rotated:
                        from system.application import Application as _FSApp
                        _FSApp.current().frontend_sink.unregister_ws(_old)  # 清理旧 session 映射
                        _FSApp.current().frontend_sink.register_ws(_rotated, ws)  # 注册新 sid 到 WebSocket 映射
                        sid = _rotated
                        await ws.send_text(
                            Message(
                                type=MessageType.SYSTEM,
                                content=json.dumps({
                                    "action": "session_rotated",
                                    "new_sid": sid,
                                    "old_sid": _old,
                                }),
                            ).to_json()
                        )

                    from system.application import Application
                    sink = Application.current().frontend_sink
                    if sink is not None:
                        await sink.emit_assistant_message(
                            sid, reply, loop.current_character_agent,
                        )
                    # 发送最终回复标记，兼容未启用流式的前端或 cron 回调路径
                    # 若前端已收到 stream_done，此消息会携带完整文本作为兜底
                    # 向前端发送实时 token 消耗更新
                    try:
                        await ws.send_text(
                            Message(
                                type=MessageType.SYSTEM,
                                session_id=sid,
                                content=json.dumps({
                                    "token_usage": loop.get_token_usage(),
                                    "context_tokens": loop.get_context_tokens(),
                                }),
                            ).to_json()
                        )
                    except Exception:
                        logger.exception("Failed to send token usage update for session=%s", sid)
                    # 发送 agent 响应后，检查本回合是否请求了
                    # 代码进化完成，若是则触发优雅关闭。
                    from main import trigger_evolution_shutdown
                    trigger_evolution_shutdown()
            except Exception as exc:
                logger.exception("User message handler error for session=%s: %s", sid, exc)

        while True:
            # Note: 进化关闭（exit -1）期间，uvicorn 会取消所有待处理
            # handler task。从 receive_text() 传播的 asyncio.CancelledError
            # 是无害且预期的 — 仅表示 gateway 正在拆除其事件循环。
            raw: str = await ws.receive_text()

            # 解析接收到的消息
            msg: Message
            try:
                msg = Message.from_json(raw)
                msg.session_id = sid  # 信任 server 而非 client
            except (ValueError, KeyError) as exc:
                await ws.send_text(
                    Message(
                        type=MessageType.ERROR,
                        session_id=sid,
                        message=f"Invalid message: {exc}",
                    ).to_json()
                )
                continue

            # 按类型路由
            if msg.type == MessageType.USER_MESSAGE:
                # agent loop 未配置时直接报错退出（启动阶段保护）
                if _get_loop(sid) is None:
                    logger.error("ParentAgentLoop not configured; cannot handle chat messages")
                    sys.exit(0)
                # 后台执行，不阻塞 WebSocket 消息循环
                asyncio.create_task(
                    _handle_user_message(msg),
                    name=f"user-msg-{sid[:8]}",
                )

            elif msg.type == MessageType.CONFIRM_RESPONSE:
                if msg.request_id is not None and msg.action is not None:
                    from system.application import Application
                    sink = Application.current().frontend_sink
                    if sink:
                        sink.resolve_confirm(msg.request_id, msg.action, deny_reason=msg.deny_reason, denied_by=msg.denied_by or "user")

            elif msg.type == MessageType.ASK_RESPONSE:
                if msg.request_id is not None:
                    from system.application import Application
                    sink = Application.current().frontend_sink
                    if sink:
                        sink.resolve_ask(msg.request_id, option=msg.option, custom_text=msg.custom_text)

            elif msg.type == MessageType.INTERRUPT:
                loop = _get_loop(sid)
                if loop is not None:
                    loop.interrupt()

            elif msg.type == MessageType.FILE_UPLOAD:
                await _handle_file_upload(ws, sid, msg)

            elif msg.type == MessageType.HANDSFREE_MODE:
                from component.approval import set_handsfree_mode
                enabled = msg.content is not None and (str(msg.content).lower() in ("true", "1", "on"))
                set_handsfree_mode(sid, enabled)

            elif msg.type == MessageType.PING:
                await ws.send_text(
                    Message(
                        type=MessageType.PONG,
                        session_id=sid,
                    ).to_json()
                )

            elif msg.type == MessageType.SYSTEM:
                logger.info("System message from session=%s: %s", sid, msg.content)

            else:
                await ws.send_text(
                    Message(
                        type=MessageType.ERROR,
                        session_id=sid,
                        message=f"Unsupported message type: {msg.type.value}",
                    ).to_json()
                )

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