---
name: evolve-refactoring
description: "Code refactoring guide for evolve-agent. Use when agent needs to (1) improve existing code structure, (2) optimize performance, (3) enhance code readability, (4) reduce technical debt, (5) apply design patterns, or (6) modernize code style. Triggers on code quality improvements, structural changes, and optimization tasks in evolve-agent contexts."
---

# Evolve Refactoring

Guide for safe and effective code refactoring in evolve-agent.

## Refactoring Principles

### Core Rules

1. **Preserve Behavior** - Functionality must remain identical
2. **Small Steps** - One change at a time
3. **Validate Frequently** - Check after each change
4. **Maintain Compatibility** - Don't break existing interfaces
5. **Document Intent** - Explain why, not just what

### Refactoring vs Evolution

| Evolution | Refactoring |
|-----------|-------------|
| Adds new features | Improves existing code |
| Changes behavior | Preserves behavior |
| Can break compatibility | Maintains compatibility |
| Often adds code | Often removes/reduces code |

## Refactoring Patterns

### 1. Extract Function

**When**: Long function doing multiple things

**Before**:
```python
def process_data(data):
    # Parse CSV
    rows = []
    for line in data.split('\n'):
        rows.append(line.split(','))
    
    # Transform
    results = []
    for row in rows:
        results.append({"name": row[0], "value": int(row[1])})
    
    # Save
    with open('output.json', 'w') as f:
        json.dump(results, f)
    
    return len(results)
```

**After**:
```python
def parse_csv(data: str) -> list[list[str]]:
    """Parse CSV string into rows."""
    return [line.split(',') for line in data.split('\n') if line]

def transform_rows(rows: list[list[str]]) -> list[dict]:
    """Transform rows to dict format."""
    return [{"name": row[0], "value": int(row[1])} for row in rows]

def save_json(data: list[dict], path: str) -> None:
    """Save data to JSON file."""
    with open(path, 'w') as f:
        json.dump(data, f)

def process_data(data: str) -> int:
    """Process CSV data and save to JSON."""
    rows = parse_csv(data)
    results = transform_rows(rows)
    save_json(results, 'output.json')
    return len(results)
```

### 2. Replace Conditional with Polymorphism

**When**: Switch statements or long if-elif chains

**Before**:
```python
def calculate_area(shape, **kwargs):
    if shape == "circle":
        return 3.14 * kwargs["radius"] ** 2
    elif shape == "rectangle":
        return kwargs["width"] * kwargs["height"]
    elif shape == "triangle":
        return 0.5 * kwargs["base"] * kwargs["height"]
```

**After**:
```python
from abc import ABC, abstractmethod
from typing import Protocol

class Shape(Protocol):
    def area(self) -> float: ...

@dataclass
class Circle:
    radius: float
    
    def area(self) -> float:
        return 3.14 * self.radius ** 2

@dataclass
class Rectangle:
    width: float
    height: float
    
    def area(self) -> float:
        return self.width * self.height

def calculate_area(shape: Shape) -> float:
    return shape.area()
```

### 3. Introduce Parameter Object

**When**: Function has too many parameters

**Before**:
```python
def create_user(name, email, age, country, city, zip_code):
    pass
```

**After**:
```python
@dataclass
class UserInfo:
    name: str
    email: str
    age: int

@dataclass
class Address:
    country: str
    city: str
    zip_code: str

def create_user(info: UserInfo, address: Address):
    pass
```

### 4. Remove Duplication (DRY)

**When**: Same code appears in multiple places

**Before**:
```python
def process_a(data):
    cleaned = data.strip().lower()
    validated = validate(cleaned)
    return transform(validated)

def process_b(data):
    cleaned = data.strip().lower()
    validated = validate(cleaned)
    return format(validated)
```

**After**:
```python
def prepare_data(data: str) -> str:
    """Common preparation pipeline."""
    cleaned = data.strip().lower()
    return validate(cleaned)

def process_a(data: str):
    prepared = prepare_data(data)
    return transform(prepared)

def process_b(data: str):
    prepared = prepare_data(data)
    return format(prepared)
```

### 5. Rename for Clarity

**When**: Names don't clearly convey intent

**Before**:
```python
def calc(d, m):
    return d * m
```

**After**:
```python
def calculate_monthly_revenue(daily_revenue: float, days_in_month: int) -> float:
    """Calculate total monthly revenue from daily average."""
    return daily_revenue * days_in_month
```

## Code Quality Improvements

### Type Hints

Add comprehensive type hints:

```python
from __future__ import annotations
from typing import Any, Dict, List, Optional, Protocol

# Before
def process(items, callback):
    pass

# After
def process(
    items: list[dict[str, Any]],
    callback: callable[[dict], bool]
) -> list[dict[str, Any]]:
    pass
```

### Docstrings

Add Google-style docstrings:

