---
name: evolve-memory-manager
description: "Memory management guide for evolve-agent. Use when agent needs to (1) persist knowledge across sessions, (2) store and retrieve memories, (3) manage conversation context, (4) understand memory providers, (5) implement long-term memory features, or (6) optimize memory usage. Triggers on memory operations, context persistence, and knowledge retention tasks in evolve-agent contexts."
---

# Evolve Memory Manager

Guide for using the memory system to persist knowledge across sessions in evolve-agent.

## Memory System Overview

### Architecture

```
┌─────────────────────────────────────────┐
│         Memory Provider Interface       │
│      (abstract/memory/provider.py)      │
└──────────────────┬──────────────────────┘
                   │
        ┌──────────┴──────────┐
        │                     │
        ▼                     ▼
┌───────────────┐     ┌───────────────┐
│  Easysave     │     │   Session     │
│  Provider     │     │   Memory      │
│ (persistent)  │     │  (temporary)  │
└───────────────┘     └───────────────┘
        │                     │
        ▼                     ▼
   workspace/           In-memory
   memory/              dictionary
```

### Memory Types

| Type | Persistence | Use Case | Location |
|------|-------------|----------|----------|
| **Session** | Temporary (per chat) | Conversation context, short-term state | In-memory |
| **Easysave** | Permanent (cross-session) | User preferences, learned patterns | `workspace/memory/` |

## Using Memory in Tools

### Basic Operations

```python
from abstract.memory.provider import get_memory_provider

# Get provider instance
memory = get_memory_provider()

# Save data
memory.save("user_preference", {"theme": "dark", "language": "zh"})

# Load data
prefs = memory.load("user_preference")
# Returns: {"theme": "dark", "language": "zh"}

# Delete data
memory.delete("user_preference")

# Check existence
exists = memory.exists("user_preference")
```

### Namespaced Keys

Use prefixes to organize memories:

```python
# User preferences
memory.save("pref:theme", "dark")
memory.save("pref:language", "zh")

# Learned facts
memory.save("fact:project_stack", ["React", "TypeScript", "Python"])

# Tool state
memory.save("state:last_command", "git commit")
```

## Memory Provider Implementation

### EasysaveMemoryProvider

Default provider using Easysave for persistence:

```python
# File-based storage
# Location: workspace/memory/easysave/
# Format: JSON files organized by key hash
```

Features:
- Automatic serialization (JSON)
- File-based persistence
- Namespace support
- Async-safe (file locking)

### Custom Provider

Create custom provider by implementing interface:

```python
from abstract.memory.provider import MemoryProvider
from typing import Any, Optional

class RedisMemoryProvider(MemoryProvider):
    """Redis-based memory provider."""
    
    def __init__(self, redis_url: str):
        import redis
        self.client = redis.from_url(redis_url)
    
    def save(self, key: str, value: Any) -> None:
        import json
        self.client.set(key, json.dumps(value))
    
    def load(self, key: str) -> Optional[Any]:
        import json
        data = self.client.get(key)
        return json.loads(data) if data else None
    
    def delete(self, key: str) -> None:
        self.client.delete(key)
    
    def exists(self, key: str) -> bool:
        return self.client.exists(key) > 0
```

## Memory Best Practices

### 1. Key Naming

Use hierarchical keys with colons:
```
user:<id>:preferences
project:<name>:config
tool:<name>:state
session:<id>:context
```

### 2. Value Size

Keep values reasonably sized:
- Small: < 10KB (preferences, flags)
- Medium: < 100KB (context, summaries)
- Large: > 100KB (consider file storage)

### 3. TTL and Cleanup

Implement expiration for temporary data:
```python
from datetime import datetime, timedelta

def save_with_ttl(key: str, value: Any, ttl_seconds: int):
    """Save with expiration."""
    expires_at = datetime.now() + timedelta(seconds=ttl_seconds)
    memory.save(key, {
        "value": value,
        "expires_at": expires_at.isoformat()
    })

def load_with_ttl(key: str) -> Any:
    """Load if not expired."""
    data = memory.load(key)
    if data:
        expires = datetime.fromisoformat(data["expires_at"])
        if datetime.now() < expires:
            return data["value"]
        memory.delete(key)
    return None
```

### 4. Error Handling

Always handle memory errors gracefully:
```python
try:
    data = memory.load("important_key")
except Exception as exc:
    logger.warning("Failed to load from memory: %s", exc)
    data = None  # Use default
```

## Use Cases

### User Preferences

