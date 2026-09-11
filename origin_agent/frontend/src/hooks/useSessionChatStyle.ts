/**
 * 会话级聊天区自定义样式 hook。
 *
 * 探测当前会话的 chat-style/index.css 是否存在，通过 Agentspace SSE
 * 监听 chat-style/ 目录的文件变化，自动热重载 CSS。
 * 加载时用 PostCSS 解析规则，为普通选择器施加 .chat-area 作用域，
 * 禁止 @import，保留 @font-face 和 @keyframes。
 * 无法安全处理时触发失败关闭，整份 CSS 不生效。
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { buildChatStyleUrls } from "../utils";
import { connectAgentspaceEvents } from "../services/agentspaceApi";
import { CHAT_STYLE } from "../constants/chatStyle";
import type { AgentspaceEvent } from "../types";

export type ChatStyleStatus = "idle" | "missing" | "ready" | "error";

export interface SessionChatStyleState {
  status: ChatStyleStatus;
  cssText: string | null;
  error: string | null;
  reloadKey: number;
}

const DEBOUNCE_MS = 300;

// ── CSS 作用域处理器 ──────────────────────────────────────────

/**
 * 使用 PostCSS 解析 CSS 并为普通选择器施加 .chat-area 作用域前缀。
 *
 * 处理规则：
 * - @font-face：保留原样（检查 font-family 前缀 ChatStyle-）
 * - @keyframes / @-webkit-keyframes：保留原样
 * - @media / @supports：递归处理内部规则
 * - @import：拒绝，返回错误
 * - 普通规则：为每个选择器前缀 .chat-area
 * - 无法识别的 at-rule：失败关闭
 *
 * 返回 { css: string } 或 { error: string }。
 */
