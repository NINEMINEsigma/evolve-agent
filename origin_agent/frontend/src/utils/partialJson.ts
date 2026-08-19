/**
 * 在可能未闭合的 JSON 片段中提取指定字符串字段的已生成内容。
 *
 * 扫描 `"field"\s*:\s*"` 起点，之后按 JSON 字符串规则逐字符反转义
 * （处理 \" \\ \n \t \r \uXXXX），直到片段结尾。
 *
 * @param raw   累积中的原始 JSON 参数片段（可能未闭合）
 * @param field 目标字段名
 * @returns     已生成的字段内容（可能不完整）；未找到字段起点返回 null
 */
export function extractPartialStringField(raw: string, field: string): string | null {
  const needle = `"${field}"`;
  const fieldIdx = raw.indexOf(needle);
  if (fieldIdx === -1) return null;

  let i = fieldIdx + needle.length;
  // 跳过空白
  while (i < raw.length && (raw[i] === " " || raw[i] === "\t" || raw[i] === "\n" || raw[i] === "\r")) i++;
  if (i >= raw.length || raw[i] !== ":") return null;
  i++;
  // 跳过空白
  while (i < raw.length && (raw[i] === " " || raw[i] === "\t" || raw[i] === "\n" || raw[i] === "\r")) i++;
  if (i >= raw.length || raw[i] !== '"') return null;
  i++; // 跳过开引号

  let result = "";
  while (i < raw.length) {
    const ch = raw[i];
    if (ch === "\\") {
      if (i + 1 >= raw.length) break; // 转义序列不完整，等下一片
      const next = raw[i + 1];
      switch (next) {
        case '"': result += '"'; break;
        case "\\": result += "\\"; break;
        case "n": result += "\n"; break;
        case "t": result += "\t"; break;
        case "r": result += "\r"; break;
        case "/": result += "/"; break;
        case "b": result += "\b"; break;
        case "f": result += "\f"; break;
        case "u": {
          if (i + 6 <= raw.length) {
            const hex = raw.slice(i + 2, i + 6);
            if (/^[0-9a-fA-F]{4}$/.test(hex)) {
              result += String.fromCharCode(parseInt(hex, 16));
              i += 6;
              continue;
            }
          }
          // \uXXXX 不完整，等下一片
          return result;
        }
        default:
          result += next;
      }
      i += 2;
    } else if (ch === '"') {
      // 闭合引号 — 字段完整
      break;
    } else {
      result += ch;
      i++;
    }
  }

  return result;
}