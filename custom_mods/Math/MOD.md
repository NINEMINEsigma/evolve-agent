# Mathematical Formulas

The frontend renders mathematical notation with KaTeX in the Markdown message path.

## Delimiters

- Use `$...$` for inline formulas.
- Use `$$...$$` for display formulas.
- `\(...\)` and `\[...\]` are also supported for inline and display formulas respectively.

Keep a formula in ordinary Markdown text when it should render. Do not put it inside an inline-code span or a fenced code block unless the user asks to see its source syntax.

## Presentation

Combine formulas with normal Markdown explanations, definitions, and tables. Use complete expressions and define symbols when they first appear.

Unknown or temporarily incomplete LaTeX remains readable during streaming. Do not switch to raw HTML solely to render a mathematical formula.

For diagrams rather than formulas, see Mermaid mod. For raw interactive content, see ChatHtml mod; that rendering path is separate from Markdown formula rendering.
