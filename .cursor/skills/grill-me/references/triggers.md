# Trigger Keywords and Activation Patterns

This document provides structured trigger definitions for agent platforms that support keyword-based or pattern-based skill activation.

## Primary Triggers (High Confidence)

These phrases should always activate `grill-me-pro`:

| Pattern | Example User Input |
|---------|-------------------|
| `grill me` | "grill me on this plan" |
| `grill-me` | "run grill-me on this design" |
| `grill me pro` | "use grill-me-pro" |
| `interrogate` + `plan\|design\|architecture` | "interrogate this architecture" |
| `challenge my` + `design\|plan\|approach` | "challenge my design" |
| `stress test` + `plan\|design\|architecture` | "stress test this plan" |
| `帮我审视` | "帮我审视一下这个架构" |
| `先别写代码` + `厘清\|明确\|讨论` | "先别写代码，先帮我把需求厘清" |
| `拷问我` | "拷问我这个方案" |

## Secondary Triggers (Context-Dependent)

These phrases should activate `grill-me-pro` when the context involves planning or design decisions:

| Pattern | Context Clue |
|---------|-------------|
| `设计` + `方案\|架构\|数据库\|API` | "我想设计一个支付系统的API" |
| `plan` + `architecture\|design\|refactor` | "plan this refactor" |
| `decide` + `technology\|framework\|database` | "decide which database to use" |
| `compare` + `options\|approaches\|solutions` | "compare these two approaches" |
| `trade-off` / `tradeoff` | "what are the trade-offs here?" |
| `assumptions` | "what assumptions am I making?" |

## Negative Triggers (Should NOT Activate)

| Pattern | Why Not |
|---------|---------|
| `grill` (food context) | "how to grill steak" — culinary, not planning |
| `interrogate` (data context) | "interrogate this dataset" — data analysis, not design review |
| `plan` alone (scheduling) | "plan my day" — personal scheduling, not technical design |
| `design` alone (visual) | "design a logo" — visual/graphic design, not architecture |
| `review code` | Code review is different from plan review |
| `debug` / `fix` | Troubleshooting is not planning |

## Activation Confidence Levels

For platforms that support confidence scoring:

| Level | Condition | Score |
|-------|-----------|-------|
| **Certain** | Exact skill name mentioned (`grill-me-pro`, `grill me pro`) | 1.0 |
| **High** | Primary trigger + design/plan context | 0.9 |
| **Medium** | Secondary trigger + clear planning context | 0.7 |
| **Low** | Single keyword match without context | 0.4 |
| **None** | Negative trigger match | 0.0 |

## Platform-Specific Notes

### evolve-agent
- No automatic trigger system
- Activate via explicit user request or GENE/SOUL integration
- See README.md "安装到你的Agent" section

### Claude Code / Claude.ai
- Uses `description` field in SKILL.md frontmatter for triggering
- Description already optimized for coverage

### Cursor / Windsurf / Codex
- Typically use `.cursorrules` or skill directory for activation
- Copy SKILL.md content to agent's rules/skills directory

### Generic (system prompt injection)
- Inject SKILL.md body into system prompt
- Triggers become irrelevant — skill is always active
