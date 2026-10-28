# Character Avatars

Use a metadata declaration to set a custom frontend avatar for the main Agent or an ordinary character.

## Declaration locations

- Main Agent: the `[avatar]` section in `ws:SOUL.md.meta`.
- Ordinary character: the `[avatar]` section in its `profile.md.meta` under `ws:characters/roleplay/<name>` or `ws:characters/task/<name>`.

The value is a single logical path to the avatar file, such as `ws:avatars/main.png`. Preserve other metadata sections when editing.

## File requirements

The target must be readable through a permitted sandbox namespace, be a file, and be at most 5 MiB. There is no extension whitelist; the browser attempts to load it. Prefer an image format the browser can render reliably.

A logical storage path belongs in the metadata. The frontend derives the HTTP display URL; do not store an HTML tag or browser URL as the avatar path.

## Refresh behavior

Editing the declaration in the workspace triggers the frontend's debounced refresh through Agentspace events. No `RefreshIdentity` call is required merely to change an avatar. Missing declarations fall back to an initial-letter avatar.

Replacing the file itself outside the workspace does not trigger the workspace watcher. Such a replacement may require reconnection or remounting before the frontend fetches it again; do not promise immediate refresh for every namespace.

An invalid avatar declaration is a display configuration error and does not make an otherwise valid ordinary character unavailable for launch.

For changing the runtime name, see Identity mod. For character profile structure, see CharacterProfiles mod.
