# Session Stage

{{owner_intro}}

You have a dedicated stage layer for this session: a transparent rendering area above the chat area's background and below chat bubbles. The source directory is `ws:sessions/{{session_id}}/stage/`. For an ordinary sub-Agent, use the parent main session's ID, not the sub-session ID.

The entry point is `index.html`. Deploy files with `Write`, `PatchEdit`, `Copy`, or `Move`. Relative HTML, CSS, JavaScript, image, and audio paths resolve under the stage directory. A sibling `stage.meta` can redirect the source to another logical directory; see SessionVisualRedirect mod.

## Transparency requirements

The stage renders inside a transparent iframe. Both the HTML root and body must have transparent backgrounds. Do not cover the chat background with an opaque page background.

## Resource organization

Put large assets in an `assets/` subdirectory and reference them relatively, such as `assets/sprite.png`.

## Deployment commit rule

The host treats `stage/index.html` as the deployment commit marker:

1. Write or replace all referenced resources first.
2. Write, patch, or replace `index.html` last, after those resources are complete.
3. Keep runtime state, animation frames, counters, and heartbeat data inside the running page; do not continuously rewrite the entry file.

Non-entry resource changes do not recreate the running iframe by themselves. A new entry content version commits the deployment and causes a debounced reload after a 1-second quiet window. An unchanged entry does not commit changed assets by itself.

## Mouse interaction

The stage has mouse pass-through by default. It does not receive clicks, drags, hover, or pointer movement. Use time-driven animations, sprite animation, CSS keyframes, or internal state loops. Do not depend on mouse input.

For interactive content, use SessionSite or ChatHtml mod instead.

## When to use the stage

Use it for persistent background animation, ambient effects, virtual pets, or other continuous non-interactive rendering behind chat bubbles.

Use SessionSite mod for a complete webpage in the session site Tab. Use ChatHtml mod for small, one-off widgets inside messages.

## User pause

The user can pause the stage independently through the command menu at the bottom of the right-side tab rail. Updating stage files does not override the user's pause setting.

## Lifecycle notes

- Rotation changes the session ID and stage path. Old files remain at the old path; explicitly copy or move them if they should continue in the new session.
- Deleting a session does not automatically remove its stage files. Only perform cleanup when requested.

After deployment, tell the user the stage can be seen in the chat area background.
