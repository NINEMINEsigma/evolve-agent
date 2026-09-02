---
name: media-display
description: "How to display and deliver files to the user in chat. Covers image rendering, HTML iframe embedding, audio playback, playlist sequencing, and download links via /files/ routes."
category: core
tags:
  - display
  - media
  - files
---

# Media Display

Guide for displaying and delivering files to the user directly in chat response text.

## Route Mapping

All files under `ws:` are accessible via HTTP routes:

| Route | Behavior | Use For |
|---|---|---|
| `/files/ws/{path}` | Inline display (browser renders content) | Images, audio, HTML pages |

**Mapping rule**: `output/img.png` → `/files/ws/output/img.png`

The URL format is `/files/{namespace}/{file_path}` where:
- `namespace` is the logical namespace **without** the colon (e.g., `ws` not `ws:`)
- `file_path` is the path within that namespace

**Example conversions**:
- `living-organism/index.html` → `/files/ws/living-organism/index.html`
- `output/diagram.png` → `/files/ws/output/diagram.png`
- `uploads/speech.mp3` → `/files/ws/uploads/speech.mp3`

## Images

Use Markdown image syntax in your response text:

```
![description](/files/ws/output/diagram.png)
```

Supported formats: PNG, JPG, JPEG, GIF, WebP.

## HTML Pages

Use an `<iframe>` tag for a small, self-contained HTML widget that benefits from inline rendering:

```html
<iframe src="/files/ws/output/report.html" style="width:100%;height:500px;border:none"></iframe>
```

The frontend renders iframes in a sandbox with `allow-scripts allow-same-origin allow-popups allow-forms`.

### Session Site deployment

For a multi-file or persistent website, deploy files under the current session's site directory:

```text
ws:sessions/<session_id>/site/
```

Use `index.html` as the entry and provide this link to the user:

```text
/files/ws/sessions/<session_id>/site/index.html
```

Do not repeatedly embed a large deployed website inside the chat bubble. Tell the user to open it from the Session Site section of the resource drawer, and provide the link when useful.

Before delivery, ensure the chosen deployment is coherent:

- A built deployment must serve the complete build output and generated assets.
- A direct static-source deployment must use same-site relative paths such as `src/main.js` and `./assets/file.png`.
- Do not leave Vite/React JSX or bundler-only bare imports in a page intended to run without a transform server; use a built bundle, an import map, or a browser-native `.js` entry.
- Test the actual `/files/ws/sessions/<session_id>/site/index.html` route in a browser. Files existing on disk are not proof that the gateway serves them with correct paths and MIME types.
- If the site is changed after a session rotation, copy the final files into the new session's site directory and update the link.

For a small one-off widget, inline embedding remains appropriate; for a large interactive site, use Session Site instead.

## Audio

Use an `<audio>` tag for single-track playback:

```html
<audio src="/files/ws/output/speech.mp3" controls></audio>
```

Supported formats: MP3, WAV, OGG, FLAC, AAC, M4A.

## Audio Playlist (Sequential Playback)

To play multiple tracks in sequence with automatic advance, use multiple `<audio>` tags with a `<script>` that listens to `onended` events:

```html
<audio id="track-0" src="/files/ws/output/chapter1.mp3" controls></audio>
<audio id="track-1" src="/files/ws/output/chapter2.mp3" controls style="display:none"></audio>
<audio id="track-2" src="/files/ws/output/chapter3.mp3" controls style="display:none"></audio>
<script>
(function() {
  var tracks = [
    document.getElementById('track-0'),
    document.getElementById('track-1'),
    document.getElementById('track-2')
  ];
  tracks.forEach(function(track, i) {
    track.addEventListener('ended', function() {
      if (i + 1 < tracks.length) {
        tracks[i].style.display = 'none';
        tracks[i + 1].style.display = '';
        tracks[i + 1].play();
      }
    });
  });
})();
</script>
```

## Workflow

1. Generate or save the file to a `ws:` path using `Write` or `PatchEdit`
2. Convert the path by stripping `ws:` and prepending `/files/ws/`
3. Write the Markdown/HTML directly in your response text
4. The frontend renders it automatically via ReactMarkdown + rehypeRaw

## Important Notes

- You do NOT need to call any tool to display files. Just write the URL in your response.
- The `ws:` prefix is a logical path, not a real filesystem directory.
- For rich HTML content with `<script>` or `<style>` tags, the frontend uses SafeHtml (iframe sandbox) to isolate rendering.
- **Do NOT use `/uploads/` or `/downloads/` routes** — these are outdated. Use `/files/ws/` instead.
