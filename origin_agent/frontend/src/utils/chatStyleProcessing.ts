/**
 * 聊天区自定义样式（chat style）的作用域处理共享入口。
 *
 * 从 useSessionChatStyle 抽出：对原始 CSS 施加作用域约束、@font-face 前缀
 * 要求、@import 禁止规则，并按最终样式表 URL 重写资源引用。
 *
 * 在线 hook 复用本函数保持既有规则与错误语义；离线导出在同一结果之上
 * 进一步重写资源为本地引用，不重复实现作用域规则。
 */

import { CHAT_STYLE } from "../constants/chatStyle";
import { exportLabels } from "../features/sessionExport/labels";
import {
  rewriteChatStyleDeclarationValue,
  type CssUrlRewriter,
} from "./chatStyleResources";

export type ChatStyleProcessingResult =
  | { ok: true; css: string }
  | { ok: false; error: string };

function scopeRuleSelectors(rule: any): void {
  rule.selectors = rule.selectors.map((selector: string) => {
    const trimmed = selector.trim();
    return trimmed.startsWith(CHAT_STYLE.SCOPE_SELECTOR)
      ? trimmed
      : `${CHAT_STYLE.SCOPE_SELECTOR} ${trimmed}`;
  });
}

/**
 * 对原始 chat style CSS 做作用域处理。
 *
 * @param rawCss        原始 CSS 文本
 * @param stylesheetUrl 最终样式表响应 URL（用作资源引用基址）
 * @param rewriteUrl    可选的资源引用重写回调；不传时按在线语义把相对
 *                      引用绝对化，保留 data:/http:/blob: 等引用原样。
 */
export async function scopeSessionChatCss(
  rawCss: string,
  stylesheetUrl: string,
  rewriteUrl?: CssUrlRewriter,
): Promise<ChatStyleProcessingResult> {
  const postcssModule: any = await import("postcss");
  const postcss: any = postcssModule.default || postcssModule;
  let root: any;
  try {
    root = postcss.parse(rawCss);
  } catch (error) {
    return { ok: false, error: exportLabels.cssSyntax.replace("{{detail}}", error instanceof Error ? error.message : String(error)) };
  }
  try {
    root.walkAtRules((atRule: any) => {
      const name = atRule.name.toLowerCase();
      if (name === "import") throw new Error(exportLabels.cssImport);
      if (name === "font-face") {
        atRule.walkDecls("font-family", (decl: any) => {
          const value = decl.value.replace(/[\"']/g, "").trim();
          if (!value.startsWith(CHAT_STYLE.FONT_FAMILY_PREFIX)) {
            throw new Error(exportLabels.cssFontPrefix.replace("{{prefix}}", CHAT_STYLE.FONT_FAMILY_PREFIX));
          }
        });
        return;
      }
      if (name === "keyframes" || name === "-webkit-keyframes") return;
      if (name === "media" || name === "supports" || name === "container") {
        atRule.walkRules((rule: any) => scopeRuleSelectors(rule));
        return;
      }
      throw new Error(exportLabels.cssRule.replace("{{name}}", atRule.name));
    });
    root.walkRules((rule: any) => {
      if (rule.parent?.type === "atrule" && ["font-face", "keyframes", "-webkit-keyframes"].includes(rule.parent.name.toLowerCase())) return;
      scopeRuleSelectors(rule);
    });
    root.walkDecls((decl: any) => {
      decl.value = rewriteChatStyleDeclarationValue(decl.value, stylesheetUrl, rewriteUrl);
    });
    return { ok: true, css: root.toString() };
  } catch (error) {
    return { ok: false, error: error instanceof Error ? error.message : String(error) };
  }
}