```python
def validate_code(path: str, deep: bool = True) -> dict:
    """Validate Python code for syntax and compilation errors.
    
    Args:
        path: Path to Python file or directory.
        deep: If True, also check compilation (slower but thorough).
        
    Returns:
        Dictionary with validation results:
            - valid: bool indicating if all checks passed
            - errors: List of error dictionaries with file, line, message
            - checked: Number of files checked
            
    Raises:
        FileNotFoundError: If path doesn't exist.
        PermissionError: If file cannot be read.
        
    Example:
        >>> result = validate_code("src/main.py")
        >>> print(result["valid"])
        True
    """
    pass
```

### Error Handling

Improve error handling:

```python
# Before
def load_config(path):
    with open(path) as f:
        return json.load(f)

# After
class ConfigError(Exception):
    """Raised when configuration cannot be loaded."""
    pass

def load_config(path: str) -> dict:
    """Load configuration from JSON file."""
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        raise ConfigError(f"Config file not found: {path}")
    except json.JSONDecodeError as e:
        raise ConfigError(f"Invalid JSON in {path}: {e}")
```

## Performance Optimization

### Lazy Evaluation

```python
# Before - eager loading
ALL_TOOLS = load_all_tools()  # Expensive at import

# After - lazy loading
_tools_cache: list | None = None

def get_tools() -> list:
    global _tools_cache
    if _tools_cache is None:
        _tools_cache = load_all_tools()
    return _tools_cache
```

### Caching

```python
from functools import lru_cache

@lru_cache(maxsize=128)
def expensive_calculation(key: str) -> dict:
    """Cached expensive operation."""
    return heavy_computation(key)
```

### Generator Expressions

```python
# Before - builds full list in memory
def get_large_dataset():
    return [process(item) for item in huge_list]

# After - lazy evaluation
def get_large_dataset():
    for item in huge_list:
        yield process(item)
```

## Refactoring Workflow

### Step-by-Step Process

```
┌─────────────────┐
│ 1. Read Existing│
│     Code        │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ 2. Identify     │
│   Issues        │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ 3. Plan Changes │
│   (one at a time)│
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ 4. Apply Change │
└────────┬────────┘
         │
         ▼
┌─────────────────┐     ┌─────────────┐
│ 5. Validate     │────▶│ Fix Errors  │
│    (validate_code)    │   if any    │
└────────┬────────┘     └─────────────┘
         │
         ▼
┌─────────────────┐
│ 6. Test if      │
│   possible      │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ 7. Repeat or    │
│   Finalize      │
└─────────────────┘
```

### Validation During Refactoring

After each change:

```python
# 1. Syntax check
validate_code: {"file": "component/tools/my_tool.py"}

# 2. Import check (if applicable)
run_command: {
  "command": ["python", "-c", "import component.tools.my_tool"],
  "reason": "Test import after refactoring"
}

# 3. Full validation before evolving
evolution: {
  "validate_code": {},
  "evolve_code": {}
}
```

## Safety Rules

### Do's

- ✅ Add type hints without changing logic
- ✅ Extract functions while preserving behavior
- ✅ Rename variables for clarity
- ✅ Add docstrings
- ✅ Improve error messages
- ✅ Add input validation
- ✅ Use constants for magic numbers

### Don'ts

- ❌ Change function signatures (breaking change)
- ❌ Modify return types without updating callers
- ❌ Remove error handling
- ❌ Change default values
- ❌ Reorder parameters
- ❌ Remove exported symbols
- ❌ Make multiple refactoring changes at once

## Compatibility Patterns

### Gradual Migration

When changing interfaces, support both temporarily:

```python
def new_function(param: str, options: dict | None = None) -> dict:
    """New improved interface."""
    pass

def old_function(param: str, option1=None, option2=None):
    """Deprecated - use new_function instead."""
    import warnings
    warnings.warn("old_function is deprecated, use new_function", DeprecationWarning)
    options = {}
    if option1:
        options['option1'] = option1
    if option2:
        options['option2'] = option2
    return new_function(param, options)
```

### Feature Flags

```python
def process_data(data, use_new_algorithm=False):
    """Process with optional new algorithm."""
    if use_new_algorithm:
        return _new_algorithm(data)
    return _legacy_algorithm(data)
```

## Common Refactoring Targets

### High Priority

1. **Long functions** (> 50 lines)
2. **Deep nesting** (> 3 levels)
3. **Duplicate code** (copy-paste patterns)
4. **Magic numbers** (bare numeric literals)
5. **Missing type hints**
6. **Poor naming**

### Medium Priority

1. **Long parameter lists** (> 4 parameters)
2. **Large classes** (> 300 lines)
3. **Feature envy** (class uses another's data heavily)
4. **Shotgun surgery** (change requires many edits)

### Low Priority

1. **Code formatting** (whitespace, alignment)
2. **Import organization** (alphabetical, grouping)
3. **Comment updates** (unless wrong)

## Measuring Improvement

### Before/After Metrics

Track these during refactoring:

| Metric | Target |
|--------|--------|
| Lines per function | < 30 |
| Nesting depth | < 3 |
| Parameters per function | < 4 |
| Cyclomatic complexity | < 10 |
| Type coverage | > 90% |
| Docstring coverage | > 80% |
