# Session Visual Resource Redirect

Use a redirect when a session should reuse a visual resource directory instead of keeping a separate deployment in its default location.

## Source metadata

The configuration is a sibling of the source directory, not a file inside it:

| Feature | Source directory | Metadata file | Entry |
|---|---|---|---|
| Stage | `ws:sessions/{{session_id}}/stage` | `ws:sessions/{{session_id}}/stage.meta` | `index.html` |
| Site | `ws:sessions/{{session_id}}/site` | `ws:sessions/{{session_id}}/site.meta` | `index.html` |
| Chat style | `ws:sessions/{{session_id}}/chat-style` | `ws:sessions/{{session_id}}/chat-style.meta` | `index.css` |

For an ordinary sub-Agent, use the parent main session's ID.

Write one `[redirect]` section with a readable logical directory path as its value, for example `ws:shared/site-demo`. Use the namespace prefix and forward slashes, with no leading or trailing slash in the relative path. The target is a directory, not an entry filename or HTTP URL.

## Resolution

The server resolves the source metadata once. It does not follow another redirect declared on the target directory. Missing or invalid configuration silently falls back to the source directory; a malformed redirect is not proof that the target is active.

The stable visual entry redirects to the effective location with HTTP 307 when valid. Relative resource URLs then resolve under that effective directory.

## Deployment workflow

1. Prepare the target entry and its referenced resources using file tools within the allowed namespaces.
2. Read the source metadata before editing so unrelated metadata is preserved.
3. Set the source `[redirect]` to the target directory.
4. Use the current session visual resource state, when provided, to distinguish source directory, effective directory, redirect status, availability, and errors.

Reading a directory's `.meta` with `Read` reports metadata; it does not itself follow the redirect. Resource availability is not proof that the browser has successfully rendered it.

## Shared resources

Redirects do not copy files or grant write access. Updating a shared target can affect every session that uses it. Respect its sandbox permissions and ownership.

Feature-specific requirements still apply: see SessionStage for transparent backgrounds and deployment commits, SessionSite for webpages, and SessionChatStyle for scoped CSS. To return to the default directory, remove the source redirect declaration while preserving other metadata and ensure the default entry exists.
