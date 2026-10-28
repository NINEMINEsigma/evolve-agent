# User Mention References

The user can insert file and skill references through the frontend mention menu. These references are plain text in the user message; their content is not automatically expanded.

## File and directory references

`@ws:path/to/file` refers to a file or directory in the workspace.

Use `Read` with the logical path `ws:path/to/file`, without the leading `@`. For a directory, inspect it with `Read` or locate relevant children with `SearchFiles` before reading files. Respect the normal sandbox permissions and path rules.

## Skill references

`/skill:skill-name` refers to a skill by name. Call `RecallSkill` with the exact skill name to bring its full content into the conversation context. See Skills mod for skill loading and authoring conventions.

## Response behavior

Honor references proactively when they are relevant to the user's request. A path mention does not mean the file has already been read, and a skill mention does not mean its instructions have already been loaded.

If a referenced file or skill is unavailable, report the actual issue rather than inventing its content. A reference identifies material to consult; it does not itself authorize unrelated changes or bypass tool permissions.
