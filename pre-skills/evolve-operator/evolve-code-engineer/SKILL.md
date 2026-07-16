---
name: evolve-code-engineer
description: "Guide for safe code evolution in the evolve-agent self-evolving AI system. Use when agent needs to (1) modify source code in the slow_agent_space via fork namespace, (2) read existing source code from self namespace, (3) plan and execute code evolution, (4) write new Python modules or modify existing ones, (5) understand the fast-slow-fallback evolution architecture, or (6) develop, optimize, or validate code within the evolve-agent ecosystem. Triggers on code-writing tasks in self-evolving agent contexts."
---

# Evolve Code Engineer

Guide for safe code evolution in evolve-agent's fast-slow-fallback architecture.

## Core Architecture

```
origin_agent/         ← Source of truth (edit here in repo)
workspace/
  fast_agent_space/   ← Runtime copy (agent runs from here)
  slow_agent_space/   ← Evolution target (write code here via fork:)
  .fallback/          ← Backup of last fast (auto-managed)
```

Agent runs from `fast_agent_space/` but **must never modify it directly**. All evolution happens through `slow_agent_space/` (accessible as `fork:` namespace). When evolution is finalized, `run.py` orchestrator swaps slow→fast automatically.

## Reading Existing Code

Use `read_own_source` tool with **bare filenames** (no namespace prefix):

```
read_own_source: {"file": "main.py"}
read_own_source: {"file": "system/sandbox.py", "offset": 1, "limit": 50}
```

Bare filenames resolve to `self:` namespace (agent's current runtime). Always read existing code before modifying it.

## Writing Evolution Code

Use `write_file` or `edit_file` with `fork:` prefix:

```
write_file: {"path": "fork:main.py", "content": "..."}
edit_file: {"path": "fork:evolve/code.py", "old_string": "...", "new_string": "..."}
```

## Evolution Workflow

1. **Analyze** — Read existing code with `read_own_source`
2. **Plan** — Determine which files need changes and why
3. **Write** — Use `write_file` or `edit_file` to write modified code to `fork:` namespace
4. **Validate** — Call `evolve_code` tool to trigger validation
5. **Finalize** — If validation passes, agent exits with code -1; orchestrator swaps slow→fast and restarts

## Critical Rules

- **Never** use `self:` namespace in write operations
- **Never** write bare filesystem paths (always use bare filenames or `fork:`/`ws:`/`fix:` prefixes)
- **Never** modify `origin_agent/` directly — always go through `fork:` namespace
- After writing code, **always** call `evolve_code` tool to validate before finalizing
- Write complete files — partial updates are not supported; include full content
- Maintain Python module structure: preserve `__init__.py` files and relative imports

## Code Evolution Best Practices

- **Minimal changes**: Only modify what is necessary. Preserve existing structure and conventions.
- **Backward compatibility**: Maintain existing tool schemas and handler signatures.
- **Import safety**: Ensure all imports resolve correctly. Use absolute imports from the package root.
- **Error handling**: Return errors via `tool_error()` helper, success via `tool_result()`.
- **Logging**: Use `logging.getLogger(__name__)` for module-level loggers.
- **Type hints**: Use `from __future__ import annotations` and type-hint public functions.
- **Registry pattern**: Tools register via `registry.register()` at module level. Follow existing conventions in `component/tools/`.

## Fallback Mode

If evolution fails validation or produces runtime errors, the orchestrator enters **fallback mode**:
- `fix:` namespace becomes writable (points to `.fallback/`)
- Agent must fix code in `fix:` namespace
- After fixing, normal evolution flow resumes

## File Structure Preservation

When adding new modules, ensure the directory structure mirrors the existing pattern:

```
component/tools/your_new_tool.py    ← Register tool at module level
abstract/your_new_module/
    __init__.py
    your_module.py
```
