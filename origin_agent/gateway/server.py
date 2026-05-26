"""FastAPI application with WebSocket endpoint for chat.

Provides:
  - ``GET /health`` — liveness check
  - ``WS /ws/chat`` — chat WebSocket (echo placeholder until Stage 3)
  - ``create_server(ctx)`` — factory for a uvicorn.Server instance
"""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Dict
from urllib.parse import parse_qs

import uvicorn
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from .chat import Message, MessageType, SessionManager

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Shared session registry
# ---------------------------------------------------------------------------

sessions = SessionManager()

# AgentLoop reference — set by main.py before the server starts.
# Falls back to echo mode when not set (useful for testing without an LLM).
_agent_loop: object | None = None


def set_agent_loop(loop: object) -> None:
    """Wire the AgentLoop into the gateway's WebSocket handler."""
    global _agent_loop
    _agent_loop = loop


def configure_sessions(store_path: str | None = None) -> None:
    """Configure the session store directory and reload persisted sessions."""
    if store_path:
        sessions.set_store_dir(store_path)


# ── tool event streaming ──────────────────────────────────────────────
# Map session_id → WebSocket for pushing tool_call / tool_result events
# to the frontend while the agent loop is processing a turn.

_tool_ws_sinks: Dict[str, WebSocket] = {}

# ── shell command confirmation ────────────────────────────────────────
# {request_id: asyncio.Future} — maps confirmation request IDs to futures
# that are resolved when the user approves/rejects a run_command.
# {request_id: session_id}  — reverse-maps request_id to session_id
# for auto-deny on WebSocket disconnect.

import asyncio as _asyncio
_pending_confirms: Dict[str, _asyncio.Future] = {}
_confirm_session_map: Dict[str, str] = {}


def _register_confirm_session(request_id: str, session_id: str) -> None:
    """Record which session owns a confirm request so we can auto-deny on disconnect."""
    _confirm_session_map[request_id] = session_id


def _resolve_confirm(request_id: str, action: str) -> None:
    fut = _pending_confirms.pop(request_id, None)
    _confirm_session_map.pop(request_id, None)
    if fut and not fut.done():
        fut.set_result(action)
        logger.info("Confirm resolved: %s → %s", request_id, action)
    else:
        logger.warning(
            "Confirm request %s not found (already resolved or timed out)", request_id
        )


def _deny_session_confirms(session_id: str) -> None:
    """Auto-deny all pending confirm requests for a disconnected session."""
    for rid in list(_confirm_session_map.keys()):
        if _confirm_session_map.get(rid) == session_id:
            _resolve_confirm(rid, "deny")


async def _send_tool_event(
    session_id: str, event_type: str, tool_name: str, payload: str,
) -> None:
    """Push a tool_call or tool_result event to the frontend WebSocket.

    Silently drops events for sessions that have been interrupted so the
    frontend doesn't receive stale tool notifications after the user
    clicked stop.
    """
    # If the session has been interrupted, skip sending tool events.
    if _agent_loop is not None and hasattr(_agent_loop, "is_interrupted"):
        try:
            if _agent_loop.is_interrupted(session_id):  # type: ignore[union-attr]
                return
        except Exception:
            pass

    ws = _tool_ws_sinks.get(session_id)
    if ws is None:
        return
    msg_type = MessageType.TOOL_CALL if event_type == "tool_call" else MessageType.TOOL_RESULT
    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        data = None

    msg = Message(
        type=msg_type,
        session_id=session_id,
        tool=tool_name,
        args=data if event_type == "tool_call" else None,
        result=(payload[:200] if event_type == "tool_result" else None),
    )
    try:
        await ws.send_text(msg.to_json())
    except Exception:
        pass  # client disconnected — ignore

# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------


import asyncio
from contextlib import asynccontextmanager


async def _cleanup_loop():
    while True:
        try:
            await asyncio.sleep(300)
            cleaned = sessions.cleanup_expired()
            if cleaned:
                logger.info("Cleaned up %d expired session(s)", cleaned)
        except Exception:
            pass


