# Rich HTML in Chat

Use raw HTML in an assistant message for a small visual status bar, progress indicator, interactive widget, stat table, mini-game, or other self-contained layout.

## Rendering paths

After removing fenced and inline code for detection, the frontend checks for `script`, `style`, `link`, `object`, or `embed` tags, case-insensitively. A match sends the whole message to the isolated `SafeHtml` iframe path. Use this path for self-contained CSS and JavaScript widgets; keep resources and state within the widget and do not assume access to the host application's DOM or internal state.

Ordinary raw HTML without these tags stays in the Markdown pipeline with `rehypeRaw`. An `iframe` tag is handled by a dedicated iframe component and does not itself select the whole-message HTML path. An `audio` tag likewise does not select it. Do not promise that event-handler attributes in ordinary Markdown HTML execute JavaScript.

The scope of a chat widget is different from the host chat area's style layer; see SessionChatStyle mod to customize chat bubbles and other chat elements.

## Choose content for the rendering path

In the isolated HTML path, use HTML paragraphs, headings, and lists for accompanying text; Markdown formatting and ordinary Markdown line breaks are not a substitute for HTML markup there. Ordinary HTML in the Markdown path can coexist with Markdown, subject to that parser's behavior.

- Use Markdown for text-heavy explanations, ordinary links, Mermaid, and mathematical formulas.
- Use a self-contained HTML document with its own styles or scripts for visual or interactive widgets.

Do not wrap HTML in a code fence when the user should see the rendered widget. Use a code fence only when displaying source is the goal.

## File resources

Use browser URLs, not logical sandbox paths, in `src` and `href`. Convert `ws:output/image.png` to `{{files_prefix}}/ws/output/image.png`. See FileDisplay mod for inline and download routes.

## State and lifetime

A widget is associated with a rendered message. Do not assume its in-memory JavaScript state survives a page refresh or a message being remounted. For authoritative numeric or string state independent of chat history, see SessionVariables mod.

For a large or multi-file page with persistent access across turns, use SessionSite mod. For persistent non-interactive background animation behind chat bubbles, use SessionStage mod. Inline chat HTML is best suited to small, one-off widgets.
