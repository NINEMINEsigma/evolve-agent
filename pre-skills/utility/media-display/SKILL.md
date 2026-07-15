---
name: media-display
description: "How to display and deliver files to the user in chat. Covers image rendering, HTML iframe embedding, audio playback, playlist sequencing, and download links via /uploads/ and /downloads/ routes."
---

# Media Display

Guide for displaying and delivering files to the user directly in chat response text.

## Route Mapping

All files under `ws:` are accessible via two HTTP routes:

| Route | Behavior | Use For |
|---|---|---|
| `/uploads/{path}` | Inline display (browser renders content) | Images, audio, HTML pages |
| `/downloads/{path}` | Forced download (Content-Disposition: attachment) | PDF, ZIP, CSV, any file |

**Mapping rule**: `ws:output/img.png` → `/uploads/output/img.png` (inline) or `/downloads/output/img.png` (download).

Simply strip the `ws:` prefix and prepend the route prefix.

## Images

Use Markdown image syntax in your response text:

```
![description](/uploads/output/diagram.png)
```

Supported formats: PNG, JPG, JPEG, GIF, WebP.

## HTML Pages

Use an `<iframe>` tag to embed a complete HTML page inline:

```html
<iframe src="/uploads/output/report.html" style="width:100%;height:500px;border:none"></iframe>
```

The frontend renders iframes in a sandbox with `allow-scripts allow-same-origin allow-popups allow-forms`.

## Audio

Use an `<audio>` tag for single-track playback:

```html
<audio src="/uploads/output/speech.mp3" controls></audio>
```

Supported formats: MP3, WAV, OGG, FLAC, AAC, M4A.

## Audio Playlist (Sequential Playback)

To play multiple tracks in sequence with automatic advance, use multiple `<audio>` tags with a `<script>` that listens to `onended` events:

```html
<audio id="track-0" src="/uploads/output/chapter1.mp3" controls></audio>
<audio id="track-1" src="/uploads/output/chapter2.mp3" controls style="display:none"></audio>
<audio id="track-2" src="/uploads/output/chapter3.mp3" controls style="display:none"></audio>
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

## Download Links

Use Markdown link syntax for files that should be downloaded rather than displayed inline:

```
[report.pdf](/downloads/output/report.pdf)
```

The `/downloads/` route sets `Content-Disposition: attachment`, so the browser will download the file instead of rendering it.

## Workflow

1. Generate or save the file to a `ws:` path using `write_file` or `run_python`
2. Determine the HTTP URL by stripping `ws:` and prepending the appropriate route
3. Write the Markdown/HTML directly in your response text
4. The frontend renders it automatically via ReactMarkdown + rehypeRaw

## Important Notes

- You do NOT need to call any tool to display files. Just write the URL in your response.
- The `ws:` prefix is a logical path, not a real filesystem directory. In `run_python`, query the agentspace path and use absolute paths for file I/O.
- If a file does not exist, the frontend will show a broken image or a 404 error. Ensure the file is saved before referencing it.
- For rich HTML content with `<script>` or `<style>` tags, the frontend uses SafeHtml (iframe sandbox) to isolate rendering.