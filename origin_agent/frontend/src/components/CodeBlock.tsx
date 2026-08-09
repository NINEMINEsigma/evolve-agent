import { useState } from "react";
import { Prism as SyntaxHighlighter } from "react-syntax-highlighter";
import { oneDark } from "react-syntax-highlighter/dist/esm/styles/prism";
import { TIMING } from "../constants/timing";

export default function CodeBlock({ language, code, startingLineNumber }: {
  language: string;
  code: string;
  startingLineNumber?: number;
}) {
  const [copied, setCopied] = useState(false);
  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(code);
      setCopied(true);
      setTimeout(() => setCopied(false), TIMING.COPY_RESET_DELAY);
    } catch {
      // ignore clipboard errors
    }
  };
  return (
    <div className="code-block-wrapper">
      <div className="code-block-header">
        <span className="code-block-lang">{language}</span>
        <button className="code-block-copy" onClick={handleCopy}>
          {copied ? "已复制" : "复制"}
        </button>
      </div>
      <SyntaxHighlighter
        style={oneDark}
        language={language}
        PreTag="div"
        customStyle={{ margin: 0, borderRadius: "0 0 6px 6px" }}
        showLineNumbers={startingLineNumber !== undefined}
        startingLineNumber={startingLineNumber ?? 1}
        lineNumberStyle={{ color: "#858585", padding: "0 8px 0 0", userSelect: "none", borderRight: "1px solid rgba(255,255,255,0.06)" }}
      >
        {code}
      </SyntaxHighlighter>
    </div>
  );
}