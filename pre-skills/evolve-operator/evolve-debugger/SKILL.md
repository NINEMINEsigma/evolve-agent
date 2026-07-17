---
name: evolve-debugger
description: "Debugging and troubleshooting guide for evolve-agent. Use when agent needs to (1) diagnose runtime errors, (2) fix code in fallback mode, (3) investigate validation failures, (4) trace code execution issues, (5) handle evolution errors, or (6) recover from crashes. Triggers on error handling, fallback mode activation, and debugging tasks in evolve-agent contexts."
---

# Evolve Debugger

Guide for debugging and troubleshooting in evolve-agent's self-evolving system.

## Error Types and Responses

### 1. Validation Errors

**Symptoms**: `validate_code` returns syntax or compilation errors

**Diagnosis Flow**:
1. Read error message carefully (file, line, offset)
2. Use `read_file` to examine the problematic file
3. Look for:
   - Syntax errors (missing colons, brackets, quotes)
   - Indentation issues (mixed tabs/spaces)
   - Import errors (missing modules, circular imports)
   - Name errors (undefined variables)

**Fix Process**:
```
read_file: {"path": "fork:problematic.py", "offset": 40, "limit": 10}
→ Identify the issue
→ edit_file: {"path": "fork:problematic.py", "old_string": "...", "new_string": "..."}
→ validate_code: {"file": "problematic.py"}
→ evolve_code: {}
```

### 2. Fallback Mode Activation

**Symptoms**: Agent enters fallback mode (exit code not 0 or -1)

**Fallback Mode Rules**:
- `fix:` namespace becomes writable (points to `.fallback/`)
- `fork:` namespace is inaccessible
- Must fix code in `fix:` namespace
- After fixing, orchestrator resumes normal flow

**Debug Process in Fallback**:
1. Check logs: `read_file: {"path": "ws:logs/error.log"}`
2. List fallback directory: `list_directory: {"path": "fix:"}`
3. Identify broken files
4. Fix in `fix:` namespace:
   ```
   read_file: {"path": "fix:main.py"}
   write_file: {"path": "fix:main.py", "content": "..."}
   ```
5. Validation is automatic on restart

### 3. Frontend Build Errors

**Symptoms**: `validate_frontend` fails

**Common Issues**:
- TypeScript type errors
- Missing imports
- Build configuration issues
- Dependency conflicts

**Debug Process**:
```
validate_frontend: {"path": "fork:frontend"}
→ Check stdout/stderr for specific errors
→ Fix TypeScript or configuration issues
→ Re-run validate_frontend
→ Then evolve_code
```

### 4. Runtime Errors

**Symptoms**: Agent crashes during execution

**Investigation Steps**:
1. Check session logs: `ws:logs/sessions/`
2. Look for stack traces
3. Check imports and dependencies
4. Verify tool registrations

## Debugging Tools

### Available Diagnostic Tools

| Tool | Purpose | When to Use |
|------|---------|-------------|
| `read_file` | Examine code/logs | Always start here |
| `list_directory` | Explore structure | Finding files |
| `file_exists` | Check presence | Verification |
| `validate_code` | Syntax check | After code changes |
| `validate_frontend` | Build check | Frontend changes |
| `run_command` | System commands | Advanced debugging |

### Reading Logs

Session logs location: `ws:logs/sessions/`

```python
# Read session index
read_file: {"path": "ws:logs/sessions/_index.json"}

# Read specific session
read_file: {"path": "ws:logs/sessions/<session_id>.jsonl", "limit": 50}
```

Evolution status: `ws:logs/evolution.status`

## Common Error Patterns

### SyntaxError

```python
# Bad - missing colon
def my_function()
    pass

# Good
def my_function():
    pass
```

### ImportError

```python
# Bad - relative import without proper structure
from ..other import thing

# Good - absolute import
from abstract.tools.registry import registry
```

### IndentationError

```python
# Bad - mixed tabs and spaces
def func():
→   if True:
→   →   pass

# Good - consistent 4 spaces
def func():
→   if True:
→   →   pass
```

### Module Registration Error

```python
# Bad - registry not imported
registry.register(...)  # NameError

# Good
from abstract.tools.registry import registry
registry.register(...)
```

### Sandbox Violation

```
SandboxError: Path must use namespace prefix
# Fix: Use "fork:" or "ws:" prefix
```

## Fallback Mode Workflow

```
┌─────────────┐
│  Evolution  │
│   Fails     │
└──────┬──────┘
       │
       ▼
┌─────────────┐
│  Fallback   │
│   Mode      │
└──────┬──────┘
       │
       ▼
┌─────────────┐     ┌─────────────┐
│ Read error  │────▶│ List files  │
│    logs     │     │   in fix:   │
└─────────────┘     └──────┬──────┘
                           │
                           ▼
                    ┌─────────────┐
                    │  Identify   │
                    │  broken file│
                    └──────┬──────┘
                           │
                           ▼
                    ┌─────────────┐
                    │ Fix in fix: │
                    │ namespace   │
                    └──────┬──────┘
                           │
                           ▼
                    ┌─────────────┐
                    │   Restart   │
                    │  (auto)     │
                    └─────────────┘
```

## Debugging Best Practices

### 1. Start with Evidence

Always read logs and error messages before attempting fixes.

### 2. Make Minimal Changes

Fix one issue at a time. Don't refactor while debugging.

### 3. Validate Incrementally

Use `validate_code` after each fix to ensure progress.

### 4. Preserve Backwards Compatibility

Don't change tool schemas or function signatures during debugging.

### 5. Document the Fix

Add comments explaining why the fix was needed.

## Emergency Recovery

If evolution completely breaks:

1. Orchestrator will automatically use `.fallback/`
2. Fix critical issues in `fix:` namespace
3. Restart will resume from `.fallback/`
4. Once stable, can attempt evolution again

## Prevention Tips

- Always validate before evolving
- Test frontend separately with `validate_frontend`
- Keep changes small and focused
- Read existing code before modifying
- Follow established patterns