@asynccontextmanager
async def _app_lifespan(app):
    task = asyncio.create_task(_cleanup_loop())
    logger.info("Session cleanup task started (interval=300s)")
    yield
    # NOTE: During evolution shutdown (exit -1) uvicorn cancels all pending
    # handler tasks.  The resulting asyncio.CancelledError noise in the
    # logs is harmless and expected — it simply means the gateway is
    # tearing down its event loop.
    task.cancel()
    logger.info("Session cleanup task stopped")


app = FastAPI(title="Evolve Agent Gateway", lifespan=_app_lifespan)

# ---- dashboard routes ----
try:
    from dashboard.server import register_dashboard_routes
    register_dashboard_routes(app)
    logger.info("Dashboard routes registered → /dashboard")
except Exception as exc:
    logger.warning("Dashboard unavailable: %s", exc)

# ---------------------------------------------------------------------------
# Built frontend discovery
# ---------------------------------------------------------------------------

_FRONTEND_DIST = Path(__file__).resolve().parent.parent / "frontend" / "dist"


def _compute_build_hash() -> str:
    """Hash of the built index.html for cache-busting detection."""
    idx = _FRONTEND_DIST / "index.html"
    if not idx.exists():
        return ""
    try:
        return hashlib.md5(idx.read_bytes()).hexdigest()[:12]
    except Exception:
        return ""


_BUILD_HASH = _compute_build_hash()

if _FRONTEND_DIST.is_dir():
    assets_dir = _FRONTEND_DIST / "assets"
    if assets_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")
    logger.info("Frontend dist found at %s (build=%s)", _FRONTEND_DIST, _BUILD_HASH or "unknown")

# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


_NO_CACHE = {"Cache-Control": "no-cache, no-store, must-revalidate", "Pragma": "no-cache"}


@app.get("/")
async def index():
    """Serve the built React frontend, or the inline fallback."""
    index_html = _FRONTEND_DIST / "index.html"
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
    """Return all active sessions with metadata."""
    return {"sessions": sessions.get_all()}


@app.post("/api/confirm/{request_id}")
async def http_confirm(request_id: str, req: Request):
    """Handle confirm response via HTTP (independent of WS connection state)."""
    try:
        body = await req.json()
    except Exception:
        body = {}
    action = str(body.get("action", "deny"))
    if action not in ("allow_once", "allow_always", "deny"):
        action = "deny"
    _resolve_confirm(request_id, action)
    return {"resolved": True, "request_id": request_id, "action": action}


@app.post("/api/interrupt/{session_id}")
async def http_interrupt(session_id: str):
    """Handle interrupt via HTTP so it works even when the WS handler is
    blocked inside ``process_message()``."""
    if _agent_loop is not None and hasattr(_agent_loop, "interrupt"):
        _agent_loop.interrupt(session_id)  # type: ignore[union-attr]
    return {"interrupted": True, "session_id": session_id}


@app.delete("/api/sessions/{session_id}")
async def delete_session(session_id: str):
    """Delete a session and its persisted data."""
    sessions.remove(session_id)
    if _agent_loop is not None and hasattr(_agent_loop, "clear_session"):
        _agent_loop.clear_session(session_id)  # type: ignore[union-attr]
    return {"deleted": True, "session_id": session_id}


@app.put("/api/sessions/{session_id}/title")
async def update_session_title(session_id: str, req: Request):
    """Manually rename a session."""
    try:
        body = await req.json()
        title = str(body.get("title", "")).strip()[:50]
    except Exception:
        title = ""
    sessions.update_title(session_id, title)
    return {"updated": True, "session_id": session_id, "title": title}


@app.post("/api/sessions/{session_id}/auto-title")
async def auto_title_session(session_id: str):
    """Ask LLM to generate a title from session messages."""
    title = ""
    if _agent_loop is not None and hasattr(_agent_loop, "auto_generate_title"):
        title = await _agent_loop.auto_generate_title(session_id)  # type: ignore[union-attr]
    if title:
        sessions.update_title(session_id, title)
    return {"title": title, "session_id": session_id}


