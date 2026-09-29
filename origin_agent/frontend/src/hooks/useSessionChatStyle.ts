import { useCallback, useEffect, useState } from "react";
import { CHAT_STYLE } from "../constants/chatStyle";
import { useSessionVisualResource } from "./useSessionVisualResource";
import { rewriteChatStyleDeclarationValue } from "../utils/chatStyleResources";

export type ChatStyleStatus = "idle" | "missing" | "ready" | "error";
export interface SessionChatStyleState {
  status: ChatStyleStatus;
  cssText: string | null;
  error: string | null;
  reloadKey: number;
}

async function scopeCss(rawCss: string, stylesheetUrl: string): Promise<{ css: string } | { error: string }> {
  const postcssModule: any = await import("postcss");
  const postcss: any = postcssModule.default || postcssModule;
  let root: any;
  try { root = postcss.parse(rawCss); } catch (error) {
    return { error: `CSS 语法错误: ${error instanceof Error ? error.message : String(error)}` };
  }
  try {
    root.walkAtRules((atRule: any) => {
      const name = atRule.name.toLowerCase();
      if (name === "import") throw new Error("禁止使用 @import");
      if (name === "font-face") {
        atRule.walkDecls("font-family", (decl: any) => {
          const value = decl.value.replace(/[\"']/g, "").trim();
          if (!value.startsWith(CHAT_STYLE.FONT_FAMILY_PREFIX)) {
            throw new Error(`@font-face 的 font-family 必须以 "${CHAT_STYLE.FONT_FAMILY_PREFIX}" 前缀`);
          }
        });
        return;
      }
      if (name === "keyframes" || name === "-webkit-keyframes") return;
      if (name === "media" || name === "supports" || name === "container") {
        atRule.walkRules((rule: any) => scopeRuleSelectors(rule));
        return;
      }
      throw new Error(`不支持 @${atRule.name} 规则`);
    });
    root.walkRules((rule: any) => {
      if (rule.parent?.type === "atrule" && ["font-face", "keyframes", "-webkit-keyframes"].includes(rule.parent.name.toLowerCase())) return;
      scopeRuleSelectors(rule);
    });
    root.walkDecls((decl: any) => {
      decl.value = rewriteChatStyleDeclarationValue(decl.value, stylesheetUrl);
    });
    return { css: root.toString() };
  } catch (error) {
    return { error: error instanceof Error ? error.message : String(error) };
  }
}

function scopeRuleSelectors(rule: any): void {
  rule.selectors = rule.selectors.map((selector: string) => {
    const trimmed = selector.trim();
    return trimmed.startsWith(CHAT_STYLE.SCOPE_SELECTOR)
      ? trimmed
      : `${CHAT_STYLE.SCOPE_SELECTOR} ${trimmed}`;
  });
}

export function useSessionChatStyle(sessionId: string | undefined, paused: boolean): SessionChatStyleState {
  const resource = useSessionVisualResource(sessionId, "chat_style", paused);
  const [cssText, setCssText] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!resource.finalUrl || resource.status !== "ready") {
      setCssText(null);
      setError(resource.error);
      return;
    }
    try {
      const response = await fetch(resource.finalUrl, { cache: "no-store" });
      if (!response.ok) throw new Error("CSS 文件加载失败");
      const raw = await response.text();
      if (raw.length > CHAT_STYLE.MAX_BYTES) throw new Error(`CSS 文件超过 ${CHAT_STYLE.MAX_BYTES} 字节上限`);
      const result = await scopeCss(raw, response.url);
      if ("error" in result) throw new Error(result.error);
      setCssText(result.css);
      setError(null);
    } catch (caught) {
      setCssText(null);
      setError(caught instanceof Error ? caught.message : "CSS 文件加载失败");
    }
  }, [resource.finalUrl, resource.status, resource.error]);

  useEffect(() => { void load(); }, [load, resource.reloadKey]);

  return {
    status: resource.status === "error" ? "error" : resource.status,
    cssText,
    error,
    reloadKey: resource.reloadKey,
  };
}
