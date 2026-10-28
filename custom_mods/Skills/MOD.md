# Skills

Skills are reusable knowledge modules stored under the `skills:` namespace, usually as a directory containing `SKILL.md` and optional scripts or references.

## Discover and load

Only skill names and short descriptions are included by default. Call `RecallSkill` without a name to list available skills. Pass the exact skill name to load its full content into the conversation context.

Do not assume a skill's title or description contains all its instructions. Load it before relying on detailed procedures. If the user includes `/skill:skill-name`, use that exact name to load the referenced skill; see UserMentions mod.

Loading a skill supplies instructions, not additional tool permissions. Use only tools available in the current request and load required toolsets separately; see Toolsets mod.

## Authoring and maintenance

Read the existing skill before changing it. Use standard file tools with `skills:` paths for files and directories. Keep related scripts and references with the module rather than embedding unrelated content into its main instructions.

Skills are shared knowledge artifacts, not personal expression. Use generic, neutral technical language independent of your SOUL personality so any Agent can understand and reuse them. Separate reusable instructions from session-specific facts.

## Lifecycle

The launch entry creates the runtime skill directory from the preset skills only when that directory is absent. Do not assume changing preset source content overwrites an already existing runtime skill.

For personal style and character settings instead of shared procedures, see Identity mod. For loading tool definitions instead of knowledge, see Toolsets mod.
