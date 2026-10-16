import valueParser from "postcss-value-parser";

/**
 * 单条 CSS 资源引用的重写回调。
 *
 * 返回新的引用字符串，或返回 null 表示保留原样（默认实现用 null 表示
 * 已经是 data:/http:/blob:/file:/# 等无需重写的引用）。离线导出复用同一
 * 遍历逻辑，通过此回调把引用映射为本地数据/Blob 引用或标记不支持。
 */
export type CssUrlRewriter = (rawUrl: string, baseUrl: string) => string | null;

/** 默认重写：把相对引用按最终样式表 URL 解析为绝对地址，其余原样保留。 */
function defaultUrlRewriter(raw: string, baseUrl: string): string | null {
  if (!raw || /^(?:data:|https?:|blob:|file:|#|\/\/)/i.test(raw)) return null;
  return new URL(raw, baseUrl).href;
}

/**
 * 以最终 CSS 响应 URL 为基准重写声明值中的 url() 和 image-set() 资源。
 * 只处理 CSS 值语法中的 URL 节点，不使用宽泛正则替换。
 *
 * 传入 rewriteUrl 时由其决定每条引用的替换值（null=保留原样）；
 * 不传入时使用默认的相对引用绝对化，保持在线聊天样式原行为。
 */
export function rewriteChatStyleResourceUrls(
  css: string,
  stylesheetUrl: string,
  rewriteUrl: CssUrlRewriter = defaultUrlRewriter,
): string {
  const base = new URL(stylesheetUrl, window.location.href);
  const rewriteValue = (value: string): string => {
    const root = valueParser(value);
    root.walk((node: any) => {
      if (node.type !== "function") return;
      const name = String(node.value).toLowerCase();
      if (name !== "url" && name !== "image-set" && name !== "-webkit-image-set") return;
      if (name === "url") {
        const argument = node.nodes?.find((child: any) => child.type === "string" || child.type === "word");
        if (!argument) throw new Error("无法解析 CSS url() 资源");
        const raw = String(argument.value).trim();
        const next = rewriteUrl(raw, base.href);
        if (next == null) return;
        argument.value = next;
        if (argument.type === "word") argument.type = "string";
        return;
      }
      for (const child of node.nodes || []) {
        if (child.type !== "string" && child.type !== "word") continue;
        const raw = String(child.value).trim();
        const next = rewriteUrl(raw, base.href);
        if (next == null) continue;
        child.value = next;
        child.type = "string";
      }
    });
    return root.toString();
  };

  return rewriteValue(css);
}

export function rewriteChatStyleDeclarationValue(
  value: string,
  stylesheetUrl: string,
  rewriteUrl?: CssUrlRewriter,
): string {
  return rewriteChatStyleResourceUrls(value, stylesheetUrl, rewriteUrl);
}
