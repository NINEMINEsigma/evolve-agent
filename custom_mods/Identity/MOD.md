# Identity and Personality

Use this guidance when the user wants to inspect or change the main Agent's persona or character name.

## Identity files

`GENE.md` defines the innate identity set by the user. You cannot modify it.

The active LLM Profile selects a SOUL file. Its current name is `{{soul_file}}`, stored at `ws:{{soul_file}}`. It contains acquired personality, constraints, character, language style, and other personalized traits. Read it before editing and use `Write` or `PatchEdit` for requested changes. SOUL text changes take effect when the next conversation turn builds its system prompt.

## Main Agent character name

The runtime reads the main Agent's character name from `ws:SOUL.md.meta`. This is a structured metadata file with each key on a separate `[key]` line and its value below it.

To rename the main Agent:

1. Read `ws:SOUL.md.meta` if present and preserve unrelated sections.
2. Set `[character_name]` to the requested name.
3. Call `RefreshIdentity` to reload the runtime name.

The default is `main-agent` when the name is missing or invalid. Editing the name alone does not refresh the runtime; it is read at startup and explicitly refreshed afterward.

The SOUL text selected by a Profile and the runtime's main identity metadata are separate concerns. Do not assume choosing a differently named SOUL text file also changes the avatar metadata file or startup name source.

## Related features

For `[avatar]` and frontend avatar refresh behavior, see CharacterAvatars mod. For ordinary sub-Agent persona files, see CharacterProfiles mod. For model-specific SOUL selection, see LlmProfiles mod.

SOUL changes are personal expression. Shared skill files must remain neutral and reusable; see Skills mod.
