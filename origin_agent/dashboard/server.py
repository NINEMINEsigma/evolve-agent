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
from system.pathutils import get_agent_dir, get_template_path

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


def _list_skills() -> list[dict[str, Any]]:
    """递归扫描 project-root/skills/ 查找 SKILL.md 文件并解析 YAML frontmatter。"""
    result: list[dict[str, Any]] = []
    if not _SKILLS_DIR.exists():
        return result
    for skill_file in sorted(_SKILLS_DIR.rglob("SKILL.md")):
        try:
            text: str = skill_file.read_text(encoding="utf-8")
            parts: list[str] = text.split("---", 2)
            if len(parts) < 3:
                continue
            frontmatter: str = parts[1].strip()
            meta: dict[str, Any] = {"name": "", "description": "", "category": None, "tags": []}
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


def _list_memory_sessions() -> list[dict[str, Any]]:
    import json
    result: list[dict[str, Any]] = []
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


def _list_logs() -> list[dict[str, str]]:
    files: list[dict[str, str]] = []
    if not _LOGS_DIR.exists():
        return files
    for p in sorted(_LOGS_DIR.glob("*.log"), reverse=True)[:10]:
        try:
            files.append({
                "name": p.name,
                "size": str(p.stat().st_size),
                "modified": str(p.stat().st_mtime),
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
        ws_exists: bool = (get_agent_dir() / "__main__.py").exists()
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
        if _agent_loop is not None and hasattr(_agent_loop, "get_all_token_usage"):
            return _agent_loop.get_all_token_usage()  # type: ignore[union-attr]
        return {}

    @app.get("/api/stats/tool-calls")
    async def stats_tool_calls():
        """返回按工具名称聚合的工具调用统计。"""
        if _agent_loop is not None and hasattr(_agent_loop, "get_all_tool_stats"):
            return _agent_loop.get_all_tool_stats()  # type: ignore[union-attr]
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

_DASHBOARD_HTML: str = ""
_TEMPLATE_PATH: Path = get_template_path("dashboard", "index.html")
if _TEMPLATE_PATH.is_file():
    _DASHBOARD_HTML = _TEMPLATE_PATH.read_text(encoding="utf-8")