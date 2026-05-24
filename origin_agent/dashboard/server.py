"""Dashboard — management UI and monitoring API.

Provides REST endpoints for monitoring agent state, memory, skills,
and evolution history.  Includes an inlined HTML dashboard served at
``GET /dashboard``.
"""

from __future__ import annotations

import json as _json
import logging
from pathlib import Path
from typing import Any, Dict, List

from fastapi import FastAPI, HTTPException

logger = logging.getLogger(__name__)

# Resolve workspace paths
_WORKSPACE = Path(".").resolve()
_LOGS_DIR = _WORKSPACE / "logs"
_MEMORY_DIR = _LOGS_DIR / "memory"
_SKILLS_DIR = _WORKSPACE / "skills"


# ── helper ───────────────────────────────────────────────────────────


def _list_skills() -> List[Dict[str, Any]]:
    try:
        from abstract.skills.loader import list_skills
        skills = list_skills()
        return [
            {
                "name": s.get("name", ""),
                "description": s.get("description", ""),
                "category": s.get("category"),
                "tags": s.get("tags", []),
                "path": s.get("path", ""),
            }
            for s in skills
        ]
    except Exception:
        return []


def _list_memory_sessions() -> List[Dict[str, Any]]:
    import json
    result: List[Dict[str, Any]] = []
    if not _MEMORY_DIR.exists():
        return result
    try:
        idx_path = _MEMORY_DIR / "_sessions.json"
        if idx_path.exists():
            idx = json.loads(idx_path.read_text(encoding="utf-8"))
            sessions = idx.get("sessions", []) if isinstance(idx, dict) else []
            for sid in sessions[-20:]:  # last 20
                sp = _MEMORY_DIR / f"session_{sid}.json"
                size = sp.stat().st_size if sp.exists() else 0
                result.append({
                    "session_id": sid,
                    "size_bytes": size,
                })
    except Exception:
        pass
    return result


def _list_logs() -> List[Dict[str, str]]:
    files: List[Dict[str, str]] = []
    if not _LOGS_DIR.exists():
        return files
    for p in sorted(_LOGS_DIR.glob("*.log"), reverse=True)[:10]:
        try:
            files.append({
                "name": p.name,
                "size": str(p.stat().st_size),
                "modified": p.stat().st_mtime,
            })
        except OSError:
            pass
    return files


def _read_log(filename: str, lines: int = 200) -> str:
    if ".." in filename or "/" in filename or "\\" in filename:
        raise HTTPException(400, "Invalid filename")
    fp = _LOGS_DIR / filename
    if not fp.exists():
        raise HTTPException(404, f"Log not found: {filename}")
    try:
        content = fp.read_text(encoding="utf-8")
        all_lines = content.splitlines()
        return "\n".join(all_lines[-lines:])
    except Exception:
        raise HTTPException(500, "Failed to read log")


# ── routes ───────────────────────────────────────────────────────────


def register_dashboard_routes(app: FastAPI) -> None:
    """Mount all dashboard routes on the given FastAPI app."""

    @app.get("/api/status")
    async def api_status():
        """Return agent runtime status."""
        from pathlib import Path as _Path
        ws_exists = (_WORKSPACE / "fast_agent_space" / "__main__.py").exists()
        return {
            "status": "running" if ws_exists else "unknown",
            "workspace": str(_WORKSPACE),
            "logs": len(_list_logs()),
            "skills": len(_list_skills()),
            "memory_sessions": len(_list_memory_sessions()),
        }

    @app.get("/api/logs")
    async def api_logs_list():
        """List available log files."""
        return _list_logs()

    @app.get("/api/logs/{filename}")
    async def api_logs_read(filename: str, lines: int = 200):
        """Read the last N lines of a log file."""
        return {"filename": filename, "content": _read_log(filename, lines)}

    @app.get("/api/memory")
    async def api_memory_list():
        """List recent memory sessions."""
        return _list_memory_sessions()

    @app.get("/api/skills")
    async def api_skills_list():
        """List all registered skills."""
        return _list_skills()

    @app.get("/dashboard")
    async def dashboard_page():
        """Serve the embedded dashboard HTML."""
        from fastapi.responses import HTMLResponse
        return HTMLResponse(_DASHBOARD_HTML)


# ── inlined dashboard HTML ───────────────────────────────────────────

_DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Evolve Agent Dashboard</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: system-ui, sans-serif; background: #1a1a1a; color: #e4e4e4; padding: 24px; max-width: 900px; margin: 0 auto; }
  h1 { font-size: 20px; margin-bottom: 8px; }
  h2 { font-size: 16px; margin: 20px 0 8px; border-bottom: 1px solid #3a3a3a; padding-bottom: 4px; }
  .card { background: #212121; border: 1px solid #3a3a3a; border-radius: 8px; padding: 16px; margin-bottom: 12px; }
  .status-dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%; margin-right: 6px; }
  .status-dot.ok { background: #19c37d; }
  .status-dot.err { background: #ef4444; }
  table { width: 100%; border-collapse: collapse; font-size: 13px; }
  th, td { padding: 6px 10px; text-align: left; border-bottom: 1px solid #2a2a2a; }
  th { color: #888; font-weight: 500; }
  pre { background: #2a2a2a; padding: 12px; border-radius: 6px; overflow-x: auto; font-size: 12px; max-height: 400px; overflow-y: auto; white-space: pre-wrap; word-break: break-all; }
  a { color: #19c37d; text-decoration: none; }
  a:hover { text-decoration: underline; }
  button { padding: 6px 14px; border: none; border-radius: 4px; cursor: pointer; font-size: 13px; }
  .btn-primary { background: #19c37d; color: #fff; }
  .btn-primary:hover { background: #1a7f5a; }
  .tag { display: inline-block; background: #2a2a2a; padding: 2px 8px; border-radius: 4px; font-size: 11px; margin-right: 4px; }
  .empty { color: #666; font-style: italic; }
  .tabs { display: flex; gap: 8px; margin-bottom: 12px; }
  .tab { padding: 6px 16px; background: #2a2a2a; border-radius: 6px; cursor: pointer; font-size: 13px; }
  .tab.active { background: #19c37d; color: #fff; }
</style>
</head>
<body>
<h1>⚡ Evolve Agent Dashboard</h1>

<div id="status" class="card">loading...</div>

<h2>📋 Evolution History</h2>
<div id="evolution" class="card"><span class="empty">no events yet</span></div>

<h2>📂 Logs</h2>
<div class="tabs" id="log-tabs"></div>
<pre id="log-viewer" class="card"><span class="empty">select a log file</span></pre>

<h2>🧠 Memory Sessions</h2>
<div id="memory" class="card"><span class="empty">loading...</span></div>

<h2>📚 Skills</h2>
<div id="skills" class="card"><span class="empty">loading...</span></div>

<script>
async function load() {
  // Status
  try {
    const r = await fetch('/api/status');
    const s = await r.json();
    document.getElementById('status').innerHTML = `
      <span class="status-dot ${s.status === 'running' ? 'ok' : 'err'}"></span>
      Status: ${s.status} &nbsp;|&nbsp;
      Workspace: ${s.workspace} &nbsp;|&nbsp;
      Logs: ${s.logs} &nbsp;|&nbsp;
      Skills: ${s.skills} &nbsp;|&nbsp;
      Sessions: ${s.memory_sessions}
    `;
  } catch(e) { document.getElementById('status').innerHTML = '<span class="status-dot err"></span> API unavailable'; }

  // Evolution
  try {
    const r = await fetch('/api/evolution/history');
    const events = await r.json();
    const el = document.getElementById('evolution');
    if (Array.isArray(events) && events.length) {
      el.innerHTML = events.map(e =>
        `<div style="margin:4px 0"><span class="tag">${e.stage}</span> ${e.time} — ${e.detail}</div>`
      ).join('');
    } else { el.innerHTML = '<span class="empty">no events yet</span>'; }
  } catch(e) {}

  // Logs
  try {
    const r = await fetch('/api/logs');
    const logs = await r.json();
    const tabs = document.getElementById('log-tabs');
    if (logs.length) {
      tabs.innerHTML = logs.map((l, i) =>
        `<div class="tab${i === 0 ? ' active' : ''}" onclick="loadLog('${l.name}', this)">${l.name}</div>`
      ).join('');
      if (logs[0]) loadLog(logs[0].name);
    }
  } catch(e) {}

  // Memory
  try {
    const r = await fetch('/api/memory');
    const sessions = await r.json();
    const el = document.getElementById('memory');
    if (sessions.length) {
      el.innerHTML = '<table><tr><th>Session ID</th><th>Size</th></tr>' +
        sessions.map(s => `<tr><td>${s.session_id}</td><td>${(s.size_bytes / 1024).toFixed(1)} KB</td></tr>`).join('') +
        '</table>';
    } else { el.innerHTML = '<span class="empty">no sessions</span>'; }
  } catch(e) {}

  // Skills
  try {
    const r = await fetch('/api/skills');
    const skills = await r.json();
    const el = document.getElementById('skills');
    if (skills.length) {
      el.innerHTML = '<table><tr><th>Name</th><th>Description</th><th>Category</th></tr>' +
        skills.map(s => `<tr><td>${s.name}</td><td>${s.description || ''}</td><td><span class="tag">${s.category || '-'}</span></td></tr>`).join('') +
        '</table>';
    } else { el.innerHTML = '<span class="empty">no skills registered</span>'; }
  } catch(e) {}
}

async function loadLog(name, tabEl) {
  document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
  if (tabEl) tabEl.classList.add('active');
  const r = await fetch('/api/logs/' + name + '?lines=300');
  const d = await r.json();
  document.getElementById('log-viewer').textContent = d.content || '(empty)';
}

load();
</script>
</body>
</html>"""