---
name: webapp-testing
description: "Use this skill whenever a web page, local web app, static HTML, React/Vite app, Three.js scene, WebGL/WebGPU demo, Session Site, or interactive frontend needs verification, debugging, screenshots, console inspection, or regression testing. Choose the current Browser* tools first; use Playwright scripts only when they provide a capability the browser tools cannot."
license: Complete terms in LICENSE.txt
category: dev
tags:
  - testing
  - browser
  - webapp
  - three.js
  - webgl
  - webgpu
  - session-site
  - mime
---

# Web Application Testing

Use a reconnaissance-first workflow. Do not declare success from source inspection or `node --check` alone: a web app is successful only when its intended delivery URL loads in a real browser and its important interactions produce observable state changes.

## Tool selection

Use the current browser tools as the default:

1. `BrowserLaunch` only when a debug browser is not already available. Use `headless: true` for ordinary DOM checks; use `headless: false` for WebGL/WebGPU, GPU acceleration, visual composition, or cases where the user needs to see the browser.
2. `BrowserConnect` to attach to an existing browser when appropriate.
3. `BrowserListTabs` to identify the target tab.
4. `BrowserGoto` to navigate to the confirmed URL.
5. `BrowserWait`, `BrowserQuery`, and `BrowserScreenshot` to inspect the rendered result.
6. `BrowserClick`, `BrowserType`, `BrowserPress`, and `BrowserScroll` to exercise discovered controls. Confirm before submit/send/destructive actions.

Use a native Playwright script only for capabilities that the Browser* tools do not expose, such as large repeated test matrices, detailed request interception, or persistent console/network collection. Do not make Playwright the default merely because an old example does so.

## Reconnaissance → assertion → interaction → regression

### 1. Reconnaissance

- Read the entry HTML and relevant source to learn the intended selectors and boot sequence.
- Navigate to the actual delivery URL, not an invented `file://` approximation.
- Wait for DOM/content readiness. For dynamic apps, allow the application to finish its own loader or ready transition.
- Query `body`, loader, fallback/error panels, primary canvas, headings, buttons, inputs, and status indicators.
- Capture a screenshot when visual composition matters.

### 2. Assertions

Record objective checks before interacting:

- The expected title and main content exist.
- The loader is hidden or gone after boot.
- The fallback/error panel is absent unless the tested condition requires it.
- The canvas or primary app root has non-zero dimensions.
- Expected controls exist and have the intended initial state.
- Runtime counters such as FPS, triangle count, part count, or a ready marker update when the app exposes them.
- No fatal console error, failed module request, or unexpected HTML response appears during startup.

### 3. Interaction assertions

For every important control, test both the action and its effect:

- Click a view/route and verify active state, URL, heading, or camera/status change.
- Toggle a panel, layer, roof, furniture, landscape, or fallback and verify `class`, `hidden`, `aria-*`, visibility, or text changes.
- Move a range input and verify its value/label or rendered state changes.
- Scroll a narrative or scene and verify the intended section/state changes.
- For 3D scenes, test at least one camera/orbit action and one scene-specific interaction, then capture a screenshot after the change.

### 4. Regression

Repeat the boot assertions after interaction, resize, refresh, and (when relevant) a second route or camera. Check that no state change leaves a blank canvas, stuck loader, duplicated UI, or stale status.

## Static delivery and MIME diagnosis

When testing a Session Site, use the real route:

```text
/files/ws/sessions/<session_id>/site/index.html
```

Keep resource paths relative to `index.html` unless the host explicitly guarantees a site root. A request for `/src/main.js` can accidentally target the gateway root rather than the Session Site. Prefer `src/main.js`, `./assets/...`, and other same-site relative paths.

Interpret module errors by the response:

- `Expected a JavaScript-or-Wasm module ... text/html`: the module URL is wrong, a SPA fallback returned `index.html`, or the file was not served at that path.
- `... text/plain`: the server is serving the module with an unsuitable MIME type; test a `.js` path, correct the host, or use a built asset.
- Bare imports such as `react` or `react-dom/client` require a bundler, an import map, or a browser-resolvable URL. They do not work in an arbitrary static source directory.
- JSX/TSX is not browser-native JavaScript. Use a built bundle, a configured transform server, or a plain `.js` bootstrap for direct static delivery.
- After fixing a path, refresh the actual `/files/ws/...` URL and verify the browser, not only the filesystem.

See `references/session-site-validation.md` for the full checklist.

## WebGL/WebGPU and visual validation

Headless DOM success is not GPU success. Use a headed browser for WebGL/WebGPU, shader compilation, GPU adapter behavior, animation smoothness, and visual composition. Do not enter a retry loop in a headless environment that lacks the required GPU feature.

For a GPU scene, check in this order:

1. Page title and boot text.
2. Loader/fallback state and any explicit error attribute.
3. Canvas dimensions and visible rendering state.
4. FPS or runtime counters after a short settling period.
5. Console/module errors.
6. One representative screenshot per major visual state.
7. At least one real interaction: orbit/drag, slider, camera button, scroll phase, or toggle.

A screenshot is evidence, not a substitute for the user's visual judgment. Report what was observed and show the image when needed; do not claim that structural visual quality is objectively perfect.

See `references/gpu-rendering-validation.md`.

## UI regression traps

Always check these common failure modes:

- `[hidden]` overridden by `.fallback { display: grid/flex }`; add an explicit `[hidden] { display: none !important; }` rule when needed.
- A loader remains above the app because opacity changed but pointer-events or z-index was not cleared.
- A route or asset uses an absolute path that escapes the deployed site.
- A React/Vite source entry is served directly without its runtime or transform.
- A control visually changes but does not update the underlying state.
- A 3D toggle hides the model but leaves furniture, lights, or overlays visible.
- Resize changes CSS dimensions but not the renderer/camera aspect.
- A screenshot is taken before asynchronous geometry, shader, or font loading settles.

See `references/ui-regression-checklist.md`.

## Local servers and helper script

Prefer an already-running server or the actual Session Site route. Do not start another process on the gateway port `8765`. Use `scripts/with_server.py` only when a project genuinely needs a temporary development server; run its `--help` first, use a free high port, and let it clean up its child process. It is a fallback helper, not the default test path.

When a background service must be stopped, use the dedicated `StopBackgroundService` tool rather than killing it through Python or shell commands.

## Screenshot and artifact handling

Use `BrowserScreenshot` for browser captures; it writes to the workspace logs. Use the `media-display` conventions when showing a result. Large sites already deployed to Session Site should be linked, not re-embedded repeatedly in chat.

## Playwright fallback

If a script is required, use Windows-compatible paths or workspace-relative output paths, wait for readiness before querying dynamic DOM, and close the browser. Prefer `page.on('console')` and request listeners for diagnostics. Keep visual GPU tests headed unless the user explicitly accepts a non-GPU smoke test.

The bundled examples are fallback references:

- `examples/element_discovery.py` — Playwright DOM reconnaissance.
- `examples/console_logging.py` — console capture.
- `examples/static_html_automation.py` — HTTP-delivered static page smoke test.

The helper implementation is in `scripts/with_server.py`.