@app.get("/{full_path:path}")
async def spa_fallback(full_path: str):
    """Catch-all for SPA client-side routes.

    Must be defined AFTER all API routes so they take precedence.
    Returns the built index.html, or 404 if the frontend wasn't built.
    """
    index_html = _FRONTEND_DIST / "index.html"
    if index_html.exists():
        return HTMLResponse(
            index_html.read_text(encoding="utf-8"),
            headers=_NO_CACHE,
        )
    from fastapi import HTTPException
    raise HTTPException(status_code=404, detail=f"Not found: {full_path}")


@app.websocket("/ws/chat")
async def ws_chat(ws: WebSocket) -> None:
    await ws.accept()
    # Resume a previous session if the client requests it
    qs = parse_qs(ws.scope.get("query_string", b"").decode())
    resume = qs.get("resume", [None])[0]
    if resume and sessions.exists(resume):
        sid = resume
    else:
        # Try loading from disk in case server was restarted
        if resume:
            sessions.load_from_disk()
            if sessions.exists(resume):
                sid = resume
            else:
                sid = sessions.create()
        else:
            sid = sessions.create()
    _tool_ws_sinks[sid] = ws  # register for tool event streaming
    logger.info("WebSocket connected | session=%s", sid)

    try:
        # Send welcome message
        await ws.send_text(
            Message(
                type=MessageType.SYSTEM,
                session_id=sid,
                content="Connected to Evolve Agent",
            ).to_json()
        )

        # Send build hash so the frontend can detect evolution and auto-reload
        if _BUILD_HASH:
            await ws.send_text(
                Message(
                    type=MessageType.SYSTEM,
                    session_id=sid,
                    content=json.dumps({"build_hash": _BUILD_HASH}),
                ).to_json()
            )

        # On resume, replay conversation history so the frontend isn't blank
        if resume and sessions.exists(resume) and _agent_loop is not None:
            get_messages = getattr(_agent_loop, "get_session_messages", None)
            get_usage = getattr(_agent_loop, "get_token_usage", None)
            if get_messages:
                history = get_messages(sid)
                usage = get_usage(sid) if get_usage else 0
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
            # NOTE: During evolution shutdown (exit -1) uvicorn cancels all
            # pending handler tasks.  The asyncio.CancelledError that
            # propagates from receive_text() here is harmless and expected
            # — it is simply the gateway tearing down its event loop.
            raw = await ws.receive_text()

            # Parse incoming message
            try:
                msg = Message.from_json(raw)
                msg.session_id = sid  # trust server, not client
            except (ValueError, KeyError) as exc:
                await ws.send_text(
                    Message(
                        type=MessageType.ERROR,
                        session_id=sid,
                        message=f"Invalid message: {exc}",
                    ).to_json()
                )
                continue

            # Route by type
            if msg.type == MessageType.USER_MESSAGE:
                # Auto-generate title from first user message
                session_info = sessions.get(sid)
                if session_info and not session_info.get("title") and msg.content:
                    title = msg.content.strip()[:30]
                    if len(msg.content.strip()) > 30:
                        title += "..."
                    sessions.update_title(sid, title)
                if _agent_loop is not None:
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
                    # Send live token-usage update to frontend
                    get_usage = getattr(_agent_loop, "get_token_usage", None)
                    if get_usage:
                        await ws.send_text(
                            Message(
                                type=MessageType.SYSTEM,
                                session_id=sid,
                                content=json.dumps({"token_usage": get_usage(sid)}),
                            ).to_json()
                        )
                    # After sending the agent response, check whether a
                    # code-evolution finalization was requested during this
                    # turn and trigger a graceful shutdown if so.
                    from main import trigger_evolution_shutdown
                    trigger_evolution_shutdown()
                else:
                    # LLM not configured — echo fallback
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
# Minimal chat UI (inlined HTML — no static files needed)
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
# Server factory
# ---------------------------------------------------------------------------


def create_server(host: str = "127.0.0.1", port: int = 8765) -> uvicorn.Server:
    """Create a uvicorn Server instance.

    *host* and *port* should come from the RuntimeContext, which itself
    receives them via CLI args passed by the orchestrator (run.py).

    Does NOT start it — the caller should ``await server.serve()``
    as an asyncio task.
    """
    config = uvicorn.Config(
        app=app,
        host=host,
        port=port,
        log_level="warning",  # quiet uvicorn's own access logs
    )
    return uvicorn.Server(config)