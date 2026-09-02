# Session Site validation

Use this checklist when a site is delivered under the Evolve Agent session site route rather than a development server.

## Delivery contract

The expected entry is:

```text
/files/ws/sessions/<session_id>/site/index.html
```

Open that exact HTTP URL in the browser. Do not substitute a `file://` URL: file URLs do not reproduce gateway routing, MIME handling, or deployed relative paths.

For a source deployment, make the entry and every local asset resolve relative to `index.html`:

```html
<script type="module" src="src/main.js"></script>
<link rel="stylesheet" href="style.css">
```

An absolute `/src/main.js` points at the gateway origin, not necessarily the site directory. Use an absolute URL only when the host explicitly documents that the deployed site is mounted at that root.

## Source versus build deployment

Choose one complete strategy:

- **Built deployment:** run the project build, then serve the complete build output including its generated assets.
- **Native static source deployment:** use browser-native JavaScript, an import map with browser-resolvable URLs, and relative paths. Do not leave JSX/TSX or bundler-only bare imports in the entry.

Do not mix a Vite/React source entry with a static file route unless the route is backed by a transform server. A plain `.jsx` file is not browser-native JavaScript, and imports such as `react` and `react-dom/client` need a bundler or an import map.

## MIME diagnosis

When a module fails, inspect the requested URL and response type:

- `text/html` for a JavaScript module usually means a wrong path, missing file, or SPA fallback returned `index.html`.
- `text/plain` means the host served the file with an unsuitable module MIME type; use a correctly configured host, a built asset, or a supported `.js` route.
- A 404 means the relative path is wrong or the asset was not included in the deployment.

Fix the URL and deployment strategy first. Do not silence the error with `type="text/plain"`, dynamic string evaluation, or duplicated scripts.

## Boot assertions

After navigation, wait for the application to settle and verify:

- document title is expected;
- the main root or canvas exists and has non-zero dimensions;
- a loader becomes hidden or receives its documented completion class;
- a fallback/error panel is absent in the success path;
- a ready marker, FPS counter, or other runtime status updates when provided;
- no fatal module or initialization error was emitted.

For applications with asynchronous geometry, shaders, fonts, or textures, wait for the application-specific ready signal or a bounded settling period before taking the first screenshot.

## Deployment-specific regression checks

Refresh the exact delivery URL and repeat boot assertions. Test one nested asset or module after refresh to catch path errors hidden by browser cache. Do not use the old `dist/` output as evidence when the source site is the intended delivery target.

For large interactive sites already deployed to Session Site, link the site for user review rather than embedding the entire site repeatedly inside the chat response.
