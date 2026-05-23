"""FastAPI application with WebSocket endpoint for chat.

Provides:
  - ``GET /health`` — liveness check
  - ``WS /ws/chat`` — chat WebSocket (echo placeholder until Stage 3)
  - ``create_server(ctx)`` — factory for a uvicorn.Server instance
"""

from __future__ import annotations

import logging
from pathlib import Path

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
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

# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------


app = FastAPI(title="Evolve Agent Gateway")

# ---------------------------------------------------------------------------
# Built frontend discovery
# ---------------------------------------------------------------------------

_FRONTEND_DIST = Path(__file__).resolve().parent.parent / "frontend" / "dist"

if _FRONTEND_DIST.is_dir():
    assets_dir = _FRONTEND_DIST / "assets"
    if assets_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")
    logger.info("Frontend dist found at %s", _FRONTEND_DIST)

# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@app.get("/")
async def index():
    """Serve the built React frontend, or the inline fallback."""
    index_html = _FRONTEND_DIST / "index.html"
    if index_html.exists():
        return HTMLResponse(index_html.read_text(encoding="utf-8"))
    return HTMLResponse(_CHAT_PAGE_HTML)


@app.get("/health")
async def health():
    return {"status": "ok", "sessions": sessions.count}


@app.get("/{full_path:path}")
async def spa_fallback(full_path: str):
    """Catch-all for SPA client-side routes.

    Must be defined AFTER all API routes so they take precedence.
    Returns the built index.html, or 404 if the frontend wasn't built.
    """
    index_html = _FRONTEND_DIST / "index.html"
    if index_html.exists():
        return HTMLResponse(index_html.read_text(encoding="utf-8"))
    from fastapi import HTTPException
    raise HTTPException(status_code=404, detail=f"Not found: {full_path}")


@app.websocket("/ws/chat")
async def ws_chat(ws: WebSocket) -> None:
    await ws.accept()
    sid = sessions.create()
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

        while True:
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
        sessions.remove(sid)


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