async function scopeCss(rawCss: string): Promise<{ css: string } | { error: string }> {
  // PostCSS 动态导入
  const postcssModule: any = await import("postcss");
  const postcss: any = postcssModule.default || postcssModule;

  let root: any;
  try {
    root = postcss.parse(rawCss);
  } catch (e) {
    return { error: `CSS 语法错误: ${e instanceof Error ? e.message : String(e)}` };
  }

  const scope = CHAT_STYLE.SCOPE_SELECTOR; // ".chat-area"
  const fontPrefix = CHAT_STYLE.FONT_FAMILY_PREFIX; // "ChatStyle-"

  try {
    root.walkAtRules((atRule: any) => {
      const name = atRule.name.toLowerCase();

      if (name === "import") {
        throw new Error("禁止使用 @import");
      }

      if (name === "font-face") {
        // 检查 font-family 是否以 ChatStyle- 前缀
        atRule.walkDecls("font-family", (decl: any) => {
          const value = decl.value.replace(/['"]/g, "").trim();
          if (!value.startsWith(fontPrefix)) {
            throw new Error(
              `@font-face 的 font-family 必须以 "${fontPrefix}" 前缀，当前为 "${value}"`
            );
          }
        });
        return;
      }

      if (name === "keyframes" || name === "-webkit-keyframes") {
        return; // 保留原样
      }

      if (name === "media" || name === "supports" || name === "container") {
        // 递归处理内部规则的选择器
        atRule.walkRules((rule: any) => {
          scopeRuleSelectors(rule, scope);
        });
        return;
      }

      // 其他 at-rule（如 @namespace, @page, @document 等）：失败关闭
      throw new Error(`不支持 @${atRule.name} 规则`);
    });

    // 处理普通规则的选择器
    root.walkRules((rule: any) => {
      // 跳过位于 at-rule 内部的规则（已在上面处理）
      if (rule.parent && rule.parent.type === "atrule") {
        const parentName = (rule.parent as any).name.toLowerCase();
        if (parentName === "font-face" || parentName === "keyframes" || parentName === "-webkit-keyframes") {
          return;
        }
      }
      scopeRuleSelectors(rule, scope);
    });

    return { css: root.toString() };
  } catch (e) {
    return { error: e instanceof Error ? e.message : String(e) };
  }
}

/**
 * 为单个规则的选择器列表添加 .chat-area 前缀。
 * 例如 ".message-bubble" → ".chat-area .message-bubble"
 */
function scopeRuleSelectors(rule: any, scope: string): void {
  const selectors = rule.selectors.map((sel: any) => {
    const trimmed = sel.trim();
    // 已经带作用域前缀的选择器不再重复添加
    if (trimmed.startsWith(scope)) return trimmed;
    return `${scope} ${trimmed}`;
  });
  rule.selectors = selectors;
}

// ── Hook 主体 ─────────────────────────────────────────────────

export function useSessionChatStyle(
  sessionId: string | undefined,
  paused: boolean,
): SessionChatStyleState {
  const [status, setStatus] = useState<ChatStyleStatus>("idle");
  const [cssText, setCssText] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);

  const urls = sessionId && !paused ? buildChatStyleUrls(sessionId) : null;
  const probeSeqRef = useRef(0);
  const debounceTimerRef = useRef<number | null>(null);
  const chatStylePathPrefixRef = useRef<string>("");

  const probe = useCallback(async () => {
    if (!urls) {
      setStatus("missing");
      setCssText(null);
      setError(null);
      return;
    }

    const seq = ++probeSeqRef.current;
    try {
      const resp = await fetch(urls.cssUrl, { cache: "no-store" });
      if (seq !== probeSeqRef.current) return;

      if (!resp.ok) {
        setStatus("missing");
        setCssText(null);
        setError(null);
        return;
      }

      const text = await resp.text();
      if (seq !== probeSeqRef.current) return;

      // 大小检查
      if (text.length > CHAT_STYLE.MAX_BYTES) {
        setStatus("error");
        setCssText(null);
        setError(`CSS 文件超过 ${CHAT_STYLE.MAX_BYTES} 字节上限`);
        return;
      }

      // 作用域处理
      const result = await scopeCss(text);
      if (seq !== probeSeqRef.current) return;

      if ("error" in result) {
        setStatus("error");
        setCssText(null);
        setError(result.error);
        return;
      }

      setStatus("ready");
      setCssText(result.css);
      setError(null);
    } catch {
      if (seq !== probeSeqRef.current) return;
      setStatus("error");
      setCssText(null);
      setError("CSS 文件加载失败");
    }
  }, [urls]);

  // 会话切换或暂停状态变化：重置并重新探测
  useEffect(() => {
    if (paused) {
      setStatus("idle");
      setCssText(null);
      setError(null);
      setReloadKey(0);
      return;
    }

    setStatus("idle");
    setReloadKey(0);
    setCssText(null);
    setError(null);
    // Agentspace 事件的 path 不带 ws: 前缀，相对于工作空间根
    chatStylePathPrefixRef.current = sessionId
      ? `sessions/${sessionId}/chat-style/`
      : "";
    if (sessionId) {
      probe();
    } else {
      setStatus("missing");
    }
  }, [sessionId, paused]); // eslint-disable-line react-hooks/exhaustive-deps

  // SSE 监听 chat-style/ 目录变化
  useEffect(() => {
    if (!sessionId || paused) return;

    const prefix = chatStylePathPrefixRef.current;
    if (!prefix) return;

    const isChatStylePath = (path: string | null): boolean => {
      if (!path) return false;
      return path.startsWith(prefix);
    };

    const handleEvent = (event: AgentspaceEvent) => {
      if (event.kind === "resync") {
        probe();
        return;
      }

      if (event.kind === "watcher_error") {
        return;
      }

      if (!isChatStylePath(event.path) && !isChatStylePath(event.new_path)) {
        return;
      }

      if (event.kind === "deleted") {
        const isIndexCss = event.path === `${prefix}index.css`;
        const isDir = event.is_directory === true && event.path === prefix.slice(0, -1);
        if (isIndexCss || isDir) {
          setStatus("missing");
          setCssText(null);
          setError(null);
          return;
        }
      }

      if (debounceTimerRef.current != null) {
        window.clearTimeout(debounceTimerRef.current);
      }
      debounceTimerRef.current = window.setTimeout(() => {
        debounceTimerRef.current = null;
        setReloadKey((k) => k + 1);
        probe();
      }, DEBOUNCE_MS);
    };

    const cleanup = connectAgentspaceEvents(handleEvent, () => {});

    return () => {
      cleanup();
      if (debounceTimerRef.current != null) {
        window.clearTimeout(debounceTimerRef.current);
        debounceTimerRef.current = null;
      }
    };
  }, [sessionId, paused]); // eslint-disable-line react-hooks/exhaustive-deps

  return { status, cssText, error, reloadKey };
}
