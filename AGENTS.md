# Evolve Agent

Self-evolving AI agent framework. An orchestrator (`run.py`) spawns the agent as a subprocess; the agent can evolve its own source code via a fast-slow-fallback mechanism.

## Architecture

- **`run.py`** — orchestrator. Copies `origin_agent/` into `workspace/{fast,slow}_agent_space/`, launches `fast/__main__.py` as subprocess. Exit code `-1` triggers slow→fast swap; other non-zero triggers fallback repair.
- **`origin_agent/`** — agent process template (what gets copied and evolved).
  - `__main__.py` — entry point: CLI parsing (`--key value` combined into single argv), `RuntimeContext` build, logging setup, frontend build.
  - `main.py` — async `App` lifecycle (gateway + signal handling).
  - `system/context.py` — `RuntimeContext` dataclass. All paths are absolute.
  - `system/prompt.py` — layered prompt assembly from `templates/{base,modes/*,tools}.txt`.
  - `entry/agent.py` — `AgentLoop`: LLM + tool calling loop (max 8 tool turns).
  - `component/llm.py` — OpenAI SDK wrapper. API key falls back to `OPENAI_API_KEY` env var.
  - `gateway/` — FastAPI + WebSocket (`/ws/chat`, `/health`). Echo mode if no `AgentLoop` wired.
  - `abstract/` — base layers: `tools` (AST-based `registry.register()` discovery), `memory` (manager + providers), `skills` (SKILL.md CRUD), `plugins` (directory scanner).
  - `frontend/` — React 18 + Vite + TypeScript. Built to `frontend/dist/`, served by gateway.
- **`third/`** — git submodules (`third/filesystem`, `third/easysave` from internal gitea).

## Development

- **Dependencies**: `pip install -r requirements.txt` (fastapi, uvicorn, websockets, openai, pydantic, jinja2).
- **Config**: `config.py` with env-var overrides (`OPENAI_API_KEY`, `OPENAI_BASE_URL`, `LLM_MODEL`).
- **Frontend**: needs Node.js. `npm install && npm run build` in `origin_agent/frontend/`. Build is non-fatal if missing.
- **Workspace**: `workspace/{fast_agent_space,slow_agent_space,logs,.fallback,init.lock}`. Created + cleaned on first run.

## Commands

```bash
# Run (from repo root):
python run.py

# Frontend dev:
cd origin_agent/frontend
npm install
npm run dev     # proxies /ws to ws://127.0.0.1:8765
```

## Project state

Stages 1-3 complete (skeleton, gateway, agent loop). Stages 4-7 pending (concrete tools, code evolve, self-evolve, dashboard).

## CLI contract (run.py → agent subprocess)

Args passed as single `"--key value"` elements: `--workspace`, `--self`, `--evolve`, `--log`, `--mode` (`fast`|`fallback`), `--gateway_host`, `--gateway_port`, `--llm_base_url`, `--llm_model`, `--fix_fork` (fallback only), `--fix` (fallback only).

## Constraints

- **One external memory provider** allowed at a time (enforced by `MemoryManager`).
- Tool registration via `registry.register()` at module level with AST-based discovery.
- Gateway defaults to `ws://127.0.0.1:8765/ws/chat`.
- `.gitignore` excludes `workspace/` and `.test*.*`.
