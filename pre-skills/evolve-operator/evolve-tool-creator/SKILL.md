---
name: evolve-tool-creator
description: "Tool creation guide for evolve-agent. Use when agent needs to (1) create new tools in component/tools/, (2) register tools with the registry, (3) define tool schemas, (4) implement tool handlers, (5) understand tool discovery, or (6) follow tool conventions. Triggers on tool development, registry operations, and extending agent capabilities in evolve-agent contexts."
---

# Evolve Tool Creator

Complete guide for creating new tools in evolve-agent's tool system.

## Tool System Overview

### Architecture

```
┌─────────────────────────────────────┐
│           Tool Registry             │
│    (abstract/tools/registry.py)     │
└──────────────┬──────────────────────┘
               │
       ┌───────┴───────┐
       │               │
       ▼               ▼
┌──────────────┐ ┌──────────────┐
│  Tool Schema │ │   Handler    │
│  (OpenAI     │ │  (Function)  │
│   format)    │ │              │
└──────────────┘ └──────────────┘
       │               │
       └───────┬───────┘
               │
               ▼
┌─────────────────────────────────────┐
│      Tool Discovery (AST scan)      │
│    (abstract/tools/discover.py)     │
└─────────────────────────────────────┘
```

### Tool Registration Flow

1. Module imports trigger `registry.register()` calls
2. `discover.py` scans `.py` files for registrations
3. Registry stores schema + handler mapping
4. Agent loop retrieves schemas for LLM
5. LLM calls tools by name, registry dispatches to handler

## Creating a New Tool

### Step 1: Choose Location

Create file in: `component/tools/<tool_name>.py`

Existing examples:
- `filesystem.py` - File operations
- `code.py` - Code evolution
- `shell.py` - Command execution
- `skills.py` - Skill management
- `frontend.py` - Frontend validation

### Step 2: File Template

```python
"""<Brief description of what this tool does>.

Module imports trigger ``registry.register()`` calls.
"""

from __future__ import annotations

import logging
from typing import Any, Dict

from abstract.tools.registry import registry, tool_error, tool_result

logger = logging.getLogger(__name__)


# ── Handler Implementation ─────────────────────────────────────────


def _handle_<tool_name>(args: Dict[str, Any]) -> str:
    """<Description of handler logic>."""
    # 1. Extract parameters
    param1: str = str(args.get("param1", "")).strip()
    param2: int = int(args.get("param2", 0))
    
    # 2. Validate required parameters
    if not param1:
        return tool_error("param1 is required")
    
    # 3. Execute logic
    try:
        result = do_something(param1, param2)
        return tool_result(success=True, data=result)
    except Exception as exc:
        logger.exception("<tool_name> failed")
        return tool_error(str(exc))


# ── Registration ───────────────────────────────────────────────────


registry.register(
    name="<tool_name>",
    toolset="<category>",
    schema={
        "description": (
            "<Clear description for LLM>.\n\n"
            "<Usage examples if applicable>."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "param1": {
                    "type": "string",
                    "description": "<Description of parameter>.",
                },
                "param2": {
                    "type": "integer",
                    "description": "<Description with default>.",
                    "default": 0,
                },
            },
            "required": ["param1"],
        },
    },
    handler=_handle_<tool_name>,
    emoji="🔧",
)
```

### Step 3: Schema Design

#### Parameter Types

| Type | Use For | Example |
|------|---------|---------|
| `string` | Text, paths, identifiers | `"path": {"type": "string"}` |
| `integer` | Counts, IDs, offsets | `"limit": {"type": "integer"}` |
| `number` | Measurements | `"temperature": {"type": "number"}` |
| `boolean` | Flags | `"recursive": {"type": "boolean"}` |
| `array` | Lists | `"tags": {"type": "array", "items": {"type": "string"}}` |
| `object` | Complex data | `"config": {"type": "object"}` |

#### Constraints

```python
{
    "type": "integer",
    "description": "Number of results (1-100).",
    "minimum": 1,
    "maximum": 100,
    "default": 10,
}
```

#### Descriptions

Good descriptions include:
- What the parameter represents
- Valid values or format
- Default value if optional
- Examples

Example:
```python
"path": {
    "type": "string",
    "description": (
        "Logical path with namespace prefix. "
        "Use 'fork:' for evolution code, 'ws:' for workspace data. "
        "Example: 'ws:data/config.json'"
    ),
}
```

## Handler Patterns

### Basic Handler

```python
def _handle_simple(args: Dict[str, Any]) -> str:
    """Simple handler with single parameter."""
    name: str = str(args.get("name", "")).strip()
    if not name:
        return tool_error("name is required")
    
    return tool_result(message=f"Hello, {name}!")
```

### Handler with Optional Parameters

```python
def _handle_with_defaults(args: Dict[str, Any]) -> str:
    """Handler with optional parameters and defaults."""
    query: str = str(args.get("query", "")).strip()
    limit: int = int(args.get("limit", 10))  # Default: 10
    
    if not query:
        return tool_error("query is required")
    
    results = search(query, limit=limit)
    return tool_result(results=results, count=len(results))
```

