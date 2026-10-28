# Session Chat Style

{{owner_intro}}

You have a session-level CSS layer for the chat area. The source directory is `ws:sessions/{{session_id}}/chat-style/`, and the entry point is `index.css`. For an ordinary sub-Agent, use the parent main session's ID.

Use standard file tools to deploy or modify the CSS and referenced resources. Relative font and image paths resolve under this directory. A sibling `chat-style.meta` can redirect to another logical directory; see SessionVisualRedirect mod.

## Scope restriction

The system scopes selectors to `.chat-area`. This feature cannot style the left sidebar, header, input bar, other Tabs, lightbox, or approval dialogs. Do not attempt to escape the scope with global selectors. A rule that cannot be safely scoped causes the entire file to be rejected.

## Public style selectors

Prefer these stable public attributes over internal class names:

| Element | Selector |
|---|---|
| Chat area root | `.chat-area` |
| Any message | `[data-chat-scope="message"]` |
| User message | `.chat-area [data-message-role="user"]` |
| Assistant message | `.chat-area [data-message-role="assistant"]` |
| Tool message | `.chat-area [data-message-role="tool"]` |
| Bubble | `[data-chat-scope="bubble"]` |
| Content body | `[data-chat-scope="content"]` |
| Reasoning block | `[data-chat-scope="reasoning"]` |
| Tool call block | `[data-chat-scope="tool-call"]` |
| Tool call detail | `[data-chat-scope="tool-detail"]` |
| Code block | `[data-chat-scope="code"]` |
| Attachments | `[data-chat-scope="attachments"]` |
| Toolbar | `[data-chat-scope="toolbar"]` |
| Message metadata | `[data-chat-scope="meta"]` |
| Waiting indicator | `[data-chat-scope="waiting"]` |
| Hovered message | `.chat-area [data-chat-scope="message"]:hover` |
| Same-character hovered | `.chat-area [data-character-hovered="true"]` |

## Custom fonts

An `@font-face` family name must start with `ChatStyle-`, such as `ChatStyle-MyFont`. Always provide fallback fonts, for example `"ChatStyle-MyFont", "Segoe UI", sans-serif`.

Font sources can use relative resource paths, HTTP/HTTPS URLs, or the local font proxy at `{{local_font_prefix}}`. For local fonts, use a proxy URL such as `{{local_font_prefix}}/C:/Windows/Fonts/arial.ttf` rather than expecting the browser to read a physical path directly. Supported local font extensions are `woff2`, `woff`, `ttf`, and `otf`, with a 20 MiB limit per file. Data URIs are unsupported.

## Rules and limits

- `index.css` must not exceed 256 KiB.
- `@import` is prohibited.
- An `@font-face` without the required family prefix rejects the file.
- Unsupported at-rules such as `@namespace`, `@page`, and `@document` reject the file.
- `@font-face`, `@keyframes`, and `@-webkit-keyframes` are preserved without selector scoping.
- Rules inside `@media`, `@supports`, and `@container` are scoped.

Missing, oversized, or rejected CSS restores the default appearance rather than partially applying the file.

## User pause

The user can independently pause chat style and the stage through the command menu at the bottom of the right-side tab rail. Updating CSS does not resume a paused style; the user must resume it.

## Lifecycle notes

Rotation changes the session ID and style path. Old files remain and must be explicitly copied or moved if needed in the new session. Deleting a session does not automatically clean up style files.

After deployment, tell the user the appearance is applied in the chat area, subject to their pause setting. For background animation, see SessionStage mod; for complete webpages, see SessionSite mod.
