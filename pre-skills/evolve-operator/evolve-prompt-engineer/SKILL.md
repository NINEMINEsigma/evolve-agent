---
name: evolve-prompt-engineer
description: "Prompt template engineering guide for evolve-agent. Use when agent needs to (1) modify prompt templates, (2) understand template hierarchy, (3) optimize system prompts, (4) add new template variables, (5) implement multi-language support, or (6) follow prompt engineering best practices. Triggers on templates/ directory modifications and prompt optimization tasks in evolve-agent contexts."
---

# Evolve Prompt Engineer

Guide for engineering and optimizing prompt templates in evolve-agent.

## Template System Overview

### Architecture

```
┌─────────────────────────────────────────┐
│        Prompt Assembly System           │
│         (system/prompt.py)              │
└──────────────────┬──────────────────────┘
                   │
                   ▼
        ┌─────────────────────┐
        │   Template Files    │
        │   (templates/)      │
        └─────────────────────┘
                   │
        ┌──────────┴──────────┐
        │                     │
        ▼                     ▼
┌───────────────┐     ┌───────────────┐
│   English     │     │    Chinese    │
│  (default)    │     │    (zh/)      │
└───────────────┘     └───────────────┘
```

### Template Hierarchy

Templates are assembled in order (later overrides earlier):

```
1. GENE          - Genetic/inherent traits
2. SOUL          - Core personality
3. base          - Base system prompt
4. modes/{fast,fallback}  - Mode-specific additions
5. tools         - Tool descriptions
6. memory        - Loaded memories
7. skills        - Loaded skills
```

## Directory Structure

```
templates/
├── base.txt           # Base system prompt
├── tools.txt          # Tool system explanation
├── compress.txt       # Compression template
├── auto_title.txt     # Auto-title template
├── modes/
│   ├── fast.txt       # Fast mode additions
│   └── fallback.txt   # Fallback mode additions
└── zh/                # Chinese translations
    ├── base.txt
    ├── tools.txt
    ├── compress.txt
    ├── auto_title.txt
    └── modes/
        ├── fast.txt
        └── fallback.txt
```

## Template Syntax

### Jinja2 Basics

Templates use Jinja2 syntax:

```jinja2
{# Comments #}
{# This is a comment #}

{# Variables #}
Hello, {{ user_name }}!

{# Default values #}
Theme: {{ theme | default('light') }}

{# Conditionals #}
{% if debug_mode %}
Debug mode is ON
{% endif %}

{# Loops #}
{% for tool in tools %}
- {{ tool.name }}: {{ tool.description }}
{% endfor %}
```

### Available Variables

| Variable | Source | Example |
|----------|--------|---------|
| `{{platform}}` | Runtime context | "Windows", "Linux" |
| `{{fork_path}}` | Runtime context | Path to fork directory |
| `{{agentspace}}` | Runtime context | Path to workspace |
| `{{mode}}` | Runtime context | "fast", "fallback" |
| `{{tools}}` | Tool registry | List of available tools |
| `{{skills}}` | Skill loader | List of loaded skills |
| `{{memories}}` | Memory provider | Relevant memories |

## Creating Templates

### Base Template Structure

```jinja2
{# templates/base.txt #}
You are {{agent_name}}, an AI assistant with the following capabilities:

{{platform}}

{% if mode == "fast" %}
You are running in fast mode with full capabilities.
{% elif mode == "fallback" %}
You are in fallback mode for error recovery.
{% endif %}

Available tools:
{% for tool in tools %}
- {{tool.name}}: {{tool.description}}
{% endfor %}
```

### Mode-Specific Templates

Fast mode (`templates/modes/fast.txt`):
```jinja2
{# Fast mode additions #}

You have full access to all tools and capabilities.
You can:
- Read and write files
- Execute shell commands
- Evolve your own code
- Manage skills

When evolving code:
1. Always read existing code first
2. Make minimal, focused changes
3. Validate before finalizing
4. Test thoroughly
```

Fallback mode (`templates/modes/fallback.txt`):
```jinja2
{# Fallback mode additions #}

You are in FALLBACK MODE for error recovery.

Current situation:
- The previous evolution failed
- You need to fix errors in the fix: namespace
- After fixing, the system will resume normal operation

Steps:
1. Read error logs to understand what failed
2. Examine files in fix: namespace
3. Fix the identified issues
4. The orchestrator will validate on restart
```

### Tools Template

```jinja2
{# templates/tools.txt #}
Tool Registry contains all available tools.

Tool invocation format:
<tool_name>: {"param1": "value1", "param2": "value2"}

Available tools by category:

## Filesystem
{% for tool in tools if tool.toolset == "filesystem" %}
### {{tool.name}}
{{tool.description}}

Parameters:
{% for param_name, param_info in tool.schema.parameters.properties.items() %}
- {{param_name}} ({{param_info.type}}{% if param_name in tool.schema.parameters.required %}, required{% endif %}): {{param_info.description}}
{% endfor %}
{% endfor %}
```

