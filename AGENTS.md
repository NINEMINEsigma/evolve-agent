# Evolve Agent — AGENTS.md

> ⚠️ **极度重要 — 绝对禁止** ⚠️
>
> **不要在 `origin_agent/frontend/` 目录下执行 `pnpm install`、`pnpm build`、`pnpm dev` 或任何其他 pnpm/npm 命令。**
>
> **同时绝对禁止在该目录或任何位置执行 `npx tsc`、`pnpm exec tsc`、`npm run typecheck`、`npm run lint` 等任何以“验证”为目的的构建/类型/语法检查命令。**
>
> `origin_agent/` 是唯一的源码真相源；前端构建必须由 `run.py` 在启动时自动复制到 `workspace/fast_agent_space/frontend/` 后进行。在 `origin_agent/frontend/` 下运行这些命令会污染源码目录、破坏构建环境，并导致不可预期的运行时错误。
>
> **严格禁止在任何位置执行 `python run.py`、`python check_env.py` 或任何其他构建/运行/启动/验证命令，除非用户明确授权。** 修改源码后不得主动替用户运行验证，必须由用户自行决定是否以及何时启动。
>
> **即使用户主动要求，也绝对禁止代其执行构建、运行或验证命令；请直接拒绝并告知用户自行在本地执行。** 如果用户报构建错误，你只能修改源码，不能通过执行任何命令来“验证”或“复现”。
>
> 违反本条造成的构建失败或状态损坏，必须优先清理并恢复 `origin_agent/frontend/` 环境。

## Startup

```bash
python run.py --load default
```

Requires `OPENAI_API_KEY`. Optional `OPENAI_BASE_URL` to override default LLM endpoint. Web UI at `http://127.0.0.1:8765`.

CLI flags (override `config.py` defaults): `--fouce_init`, `--approval_model_path`, `--approval_model_cuda`, `--llm_model`, `--llm_temperature`, `--llm_max_context_tokens`, `--llm_max_output_tokens`, `--llm_reasoning_effort`, `--gateway_host`, `--gateway_port`, `--console_log`.

Environment check: `python check_env.py --cuda`

### Configuration gotchas

- `config.py` prompts interactively for a config key unless `--load <key>` or `--save <key>` is given. In non-interactive/agent sessions always pass `--load default` (or another key from `config.json`).
- `config.json` contains an unencrypted API key and is gitignored. Do not commit it.
- The `default` config in `config.json` has `fouce_init: true`, so `--load default` wipes `workspace/` on each start. Use a different config key for persistent workspaces.

## Iron rules

- **Never execute `origin_agent/` directly.** `run.py` copies it to `workspace/fast_agent_space/` before running. No: `origin_agent/__main__.py` direct execution, `pnpm install/build/dev` in `origin_agent/frontend/`, or using `origin_agent/` paths in `sys.path` or `cwd`.
- **Never run validation commands on behalf of the user.** This includes `npx tsc`, `pnpm exec tsc`, `npm run typecheck`, `npm run lint`, `pnpm build`, `python check_env.py`, or any other command whose purpose is to verify builds/types/syntax. When the user reports a build error, only edit source code; never try to reproduce or validate by running commands.
- **Never modify `workspace/` code files** (`.py`, `.js`, `.ts`, `.tsx`, `.css`). They are runtime copies — changes are lost on re-init. Non-code files (logs, JSON) are readable but not writable.
- **Never read or search `workspace/` code files.** Do not use them as code evidence; they are runtime copies of `origin_agent/`.
- **Never use scripts to batch-edit source files.** Make targeted, reviewable edits.
- `origin_agent/frontend/` is not at the repo root, so static type/IDE awareness may be inaccurate. Before relying on frontend type checks or builds, stop and notify the user.

## Architecture

```
origin_agent/        ← sole source of truth (edit here)
workspace/
  fast_agent_space/    running agent copy
  slow_agent_space/    evolution target (fork:)
  .fallback/           previous fast backup (for repair)
  agentspace/          agent I/O workspace (ws:)
  logs/                sessions, evolution status
third/               ← git submodules: easysave, filesystem, llamaapis
```

- No CI/CD, no test framework, no lint/typecheck. Pure runtime code evolution.
- `pyrightconfig.json` adds `origin_agent/` and `third/` to `extraPaths`.
- `.shell_allowlist.json` at project root stores permanently-allowed shell commands.

## Tool registration style

When adding new `registry.register(...)` tools, follow the convention in `component/tools/`:

