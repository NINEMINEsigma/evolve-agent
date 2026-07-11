---
name: evolve-sandbox-operator
description: "Path sandbox operations for the evolve-agent self-evolving system. Use when agent needs to (1) read or write files using logical paths with namespace prefixes, (2) understand the fork, ws, and fix namespace system, (3) perform filesystem operations within sandbox constraints, (4) check file permissions and access rights, (5) resolve logical paths to real filesystem paths, or (6) understand sandbox security boundaries. Triggers on filesystem operations, path resolution, and namespace-related tasks in evolve-agent contexts."
---

# Evolve Sandbox Operator

Guide for filesystem operations within evolve-agent's path sandbox.

## Namespace System

All filesystem paths **must** use logical paths with namespace prefixes. Bare paths are rejected.

| Namespace | Maps To | Mode | Purpose |
|---|---|---|---|
| `fork:` | `slow_agent_space/` | rw (fast mode) | Write evolved code here |
| `ws:` | `workspace/agentspace/` | rw | General agent I/O |
| `fix:` | `.fallback/` | rw (fallback mode) | Fix broken code |

No `self:` namespace for writes — agent cannot modify its own runtime copy.

## Reading Files

Use `read_file` tool with namespace prefix:

```
read_file: {"path": "ws:logs/error.log"}
read_file: {"path": "ws:config/settings.json", "offset": 1, "limit": 20}
```

Parameters:
- `path`: Logical path with namespace prefix
- `offset`: Starting line (default 0)
- `limit`: Max lines to read (default 100, max 100)

## Writing Files

Use `write_file` tool with namespace prefix:

```
write_file: {"path": "ws:output/result.json", "content": "..."}
write_file: {"path": "ws:notes/plan.md", "content": "...", "append": false}
```

For code evolution, prefer `write_fork` (resolves to `fork:` automatically).

## Listing Directories

Use `list_dir` tool:

```
list_dir: {"path": "ws:"}
list_dir: {"path": "fork:system/"}
```

## File Operations

| Operation | Tool | Example |
|---|---|---|
| Read | `read_file` | `read_file: {"path": "ws:data.txt"}` |
| Write | `write_file` | `write_file: {"path": "ws:out.txt", "content": "..."}` |
| List | `list_dir` | `list_dir: {"path": "fork:component/"}` |

## Path Rules

- **Always** use namespace prefixes: `fork:`, `ws:`, `fix:`
- **Never** use bare paths, `..`, or absolute filesystem paths
- **Never** attempt to write to `self:` — it does not exist
- All paths are relative within their namespace
- Path traversal (`../`) is unconditionally rejected

## Permission Model

Access depends on runtime mode:

**Fast mode** (normal operation):
- `fork:` — read + write
- `ws:` — read + write
- `fix:` — access denied

**Fallback mode** (error recovery):
- `fix:` — read + write
- `ws:` — read + write
- `fork:` — access denied

## Sandbox Errors

| Error | Cause | Fix |
|---|---|---|
| `SandboxError: path must use namespace prefix` | Missing `fork:`/`ws:`/`fix:` prefix | Add namespace prefix |
| `SandboxError: access denied` | Wrong mode or namespace | Check current mode, use correct namespace |
| `SandboxError: path traversal detected` | Contains `..` | Remove parent directory references |
| `SandboxError: absolute paths not allowed` | Starts with `/` | Use relative path with namespace |

## Code Evolution Paths

When evolving code, always use `fork:` namespace:

```
# Correct
write_fork: {"file": "main.py", "content": "..."}
read_own_source: {"file": "main.py"}  # Reads from self:

# Also correct (explicit)
write_file: {"path": "fork:main.py", "content": "..."}
read_file: {"path": "fork:main.py"}
```

## Workspace I/O Paths

For general data exchange (logs, configs, outputs), use `ws:` namespace:

```
read_file: {"path": "ws:logs/error.log"}
write_file: {"path": "ws:output/report.json", "content": "..."}
list_dir: {"path": "ws:"}
```
