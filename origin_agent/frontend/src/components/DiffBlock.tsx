interface DiffBlockProps {
  oldText: string;
  newText: string;
  startLine?: number;
  plain?: boolean;
}

export default function DiffBlock({ oldText, newText, startLine = 1, plain = false }: DiffBlockProps) {
  const oldLines = oldText ? oldText.split("\n") : [];
  const newLines = newText ? newText.split("\n") : [];

  if (plain) {
    const lines = newLines.length > 0 ? newLines : oldLines;
    return (
      <div className="diff-block">
        {lines.map((line, i) => (
          <div key={i} className="diff-line diff-line-plain">
            <span className="diff-line-number">{startLine + i}</span>
            <span className="diff-line-content">{line}</span>
          </div>
        ))}
      </div>
    );
  }

  return (
    <div className="diff-block">
      {oldLines.map((line, i) => (
        <div key={`del-${i}`} className="diff-line diff-line-del">
          <span className="diff-line-number">{startLine + i}</span>
          <span className="diff-line-prefix">-</span>
          <span className="diff-line-content">{line}</span>
        </div>
      ))}
      {newLines.map((line, i) => (
        <div key={`add-${i}`} className="diff-line diff-line-add">
          <span className="diff-line-number">{startLine + i}</span>
          <span className="diff-line-prefix">+</span>
          <span className="diff-line-content">{line}</span>
        </div>
      ))}
    </div>
  );
}