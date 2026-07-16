---
name: evolve-code-validator
description: "Python code validation for self-evolving agents. Use when agent needs to (1) validate evolved code before finalization, (2) check Python syntax using ast.parse, (3) verify code compiles with py_compile, (4) validate import statements and module dependencies, (5) run directory-wide validation checks, (6) diagnose syntax or compilation errors in fork namespace code, or (7) ensure code quality before triggering the evolution swap. Triggers on code verification, validation, and pre-commit checks in evolve-agent contexts."
---

# Evolve Code Validator

Guide for validating evolved Python code before triggering the slow→fast swap.

## Validation System

The validator provides two levels of checks:

| Check | Method | Catches | Speed |
|---|---|---|---|
| Syntax | `ast.parse()` | Syntax errors, invalid Python grammar | Fast |
| Compile | `py_compile.compile()` | Import errors, missing dependencies, broken relative imports | Slower |

## When to Validate

**Always validate** after writing code to `fork:` namespace and before calling `evolve_code`.

Validation workflow:

1. Write code with `write_file` or `edit_file` (with `fork:` prefix)
2. Call `evolve_code` tool (triggers validation internally)
3. If validation fails → fix errors → repeat
4. If validation passes → process exits with code -1 → orchestrator swaps slow→fast

## Manual Validation

The `evolve_code` tool performs validation automatically. Do not call validation functions directly — use the tool.

```
evolve_code: {}   # Uses deep=True by default (both syntax + compile checks)
```

## Interpreting Validation Results

### Success Response

```json
{
  "evolved": true,
  "validation": {
    "valid": true,
    "checked": 5,
    "syntax_ok": 5,
    "compile_ok": 5,
    "results": [...]
  }
}
```

After this response, the process exits with code -1. The orchestrator performs the swap and restarts.

### Failure Response

```json
{
  "evolved": false,
  "validation": {
    "valid": false,
    "checked": 5,
    "syntax_ok": 4,
    "compile_ok": 5,
    "results": [
      {
        "file": "broken.py",
        "status": "syntax_error",
        "line": 42,
        "offset": 15,
        "message": "invalid syntax"
      }
    ]
  }
}
```

When validation fails:
1. Read the error details from the response
2. Use `read_own_source` to examine the problematic file
3. Fix the code with `write_file` or `edit_file` (with `fork:` prefix)
4. Call `evolve_code` again

## Common Errors and Fixes

| Error Type | Example Fix |
|---|---|
| Syntax error | Check indentation, colons, brackets, quotes |
| Import error | Ensure module exists, fix relative import paths |
| Name error | Define missing variables or functions |
| Indentation error | Use consistent 4-space indentation |

## Validation Scope

The validator checks **all `.py` files** in the `fork:` namespace recursively. Ensure every Python file is valid — not just the ones you modified.

## Deep vs Shallow Validation

- `deep=True` (default): Both syntax + compile checks. Use for final validation.
- `deep=False`: Syntax only. Use for quick iteration during development.

## Critical Rules

- Always validate before finalizing evolution
- Fix all errors — partial fixes will still fail validation
- Pay attention to line numbers and offsets in error messages
- Compilation errors often indicate missing imports or broken module structure
- Do not modify `fast_agent_space/` directly to fix errors — always use `fork:` namespace