### Async Handler

For I/O-bound operations:
```python
import asyncio

async def _handle_async(args: Dict[str, Any]) -> str:
    """Async handler for non-blocking operations."""
    url: str = str(args.get("url", "")).strip()
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                data = await response.text()
                return tool_result(data=data)
    except Exception as exc:
        return tool_error(str(exc))


registry.register(
    name="fetch_url",
    toolset="network",
    schema={...},
    handler=_handle_async,
    is_async=True,  # Mark as async
    emoji="🌐",
)
```

### Handler with File Operations

```python
from component.tools.filesystem import _s

def _handle_file_tool(args: Dict[str, Any]) -> str:
    """Handler using sandbox for file operations."""
    path: str = str(args.get("path", "")).strip()
    
    if not path:
        return tool_error("path is required")
    
    try:
        sandbox = _s()
        content = sandbox.read(path)
        return tool_result(content=content)
    except Exception as exc:
        return tool_error(str(exc))
```

## Tool Categories

Organize tools by `toolset`:

| Toolset | Purpose | Examples |
|---------|---------|----------|
| `filesystem` | File operations | read_file, write_file |
| `code` | Code evolution | validate_code, evolve_code |
| `shell` | System commands | run_command |
| `frontend` | Frontend build | validate_frontend |
| `skills` | Skill management | learn_skill, recall_skill |
| `network` | HTTP/WebSocket | (custom) |
| `utils` | Utilities | (custom) |

## Error Handling

### Return Types

Always return JSON string via helpers:

```python
# Success
tool_result(
    success=True,
    data=result,
    message="Operation completed"
)
# Returns: '{"success": true, "data": ..., "message": "..."}'

# Error
tool_error("Something went wrong")
# Returns: '{"error": "Something went wrong"}'
```

### Error Patterns

| Situation | Response |
|-----------|----------|
| Missing required param | `tool_error("param is required")` |
| Invalid param value | `tool_error("Invalid value for param: ...")` |
| File not found | `tool_error("File not found: ...")` |
| Permission denied | `tool_error("Access denied")` |
| Runtime exception | `tool_error(str(exc))` |

## Advanced Patterns

### Check Functions

Control tool availability:
```python
def _can_use_advanced_features() -> bool:
    """Check if advanced features are enabled."""
    return config.get("advanced_mode", False)


registry.register(
    name="advanced_tool",
    toolset="advanced",
    schema={...},
    handler=_handle_advanced,
    check_fn=_can_use_advanced_features,  # Tool only shown when True
)
```

### Tool Composition

Call other tools from handlers:
```python
def _handle_composite(args: Dict[str, Any]) -> str:
    """Handler that uses other tools."""
    # Call filesystem tool
    from component.tools.filesystem import _handle_read
    
    file_result = _handle_read({"path": args.get("path")})
    data = json.loads(file_result)
    
    if "error" in data:
        return tool_error(f"Failed to read file: {data['error']}")
    
    # Process and return
    return tool_result(processed=transform(data["content"]))
```

## Validation Checklist

Before finalizing a new tool:

- [ ] Tool name is descriptive and follows `snake_case`
- [ ] Toolset is appropriate for the category
- [ ] Schema is complete with all parameters
- [ ] Required parameters are marked
- [ ] Descriptions are clear and include examples
- [ ] Handler validates all inputs
- [ ] Handler uses try/except for error handling
- [ ] Returns proper JSON via tool_result/tool_error
- [ ] Logging is used for debugging
- [ ] Async handlers marked with `is_async=True`

## Testing New Tools

After creating a tool:

1. Validate code:
   ```
   validate_code: {"file": "component/tools/my_tool.py"}
   ```

2. Test via evolution:
   ```
   evolve_code: {}
   ```

3. After restart, tool will be auto-discovered

## Common Mistakes

### Mistake 1: Not Using Type Hints

```python
# Bad
def _handle_tool(args):
    name = args.get("name")

# Good
def _handle_tool(args: Dict[str, Any]) -> str:
    name: str = str(args.get("name", "")).strip()
```

### Mistake 2: Missing Validation

```python
# Bad - will crash if param missing
def _handle_tool(args: Dict[str, Any]) -> str:
    path = args["path"]  # KeyError!

# Good - safe access with validation
def _handle_tool(args: Dict[str, Any]) -> str:
    path: str = str(args.get("path", "")).strip()
    if not path:
        return tool_error("path is required")
```

### Mistake 3: Not Using Return Helpers

```python
# Bad - manual JSON
def _handle_tool(args: Dict[str, Any]) -> str:
    return json.dumps({"ok": True})

# Good - use helpers
def _handle_tool(args: Dict[str, Any]) -> str:
    return tool_result(success=True)
```

### Mistake 4: Module-Level Side Effects

```python
# Bad - side effects at import time
print("Loading tool")  # Don't do this
expensive_setup()      # Don't do this

# Good - lazy initialization
def _handle_tool(args: Dict[str, Any]) -> str:
    expensive_setup()  # Do this in handler
```
