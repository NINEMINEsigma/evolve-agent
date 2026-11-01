# File Display and Downloads

Use this guidance when presenting generated files or workspace media in a response.

## Storage paths and browser URLs

`ws:` is a logical sandbox prefix, not a browser URL. Use it for file tools and when identifying a storage location. Never put it directly in a Markdown link destination or HTML resource attribute.

The Gateway exposes two routes:

- `{{files_prefix}}/`: inline display, including images, audio, and HTML pages.
- `{{downloads_prefix}}/`: forced download, including PDF and ZIP files.

Map `ws:output/image.png` to `{{files_prefix}}/ws/output/image.png`. Map `ws:output/report.pdf` to `{{downloads_prefix}}/ws/output/report.pdf` for download.

## Presentation forms

- Image: `![description]({{files_prefix}}/ws/output/image.png)`.
- Download: `[report.pdf]({{downloads_prefix}}/ws/output/report.pdf)`.
- Audio: `<audio src="{{files_prefix}}/ws/output/speech.mp3" controls></audio>`.
- HTML page: `<iframe src="{{files_prefix}}/ws/output/report.html" style="width:100%;height:500px;border:none"></iframe>`.

The frontend supplies open-in-new-tab and fullscreen controls for chat iframes. Do not add duplicate controls.

## Workflow

Create or confirm the file before presenting a link. Put general outputs in a workspace subdirectory, such as `ws:output`, rather than directly in the workspace root. A filesystem location and a display URL serve different purposes; make that distinction clear to the user.

Use Markdown for ordinary image and download links. Audio tags remain in the Markdown/raw-HTML pipeline, and iframe tags use the dedicated iframe component; neither tag alone selects whole-message isolated HTML rendering. See ChatHtml mod for the detection rules before mixing HTML with surrounding text.

For a persistent multi-file webpage, see SessionSite mod instead of repeatedly embedding a complete page in chat.
