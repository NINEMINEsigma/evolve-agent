"""Dashboard — 管理界面和监控 API。

提供用于监控 agent 状态、memory、skill 和进化历史的 REST 端点。
包含在 ``GET /dashboard`` 提供的内联 HTML dashboard。
"""

from __future__ import annotations

import json as _json
import logging
from pathlib import Path
from typing import Any, Dict, List

from fastapi import FastAPI, HTTPException

logger = logging.getLogger(__name__)

# 解析 workspace 路径
_WORKSPACE: Path = Path(".").resolve()
_LOGS_DIR: Path = _WORKSPACE / "logs"
_MEMORY_DIR: Path = _LOGS_DIR / "memory"
_SKILLS_DIR: Path = _WORKSPACE / "skills"

# AgentLoop 引用 — 由 gateway.server 在 server 启动前设置。
# 用于暴露运行中 agent 的 token 消耗和工具调用统计。
_agent_loop: object | None = None


def set_agent_loop(loop: object) -> None:
    """将 AgentLoop 注入 dashboard 以访问统计数据。"""
    global _agent_loop
    _agent_loop = loop


# ── 辅助函数 ───────────────────────────────────────────────────────────


def _list_skills() -> List[Dict[str, Any]]:
    """递归扫描 project-root/skills/ 查找 SKILL.md 文件并解析 YAML frontmatter。"""
    result: List[Dict[str, Any]] = []
    if not _SKILLS_DIR.exists():
        return result
    for skill_file in sorted(_SKILLS_DIR.rglob("SKILL.md")):
        try:
            text: str = skill_file.read_text(encoding="utf-8")
            parts: list[str] = text.split("---", 2)
            if len(parts) < 3:
                continue
            frontmatter: str = parts[1].strip()
            meta: Dict[str, Any] = {"name": "", "description": "", "category": None, "tags": []}
            for line in frontmatter.splitlines():
                line = line.strip()
                if ":" in line:
                    key: str
                    val: str
                    key, _, val = line.partition(":")
                    val = val.strip()
                    if key == "name":
                        meta["name"] = val
                    elif key == "description":
                        meta["description"] = val
                    elif key == "category":
                        meta["category"] = val
                    elif key == "tags":
                        # 支持逗号分隔或 YAML 列表
                        if val.startswith("[") and val.endswith("]"):
                            meta["tags"] = [t.strip().strip('"').strip("'") for t in val[1:-1].split(",")]
                        else:
                            meta["tags"] = [t.strip() for t in val.split(",") if t.strip()]
            meta["path"] = str(skill_file)
            result.append(meta)
        except Exception:
            continue
    return result


