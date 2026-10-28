# Mermaid Diagrams

Use Mermaid when a response needs a flowchart, sequence diagram, class diagram, state diagram, Gantt chart, or another supported diagram.

## Output format

Put the diagram source in a fenced Markdown code block with the language tag `mermaid`.

The frontend renders it as an interactive SVG diagram with zoom, pan, and download support. Mermaid remains part of the Markdown rendering path, so normal Markdown explanations can appear before and after the diagram in the same message.

## Writing diagrams

Choose the diagram type that matches the information. Use stable node identifiers and clear labels. Keep syntax complete and avoid inventing relationships not supported by the available evidence.

Use ordinary Markdown text to explain assumptions or incomplete information rather than presenting an uncertain relationship as established fact.

## Related rendering features

Use Math mod for mathematical notation. Use ChatHtml mod for a custom interactive widget that needs JavaScript or canvas. Do not switch a Mermaid explanation to raw HTML merely to add visual formatting, because the message rendering paths differ.
