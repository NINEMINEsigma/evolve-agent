---
name: evolve-testing
description: "Testing and validation guide for evolve-agent. Use when agent needs to (1) verify code correctness, (2) validate changes work as intended, (3) test edge cases, (4) ensure no regressions, (5) understand validation tools, or (6) plan testing strategies. Triggers on code verification, quality assurance, and testing tasks in evolve-agent contexts."
---

# Evolve Testing

Guide for testing and validating code in evolve-agent's self-evolving system.

## Testing Philosophy

### Core Principles

1. **Validate Early** - Check code after every change
2. **Test Incrementally** - Small steps, immediate feedback
3. **Verify Behavior** - Ensure functionality is preserved
4. **Edge Cases Matter** - Test boundaries and errors
5. **No Assumptions** - Actually run the code

### Testing Pyramid for Agent Evolution

```
         ┌─────────┐
         │ Manual  │  <- User interaction
         │ Testing │
        ┌┴─────────┴┐
        │ Integration│  <- Tool interactions
        │   Tests   │
       ┌┴───────────┴┐
       │  Validation  │  <- Syntax + compilation
       │   (Built-in) │
      ┌┴──────────────┴┐
      │   Import Tests   │  <- Module loading
      └──────────────────┘
```

## Built-in Validation Tools

### 1. validate_code

**Purpose**: Syntax and compilation checking

**Usage**:
```
# Validate single file
validate_code: {"file": "component/tools/my_tool.py"}

# Validate all files in fork:
validate_code: {}
```

**What it checks**:
- Python syntax (`ast.parse`)
- Import resolution
- Basic compilation errors

**Response interpretation**:
```json
{
  "valid": true,           // All checks passed
  "checked": 5,            // Number of files checked
  "results": [...]         // Per-file results
}
```

### 2. validate_frontend

**Purpose**: Frontend build validation

**Usage**:
```
validate_frontend: {"path": "fork:frontend"}
```

**What it checks**:
- `pnpm install` succeeds
- `pnpm run build` succeeds
- TypeScript compilation
- No build errors

**When to use**:
- After modifying `.tsx` files
- After changing `package.json`
- Before `evolve_code` with frontend changes

### 3. evolve_code

**Purpose**: Final validation and evolution trigger

**Usage**:
```
# Deep validation (default)
evolve_code: {"deep": true}

# Quick validation (syntax only)
evolve_code: {"deep": false}
```

**What it does**:
1. Validates all `.py` files in `fork:`
2. Runs compilation checks (if deep=True)
3. If valid, triggers slow→fast swap
4. Process exits with code -1

**Response**:
```json
{
  "evolved": true,         // Evolution triggered
  "validation": {
    "valid": true,
    "checked": 10,
    "results": [...]
  }
}
```

## Manual Testing Strategies

### Import Testing

Test that modules can be imported:

```
run_command: {
  "command": ["python", "-c", "from component.tools.my_tool import _handle_function"],
  "reason": "Test import of refactored module"
}
```

### Function Testing

Test specific functions:

```
run_command: {
  "command": [
    "python", "-c",
    "from component.tools.utils import parse_path; print(parse_path('ws:test.txt'))"
  ],
  "reason": "Test parse_path function"
}
```

### File Operations Testing

Test file operations work correctly:

```
# Setup test
write_file: {"path": "ws:test_input.txt", "content": "test data"}

# Run operation
read_file: {"path": "ws:test_input.txt"}

# Verify output
# (assert content matches expected)

# Cleanup
delete_file: {"path": "ws:test_input.txt"}
```

## Testing Checklist

### Before Evolution

- [ ] Syntax validation passes (`validate_code`)
- [ ] All imports resolve (import test)
- [ ] No undefined variables
- [ ] Type hints are valid (if using mypy)
- [ ] Frontend builds (if applicable) (`validate_frontend`)

### After Evolution

- [ ] Process restarts successfully
- [ ] No import errors on startup
- [ ] Tools register correctly
- [ ] Basic operations work
- [ ] No console errors

### Edge Cases to Test

- [ ] Empty input handling
- [ ] Maximum input size
- [ ] Special characters
- [ ] Unicode text
- [ ] Missing optional parameters
- [ ] Invalid parameter types
- [ ] File not found scenarios
- [ ] Permission denied scenarios
- [ ] Network timeouts (if applicable)

## Validation Workflows

### Workflow 1: Simple Python Change

```
┌─────────────────┐
│ Make changes to │
│   Python file   │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ validate_code:  │
│ {"file": "..."} │
└────────┬────────┘
         │
     ┌───┴───┐
     │       │
    OK     FAIL
     │       │
     ▼       ▼
┌─────────┐ ┌─────────┐
│evolve_  │ │ Fix     │
│code: {} │ │ errors  │
└────┬────┘ └────┬────┘
     │           │
     ▼           │
┌─────────┐      │
│ Process │◄─────┘
│ exits -1│ (retry)
└────┬────┘
     │
     ▼
┌─────────┐
│Restart  │
│with new │
│ code    │
└─────────┘
```

### Workflow 2: Frontend Change

