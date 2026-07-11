---
name: evolve-architect
description: "System architecture design guide for evolve-agent. Use when agent needs to (1) design new modules or components, (2) plan directory structure for new features, (3) define interfaces between components, (4) refactor existing architecture, (5) understand module responsibilities and boundaries, or (6) plan integration with existing systems. Triggers on architectural planning, module creation, and system design tasks in evolve-agent contexts."
---

# Evolve Architect

Guide for designing system architecture and planning code structure in evolve-agent.

## Architecture Principles

### Directory Structure

```
origin_agent/
├── abstract/           # Abstract interfaces and contracts
│   ├── tools/         # Tool registry and discovery
│   ├── memory/        # Memory management interfaces
│   └── plugins/       # Plugin system
├── component/          # Concrete implementations
│   ├── tools/         # Tool handlers (filesystem, code, shell, etc.)
│   └── llm.py         # LLM client
├── system/            # Core infrastructure
│   ├── sandbox.py     # Path sandbox and security
│   ├── prompt.py      # Prompt assembly
│   ├── context.py     # Runtime context
│   └── pathutils.py   # Path utilities
├── evolve/            # Evolution system
│   ├── code.py        # Evolution orchestrator
│   └── validator.py   # Code validation
├── gateway/           # WebSocket and HTTP gateway
│   ├── server.py      # FastAPI server
│   └── chat.py        # Chat protocol
├── entry/             # Agent entry points
│   └── agent.py       # Main agent loop
├── dashboard/         # Web dashboard
│   └── server.py
├── memory/            # Memory provider implementations
│   └── provider.py
├── templates/         # Prompt templates
│   ├── base.txt
│   ├── tools.txt
│   └── zh/            # Chinese templates
└── frontend/          # React frontend (React + Vite + TypeScript)
```

### Module Responsibility Guidelines

| Module | Responsibility | Should NOT |
|--------|---------------|------------|
| `abstract/` | Define interfaces, contracts, base classes | Contain business logic |
| `component/` | Implement tools, concrete functionality | Import from `entry/` or `gateway/` |
| `system/` | Infrastructure, security, context | Contain tool implementations |
| `evolve/` | Code evolution, validation | Import from `component/` directly |
| `gateway/` | Web protocols, communication | Contain business logic |
| `entry/` | Agent lifecycle, main loop | Implement tools |

## Adding New Components

### 1. New Tool Development

Location: `component/tools/<tool_name>.py`

Requirements:
- Import `from abstract.tools.registry import registry, tool_error, tool_result`
- Register at module level with `registry.register()`
- Handler receives `Dict[str, Any]`, returns JSON string
- Use type hints: `from __future__ import annotations`
- Use module-level logger: `logger = logging.getLogger(__name__)`

Template:
```python
"""Description of the tool."""

from __future__ import annotations

import logging
from typing import Any, Dict

from abstract.tools.registry import registry, tool_error, tool_result

logger = logging.getLogger(__name__)


def _handle_my_tool(args: Dict[str, Any]) -> str:
    """Handler implementation."""
    param = str(args.get("param", "")).strip()
    if not param:
        return tool_error("param is required")
    
    try:
        # Implementation
        return tool_result(success=True, data=result)
    except Exception as exc:
        return tool_error(str(exc))


registry.register(
    name="my_tool",
    toolset="category",
    schema={
        "description": "What this tool does...",
        "parameters": {
            "type": "object",
            "properties": {
                "param": {
                    "type": "string",
                    "description": "Parameter description.",
                },
            },
            "required": ["param"],
        },
    },
    handler=_handle_my_tool,
    emoji="🔧",
)
```

### 2. New Abstract Module

Location: `abstract/<module_name>/`

Structure:
```
abstract/my_module/
├── __init__.py      # Public API exports
├── interface.py     # Abstract base classes
└── utils.py         # Helper functions
```

Requirements:
- Use ABC (Abstract Base Classes) for interfaces
- Define clear contracts
- Document expected behavior

### 3. New System Module

Location: `system/<module_name>.py`

Requirements:
- Handle cross-cutting concerns
- Maintain security boundaries
- Be stateless where possible
- Use dependency injection for context

## Interface Design

### Tool Schema Design

Good schema characteristics:
- Clear, descriptive parameter names
- Explicit required fields
- Sensible defaults
- Examples in descriptions

Example:
```python
{
    "description": (
        "Read file content with pagination support.\n\n"
        "Example: read_file: {\"path\": \"ws:data.txt\", \"offset\": 0, \"limit\": 50}"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Logical path with namespace prefix (ws:, fork:, fix:).",
            },
            "offset": {
                "type": "integer",
                "description": "Starting line (0-indexed, default 0).",
                "default": 0,
                "minimum": 0,
            },
            "limit": {
                "type": "integer",
                "description": "Max lines to return (1-100, default 100).",
                "default": 100,
                "minimum": 1,
                "maximum": 100,
            },
        },
        "required": ["path"],
    },
}
```

## Integration Patterns

### Tool Discovery

Tools are auto-discovered via `abstract/tools/discover.py`:
- Scans `component/tools/*.py`
- Finds `registry.register()` calls via AST
- Auto-imports modules

### Memory Integration

For tools needing memory:
```python
from abstract.memory.provider import get_memory_provider

memory = get_memory_provider()
memory.save("key", value)
value = memory.load("key")
```

### Sandbox Integration

For filesystem operations:
```python
from component.tools.filesystem import _s

sandbox = _s()
content = sandbox.read("ws:file.txt")
sandbox.write("ws:file.txt", content)
```

## Planning Checklist

Before implementing new architecture:

- [ ] Which existing module should host this functionality?
- [ ] Does it need a new module or fit in existing?
- [ ] What are the interfaces/contracts?
- [ ] How does it interact with sandbox?
- [ ] What tools need to be created?
- [ ] Does it need memory persistence?
- [ ] Are there frontend implications?
- [ ] How will it be tested?

## Common Patterns

### Registry Pattern

Used for tools, plugins, skills:
```python
class Registry:
    def register(self, name, toolset, schema, handler, **kwargs):
        # Register for auto-discovery
        pass
```

### Provider Pattern

Used for memory, LLM:
```python
class Provider:
    def get_instance(self):
        # Return configured instance
        pass
```

### Handler Pattern

Tool handlers follow convention:
```python
def _handle_<tool_name>(args: Dict[str, Any]) -> str:
    # Extract and validate args
    # Execute logic
    # Return tool_result() or tool_error()
```
