# Character Profiles

Ordinary sub-Agents and non-main multi-Agent participants are discovered from character directories in the workspace. There is no separate explicit registration tool.

## Directory layout

A character lives under either `ws:characters/roleplay/<name>` or `ws:characters/task/<name>`. The directory must contain `profile.md` and its sibling `profile.md.meta`.

`roleplay` and `task` are categories, not separate name namespaces. Names must be valid and globally unique across both directories. Duplicate names are listed as errors and cannot be launched.

## Prompt and metadata

`profile.md` supplies the first custom system prompt. Write the role's purpose, behavior, and task-specific constraints there.

`profile.md.meta` uses separate `[key]` sections:

- `[llm_profile]`: required name of an existing, usable LLM Profile.
- `[description]`: optional short description used in discovery and the main Agent's character catalog; it is not a replacement for the full prompt.
- `[profile]`: optional additional system prompt paths, one complete logical file path per line.
- `[avatar]`: optional avatar file path; see CharacterAvatars mod.

Additional prompt files are loaded in declared order as separate system messages. Their paths must exist, be files, and be readable in the current sandbox. Do not copy model credentials into the character directory; reference an existing Profile by name instead.

## Create and inspect

Use file tools to create or edit character files. Preserve unrelated metadata when updating one field. Use `ListSubAgents` to see current discovery and configuration errors; invalid characters remain visible there but are rejected at launch.

The character profiles Tab is a read-only view of profiles, errors, and prompt text. Editing files changes subsequent discovery; do not assume it rewrites the context of an already running role or participant snapshot.

For launching and communicating with an ordinary sub-Agent, see SubAgent mod. For shared-history participation, see MultiAgent mod. For model registry structure, see LlmProfiles mod.