- `schema["description"]` is written in English.
- The line immediately above the `description` string is a Chinese comment explaining the tool behavior.

## Lifecycle (run.py)

1. First run or `--fouce_init`: wipe `workspace/*`, copy `origin_agent/` to both `fast_agent_space/` and `slow_agent_space/`.
2. Run `fast_agent_space/__main__.py`.
3. Exit code `0` = normal stop. `-1` = evolution swap (fast → .fallback, slow → fast, restart). Other = fallback mode (run `.fallback/__main__.py` to repair).

## Sandbox

All file operations use logical path prefixes. No bare paths, no `..`, no absolute paths.

| Prefix | Maps to | Mode | Permission |
|--------|---------|------|------------|
| `fork:` | `slow_agent_space/` | fast | rw |
| `ws:` | `agentspace/` | fast / fallback | rw |
| `fix:` | `.fallback/` | fallback | rw |

There is **no** `self:` namespace. Agent reads its own source from `fork:` (which starts as a copy of `origin_agent/`).

## Evolution flow

```
read_file (fork:path) → write_fork (or edit_file fork:path) → validate_code → [validate_frontend if frontend changed] → evolve_code
```

- `read_own_source` is **disabled** (handler exists but not registered). Use `read_file` with `fork:` prefix instead.
- `write_fork` supports 3 modes: full overwrite (content), incremental edit (old_string+new_string), append (content+append=true). Max 1000 chars for overwrite, 10 lines for append.
- `edit_file` (filesystem.py:274): same-purpose incremental edit using `fork:`/`ws:`/`fix:` prefix.
- `validate_code`: AST syntax check on `fork:` all `.py` files.
- `validate_frontend`: runs `pnpm install && pnpm run build` on `fork:frontend`. Required if frontend touched.
- `evolve_code` calls `finalize_evolution()` → py_compile deep check → triggers exit code -1.
- `fouce_init` is intentionally misspelled (not `force_init`).
- `diff_fast_fork`: compare `fast_agent_space/` vs `fork:` before swapping; skip `evolve_code` if identical.

## Template system

Assembled by `system/prompt.py`. Detects `templates/zh/` existence → defaults to Chinese. Hierarchy: `GENE > SOUL > base > modes/{fast,fallback} > tools > memory > skills`.

## Tool system

Tools register via `registry.register()` at import time. Auto-discovered by AST scan (`abstract/tools/discover.py`) scanning for module-level `registry.register()` calls. Tool sources:

- `component/tools/` — core (filesystem, code, shell, frontend, skills, read_image, run_python)
- `component/extools/` — extras (web_search, web_fetch, csv_tools, excel_tools, docx_tools, pdf_tools, diff_tools, ffmpeg_tools, diagram, display, docgen_tools, excalidraw_render, gui_windows, pip, ssh_tools, web_browser)
- `custom_tools/` — user-defined, auto-discovered if directory exists

## Approval (component/approval.py)

- **Normal mode**: user confirms tools via WebSocket frontend prompt.
- **Adventure mode**: local GGUF model auto-approves. Enable via `--approval_model_path <gguf>` and optional `--approval_model_cuda`. Uses `third/llamaapis` (llama.cpp subprocess wrapper). Model files go in `custom_models/`.

## Frontend

React + Vite + TypeScript in `origin_agent/frontend/`. Uses pnpm (**pnpm.cmd** on Windows). Auto-built at startup (`_build_frontend()` in `__main__.py:141`): `pnpm install && pnpm run build`. Build failure → exit code 1 → orchestrator enters fallback mode.

## Memory

`memory/provider.py`: `EasysaveMemoryProvider` backed by `third/easysave`. Sessions persisted to `workspace/logs/sessions/` (JSONL) with `_index.json` metadata. Evolution status at `workspace/logs/evolution.status` (JSON array).

## Windows specifics

- Python command is `python` (not `python3`).
- Native executables (pnpm, etc.) invoked as `pnpm.cmd`.
- Process tree kill uses `taskkill /T /F`.
- Sandbox subprocess uses `CREATE_NEW_PROCESS_GROUP`.
- `signal.add_signal_handler` unavailable → falls back to `signal.signal`.

## pre-skills/

`pre-skills/` contains built-in skill templates for agent self-evolution (evolve-architect, evolve-code-engineer, evolve-code-validator, evolve-debugger, evolve-frontend-builder, etc.). These are reference guides; the agent can load them as skills at runtime.
