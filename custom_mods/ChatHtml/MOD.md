# Rich HTML in Chat

Use raw HTML in an assistant message for a small visual status bar, progress indicator, interactive widget, stat table, mini-game, or other self-contained layout.

## Rendering capabilities

The frontend renders HTML inside a sandboxed iframe. Self-contained `script` and `style` tags, inline styles, event handlers, SVG, canvas, animations, and interactive elements are supported. Keep the widget's resources and state within its own page; do not assume access to the host application's DOM or internal state.

Prefer inline styles or self-contained stylesheets. The scope of a chat widget is different from the host chat area's style layer; see SessionChatStyle mod to customize chat bubbles and other chat elements.

## Choose HTML or Markdown per message

A message containing raw HTML uses the HTML rendering path. Markdown formatting and ordinary Markdown line breaks in that same message may appear as literal text rather than formatting.

Choose one form per message:

- Markdown for text-heavy explanations, ordinary links, Mermaid, and mathematical formulas.
- Raw HTML for visual or interactive content. Use HTML paragraphs, headings, and lists for accompanying text.

Do not wrap HTML in a code fence when the user should see the rendered widget. Use a code fence only when displaying source is the goal.

## File resources

Use browser URLs, not logical sandbox paths, in `src` and `href`. Convert `ws:output/image.png` to `{{files_prefix}}/ws/output/image.png`. See FileDisplay mod for inline and download routes.

## State and lifetime

A widget is associated with a rendered message. Do not assume its in-memory JavaScript state survives a page refresh or a message being remounted. For authoritative numeric or string state independent of chat history, see SessionVariables mod.

For a large or multi-file page with persistent access across turns, use SessionSite mod. For persistent non-interactive background animation behind chat bubbles, use SessionStage mod. Inline chat HTML is best suited to small, one-off widgets.
