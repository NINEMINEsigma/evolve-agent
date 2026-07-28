# Evolve Agent — AGENTS.md

> **Hard rules — violating these corrupts the build or loses work**
>
> - **Never run pnpm/npm in `origin_agent/frontend/`.** Builds only happen inside `workspace/fast_agent_space/frontend/` at runtime. Running pnpm in `origin_agent/` creates `node_modules/`/`dist/` that can be copied into workspace on `--fouce_init` and break builds.
> - **Never run validation commands for the user.** No `npx tsc`, `pnpm exec tsc`, `npm run typecheck`, `npm run lint`, `pnpm build`, `python check_env.py`, etc. If the user reports a build error, only edit source code; do not reproduce or validate by running commands.
> - **Never run `python run.py` / `python check_env.py` or start the app unless the user explicitly authorizes it.**
> - **Never execute `origin_agent/` directly.** `run.py` copies it to `workspace/fast_agent_space/` and runs that copy. No `python origin_agent/__main__.py`, no `sys.path`/`cwd` tricks pointing at `origin_agent/`.
> - **Never read, search, or modify `workspace/` code files.** They are disposable runtime copies of `origin_agent/`. Non-code files (logs, JSON, `.lock`) are readable but not writable.
> - **Git is read-only.** Only `git diff` and `git log` are allowed. All write git operations (`add`, `commit`, `push`, `checkout`, `branch`, etc.) must be done by the user.
> - **No batch-editing scripts.** Make targeted, reviewable edits.
> - **Do not switch RIPER-5 modes without explicit approval.** Especially never jump from RESEARCH/PLAN to EXECUTE without the user saying so.

## Startup

```bash
python run.py --load <config_key>
```

- Requires `OPENAI_API_KEY`. `OPENAI_BASE_URL` overrides the endpoint.
- Web UI: `http://127.0.0.1:8765`.
- `config.py` prompts interactively if neither `--load` nor `--save` is given. In agent/non-interactive sessions always pass `--load <key>` or `--save <key>`.
- `--interactive` launches the `rich`-based TUI config wizard (`config_tui.py`): profile selection → grouped field editing with validation → optional save. CLI overrides (e.g. `--llm_model`) can be combined with `--interactive` to pre-fill values.
- `config.json` is gitignored and contains the unencrypted API key. Do not commit it.
- `--fouce_init` is intentionally misspelled. When `true` in the loaded config, `--load` wipes `workspace/fast_agent_space/`, `workspace/slow_agent_space/`, and `workspace/.fallback/` (code directories only) and recopies `origin_agent/` into them. `workspace/agentspace/`, `workspace/logs/`, and session persistence (`workspace/sessions/`) are NOT affected. Use `fouce_init: false` for persistent workspaces.
- Common CLI overrides: `--fouce_init`, `--llm_model`, `--llm_base_url`, `--llm_api_key`, `--llm_temperature`, `--llm_max_context_tokens`, `--llm_max_output_tokens`, `--llm_reasoning_effort`, `--approval_model`, `--approval_model_cuda`, `--gateway_host`, `--gateway_port`, `--console_log`, `--interactive`.

## Repository layout

```
origin_agent/        ← sole source of truth — edit here
workspace/
  fast_agent_space/  ← running agent copy
  slow_agent_space/  ← evolution target (fork:)
  .fallback/         ← previous fast backup
  agentspace/        ← agent I/O workspace (ws:)
  logs/              ← sessions, evolution status
third/               ← git submodules (easysave, llamaapis)
skills/              ← runtime skill files, gitignored
```

- No CI/CD, no test framework, no lint/typecheck. Pure runtime code evolution.
- `pyrightconfig.json` adds `./origin_agent` and `./third` to `extraPaths`.
- `skills/` is created at runtime and gitignored; do not commit it.
- `pre-skills/` contains built-in skill templates for self-evolution.

## Lifecycle (run.py)

1. First run or `--fouce_init`: copies `origin_agent/` into both `workspace/fast_agent_space/` and `workspace/slow_agent_space/`.
2. Runs `fast_agent_space/__main__.py`.
3. Exit codes:
   - `0` — normal stop
   - `-1` / `4294967295` — evolution succeeded; run.py swaps slow→fast and restarts
   - anything else — runtime error; run.py enters fallback mode and runs `.fallback/__main__.py` to repair

## Sandbox paths

All file operations use logical prefixes. No bare paths, `..`, or absolute paths.

| Prefix   | Maps to                          | Modes           | Permission |
|----------|----------------------------------|-----------------|------------|
| `fork:`  | `workspace/slow_agent_space/`    | fast            | rw         |
| `ws:`    | `workspace/agentspace/`          | fast / fallback | rw         |
| `fix:`   | `workspace/.fallback/`           | fallback        | rw         |
| `skills:`| repo-root `skills/`              | fast / fallback | rw         |

**No `self:` namespace.** Read agent source via `fork:` (which is `slow_agent_space/`, not the running `fast_agent_space/`).