## Multi-Language Support

### Adding New Language

1. Create language directory: `templates/<lang>/`
2. Translate all template files
3. System auto-detects based on templates directory

### Language Detection

```python
# In system/prompt.py
def get_template_dir():
    """Get appropriate template directory."""
    if Path("templates/zh").exists():
        return "templates/zh"
    return "templates"  # Default English
```

### Translation Guidelines

When translating templates:

1. **Keep structure identical** - Same Jinja2 tags
2. **Preserve variable names** - Don't translate `{{tools}}`
3. **Adapt examples** - Use culturally relevant examples
4. **Maintain tone** - Keep professional but friendly
5. **Test rendering** - Ensure templates compile

Example translation:
```jinja2
{# English #}
You are {{agent_name}}, an AI assistant.

{# Chinese #}
你是 {{agent_name}}，一个AI助手。
```

## Template Optimization

### Conciseness

Keep templates concise:
```jinja2
{# Bad - verbose #}
You are an AI assistant. You can help users with various tasks. 
You have tools available. The tools help you do things.

{# Good - concise #}
AI assistant with tool access.
```

### Clarity

Be explicit about behavior:
```jinja2
{# Bad - vague #}
Use tools when helpful.

{# Good - specific #}
Always use read_file before modifying files.
Always validate_code before evolve_code.
```

### Context Efficiency

Minimize token usage:
```jinja2
{# Bad - repetitive #}
{% for tool in tools %}
Tool {{tool.name}}: {{tool.description}}
This tool belongs to {{tool.toolset}}.
{% endfor %}

{# Good - compact #}
Tools: {% for tool in tools %}{{tool.name}} ({{tool.toolset}}): {{tool.description}}{% endfor %}
```

## Advanced Patterns

### Dynamic Sections

```jinja2
{% if skills %}
## Loaded Skills
{% for skill in skills %}
### {{skill.name}}
{{skill.description}}

{{skill.content}}
{% endfor %}
{% endif %}
```

### Conditional Instructions

```jinja2
{% if mode == "debug" %}
DEBUG MODE INSTRUCTIONS:
- Log all operations
- Show intermediate results
- Explain reasoning
{% else %}
PRODUCTION MODE:
- Be concise
- Focus on results
{% endif %}
```

### Template Inheritance

Not native Jinja2, but can simulate:
```jinja2
{# base.txt includes sub-templates #}
{% include 'modes/' + mode + '.txt' ignore missing %}
```

## Testing Templates

### Render Testing

```python
from system.prompt import assemble_prompt
from jinja2 import Template

# Test template rendering
template_str = Path("templates/base.txt").read_text()
template = Template(template_str)

result = template.render(
    agent_name="Evolve Agent",
    platform="Windows",
    mode="fast",
    tools=[{"name": "read_file", "description": "Read files"}]
)

print(result)
```

### Validation Checklist

- [ ] All Jinja2 syntax is valid
- [ ] Variables used exist in context
- [ ] No undefined variables (use `| default`)
- [ ] Conditionals cover all cases
- [ ] Loops handle empty lists
- [ ] Multi-byte characters render correctly
- [ ] Template size is reasonable (< 2000 tokens)

## Common Mistakes

### Mistake 1: Undefined Variables

```jinja2
{# Bad - may be undefined #}
Hello, {{user_name}}!

{# Good - safe with default #}
Hello, {{user_name | default('User')}}!
```

### Mistake 2: Syntax Errors

```jinja2
{# Bad - missing endif #}
{% if debug %}Debug mode{% endif %}

{# Bad - wrong syntax #}
{% if debug %}
  Debug mode
{% end %}  {# Should be {% endif %} #}
```

### Mistake 3: Over-Nesting

```jinja2
{# Bad - too complex #}
{% if a %}{% if b %}{% if c %}X{% endif %}{% endif %}{% endif %}

{# Good - flat structure #}
{% if a and b and c %}X{% endif %}
```

### Mistake 4: Inconsistent Indentation

```jinja2
{# Bad - messy #}
{% if x %}
Line 1
  Line 2
    {% if y %}
Line 3
    {% endif %}
{% endif %}

{# Good - clean #}
{% if x %}
Line 1
Line 2
{% if y %}
Line 3
{% endif %}
{% endif %}
```

## Evolution Patterns

When evolving templates through `fork:`:

1. **Read current template**:
   ```
   read_file: {"path": "fork:templates/base.txt"}
   ```

2. **Modify incrementally**:
   ```
   edit_file: {
     "path": "fork:templates/base.txt",
     "old_string": "...",
     "new_string": "..."
   }
   ```

3. **Test before evolving**:
   - Templates don't need validation_code
   - But should be syntactically valid Jinja2

4. **Evolution flow**:
   ```
   Modify templates
        │
        ▼
   No validation needed
   (templates are text)
        │
        ▼
   evolve_code: {}
        │
        ▼
   Restart with new prompts
   ```
