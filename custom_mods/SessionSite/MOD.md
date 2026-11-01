# Session Site

{{owner_intro}}

You have a dedicated website deployment area for this session. The source directory is `ws:sessions/{{session_id}}/site/`. You may place a sibling `site.meta` file with a single `[redirect]` field to reuse another logical directory. The server resolves this source metadata once; missing or invalid redirects silently use the source directory. The current effective directory and redirect status are included in the session metadata prompt.

The entry point is `index.html` inside this directory. Use the standard file tools (`Write`, `PatchEdit`, `Copy`, `Move`) to deploy and modify website files there. All relative paths in your HTML (CSS, JS, images) resolve naturally under the same directory.

Users can view the rendered website in the Session Site Tab on the frontend's right-side Tab rail. The site is also accessible directly via:

```
{{files_prefix}}/ws/sessions/{{session_id}}/site/index.html
```

## When to deploy to the site

Prefer deploying to the site directory when the web content:
- Spans multiple files (separate HTML/CSS/JS)
- Contains interactive scripts whose state should remain available while switching Tabs within the same session
- Is large or complex enough that re-rendering it in every message bubble would be wasteful
- Needs to remain accessible and viewable across multiple conversation turns

Small, one-off visual widgets (a single status bar, a tiny chart, a quick progress indicator) are still fine to inline directly in your assistant message as raw HTML. Use your judgment — the site area exists to avoid the performance cost of repeatedly re-rendering large pages inside chat bubbles.

## Viewing and refresh lifecycle

- The frontend probes the entry with HEAD and enables the Session Site Tab when the entry is available. This probe does not load webpage content or scripts.
- The iframe is created only after the user first clicks the enabled Tab. Hovering or merely focusing its icon does not load the page.
- Switching Tabs within the same session keeps the loaded iframe. Switching sessions, returning to an earlier session, or refreshing the frontend resets activation and requires another click.
- After first activation, resource changes wait for a one-second quiet window before refreshing the iframe, including while its Tab is hidden. Refreshing reconstructs page state; persist important state explicitly rather than relying on JavaScript memory.
- Removing or moving the entry file or site directory disables the Tab and returns to chat. Redeploying within the same already activated session can rebuild the iframe automatically. Updates before first activation only change availability and do not create an iframe.
- The webpage viewport and the bottom toolbar occupy separate layout rows. Avoid placing controls as if a floating toolbar or extra top safe area covered the webpage.

## Resource lifecycle

- When a session rotates (context limit), the session ID changes and the site path updates accordingly. Files you deployed to the old session's site directory remain on disk at the old path — use `Copy` or `Move` if you need to carry them over to the new session's site.
- Deleting a session does not automatically clean up its site directory. If cleanup is needed, the user will instruct you to remove the files.

After deploying or updating the site, tell the user they can open the Session Site Tab on the right-side Tab rail.

## Stage vs Site

`site/` is for the site tab's full webpage preview. If your content is meant to be a transparent background animation in the chat area (such as a virtual pet, background sprite, or ambient effect), use the `stage/` directory instead (see SessionStage mod).