def _list_memory_sessions() -> List[Dict[str, Any]]:
    import json
    result: List[Dict[str, Any]] = []
    if not _MEMORY_DIR.exists():
        return result
    try:
        idx_path: Path = _MEMORY_DIR / "_sessions.json"
        if idx_path.exists():
            idx: dict = json.loads(idx_path.read_text(encoding="utf-8"))
            sessions: list = idx.get("sessions", []) if isinstance(idx, dict) else []
            for sid in sessions[-20:]:  # 最近 20 个
                sp: Path = _MEMORY_DIR / f"session_{sid}.json"
                size: int = sp.stat().st_size if sp.exists() else 0
                # 尝试从 session 文件提取消息计数和最后修改时间
                msg_count: int = 0
                last_active: float | None = None
                if sp.exists():
                    msg_count = idx.get("msg_counts", {}).get(str(sid), 0)
                    try:
                        last_active = sp.stat().st_mtime
                    except OSError:
                        pass
                result.append({
                    "session_id": sid,
                    "size_bytes": size,
                    "message_count": msg_count,
                    "last_active": last_active,
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
    # 解析以防护路径遍历
    resolved: Path
    try:
        resolved = (_LOGS_DIR / filename).resolve()
        resolved.relative_to(_LOGS_DIR.resolve())
    except (ValueError, OSError):
        raise HTTPException(400, "Invalid filename")
    if not resolved.exists():
        raise HTTPException(404, f"Log not found: {filename}")
    try:
        content: str = resolved.read_text(encoding="utf-8")
        all_lines: list[str] = content.splitlines()
        return "\n".join(all_lines[-lines:])
    except Exception:
        raise HTTPException(500, "Failed to read log")


# ── 路由 ───────────────────────────────────────────────────────────


def register_dashboard_routes(app: FastAPI) -> None:
    """将 dashboard 路由挂载到 FastAPI app 上。"""

    @app.get("/api/status")
    async def api_status():
        """返回 agent 运行时状态。"""
        ws_exists: bool = (_WORKSPACE / "fast_agent_space" / "__main__.py").exists()
        return {
            "status": "running" if ws_exists else "unknown",
            "workspace": str(_WORKSPACE),
            "logs": len(_list_logs()),
            "skills": len(_list_skills()),
            "memory_sessions": len(_list_memory_sessions()),
        }

    @app.get("/api/logs")
    async def api_logs_list():
        """列出可用的日志文件。"""
        return _list_logs()

    @app.get("/api/logs/{filename}")
    async def api_logs_read(filename: str, lines: int = 200):
        """读取日志文件的最后 N 行。"""
        return {"filename": filename, "content": _read_log(filename, lines)}

    @app.get("/api/memory")
    async def api_memory_list():
        """列出最近的 memory session。"""
        return _list_memory_sessions()

    @app.get("/api/skills")
    async def api_skills_list():
        """列出所有已注册的 skill。"""
        return _list_skills()

    @app.get("/api/evolution/history")
    async def evolution_history():
        """返回 run.py 在交换期间写入的进化日志。"""
        status_file: Path = Path(__file__).resolve().parent.parent.parent / "workspace" / "logs" / "evolution.status"
        if status_file.exists():
            return _json.loads(status_file.read_text(encoding="utf-8"))
        return []

    # ── 统计端点 ────────────────

    @app.get("/api/stats/token-usage")
    async def stats_token_usage():
        """返回每个 session 的累计 token 消耗。"""
        if _agent_loop is not None and hasattr(_agent_loop, "_token_usage"):
            return dict(_agent_loop._token_usage)  # type: ignore[union-attr]
        return {}

    @app.get("/api/stats/tool-calls")
    async def stats_tool_calls():
        """返回按工具名称聚合的工具调用统计。"""
        if _agent_loop is not None and hasattr(_agent_loop, "_tool_stats"):
            return _agent_loop._tool_stats  # type: ignore[union-attr]
        return {}

    @app.get("/api/stats/session-activity")
    async def stats_session_activity():
        """返回按时间段（今天/昨天/本周）分组的 session 计数。"""
        from gateway.server import sessions as _sessions
        import time
        now: float = time.time()
        day: float = 86400
        today: int = 0
        yesterday: int = 0
        this_week: int = 0
        for s in _sessions.get_all():
            created: float = s.get("created_at", 0)
            if created > now - day:
                today += 1
            elif created > now - 2 * day:
                yesterday += 1
            if created > now - 7 * day:
                this_week += 1
        return {"today": today, "yesterday": yesterday, "this_week": this_week}

    @app.get("/dashboard")
    async def dashboard_page():
        """返回内嵌的 dashboard HTML。"""
        from fastapi.responses import HTMLResponse
        return HTMLResponse(_DASHBOARD_HTML)


# ── 内联 dashboard HTML ───────────────────────────────────────────

_DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Evolve Agent Dashboard</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: system-ui, sans-serif; background: #1a1a1a; color: #e4e4e4; padding: 20px; }
  .dash-wrap { max-width: 1100px; margin: 0 auto; }
  h1 { font-size: 18px; margin-bottom: 16px; display: flex; align-items: center; gap: 8px; }
  h2 { font-size: 14px; font-weight: 600; margin: 16px 0 8px; padding-bottom: 4px; border-bottom: 1px solid #333; }

  .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 10px; margin-bottom: 10px; }
  .cols2 { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
  .col { display: flex; flex-direction: column; gap: 10px; }
  .card { background: #212121; border: 1px solid #333; border-radius: 8px; padding: 14px 16px; }

  .label { color: #888; font-size: 12px; }
  .value { color: #e4e4e4; font-size: 13px; }
  .row { display: flex; justify-content: space-between; align-items: center; padding: 4px 0; border-bottom: 1px solid #2a2a2a; }
  .row:last-child { border-bottom: none; }
  .num { font-size: 28px; font-weight: 700; color: #19c37d; }

  .ok { color: #19c37d; } .err { color: #ef4444; }
  .ok::before, .err::before { content: ""; display: inline-block; width: 7px; height: 7px; border-radius: 50%; margin-right: 6px; }
  .ok::before { background: #19c37d; } .err::before { background: #ef4444; }

  table { width: 100%; border-collapse: collapse; font-size: 12px; }
  th, td { padding: 5px 8px; text-align: left; border-bottom: 1px solid #2a2a2a; }
  th { color: #666; font-weight: 500; font-size: 11px; text-transform: uppercase; }
  td code { font-family: "SF Mono", "Fira Code", monospace; color: #e5c07b; font-size: 11px; }

  .tag { display: inline-block; background: #2a2a2a; padding: 1px 7px; border-radius: 4px; font-size: 10px; color: #888; }

  .log-tabs { display: flex; flex-wrap: wrap; gap: 3px; margin-bottom: 6px; }
  .log-tab { padding: 3px 8px; border: 1px solid #333; border-radius: 4px; background: #2a2a2a; color: #888; font-size: 10px; cursor: pointer; font-family: "SF Mono", monospace; }
  .log-tab:hover { border-color: #19c37d; color: #e4e4e4; }
  .log-tab.active { background: #19c37d; color: #fff; border-color: #19c37d; }
  .log-view { background: #2a2a2a; padding: 10px; border-radius: 6px; font-size: 11px; line-height: 1.5; max-height: 350px; overflow-y: auto; font-family: "SF Mono", monospace; white-space: pre-wrap; word-break: break-all; }

  .evt { display: flex; align-items: center; gap: 6px; padding: 4px 0; border-bottom: 1px solid #2a2a2a; font-size: 12px; }
  .evt:last-child { border-bottom: none; }
  .evt-time { color: #666; font-family: "SF Mono", monospace; font-size: 11px; flex-shrink: 0; }

  .empty { color: #555; font-style: italic; font-size: 12px; }

  @media (max-width: 700px) { .cols2 { grid-template-columns: 1fr; } }
</style>
</head>
<body>
<div class="dash-wrap">
<h1>⚡ Evolve Agent Dashboard</h1>

<div id="status-card" class="card">loading...</div>

<div class="grid">
  <div class="card">
    <div class="label" style="margin-bottom:6px">Token 消耗</div>
    <div id="token-total" class="num">-</div>
    <div id="token-detail" style="font-size:11px;color:#666;margin-top:6px"></div>
  </div>
  <div class="card">
    <div class="label" style="margin-bottom:6px">会话活跃度</div>
    <div id="activity" style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:8px;text-align:center"></div>
  </div>
  <div class="card">
    <div class="label" style="margin-bottom:6px">工具调用</div>
    <div id="tool-summary" style="font-size:11px;color:#666"></div>
  </div>
</div>

<div class="cols2">
  <div class="col">
    <div class="card">
      <h2>📋 进化历史</h2>
      <div id="evolution" class="empty">loading...</div>
    </div>
    <div class="card">
      <h2>🔧 工具调用统计</h2>
      <div id="tool-stats"><span class="empty">loading...</span></div>
    </div>
    <div class="card">
      <h2>🧠 记忆会话</h2>
      <div id="memory"><span class="empty">loading...</span></div>
    </div>
  </div>
  <div class="col">
    <div class="card">
      <h2>📂 日志查看器</h2>
      <div id="log-tabs" class="log-tabs"></div>
      <pre id="log-viewer" class="log-view"><span class="empty">select a log file</span></pre>
    </div>
    <div class="card">
      <h2>📚 已注册技能</h2>
      <div id="skills"><span class="empty">loading...</span></div>
    </div>
  </div>
</div>

<script>
async function load() {
  // ── Status ──
  try {
    const r = await fetch('/api/status');
    const s = await r.json();
    document.getElementById('status-card').innerHTML =
      `<span class="${s.status === 'running' ? 'ok' : 'err'}">${s.status}</span>` +
      ` &nbsp;|&nbsp; <span class="label">workspace:</span> ${s.workspace}` +
      ` &nbsp;|&nbsp; <span class="label">logs:</span> ${s.logs}` +
      ` &nbsp;|&nbsp; <span class="label">skills:</span> ${s.skills}` +
      ` &nbsp;|&nbsp; <span class="label">sessions:</span> ${s.memory_sessions}`;
  } catch(e) { document.getElementById('status-card').innerHTML = '<span class="err">API unavailable</span>'; }

  // ── Token Usage ──
  try {
    const r = await fetch('/api/stats/token-usage');
    const usage = await r.json();
    const total = Object.values(usage).reduce((a, b) => a + b, 0);
    document.getElementById('token-total').textContent = total.toLocaleString();
    const detail = Object.entries(usage).slice(0, 5).map(([k, v]) =>
      `<div class="row"><span class="label">${k.slice(0, 8)}..</span><span class="value">${v.toLocaleString()}</span></div>`
    ).join('');
    document.getElementById('token-detail').innerHTML = detail || `${Object.keys(usage).length} sessions`;
  } catch(e) {}

  // ── Session Activity ──
  try {
    const r = await fetch('/api/stats/session-activity');
    const a = await r.json();
    document.getElementById('activity').innerHTML =
      `<div><div style="font-size:22px;font-weight:700;color:#19c37d">${a.today}</div><div class="label">今天</div></div>` +
      `<div><div style="font-size:22px;font-weight:700;color:#e4e4e4">${a.yesterday}</div><div class="label">昨天</div></div>` +
      `<div><div style="font-size:22px;font-weight:700;color:#e4e4e4">${a.this_week}</div><div class="label">本周</div></div>`;
  } catch(e) {}

  // ── Tool Stats ──
  try {
    const r = await fetch('/api/stats/tool-calls');
    const stats = await r.json();
    const keys = Object.keys(stats);
    const totalCalls = keys.reduce((sum, k) => sum + stats[k].calls, 0);
    const totalErr = keys.reduce((sum, k) => sum + stats[k].errors, 0);
    document.getElementById('tool-summary').textContent =
      `${totalCalls} 次调用 · ${keys.length} 个工具 · ${totalErr > 0 ? totalErr + ' 次错误' : '无错误'}`;

    if (keys.length) {
      document.getElementById('tool-stats').innerHTML =
        '<table><thead><tr><th>工具</th><th>调用</th><th>成功率</th></tr></thead><tbody>' +
        keys.map(k => {
          const rate = stats[k].calls > 0 ? ((1 - stats[k].errors / stats[k].calls) * 100).toFixed(0) + '%' : '-';
          return `<tr><td><code>${k}</code></td><td>${stats[k].calls}</td><td>${rate}</td></tr>`;
        }).join('') +
        '</tbody></table>';
    } else {
      document.getElementById('tool-stats').innerHTML = '<span class="empty">暂无数据</span>';
    }
  } catch(e) {}

  // ── Evolution ──
  try {
    const r = await fetch('/api/evolution/history');
    const events = await r.json();
    const el = document.getElementById('evolution');
    if (Array.isArray(events) && events.length) {
      el.innerHTML = events.map(e =>
        `<div class="evt"><span class="tag">${e.stage}</span><span class="evt-time">${e.time}</span>${e.detail}</div>`
      ).join('');
    } else { el.innerHTML = '<span class="empty">no events yet</span>'; }
  } catch(e) {}

  // ── Logs ──
  try {
    const r = await fetch('/api/logs');
    const logs = await r.json();
    const tabs = document.getElementById('log-tabs');
    if (logs.length) {
      tabs.innerHTML = logs.map((l, i) =>
        `<div class="log-tab${i === 0 ? ' active' : ''}" onclick="loadLog('${l.name}', this)">${l.name}</div>`
      ).join('');
      if (logs[0]) loadLog(logs[0].name);
    } else { tabs.innerHTML = ''; document.getElementById('log-viewer').innerHTML = '<span class="empty">no log files</span>'; }
  } catch(e) {}

  // ── Skills ──
  try {
    const r = await fetch('/api/skills');
    const skills = await r.json();
    const el = document.getElementById('skills');
    if (skills.length) {
      el.innerHTML = '<table><thead><tr><th>Name</th><th>Description</th><th>Category</th></tr></thead><tbody>' +
        skills.map(s => `<tr><td><code>${s.name}</code></td><td>${s.description || '-'}</td><td><span class="tag">${s.category || '-'}</span></td></tr>`).join('') +
        '</tbody></table>';
    } else { el.innerHTML = '<span class="empty">no skills registered</span>'; }
  } catch(e) {}

  // ── Memory ──
  try {
    const r = await fetch('/api/memory');
    const sessions = await r.json();
    const el = document.getElementById('memory');
    if (sessions.length) {
      el.innerHTML = '<table><thead><tr><th>ID</th><th>Size</th><th>Msgs</th></tr></thead><tbody>' +
        sessions.slice(0, 10).map(s =>
          `<tr><td><code>${(s.session_id || '').slice(0, 8)}..</code></td><td>${(s.size_bytes / 1024).toFixed(1)} KB</td><td>${s.message_count || '-'}</td></tr>`
        ).join('') +
        '</tbody></table>';
    } else { el.innerHTML = '<span class="empty">no sessions</span>'; }
  } catch(e) {}
}

async function loadLog(name, tabEl) {
  document.querySelectorAll('.log-tab').forEach(t => t.classList.remove('active'));
  if (tabEl) tabEl.classList.add('active');
  try {
    const r = await fetch('/api/logs/' + name + '?lines=200');
    const d = await r.json();
    document.getElementById('log-viewer').textContent = d.content || '(empty)';
  } catch(e) { document.getElementById('log-viewer').textContent = 'failed to load log'; }
}

load();
</script>
</div>
</body>
</html>"""