```
┌─────────────────┐
│ Modify frontend │
│  files (.tsx)   │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ validate_       │
│ frontend: {}    │
└────────┬────────┘
         │
     ┌───┴───┐
     │       │
    OK     FAIL
     │       │
     ▼       ▼
┌─────────┐ ┌─────────┐
│ validate│ │ Fix TS  │
│ _code   │ │ errors  │
│ {}      │ │         │
└────┬────┘ └────┬────┘
     │           │
     ▼           │
┌─────────┐      │
│evolve_  │◄─────┘
│code: {} │ (retry)
└────┬────┘
     │
     ▼
┌─────────┐
│ Restart │
└─────────┘
```

### Workflow 3: Complex Multi-File Change

```
┌──────────────────────────┐
│ Change multiple related  │
│ files                    │
└───────────┬──────────────┘
            │
            ▼
┌──────────────────────────┐
│ validate_code: {}        │
│ (check all fork: files)  │
└───────────┬──────────────┘
            │
            ▼
┌──────────────────────────┐
│ If frontend changed:     │
│ validate_frontend: {}    │
└───────────┬──────────────┘
            │
            ▼
┌──────────────────────────┐
│ Test critical imports:   │
│ run_command: ["python",  │
│   "-c", "import ..."]    │
└───────────┬──────────────┘
            │
            ▼
┌──────────────────────────┐
│ evolve_code: {}          │
└──────────────────────────┘
```

## Regression Testing

### What to Check

After evolution, verify:

1. **Core functionality still works**:
   - File operations
   - Tool registration
   - Memory access
   - LLM communication

2. **No broken imports**:
   ```python
   # Test all major modules import
   python -c "
   from component.tools import filesystem, code, shell
   from system import sandbox, prompt
   from evolve import code as evolve_code
   print('All imports OK')
   "
   ```

3. **Tool registry intact**:
   ```
   list_skills: {}
   # Should return all expected skills
   ```

### Regression Test Suite

Create a simple validation script:

```python
# ws:tests/regression.py
"""Quick regression tests after evolution."""

def test_imports():
    """Test all critical imports."""
    try:
        from component.tools import filesystem, code, shell, skills
        from system import sandbox, prompt, context
        from evolve import code as evolve_code
        print("✓ Imports OK")
        return True
    except Exception as e:
        print(f"✗ Import failed: {e}")
        return False

def test_sandbox():
    """Test sandbox operations."""
    try:
        from component.tools.filesystem import _s
        s = _s()
        # Test read
        s.read("ws:test.txt")
        print("✓ Sandbox OK")
        return True
    except Exception as e:
        print(f"✗ Sandbox failed: {e}")
        return False

def test_tools():
    """Test tool registry."""
    try:
        from abstract.tools.registry import registry
        tools = registry.get_definitions()
        print(f"✓ Tools OK ({len(tools)} tools)")
        return True
    except Exception as e:
        print(f"✗ Tools failed: {e}")
        return False

if __name__ == "__main__":
    results = [
        test_imports(),
        test_sandbox(),
        test_tools(),
    ]
    if all(results):
        print("\n✓ All regression tests passed")
    else:
        print("\n✗ Some tests failed")
```

## Debugging Failed Tests

### Validation Fails

1. **Read the error carefully**:
   - File path
   - Line number
   - Error message

2. **Examine the file**:
   ```
   read_file: {"path": "fork:broken.py", "offset": error_line - 3, "limit": 7}
   ```

3. **Fix and retry**:
   ```
   write_fork: {"file": "broken.py", "old_string": "...", "new_string": "..."}
   validate_code: {"file": "broken.py"}
   ```

### Frontend Build Fails

1. **Check TypeScript errors**:
   - Look for type mismatches
   - Missing imports
   - Undefined variables

2. **Common fixes**:
   ```typescript
   // Add missing import
   import { SomeType } from './types';
   
   // Fix type error
   const value: string = data as string;
   
   // Add null check
   if (data) { ... }
   ```

### Import Errors

Circular import example and fix:

```python
# Bad - circular import
# a.py
from b import func_b

def func_a():
    func_b()

# b.py
from a import func_a  # Circular!

def func_b():
    pass

# Good - break the cycle
# a.py
import b

def func_a():
    b.func_b()

# b.py (no import from a)
def func_b():
    pass
```

## Best Practices

### 1. Test Small Changes

Don't batch many changes together. Test each:

```
Change A → validate → Change B → validate → evolve
```

### 2. Validate Before Finalizing

Always run validation before `evolve_code`:

```
validate_code: {}  # <-- Don't skip this!
evolve_code: {}
```

### 3. Keep Test Files

Use `ws:` namespace for tests (they won't affect evolution):

```
ws:tests/unit/test_parser.py
ws:tests/integration/test_workflow.py
```

### 4. Document Test Cases

Add comments explaining what you're testing:

```python
# Test: Ensure empty input returns empty list
# Edge case: None input should raise ValueError
```

### 5. Cleanup After Testing

Remove temporary test files:

```
delete_file: {"path": "ws:test_input.txt"}
delete_file: {"path": "ws:test_output.txt"}
```
