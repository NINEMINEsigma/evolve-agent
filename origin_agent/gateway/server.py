"""基于 FastAPI 的 WebSocket 聊天端点。

提供：
  - ``GET /health`` — 存活检查
  - ``WS /ws/chat`` — 聊天 WebSocket（LLM 未配置时回退到 echo）
  - ``create_server(ctx)`` — uvicorn.Server 实例工厂

支持流式消息转发：将 AgentLoop 产生的 ``stream_delta`` / ``stream_done``
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

from .chat import Message, MessageType, SessionManager
from component.approval import ApprovalResult
from datetime import datetime, timezone
from entity.constant import CRON_STDOUT_PREVIEW_MAX_LENGTH, SUBPROCESS_TIMEOUT_DEFAULT, UPLOAD_FILENAME_TIME_FORMAT
from system.context import get_runtime_context

if TYPE_CHECKING:
    from entry.agent import AgentLoop

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 共享 session 注册表
# ---------------------------------------------------------------------------

sessions: SessionManager = SessionManager()

# AgentLoop 引用 — 由 main.py 在 server 启动前设置。
# 未设置时回退到 echo 模式（适用于无 LLM 的测试场景）。
_agent_loop: AgentLoop | None = None

# agentspace 路径 — 由 main.py 在 server 启动前设置。
# 用于 FILE_UPLOAD 消息的文件保存目标。
_agentspace_path: Path | None = None


def set_agent_loop(loop: AgentLoop) -> None:
    """将 AgentLoop 注入 gateway 的 WebSocket handler。"""
    global _agent_loop
    _agent_loop = loop


def set_agentspace_path(path: str | Path) -> None:
    """设置文件上传的目标目录（ws: 命名空间的根）。"""
    global _agentspace_path
    _agentspace_path = Path(path)
    _agentspace_path.mkdir(parents=True, exist_ok=True)


def configure_sessions(store_path: str | None = None) -> None:
    """配置 session 存储目录并重新加载持久化的 session。"""
    if store_path:
        sessions.set_store_dir(store_path)


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


# ── 工具事件流 ──────────────────────────────────────────────
# 映射 session_id → WebSocket，用于在 agent 循环处理回合期间
# 向前端推送 tool_call / tool_result 事件。

_tool_ws_sinks: dict[str, WebSocket] = {}

# ── cron 定时任务结果推送 ────────────────────────────────────
# 后台线程通过 ws_chat 保存的 uvicorn 主事件循环调度协程。
# 必须在 ws_chat 中设置，因为主循环引用无法从后台线程获取。

_cron_push_loop: _asyncio.AbstractEventLoop | None = None


def set_cron_event_loop(loop: _asyncio.AbstractEventLoop) -> None:
    """由 main.py 在 server 启动后调用，保存主事件循环供后台线程使用。"""
    global _cron_push_loop
    _cron_push_loop = loop

# ── shell 命令确认 ────────────────────────────────────────
# {request_id: asyncio.Future} — 映射确认请求 ID 到 future，
#   当用户批准/拒绝 run_command 时解析。
# {request_id: session_id}  — request_id 到 session_id 的反向映射，
#   用于 WebSocket 断开时自动拒绝。

import asyncio as _asyncio
_pending_confirms: dict[str, _asyncio.Future[ApprovalResult]] = {}
_confirm_session_map: dict[str, str] = {}


def _register_confirm_session(request_id: str, session_id: str) -> None:
    """记录确认请求所属的 session，以便断开时自动拒绝。"""
    _confirm_session_map[request_id] = session_id


def _resolve_confirm(request_id: str, action: str, deny_reason: str | None = None, denied_by: str = "user") -> None:
    fut: _asyncio.Future[ApprovalResult] | None = _pending_confirms.pop(request_id, None)
    _confirm_session_map.pop(request_id, None)
    if fut and not fut.done():
        fut.set_result(ApprovalResult(action=action, deny_reason=deny_reason, denied_by=denied_by))
        logger.info("Confirm resolved: %s -> %s (reason=%s, by=%s)", request_id, action, deny_reason, denied_by)
    else:
        logger.warning(
            "Confirm request %s not found (already resolved or timed out)", request_id
        )


def _deny_session_confirms(session_id: str) -> None:
    """自动拒绝断开连接 session 的所有待处理确认请求。"""
    for rid in list(_confirm_session_map.keys()):
        if _confirm_session_map.get(rid) == session_id:
            _resolve_confirm(rid, "deny", deny_reason="WebSocket connection disconnected", denied_by="system")


# ── ask（提问） ──────────────────────────────────────────────
# {request_id: asyncio.Future} — 映射提问请求 ID 到 future，
#   当用户在对话框中选择或提交时解析。
# 结果格式：{"option": str | None, "custom_text": str | None}

_pending_asks: dict[str, _asyncio.Future[str]] = {}
_ask_session_map: dict[str, str] = {}


def _register_ask_session(request_id: str, session_id: str) -> None:
    """记录提问请求所属的 session，以便断开时自动拒绝。"""
    _ask_session_map[request_id] = session_id


def _resolve_ask(request_id: str, option: str | None = None, custom_text: str | None = None) -> None:
    """解析提问请求 — 将用户选择传递给等待的 tool handler。"""
    fut: _asyncio.Future[str] | None = _pending_asks.pop(request_id, None)
    _ask_session_map.pop(request_id, None)
    if fut and not fut.done():
        result = json.dumps({"option": option, "custom_text": custom_text}, ensure_ascii=False)
        fut.set_result(result)
        logger.info("Ask resolved: %s -> option=%s custom=%s", request_id, option, custom_text)
    else:
        logger.warning("Ask request %s not found (already resolved or timed out)", request_id)


def _deny_session_asks(session_id: str) -> None:
    """自动拒绝断开连接 session 的所有待处理提问请求。"""
    for rid in list(_ask_session_map.keys()):
        if _ask_session_map.get(rid) == session_id:
            _resolve_ask(rid, option=None, custom_text=None)


async def _send_tool_event(
    session_id: str, event_type: str, tool_name: str, payload: str,
) -> None:
    """向前端 WebSocket 推送 tool_call 或 tool_result 事件。

    对已中断的 session 静默丢弃事件，
    防止前端在用户点击停止后收到过期的工具通知。
    """
    # 如果 session 已被中断，跳过发送工具事件。
    if _agent_loop is not None and hasattr(_agent_loop, "is_interrupted"):
        try:
            if _agent_loop.is_interrupted(session_id):  # type: ignore[union-attr]
                return
        except Exception:
            pass

    ws: WebSocket | None = _tool_ws_sinks.get(session_id)
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
            pass
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
            pass
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
            pass
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
            pass
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
        )
        try:
            await ws.send_text(msg.to_json())
        except Exception:
            pass
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
            pass
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
    except Exception:
        pass  # 客户端已断开 — 忽略

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
    return {"status": "ok", "sessions": sessions.count}


@app.get("/api/sessions")
async def list_sessions():
    """返回所有活跃 session 及其元数据。"""
    return {"sessions": sessions.get_all()}


@app.get("/api/tags")
async def list_tags():
    """返回全局已有标签列表。"""
    return {"tags": sessions.get_all_tags()}


@app.put("/api/sessions/{session_id}/tags")
async def update_session_tags(session_id: str, req: Request):
    """更新 session 的标签列表。"""
    body: dict = {}
    try:
        body = await req.json()
    except Exception:
        body = {}
    raw_tags = body.get("tags", [])
    if not isinstance(raw_tags, list):
        return {"updated": False, "error": "tags must be an array", "session_id": session_id}
    tags: list[str] = [str(t).strip() for t in raw_tags]
    valid = sessions.set_session_tags(session_id, tags)
    return {"updated": True, "session_id": session_id, "tags": valid}


@app.get("/api/sessions/{session_id}/tool-resources")
async def get_session_tool_resources(session_id: str):
    """返回 session 的可恢复工具副作用资源快照。"""
    if not sessions.exists(session_id):
        return {"session_id": session_id, "task_progress": {}, "clipboard_display": {}}
    if _agent_loop is None or not hasattr(_agent_loop, "get_tool_resources"):
        return {"session_id": session_id, "task_progress": {}, "clipboard_display": {}}
    resources = _agent_loop.get_tool_resources(session_id)  # type: ignore[union-attr]
    return {
        "session_id": session_id,
        "task_progress": resources.get("task_progress", {}),
        "clipboard_display": resources.get("clipboard_display", {}),
    }


@app.post("/api/confirm/{request_id}")
async def http_confirm(request_id: str, req: Request):
    """通过 HTTP 处理确认响应（独立于 WebSocket 连接状态）。"""
    body: dict = {}
    try:
        body = await req.json()
    except Exception:
        body = {}
    action: str = str(body.get("action", "deny"))
    if action not in ("allow_once", "allow_always", "deny"):
        action = "deny"
    deny_reason: str | None = str(body.get("deny_reason", "")) or None
    denied_by: str = str(body.get("denied_by", "user"))
    if action != "deny":
        deny_reason = None
    _resolve_confirm(request_id, action, deny_reason=deny_reason, denied_by=denied_by)
    return {"resolved": True, "request_id": request_id, "action": action}


@app.post("/api/ask/{request_id}")
async def http_ask(request_id: str, req: Request):
    """通过 HTTP 处理提问响应（独立于 WebSocket 连接状态）。"""
    body: dict = {}
    try:
        body = await req.json()
    except Exception:
        body = {}
    option: str | None = str(body.get("option")) if body.get("option") is not None else None
    custom_text: str | None = str(body.get("custom_text")) if body.get("custom_text") is not None else None
    _resolve_ask(request_id, option=option, custom_text=custom_text)
    return {"resolved": True, "request_id": request_id, "option": option, "custom_text": custom_text}


@app.post("/api/interrupt/{session_id}")
async def http_interrupt(session_id: str):
    """通过 HTTP 处理中断请求，使其在 WS handler 被
    ``process_message()`` 阻塞时仍能生效。"""
    if _agent_loop is not None and hasattr(_agent_loop, "interrupt"):
        _agent_loop.interrupt(session_id)  # type: ignore[union-attr]
    return {"interrupted": True, "session_id": session_id}


@app.delete("/api/sessions/{session_id}")
async def delete_session(session_id: str):
    """删除 session 及其持久化数据。"""
    sessions.remove(session_id)
    if _agent_loop is not None and hasattr(_agent_loop, "clear_session"):
        _agent_loop.clear_session(session_id)  # type: ignore[union-attr]
    return {"deleted": True, "session_id": session_id}


@app.put("/api/sessions/{session_id}/messages/{message_index}")
async def update_session_message(session_id: str, message_index: int, req: Request):
    """编辑指定 session 中一条历史消息的正文，不触发重新生成。"""
    body: dict = {}
    try:
        body = await req.json()
    except Exception:
        body = {}
    content = body.get("content")
    info = sessions.get(session_id)
    if info and info.get("status") == "archived":
        result = {"updated": False, "error": "archived session cannot be edited", "session_id": session_id}
        return HTMLResponse(
            json.dumps(result, ensure_ascii=False),
            media_type="application/json",
            status_code=403,
        )
    if _agent_loop is None or not hasattr(_agent_loop, "edit_session_message"):
        return {"updated": False, "error": "agent loop not ready", "session_id": session_id}
    result = _agent_loop.edit_session_message(session_id, message_index, content)  # type: ignore[union-attr]
    status_code = 200 if result.get("updated") else 400
    return HTMLResponse(
        json.dumps(result, ensure_ascii=False),
        media_type="application/json",
        status_code=status_code,
    )


@app.put("/api/sessions/{session_id}/title")
async def update_session_title(session_id: str, req: Request):
    """手动重命名 session。"""
    title: str = ""
    try:
        body = await req.json()
        title = str(body.get("title", "")).strip()[:50]
    except Exception:
        title = ""
    sessions.update_title(session_id, title)
    return {"updated": True, "session_id": session_id, "title": title}


@app.post("/api/sessions/{session_id}/auto-title")
async def auto_title_session(session_id: str):
    """请求 LLM 根据 session 消息自动生成标题。"""
    title: str = ""
    if _agent_loop is not None and hasattr(_agent_loop, "auto_generate_title"):
        title = await _agent_loop.auto_generate_title(session_id)  # type: ignore[union-attr]
    if title:
        sessions.update_title(session_id, title)
    return {"title": title, "session_id": session_id}


@app.post("/api/sessions/{session_id}/auto-tags")
async def auto_tags_session(session_id: str):
    """请求根据 session 摘要重新生成标签并持久化。"""
    tags: list[str] = []
    if _agent_loop is not None and hasattr(_agent_loop, "regenerate_session_tags"):
        tags = await _agent_loop.regenerate_session_tags(session_id)  # type: ignore[union-attr]
    return {"tags": tags, "session_id": session_id}


@app.post("/api/sessions/{session_id}/terminate")
async def terminate_session_endpoint(session_id: str):
    """手动终结指定会话：归档 + 压缩（生成摘要），不旋转。"""
    if _agent_loop is not None and hasattr(_agent_loop, "terminate_session"):
        result = await _agent_loop.terminate_session(session_id)  # type: ignore[union-attr]
        return result
    return {"terminated": False, "error": "agent loop not ready", "session_id": session_id}


@app.post("/api/sessions/{session_id}/pin")
async def pin_session_endpoint(session_id: str):
    """切换 session 置顶状态。"""
    pinned: bool = sessions.toggle_pin(session_id)
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
        pass
    sources: list[str] = body.get("sources", [])
    if not sources:
        return {"error": "sources array required", "merged": False}
    err = sessions.validate_merge_sources(sources)
    if err:
        return {"error": err, "merged": False}
    if _agent_loop is not None and hasattr(_agent_loop, "merge_sessions"):
        result = await _agent_loop.merge_sessions(sources)  # type: ignore[union-attr]
        return result
    return {"error": "agent loop not ready", "merged": False}


@app.post("/api/sessions/{session_id}/branch")
async def branch_session_endpoint(session_id: str):
    """从指定会话创建分支延续（单源 merge 的快捷端点）。"""
    err = sessions.validate_merge_sources([session_id])
    if err:
        return {"error": err, "merged": False}
    if _agent_loop is not None and hasattr(_agent_loop, "merge_sessions"):
        result = await _agent_loop.merge_sessions([session_id])  # type: ignore[union-attr]
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
    from component.approval import shutdown_approval_model
    ok = shutdown_approval_model()
    return {"ok": ok}


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
    # 保存事件循环引用，供后台 cron 任务线程调度协程使用
    global _cron_push_loop
    _cron_push_loop = _asyncio.get_running_loop()
    # 如果客户端请求恢复之前的 session
    qs: dict[str, list[str]] = parse_qs(ws.scope.get("query_string", b"").decode())
    resume: str | None = qs.get("resume", [None])[0]
    sid: str
    if resume and sessions.exists(resume):
        sid = resume
    else:
        # 尝试从磁盘加载（server 重启后恢复）
        if resume:
            sessions.load_from_disk()
            if sessions.exists(resume):
                sid = resume
            else:
                sid = sessions.create()
        else:
            sid = sessions.create()

    _tool_ws_sinks[sid] = ws  # 注册用于工具事件流推送
    logger.info("WebSocket connected | session=%s", sid)

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
            model_path: str = Path(ctx.approval_model_path).name if ctx.approval_model_path else ""
            await ws.send_text(
                Message(
                    type=MessageType.SYSTEM,
                    session_id=sid,
                    content=json.dumps({
                        "server_info": {
                            "llm_max_context_tokens": ctx.llm_max_context_tokens,
                            "approval_model_name": model_path,
                            "approval_model_available": bool(ctx.approval_model_path),
                        },
                    }),
                ).to_json()
            )
        except Exception:
            # RuntimeContext 未初始化时静默跳过（fallback 模式可能无 LLM）
            pass

        # 恢复 session 时回放会话历史，使前端不为空白
        if resume and sessions.exists(resume) and _agent_loop is not None:
            get_messages = getattr(_agent_loop, "get_session_messages", None)
            get_usage = getattr(_agent_loop, "get_token_usage", None)
            get_context = getattr(_agent_loop, "get_context_tokens", None)
            is_processing = getattr(_agent_loop, "is_processing", None)
            if get_messages:
                history: list[dict] = get_messages(sid)
                usage: int = get_usage(sid) if get_usage else 0
                context: int = get_context(sid) if get_context else 0
                processing: bool = is_processing(sid) if is_processing else False
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
                # 从首条用户消息自动生成标题
                session_info: dict | None = sessions.get(sid)
                if session_info and not session_info.get("title") and msg.content:
                    text_content: str = _extract_text(msg.content)
                    title: str = text_content.strip()[:30]
                    if len(text_content.strip()) > 30:
                        title += "..."
                    sessions.update_title(sid, title)
                sessions.update_last_activity(sid)
                # 拦截 archived 会话的新消息
                _session_info = sessions.get(sid)
                if _session_info and _session_info.get("status") == "archived":
                    await ws.send_text(
                        Message(
                            type=MessageType.ERROR,
                            session_id=sid,
                            message="This session has been archived. Please switch to the continuation session or create a new one.",
                        ).to_json()
                    )
                    continue
                if _agent_loop is not None:
                    reply: str
                    try:
                        reply = await _agent_loop.process_message(  # type: ignore[union-attr]
                            sid, msg.content or ""
                        )
                    except Exception as exc:
                        logger.exception("Agent loop error for session=%s", sid)
                        reply = f"Internal error: {exc}"

                    # 检查 AgentLoop 是否旋转了会话（归档+新会话）
                    _old: str = sid
                    _pop_rotated: Callable[[str], str] | None = getattr(_agent_loop, "pop_session_rotated", None)
                    _rotated: str | None = _pop_rotated(sid) if callable(_pop_rotated) else None
                    if _rotated:
                        _tool_ws_sinks.pop(_old, None)  # 清理旧 session 映射
                        _tool_ws_sinks[_rotated] = ws  # 注册新 sid 到 WebSocket 映射
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

                    await ws.send_text(
                        Message(
                            type=MessageType.AGENT_MESSAGE,
                            session_id=sid,
                            content=reply,
                        ).to_json()
                    )
                    # 发送最终回复标记，兼容未启用流式的前端或 cron 回调路径
                    # 若前端已收到 stream_done，此消息会携带完整文本作为兜底
                    # 向前端发送实时 token 消耗更新
                    get_usage = getattr(_agent_loop, "get_token_usage", None)
                    get_context = getattr(_agent_loop, "get_context_tokens", None)
                    if get_usage:
                        await ws.send_text(
                            Message(
                                type=MessageType.SYSTEM,
                                session_id=sid,
                                content=json.dumps({
                                    "token_usage": get_usage(sid),
                                    "context_tokens": get_context(sid) if get_context else 0,
                                }),
                            ).to_json()
                        )
                    # 发送 agent 响应后，检查本回合是否请求了
                    # 代码进化完成，若是则触发优雅关闭。
                    from main import trigger_evolution_shutdown
                    trigger_evolution_shutdown()
                else:
                    # LLM 未配置 — 直接报错退出
                    logger.error("AgentLoop not configured; cannot handle chat messages")
                    sys.exit(0)

            elif msg.type == MessageType.CONFIRM_RESPONSE:
                if msg.request_id is not None and msg.action is not None:
                    _resolve_confirm(msg.request_id, msg.action, deny_reason=msg.deny_reason, denied_by=msg.denied_by or "user")

            elif msg.type == MessageType.ASK_RESPONSE:
                if msg.request_id is not None:
                    _resolve_ask(msg.request_id, option=msg.option, custom_text=msg.custom_text)

            elif msg.type == MessageType.INTERRUPT:
                if _agent_loop is not None and hasattr(_agent_loop, "interrupt"):
                    _agent_loop.interrupt(sid)  # type: ignore[union-attr]

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
    except _asyncio.CancelledError:
        # uvicorn 关闭时取消 handler task，属于正常退出，无需记录为错误
        logger.debug("WebSocket handler cancelled for session=%s (server shutting down)", sid)
    except RuntimeError as exc:
        # 收到非 text 消息（如 binary）或连接已关闭时仍尝试读写
        logger.info("WebSocket runtime error for session=%s: %s", sid, exc)
    finally:
        _deny_session_confirms(sid)
        _deny_session_asks(sid)
        _tool_ws_sinks.pop(sid, None)


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


# ---------------------------------------------------------------------------
# Cron 定时任务结果回调
# ---------------------------------------------------------------------------


def _on_cron_event(
    session_id: str,
    task_id: str,
    name: str,
    exit_code: int,
    stdout_preview: str,
) -> None:
    """定时任务执行完成后触发 Agent 回复。

    将任务结果作为一条特殊修饰的用户消息注入 Agent 历史，
    让 Agent 生成回复。若 session 当前有 WebSocket 连接，
    则将回复推送到前端。
    """
    # 优先使用 ws_chat 中保存的主循环（保证正确）；
    # 回退到 get_event_loop（仅在主线程中有效）
    loop: _asyncio.AbstractEventLoop | None = _cron_push_loop
    if loop is None:
        try:
            loop = _asyncio.get_event_loop()
        except RuntimeError:
            return
    if loop.is_closed():
        return

    agent = _agent_loop
    if agent is None or not hasattr(agent, "process_message"):
        return

    # 构建触发 Agent 的消息
    status_label = "success" if exit_code == 0 else f"failed (exit={exit_code})"
    message = (
        f"[cron-result] Scheduled task `{name}` ({task_id}) {status_label}.\n"
        "This is a background scheduled-task result visible only to the Agent; the user does not directly see the raw output below.\n"
        "If the user should be informed, the Agent must actively summarize, explain, or continue acting.\n"
        "If the goal requires continued execution, schedule only one next run now; do not backfill multiple future runs.\n"
        f"Output preview:\n{stdout_preview[:CRON_STDOUT_PREVIEW_MAX_LENGTH]}"
    )

    async def _trigger() -> None:
        try:
            reply: str = await agent.process_message(session_id, message)  # type: ignore[union-attr]
        except Exception as exc:
            logger.warning("Cron agent trigger error for session=%s: %s", session_id, exc)
            return

        # 若前端仍在连接，推送 Agent 回复
        ws: WebSocket | None = _tool_ws_sinks.get(session_id)
        if ws is not None:
            try:
                await ws.send_text(
                    Message(
                        type=MessageType.AGENT_MESSAGE,
                        session_id=session_id,
                        content=reply,
                    ).to_json()
                )
            except Exception as exc:
                logger.warning("Failed to push cron reply to session=%s: %s", session_id, exc)

    _asyncio.run_coroutine_threadsafe(_trigger(), loop)


# 注册回调（静默失败，避免 discover 阶段循环导入问题）
try:
    from component.extools.cron_tools import register_cron_event_callback
    register_cron_event_callback(_on_cron_event)
except Exception:
    pass