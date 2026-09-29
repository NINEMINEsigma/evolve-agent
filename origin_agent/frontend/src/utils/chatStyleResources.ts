import valueParser from "postcss-value-parser";

/**
 * 以最终 CSS 响应 URL 为基准重写声明值中的 url() 和 image-set() 资源。
 * 只处理 CSS 值语法中的 URL 节点，不使用宽泛正则替换。
 */
export function rewriteChatStyleResourceUrls(css: string, stylesheetUrl: string): string {
  const base = new URL(stylesheetUrl, window.location.href);
  const rewriteValue = (value: string): string => {
    const root = valueParser(value);
    root.walk((node: any) => {
      if (node.type !== "func") return;
      const name = String(node.value).toLowerCase();
      if (name !== "url" && name !== "image-set" && name !== "-webkit-image-set") return;
      if (name === "url") {
        const argument = node.nodes?.find((child: any) => child.type === "string" || child.type === "word");
        if (!argument) throw new Error("无法解析 CSS url() 资源");
        const raw = String(argument.value).trim();
        if (!raw || /^(?:data:|https?:|blob:|file:|#|\/\/)/i.test(raw)) return;
        argument.value = new URL(raw, base.href).href;
        if (argument.type === "word") argument.type = "string";
        return;
      }
      for (const child of node.nodes || []) {
        if (child.type !== "string" && child.type !== "word") continue;
        const raw = String(child.value).trim();
        if (!raw || /^(?:data:|https?:|blob:|file:|#|\/\/)/i.test(raw)) continue;
        child.value = new URL(raw, base.href).href;
        child.type = "string";
      }
    });
    return root.toString();
  };

  return rewriteValue(css);
}

export function rewriteChatStyleDeclarationValue(value: string, stylesheetUrl: string): string {
  return rewriteChatStyleResourceUrls(value, stylesheetUrl);
}