## Evolution flow

```
read_file (fork:path) → write_file / edit_file (fork:path)
  → validate_code → [validate_frontend if frontend changed]
  → evolve_code → exit -1 → run.py swaps slow→fast and restarts
```

- `read_file` / `write_file` / `edit_file` use `fork:`/`ws:`/`fix:`/`skills:` prefixes.
- `validate_code`: AST syntax check across all `.py` files in `fork:`.
- `validate_frontend`: runs `pnpm install && pnpm run build` in target frontend dir (default `fork:frontend`). Required if frontend files changed.
- `evolve_code`: deep `py_compile` check, then exits with `-1` to trigger the swap.
- `diff_fast_fork` (in `extools/diff_tools.py`): compares `fast_agent_space/` with `fork:`; skip `evolve_code` if identical.
- `diff_origin_fast`: compares `origin_agent/` with `fast_agent_space/`.

## Tool registration

Tools are auto-discovered by AST scan (`abstract/tools/discover.py`) looking for module-level `registry.register()` calls. Sources:

- `origin_agent/component/tools/` — core (filesystem, code, frontend, skills, etc.)
- `origin_agent/component/extools/` — extras (web, ssh, cron, diff, archive, pip, background_service, etc.)
- `origin_agent/component/mutliagenttools/` — sub-agent/multi-agent tools (note directory name typo: `mutliagenttools`)
- `custom_tools/` — user-defined, loaded if directory exists
- MCP servers — bridged via `component/mcp_tools.py`

When adding `registry.register(...)`:

- `schema["description"]` is written in English.
- The line immediately above `description` is a Chinese comment explaining behavior.

## Frontend

React + Vite + TypeScript in `origin_agent/frontend/`. Package scripts: `dev`, `build` (`tsc -b && vite build`), `preview`.

Auto-built at startup by `__main__.py::_build_frontend()` inside the running agent directory (`workspace/fast_agent_space/frontend/`) using `pnpm install && pnpm run build`. Build failure returns exit code `1` and triggers fallback mode.

Uses `frontend_build_signature` caching: source files are hashed before build; on subsequent starts, if the hash matches and `dist/` exists, the build is skipped. `--frontend_force_build` bypasses the cache.

Because `origin_agent/frontend/` is not at the repo root, IDE static type awareness may be inaccurate. Do not rely on frontend type checks or builds without telling the user.

## Approval

- **Normal mode**: user confirms tools via the WebSocket frontend.
- **Handsfree mode**: local GGUF model auto-approves. Auto-enabled if a `.gguf` is found in `custom_models/` (auto-detected at startup). Explicit flags: `--approval_model <gguf>`, `--approval_model_cuda`. Uses `third/llamaapis` (llama.cpp wrapper). Falls back to remote approval API if configured (`--approval_remote_*`) when no local model is found.
- Approval module at `component/approval/`: `core.py`, `backend.py`, `executor.py`, `handsfree.py`, `allowlist.py`, `policy.py`.

## Template system (system/prompt.py)

Assembled by `system/prompt.py`. Hierarchy:

1. `GENE.md` (project root) — immutable core identity
2. `SOUL.md` (agentspace/) — editable personality (empty by default)
3. `base.txt` — foundation prompt (always included)
4. `modes/{fast,fallback}.txt` — mode-specific instructions
5. `tools.txt` + `tools_subagent.txt` (only for MAIN scope)
6. Extra blocks (skills, memory provider contexts, etc.)

## Windows specifics

- Python command is `python` (not `python3`).
- Invoke native executables as `pnpm.cmd`.
- Process tree kill uses `taskkill /T /F`.
- Sandbox subprocess uses `CREATE_NEW_PROCESS_GROUP`.
- `signal.add_signal_handler` is unavailable; falls back to `signal.signal`.

## Git commit style

Use Chinese commit messages with repo prefixes: `[feature]`, `[fix]`, `[refactor]`, `[docs]`, etc.

```
[fix] 修复 ssh 审批弹窗 command 类型错误导致前端黑屏

- ConfirmDialog 兼容 command 为字符串（ssh_exec）或数组（run_command）
- 新增 ErrorBoundary，避免模态组件渲染异常导致整个 App 被卸载
```

## Memory

记忆系统由 `custom_tools/memory_tools/` 实现（非核心模块），包含 `remember` 和 `forget` 两个工具。底层通过 `custom_tools/memory_tools/_store.py` 基于 easysave 对象引用机制实现会话隔离与父链继承：记忆数据存储在 `agentspace/memory_data.json`，每个会话拥有独立分区，子会话通过 `__parents__` 引用链自动继承父会话记忆。`custom_hooks/memory_hook.py` 作为消息 hook 在每轮 LLM 调用前自动将合并后的记忆注入用户消息上下文。

## Sessions & Evolution status

Sessions persist to `workspace/logs/sessions/` (JSONL with `_index.json` metadata). Evolution status is at `workspace/logs/evolution.status` (JSON array).
