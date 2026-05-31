"""基于 FastAPI 的 WebSocket 聊天端点。

提供：
  - ``GET /health`` — 存活检查
  - ``WS /ws/chat`` — 聊天 WebSocket（LLM 未配置时回退到 echo）
  - ``create_server(ctx)`` — uvicorn.Server 实例工厂
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from pathlib import Path
from typing import Dict
from urllib.parse import parse_qs, quote

import uvicorn
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from .chat import Message, MessageType, SessionManager

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 共享 session 注册表
# ---------------------------------------------------------------------------

sessions: SessionManager = SessionManager()

# AgentLoop 引用 — 由 main.py 在 server 启动前设置。
# 未设置时回退到 echo 模式（适用于无 LLM 的测试场景）。
_agent_loop: object | None = None

# agentspace 路径 — 由 main.py 在 server 启动前设置。
# 用于 FILE_UPLOAD 消息的文件保存目标。
_agentspace_path: Path | None = None


def set_agent_loop(loop: object) -> None:
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


# ── 工具事件流 ──────────────────────────────────────────────
# 映射 session_id → WebSocket，用于在 agent 循环处理回合期间
# 向前端推送 tool_call / tool_result 事件。

_tool_ws_sinks: Dict[str, WebSocket] = {}

# ── shell 命令确认 ────────────────────────────────────────
# {request_id: asyncio.Future} — 映射确认请求 ID 到 future，
#   当用户批准/拒绝 run_command 时解析。
# {request_id: session_id}  — request_id 到 session_id 的反向映射，
#   用于 WebSocket 断开时自动拒绝。

import asyncio as _asyncio
_pending_confirms: Dict[str, _asyncio.Future] = {}
_confirm_session_map: Dict[str, str] = {}


def _register_confirm_session(request_id: str, session_id: str) -> None:
    """记录确认请求所属的 session，以便断开时自动拒绝。"""
    _confirm_session_map[request_id] = session_id


def _resolve_confirm(request_id: str, action: str) -> None:
    fut: _asyncio.Future | None = _pending_confirms.pop(request_id, None)
    _confirm_session_map.pop(request_id, None)
    if fut and not fut.done():
        fut.set_result(action)
        logger.info("Confirm resolved: %s → %s", request_id, action)
    else:
        logger.warning(
            "Confirm request %s not found (already resolved or timed out)", request_id
        )


def _deny_session_confirms(session_id: str) -> None:
    """自动拒绝断开连接 session 的所有待处理确认请求。"""
    for rid in list(_confirm_session_map.keys()):
        if _confirm_session_map.get(rid) == session_id:
            _resolve_confirm(rid, "deny")


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
    """返回构建后的 React 前端，未构建时返回内置回退页面。"""
    index_html: Path = _FRONTEND_DIST / "index.html"
    if index_html.exists():
        return HTMLResponse(
            index_html.read_text(encoding="utf-8"),
            headers=_NO_CACHE,
        )
    return HTMLResponse(_CHAT_PAGE_HTML, headers=_NO_CACHE)


@app.get("/health")
async def health():
    return {"status": "ok", "sessions": sessions.count}


@app.get("/api/sessions")
async def list_sessions():
    """返回所有活跃 session 及其元数据。"""
    return {"sessions": sessions.get_all()}


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
    _resolve_confirm(request_id, action)
    return {"resolved": True, "request_id": request_id, "action": action}


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
    """处理 FILE_UPLOAD 消息：将 base64 文件保存到 agentspace。"""
    import base64
    import uuid

    filename: str = (msg.filename or "uploaded_file").strip()
    mime_type: str = (msg.mime_type or "application/octet-stream").strip()
    file_data: str = (msg.file_data or "").strip()

    if not file_data:
        await ws.send_text(
            Message(
                type=MessageType.ERROR,
                session_id=sid,
                message="文件上传失败：文件内容为空",
            ).to_json()
        )
        return

    # 清理文件名中的路径遍历字符
    safe_name: str = filename.replace("\\", "/").split("/")[-1]
    if not safe_name:
        safe_name = "uploaded_file"

    # 避免文件名冲突：添加短 UUID 前缀
    unique_name: str = f"{uuid.uuid4().hex[:8]}_{safe_name}"
    upload_dir: Path = _agentspace_path / "uploads" if _agentspace_path else Path("workspace/agentspace/uploads")
    upload_dir.mkdir(parents=True, exist_ok=True)
    dest: Path = upload_dir / unique_name

    try:
        raw_bytes: bytes = base64.b64decode(file_data)
        dest.write_bytes(raw_bytes)
    except Exception as exc:
        logger.exception("File upload failed for session=%s", sid)
        await ws.send_text(
            Message(
                type=MessageType.ERROR,
                session_id=sid,
                message=f"文件保存失败：{exc}",
            ).to_json()
        )
        return

    logical_path: str = f"ws:uploads/{unique_name}"
    logger.info("File uploaded | session=%s path=%s size=%d", sid, logical_path, len(raw_bytes))

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

        # 恢复 session 时回放会话历史，使前端不为空白
        if resume and sessions.exists(resume) and _agent_loop is not None:
            get_messages = getattr(_agent_loop, "get_session_messages", None)
            get_usage = getattr(_agent_loop, "get_token_usage", None)
            if get_messages:
                history: list[dict] = get_messages(sid)
                usage: int = get_usage(sid) if get_usage else 0
                await ws.send_text(
                    Message(
                        type=MessageType.SYSTEM,
                        session_id=sid,
                        content=json.dumps({
                            "session_history": history,
                            "token_usage": usage,
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
                    title: str = msg.content.strip()[:30]
                    if len(msg.content.strip()) > 30:
                        title += "..."
                    sessions.update_title(sid, title)
                if _agent_loop is not None:
                    reply: str
                    try:
                        reply = await _agent_loop.process_message(  # type: ignore[union-attr]
                            sid, msg.content or ""
                        )
                    except Exception as exc:
                        logger.exception("Agent loop error for session=%s", sid)
                        reply = f"Internal error: {exc}"
                    await ws.send_text(
                        Message(
                            type=MessageType.AGENT_MESSAGE,
                            session_id=sid,
                            content=reply,
                        ).to_json()
                    )
                    # 向前端发送实时 token 消耗更新
                    get_usage = getattr(_agent_loop, "get_token_usage", None)
                    if get_usage:
                        await ws.send_text(
                            Message(
                                type=MessageType.SYSTEM,
                                session_id=sid,
                                content=json.dumps({"token_usage": get_usage(sid)}),
                            ).to_json()
                        )
                    # 发送 agent 响应后，检查本回合是否请求了
                    # 代码进化完成，若是则触发优雅关闭。
                    from main import trigger_evolution_shutdown
                    trigger_evolution_shutdown()
                else:
                    # LLM 未配置 — echo 回退
                    await ws.send_text(
                        Message(
                            type=MessageType.AGENT_MESSAGE,
                            session_id=sid,
                            content=f"[echo] {msg.content}",
                        ).to_json()
                    )

            elif msg.type == MessageType.CONFIRM_RESPONSE:
                if msg.request_id is not None and msg.action is not None:
                    _resolve_confirm(msg.request_id, msg.action)

            elif msg.type == MessageType.INTERRUPT:
                if _agent_loop is not None and hasattr(_agent_loop, "interrupt"):
                    _agent_loop.interrupt(sid)  # type: ignore[union-attr]

            elif msg.type == MessageType.FILE_UPLOAD:
                await _handle_file_upload(ws, sid, msg)

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
    finally:
        _deny_session_confirms(sid)
        _tool_ws_sinks.pop(sid, None)


# ---------------------------------------------------------------------------
# 最小聊天界面（内联 HTML — 无需静态文件）
# ---------------------------------------------------------------------------

_CHAT_PAGE_HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Evolve Agent Chat</title>
<style>
  body { font-family: system-ui, sans-serif; max-width: 640px; margin: 40px auto; padding: 0 16px; }
  #log { height: 360px; overflow-y: auto; border: 1px solid #ccc; padding: 12px; margin-bottom: 12px; background: #fafafa; font-size: 14px; }
  #log .sys { color: #888; }
  #log .user { color: #2563eb; }
  #log .agent { color: #16a34a; }
  #log .err { color: #dc2626; }
  #input { display: flex; gap: 8px; }
  #msg { flex: 1; padding: 8px; font-size: 14px; }
  button { padding: 8px 16px; cursor: pointer; }
  .status { font-size: 12px; color: #888; margin-bottom: 8px; }
</style>
</head>
<body>
<h2>Evolve Agent Chat</h2>
<div class="status" id="status">connecting...</div>
<div id="log"></div>
<div id="input">
  <input id="msg" type="text" placeholder="输入消息..." autofocus />
  <button onclick="send()">发送</button>
</div>
<script>
const log = document.getElementById('log');
const status = document.getElementById('status');
const input = document.getElementById('msg');

function addLine(cls, text) {
  const div = document.createElement('div');
  div.className = cls;
  div.textContent = text;
  log.appendChild(div);
  log.scrollTop = log.scrollHeight;
}

const ws = new WebSocket('ws://' + location.host + '/ws/chat');
ws.onopen = () => { status.textContent = '已连接'; addLine('sys', '已连接到 Evolve Agent'); };
ws.onclose = () => { status.textContent = '已断开'; addLine('sys', '连接已断开'); };
ws.onmessage = (e) => {
  const msg = JSON.parse(e.data);
  if (msg.type === 'system') addLine('sys', msg.content);
  else if (msg.type === 'agent_message') addLine('agent', msg.content);
  else if (msg.type === 'error') addLine('err', msg.message);
};

function send() {
  const text = input.value.trim();
  if (!text) return;
  addLine('user', text);
  ws.send(JSON.stringify({type: 'user_message', content: text}));
  input.value = '';
}

input.addEventListener('keydown', (e) => { if (e.key === 'Enter') send(); });
</script>
</body>
</html>"""

# ---------------------------------------------------------------------------
# Server 工厂
# ---------------------------------------------------------------------------


def create_server(host: str = "127.0.0.1", port: int = 8765) -> uvicorn.Server:
    """创建 uvicorn Server 实例。

    *host* 和 *port* 应来自 RuntimeContext，
    后者通过编排器（run.py）传递的 CLI 参数接收。

    不会启动 server — 调用方应 ``await server.serve()``
    作为 asyncio task 运行。
    """
    config: uvicorn.Config = uvicorn.Config(
        app=app,
        host=host,
        port=port,
        log_level="warning",  # 抑制 uvicorn 自身的访问日志
    )
    return uvicorn.Server(config)