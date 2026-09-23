type FenceOpening = {
  marker: "`" | "~";
  length: number;
  markerIndex: number;
};

function isLineStart(markdown: string, index: number): boolean {
  return index === 0 || markdown[index - 1] === "\n";
}

function getFenceOpening(markdown: string, start: number): FenceOpening | null {
  if (!isLineStart(markdown, start)) return null;

  let markerIndex = start;
  let indentation = 0;
  while (indentation < 4 && markdown[markerIndex] === " ") {
    markerIndex++;
    indentation++;
  }
  if (indentation > 3) return null;

  const marker = markdown[markerIndex];
  if (marker !== "`" && marker !== "~") return null;

  let length = 0;
  while (markdown[markerIndex + length] === marker) length++;
  if (length < 3) return null;

  return { marker, length, markerIndex };
}

function lineEnd(markdown: string, start: number): number {
  const newlineIndex = markdown.indexOf("\n", start);
  return newlineIndex === -1 ? markdown.length : newlineIndex;
}

function isClosingFenceLine(
  markdown: string,
  start: number,
  marker: "`" | "~",
  minimumLength: number,
): boolean {
  let markerIndex = start;
  let indentation = 0;
  while (indentation < 4 && markdown[markerIndex] === " ") {
    markerIndex++;
    indentation++;
  }
  if (indentation > 3 || markdown[markerIndex] !== marker) return false;

  let length = 0;
  while (markdown[markerIndex + length] === marker) length++;
  if (length < minimumLength) return false;

  return markdown.slice(markerIndex + length, lineEnd(markdown, markerIndex)).trim() === "";
}

function findFencedCodeEnd(markdown: string, start: number): number | null {
  const opening = getFenceOpening(markdown, start);
  if (!opening) return null;

  let cursor = lineEnd(markdown, opening.markerIndex);
  if (cursor < markdown.length) cursor++;

  while (cursor < markdown.length) {
    const currentLineEnd = lineEnd(markdown, cursor);
    if (isClosingFenceLine(markdown, cursor, opening.marker, opening.length)) {
      return currentLineEnd < markdown.length ? currentLineEnd + 1 : currentLineEnd;
    }
    cursor = currentLineEnd < markdown.length ? currentLineEnd + 1 : markdown.length;
  }

  return markdown.length;
}

function countPrecedingBackslashes(markdown: string, index: number): number {
  let count = 0;
  for (let cursor = index - 1; cursor >= 0 && markdown[cursor] === "\\"; cursor--) {
    count++;
  }
  return count;
}

function isUnescapedDelimiter(markdown: string, index: number): boolean {
  return countPrecedingBackslashes(markdown, index) % 2 === 0;
}

function findInlineCodeEnd(markdown: string, start: number, length: number): number | null {
  const marker = "`".repeat(length);
  const closingIndex = markdown.indexOf(marker, start + length);
  return closingIndex === -1 ? null : closingIndex + length;
}

function findMathClose(markdown: string, start: number, delimiter: "\\)" | "\\]"): number | null {
  let cursor = start;
  while (cursor < markdown.length) {
    const closeIndex = markdown.indexOf(delimiter, cursor);
    if (closeIndex === -1) return null;
    if (isUnescapedDelimiter(markdown, closeIndex)) return closeIndex;
    cursor = closeIndex + delimiter.length;
  }
  return null;
}

/**
 * 将常见的 LaTeX 反斜杠分隔符转换为 remark-math 支持的美元分隔符。
 *
 * 只处理普通 Markdown 文本中的完整配对标记；行内代码、围栏代码、
 * 转义标记和未闭合标记均原样保留，以兼容流式消息的中间状态。
 */
export function normalizeMarkdownMathDelimiters(markdown: string): string {
  let result = "";
  let index = 0;

  while (index < markdown.length) {
    const fencedCodeEnd = findFencedCodeEnd(markdown, index);
    if (fencedCodeEnd !== null) {
      result += markdown.slice(index, fencedCodeEnd);
      index = fencedCodeEnd;
      continue;
    }

    if (markdown[index] === "`") {
      let codeMarkerLength = 0;
      while (markdown[index + codeMarkerLength] === "`") codeMarkerLength++;
      const inlineCodeEnd = findInlineCodeEnd(markdown, index, codeMarkerLength);
      if (inlineCodeEnd !== null) {
        result += markdown.slice(index, inlineCodeEnd);
        index = inlineCodeEnd;
        continue;
      }
      result += markdown.slice(index);
      break;
    }

    const current = markdown[index];
    const next = markdown[index + 1];
    if (
      current === "\\" &&
      (next === "(" || next === "[") &&
      isUnescapedDelimiter(markdown, index)
    ) {
      const closeDelimiter = next === "(" ? "\\)" : "\\]";
      const closeIndex = findMathClose(markdown, index + 2, closeDelimiter);
      if (closeIndex !== null) {
        const openingReplacement = next === "(" ? "$" : "$$";
        const closingReplacement = openingReplacement;
        result += openingReplacement;
        result += markdown.slice(index + 2, closeIndex);
        result += closingReplacement;
        index = closeIndex + closeDelimiter.length;
        continue;
      }
    }

    result += current;
    index++;
  }

  return result;
}