```python
def get_user_theme() -> str:
    """Get user's preferred theme."""
    memory = get_memory_provider()
    return memory.load("pref:theme") or "light"

def set_user_theme(theme: str) -> None:
    """Save user's theme preference."""
    memory = get_memory_provider()
    memory.save("pref:theme", theme)
```

### Learned Patterns

```python
def record_successful_pattern(pattern: str) -> None:
    """Record a pattern that worked well."""
    memory = get_memory_provider()
    
    patterns = memory.load("learned:patterns") or []
    patterns.append({
        "pattern": pattern,
        "timestamp": datetime.now().isoformat(),
        "success_count": 1
    })
    
    # Keep only recent 100 patterns
    patterns = patterns[-100:]
    memory.save("learned:patterns", patterns)
```

### Conversation Context

```python
def save_conversation_context(session_id: str, context: dict) -> None:
    """Save conversation context for session."""
    memory = get_memory_provider()
    memory.save(f"session:{session_id}:context", context)

def load_conversation_context(session_id: str) -> dict:
    """Load conversation context."""
    memory = get_memory_provider()
    return memory.load(f"session:{session_id}:context") or {}
```

### Tool State Persistence

```python
def save_tool_state(tool_name: str, state: dict) -> None:
    """Persist tool state across restarts."""
    memory = get_memory_provider()
    memory.save(f"tool:{tool_name}:state", state)

def load_tool_state(tool_name: str) -> dict:
    """Restore tool state."""
    memory = get_memory_provider()
    return memory.load(f"tool:{tool_name}:state") or {}
```

## Integration with Skills

Skills can use memory to remember learned information:

```python
# In a skill or tool
def learn_from_interaction(data: dict) -> None:
    """Learn from user interaction."""
    memory = get_memory_provider()
    
    # Load existing knowledge
    knowledge = memory.load("agent:knowledge") or {}
    
    # Update with new information
    knowledge.update(extract_facts(data))
    
    # Save back
    memory.save("agent:knowledge", knowledge)
```

## Memory Management Tools

### List Memories

```python
def list_memories(prefix: str = "") -> list:
    """List all memory keys with optional prefix filter."""
    memory = get_memory_provider()
    # Implementation depends on provider
    return memory.list_keys(prefix)
```

### Clear Memories

```python
def clear_memories(prefix: str = "") -> None:
    """Clear memories matching prefix."""
    memory = get_memory_provider()
    keys = memory.list_keys(prefix)
    for key in keys:
        memory.delete(key)
```

### Memory Stats

```python
def get_memory_stats() -> dict:
    """Get memory usage statistics."""
    memory = get_memory_provider()
    return {
        "total_keys": len(memory.list_keys()),
        "size_bytes": memory.get_size(),
    }
```

## Performance Considerations

### Caching

Cache frequently accessed memory:
```python
from functools import lru_cache

@lru_cache(maxsize=128)
def get_cached_config(key: str) -> Any:
    """Cached config lookup."""
    memory = get_memory_provider()
    return memory.load(key)
```

### Batch Operations

Batch saves when possible:
```python
def batch_save(items: dict) -> None:
    """Save multiple items efficiently."""
    memory = get_memory_provider()
    for key, value in items.items():
        memory.save(key, value)
```

### Lazy Loading

Don't load memory until needed:
```python
class LazyMemory:
    """Lazy memory accessor."""
    
    def __init__(self):
        self._memory = None
    
    @property
    def memory(self):
        if self._memory is None:
            self._memory = get_memory_provider()
        return self._memory
```

## Migration Patterns

When changing memory structure:

```python
def migrate_memory_v1_to_v2() -> None:
    """Migrate old memory format to new."""
    memory = get_memory_provider()
    
    # Load old format
    old_data = memory.load("data:v1")
    if old_data:
        # Transform to new format
        new_data = transform_data(old_data)
        
        # Save new format
        memory.save("data:v2", new_data)
        
        # Optionally delete old
        memory.delete("data:v1")
```

## Security Considerations

### Sensitive Data

Don't store in memory:
- API keys
- Passwords
- Private tokens

Use environment variables instead:
```python
import os
api_key = os.environ["API_KEY"]  # Not memory.save()
```

### Data Sanitization

Sanitize before storing:
```python
def sanitize_for_memory(data: dict) -> dict:
    """Remove sensitive fields."""
    forbidden_keys = {"password", "token", "secret", "key"}
    return {
        k: v for k, v in data.items()
        if k.lower() not in forbidden_keys
    }
```
